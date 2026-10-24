#!/usr/bin/env python3
"""Retrieve Dimensions policy documents linked to the frozen FAIRification anchor.

The script uses only the 144 retained Dimensions publication IDs from the frozen
publication anchor. It queries policy documents whose `publication_ids` include
one or more of those IDs, handles per-batch paging, and retains the returned
`publication_ids` field so policy-document–publication edges can be constructed
later by identifier intersection. It also retains publisher organization fields.

It does not retrieve policy-document full text, grant records, or perform
association/causal analyses. All raw queries, responses, records, and manifests
are protected local licensed materials and must not be committed to GitHub.

Example:
    python code/relational/09_retrieve_linked_policy_documents.py \
      --anchor-file /path/to/publication_anchor_final_run.pkl \
      --anchor-manifest-file /path/to/publication_anchor_retrieval_manifest_run.json \
      --api-key-file /path/to/dimensions_api_key.txt \
      --raw-output-dir /path/to/data/02_dimensions_raw/linked_policy_documents_run \
      --policy-file /path/to/data/04_final_linked/linked_policy_documents_final_run.pkl \
      --manifest-file /path/to/data/04_final_linked/linked_policy_documents_retrieval_manifest_run.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import re
import socket
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DEFAULT_DIMENSIONS_BASE_URL = "https://app.dimensions.ai"
DEFAULT_PUBLICATION_BATCH_SIZE = 20
DEFAULT_PAGE_SIZE = 1000
DEFAULT_DELAY_SECONDS = 2.1
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RETRY_ATTEMPTS = 3
EXPECTED_PUBLICATION_RECORDS = 144
USER_AGENT = "FAIRification-institutional-linkages-research/1.0 (linked-policy-document retrieval)"
ANCHOR_REQUIRED_COLUMNS = {"id", "retain_in_final_P"}
POLICY_FIELDS = ["title", "year", "publication_ids", "publisher_org", "publisher_org_country", "publisher_org_city", "linkout"]
POLICY_OUTPUT_COLUMNS = [
    "id",
    "title",
    "year",
    "publication_ids",
    "publisher_org",
    "publisher_org_country",
    "publisher_org_city",
    "linkout",
    "retrieved_by_publication_ids",
    "retrieved_by_publication_count",
    "policy_retrieval_status",
]


class RequestFailure(RuntimeError):
    """Sanitized HTTP or transport failure suitable for local output."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class IncompleteResponse(RuntimeError):
    """Response with warnings, truncation, or an invalid payload shape."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-file", type=Path, required=True)
    parser.add_argument("--anchor-manifest-file", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--raw-output-dir", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--dimensions-base-url", default=DEFAULT_DIMENSIONS_BASE_URL)
    parser.add_argument("--publication-batch-size", type=int, default=DEFAULT_PUBLICATION_BATCH_SIZE)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retry-attempts", type=int, default=DEFAULT_RETRY_ATTEMPTS)
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    if text.casefold() == "nan":
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def parse_list(value: Any) -> list[Any]:
    """Read list-like Dimensions values without inventing identifiers."""
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() == "nan":
            return []
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(text)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
            return parse_list(parsed)
        return [text]
    return [value]


def identifier_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in parse_list(value):
        if isinstance(item, dict):
            identifier = clean_text(item.get("id"))
        else:
            identifier = clean_text(item)
        if identifier and identifier not in result:
            result.append(identifier)
    return result


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def ensure_regular_output_target(path: Path, overwrite: bool) -> None:
    if path.exists() and (path.is_dir() or path.is_symlink()):
        raise ValueError(f"Final output must be a regular file, not a directory or symlink: {path}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}. Use --overwrite only for a documented rerun.")
    path.parent.mkdir(parents=True, exist_ok=True)


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in ("anchor_file", "anchor_manifest_file", "api_key_file", "raw_output_dir", "policy_file", "manifest_file"):
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [args.anchor_file, args.anchor_manifest_file, args.api_key_file]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))
    final_targets = [args.policy_file, args.manifest_file]
    if len(set(final_targets)) != len(final_targets):
        raise ValueError("Policy-record and manifest outputs must use distinct paths.")
    for target in final_targets:
        if target in inputs:
            raise ValueError(f"Final output cannot overwrite an input: {target}")
        ensure_regular_output_target(target, args.overwrite)
    raw = args.raw_output_dir
    if raw.exists() and (raw.is_file() or raw.is_symlink()):
        raise ValueError(f"Raw output path must be a real directory: {raw}")
    for protected in [*inputs, *final_targets]:
        if is_within(protected, raw):
            raise ValueError("Raw output directory must not be an ancestor of an input or final output: " + str(raw))
    if raw.exists() and any(raw.iterdir()):
        raise FileExistsError(
            f"Raw output directory is not empty: {raw}. Choose a new empty directory; raw archives are never deleted."
        )
    raw.mkdir(parents=True, exist_ok=True)
    return args


def atomic_write_json(path: Path, payload: Any) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def atomic_write_pickle(path: Path, frame: pd.DataFrame) -> None:
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            frame.to_pickle(handle)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def redact(value: Any, secrets: Iterable[str]) -> str:
    text = clean_text(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*jwt\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(token\s*[:=]\s*[\"']?)[^\s,;\"']+", r"\1[REDACTED]", text)
    return text[:8000]


def write_raw_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_raw_json(path: Path, payload: Any) -> None:
    write_raw_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_failure_status(raw_dir: Path | None, stage: str, message: str, batch: int | None = None, page: int | None = None) -> None:
    if raw_dir is None or not raw_dir.is_dir():
        return
    atomic_write_json(raw_dir / "retrieval_failure_status.json", {
        "status": "failed",
        "stage": stage,
        "batch": batch,
        "page": page,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "credential_values_stored": False,
    })


def retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    header = error.headers.get("Retry-After") if error.headers else None
    if header:
        try:
            return min(max(float(header), 0.0), 60.0)
        except ValueError:
            pass
    return min(5.0 * attempt, 30.0)


def post_json_response(
    url: str, data: bytes, headers: dict[str, str], timeout: int, retries: int, secrets: Iterable[str]
) -> dict[str, Any]:
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            decoded = json.loads(body.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise RequestFailure("Dimensions returned a JSON value that is not an object.")
            return decoded
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if (error.code == 429 or 500 <= error.code <= 599) and attempt < retries:
                time.sleep(retry_delay(error, attempt))
                continue
            raise RequestFailure(f"HTTP {error.code}: {redact(body, secrets)}", status_code=error.code) from error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
            if attempt < retries:
                time.sleep(min(5.0 * attempt, 30.0))
                continue
            raise RequestFailure(f"Transport failure: {redact(getattr(error, 'reason', error), secrets)}") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestFailure(f"Invalid JSON response: {type(error).__name__}") from error
    raise AssertionError("Retry loop ended unexpectedly.")


def authenticate(base_url: str, api_key: str, timeout: int, retries: int) -> tuple[str, str]:
    auth_url = base_url + "/api/auth"
    response = post_json_response(
        auth_url,
        json.dumps({"key": api_key}).encode("utf-8"),
        {"Content-Type": "application/json", "User-Agent": USER_AGENT},
        timeout,
        retries,
        [api_key],
    )
    token = response.get("token")
    if not isinstance(token, str) or not token.strip():
        raise RequestFailure("Authentication response did not contain a usable query token.")
    return token, auth_url


def build_dsl(publication_ids: list[str], page_size: int, offset: int) -> str:
    quoted = ", ".join(json.dumps(identifier) for identifier in publication_ids)
    fields = "+".join(["id", *POLICY_FIELDS])
    return (
        f"search policy_documents where publication_ids in [{quoted}] "
        f"return policy_documents[{fields}] limit {page_size} skip {offset}"
    )


def policy_page(response: dict[str, Any], page_size: int, offset: int) -> tuple[list[dict[str, Any]], int | None]:
    if response.get("errors"):
        raise IncompleteResponse("Dimensions returned a DSL error payload.")
    policies = response.get("policy_documents")
    if not isinstance(policies, list):
        raise IncompleteResponse("Dimensions response has no policy_documents list; no page was accepted.")
    if response.get("_warnings") or response.get("warnings"):
        raise IncompleteResponse("Dimensions response contains a warning; no potentially incomplete page was accepted.")
    stats = response.get("_stats")
    total = stats.get("total_count") if isinstance(stats, dict) else None
    if total is not None and (not isinstance(total, int) or total < 0):
        raise IncompleteResponse("Dimensions response has an invalid _stats.total_count value.")
    if total is None and len(policies) >= page_size:
        raise IncompleteResponse(
            "Dimensions did not report total_count for a full policy-document page; completeness cannot be established."
        )
    if total is not None and offset + len(policies) > total:
        raise IncompleteResponse("Dimensions returned more policy documents than its reported total_count.")
    if total is not None and len(policies) == 0 and offset < total:
        raise IncompleteResponse("Dimensions returned an empty policy-document page before its reported total_count was reached.")
    return policies, total


def validate_arguments(args: argparse.Namespace) -> None:
    if args.publication_batch_size < 1 or args.publication_batch_size > 100:
        raise ValueError("--publication-batch-size must be between 1 and 100.")
    if args.page_size < 1 or args.page_size > 2000:
        raise ValueError("--page-size must be between 1 and 2000.")
    if args.request_delay_seconds < 0:
        raise ValueError("--request-delay-seconds cannot be negative.")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive.")
    if args.retry_attempts < 1 or args.retry_attempts > 5:
        raise ValueError("--retry-attempts must be between 1 and 5.")
    if args.expected_publication_records < 1:
        raise ValueError("--expected-publication-records must be positive.")
    args.dimensions_base_url = args.dimensions_base_url.strip().rstrip("/")
    if not re.fullmatch(r"https?://[^/]+(?:/[^/]+)*", args.dimensions_base_url):
        raise ValueError("--dimensions-base-url must be an http(s) base URL without an API endpoint suffix.")


def main() -> None:
    raw_dir: Path | None = None
    api_key = ""
    token = ""
    try:
        args = parse_args()
        validate_arguments(args)
        args = preflight_paths(args)
        raw_dir = args.raw_output_dir
        input_hashes = {
            "publication_anchor": sha256(args.anchor_file),
            "publication_anchor_manifest": sha256(args.anchor_manifest_file),
        }
        anchor = pd.read_pickle(args.anchor_file).copy()
        anchor_manifest = json.loads(args.anchor_manifest_file.read_text(encoding="utf-8"))
        if not isinstance(anchor_manifest, dict):
            raise ValueError("Publication-anchor manifest must be a JSON object.")
        missing_columns = sorted(ANCHOR_REQUIRED_COLUMNS.difference(anchor.columns))
        if missing_columns:
            raise ValueError("Publication anchor is missing required columns: " + ", ".join(missing_columns))
        if len(anchor) != args.expected_publication_records:
            raise ValueError(f"Expected {args.expected_publication_records} final publication-anchor records; found {len(anchor)}.")
        anchor["id"] = anchor["id"].map(clean_text)
        if anchor["id"].eq("").any() or anchor["id"].duplicated().any():
            raise ValueError("Publication anchor has blank or duplicate Dimensions publication IDs.")
        retained = anchor["retain_in_final_P"].map(lambda value: clean_text(value).casefold() in {"true", "1", "yes"})
        if not retained.all():
            raise ValueError("Publication anchor contains a record outside the retained final P set.")
        if (
            anchor_manifest.get("outputs", {}).get("returned_records") != args.expected_publication_records
            or anchor_manifest.get("outputs", {}).get("unreturned_records") != 0
        ):
            raise ValueError("Publication-anchor manifest does not certify a complete frozen 144-record anchor.")
        anchor_ids = anchor["id"].tolist()
        anchor_id_set = set(anchor_ids)

        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError("Dimensions API key file is empty.")
        try:
            token, auth_url = authenticate(args.dimensions_base_url, api_key, args.timeout_seconds, args.retry_attempts)
        except RequestFailure as error:
            message = redact(str(error), [api_key, token])
            write_failure_status(raw_dir, "authentication", message)
            raise RuntimeError(f"DIMENSIONS AUTHENTICATION FAILED — {message}") from error

        publication_batches = [
            anchor_ids[index : index + args.publication_batch_size]
            for index in range(0, len(anchor_ids), args.publication_batch_size)
        ]
        query_url = args.dimensions_base_url + "/api/dsl/v2"
        policies_by_id: dict[str, dict[str, Any]] = {}
        provenance_by_policy_id: dict[str, set[str]] = {}
        request_log: list[dict[str, Any]] = []
        request_count = 0

        for batch_number, publication_batch in enumerate(publication_batches, start=1):
            active_ids = set(publication_batch)
            offset = 0
            page_number = 1
            total_count: int | None = None
            records_seen_in_batch = 0
            while total_count is None or offset < total_count:
                query = build_dsl(publication_batch, args.page_size, offset)
                stem = f"batch_{batch_number:03d}_page_{page_number:03d}"
                query_file = raw_dir / f"{stem}_query.dsl"
                response_file = raw_dir / f"{stem}_response.json"
                write_raw_text(query_file, query + "\n")
                try:
                    response = post_json_response(
                        query_url,
                        query.encode("utf-8"),
                        {"Authorization": f"JWT {token}", "User-Agent": USER_AGENT},
                        args.timeout_seconds,
                        args.retry_attempts,
                        [api_key, token],
                    )
                    write_raw_json(response_file, response)
                    policies, returned_total = policy_page(response, args.page_size, offset)
                except (RequestFailure, IncompleteResponse) as error:
                    message = redact(str(error), [api_key, token])
                    write_raw_text(raw_dir / f"{stem}_error.txt", message + "\n")
                    write_failure_status(raw_dir, "linked_policy_document_retrieval", message, batch_number, page_number)
                    raise RuntimeError(f"DIMENSIONS REQUEST FAILED — {message}\nFAILED QUERY FILE: {query_file}") from error

                if total_count is None:
                    total_count = returned_total if returned_total is not None else len(policies)
                elif returned_total is not None and returned_total != total_count:
                    raise RuntimeError("Dimensions policy-document total_count changed between pages of the same batch.")
                for policy in policies:
                    if not isinstance(policy, dict):
                        raise RuntimeError("Dimensions returned a non-object policy-document record.")
                    policy_id = clean_text(policy.get("id"))
                    if not policy_id:
                        raise RuntimeError("Dimensions returned a policy document without an ID.")
                    policy_publication_ids = identifier_list(policy.get("publication_ids", []))
                    matched_ids = sorted(set(policy_publication_ids).intersection(active_ids))
                    if not matched_ids:
                        raise RuntimeError(
                            "Returned policy document does not expose a publication_ids link to an ID in the active request batch."
                        )
                    all_matched_ids = set(policy_publication_ids).intersection(anchor_id_set)
                    if not all_matched_ids:
                        raise RuntimeError("Returned policy document has no publication_ids link to the frozen publication anchor.")
                    existing = policies_by_id.get(policy_id)
                    if existing is not None:
                        if identifier_list(existing.get("publication_ids", [])) != policy_publication_ids:
                            raise RuntimeError("The same policy document ID was returned with inconsistent publication_ids across requests.")
                    else:
                        policies_by_id[policy_id] = policy
                    provenance_by_policy_id.setdefault(policy_id, set()).update(all_matched_ids)
                records_seen_in_batch += len(policies)
                request_count += 1
                request_log.append({
                    "publication_batch": batch_number,
                    "page": page_number,
                    "offset": offset,
                    "request_file": query_file.name,
                    "request_sha256": sha256(query_file),
                    "response_file": response_file.name,
                    "response_sha256": sha256(response_file),
                    "queried_publication_ids": len(publication_batch),
                    "returned_policy_documents_page": len(policies),
                    "reported_total_count_batch": total_count,
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                })
                offset += len(policies)
                if offset < total_count:
                    if not policies:
                        raise RuntimeError("Empty policy-document page encountered before the batch retrieval was complete.")
                    if args.request_delay_seconds:
                        time.sleep(args.request_delay_seconds)
                    page_number += 1
                    continue
                break
            if records_seen_in_batch != total_count:
                raise RuntimeError("Policy-document page counts do not equal the reported batch total_count.")
            if batch_number < len(publication_batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)

        rows: list[dict[str, Any]] = []
        for policy_id in sorted(policies_by_id):
            policy = policies_by_id[policy_id]
            provenance = sorted(provenance_by_policy_id[policy_id])
            rows.append({
                "id": policy_id,
                "title": clean_text(policy.get("title")),
                "year": policy.get("year"),
                "publication_ids": policy.get("publication_ids", []),
                "publisher_org": policy.get("publisher_org", {}),
                "publisher_org_country": policy.get("publisher_org_country", {}),
                "publisher_org_city": policy.get("publisher_org_city", {}),
                "linkout": clean_text(policy.get("linkout")),
                "retrieved_by_publication_ids": provenance,
                "retrieved_by_publication_count": len(provenance),
                "policy_retrieval_status": "returned",
            })
        policies_frame = pd.DataFrame(rows, columns=POLICY_OUTPUT_COLUMNS)
        if policies_frame["id"].duplicated().any():
            raise RuntimeError("The final linked-policy-document table has duplicate policy document IDs.")
        policy_ids_linked_to_multiple_p = int((policies_frame["retrieved_by_publication_count"] > 1).sum())
        years = pd.to_numeric(policies_frame["year"], errors="coerce") if not policies_frame.empty else pd.Series(dtype=float)
        if sha256(args.anchor_file) != input_hashes["publication_anchor"]:
            raise RuntimeError("Publication anchor changed during policy-document retrieval.")
        if sha256(args.anchor_manifest_file) != input_hashes["publication_anchor_manifest"]:
            raise RuntimeError("Publication-anchor manifest changed during policy-document retrieval.")

        try:
            atomic_write_pickle(args.policy_file, policies_frame)
            manifest = {
                "stage": "09_retrieve_linked_policy_documents",
                "status": "complete",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "dimensions_api": {
                    "base_url": args.dimensions_base_url,
                    "authentication_endpoint": auth_url,
                    "query_endpoint": query_url,
                    "api_key_value_stored": False,
                    "query_token_stored": False,
                    "requested_fields": ["id", *POLICY_FIELDS],
                    "policy_document_full_text_requested": False,
                },
                "input": {
                    "publication_anchor_file": str(args.anchor_file),
                    "sha256": input_hashes["publication_anchor"],
                    "publication_records": len(anchor),
                    "anchor_manifest_file": str(args.anchor_manifest_file),
                    "anchor_manifest_sha256": input_hashes["publication_anchor_manifest"],
                },
                "retrieval": {
                    "publication_batch_size": args.publication_batch_size,
                    "page_size": args.page_size,
                    "publication_id_query_batches": len(publication_batches),
                    "api_policy_document_requests": request_count,
                    "raw_output_directory": str(raw_dir),
                    "request_log": request_log,
                },
                "outputs": {
                    "linked_policy_documents_file": str(args.policy_file),
                    "unique_policy_documents_returned": len(policies_frame),
                    "policy_documents_linked_to_more_than_one_retained_publication": policy_ids_linked_to_multiple_p,
                    "minimum_policy_year": int(years.min()) if years.notna().any() else None,
                    "maximum_policy_year": int(years.max()) if years.notna().any() else None,
                },
                "interpretive_boundary": (
                    "Policy-document relationships are Dimensions-recorded identifier links. They do not demonstrate policy "
                    "endorsement, uptake, topical similarity, policy impact, institutional intention, or causal influence."
                ),
                "data_boundary": "Raw responses, linked policy-document records, and this manifest are protected local data and must not be committed to GitHub.",
            }
            atomic_write_json(args.manifest_file, manifest)
            atomic_write_json(raw_dir / "retrieval_success_status.json", {
                "status": "complete",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "credential_values_stored": False,
                "api_policy_document_requests": request_count,
            })
        except Exception as error:
            message = redact(f"Final output promotion failed: {type(error).__name__}: {error}", [api_key, token])
            write_failure_status(raw_dir, "final_output_promotion", message)
            raise RuntimeError(message) from error

        print("LINKED POLICY-DOCUMENT RETRIEVAL: PASS")
        print(f"FINAL PUBLICATION ANCHOR RECORDS: {len(anchor)}")
        print(f"PUBLICATION-ID QUERY BATCHES: {len(publication_batches)}")
        print(f"API POLICY-DOCUMENT REQUESTS: {request_count}")
        print(f"UNIQUE LINKED POLICY DOCUMENTS RETURNED: {len(policies_frame)}")
        print(f"POLICY DOCUMENTS LINKED TO MORE THAN ONE RETAINED PUBLICATION: {policy_ids_linked_to_multiple_p}")
        if years.notna().any():
            print(f"RETURNED POLICY YEAR RANGE: {int(years.min())}-{int(years.max())}")
        else:
            print("RETURNED POLICY YEAR RANGE: unavailable")
        print(f"LINKED POLICY DOCUMENTS WRITTEN: {args.policy_file}")
        print(f"MANIFEST WRITTEN: {args.manifest_file}")
    except KeyboardInterrupt:
        write_failure_status(raw_dir, "interrupted", "Retrieval was interrupted by the user.")
        print("DIMENSIONS RETRIEVAL INTERRUPTED", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        message = redact(str(error), [api_key, token])
        write_failure_status(raw_dir, "failed", message)
        print(message, file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

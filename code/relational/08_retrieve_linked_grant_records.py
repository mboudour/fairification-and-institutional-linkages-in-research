#!/usr/bin/env python3
"""Retrieve grant records linked by the frozen FAIRification publication anchor.

The script reads `supporting_grant_ids` from the already frozen 144-record
publication anchor and retrieves only the corresponding Dimensions grant records.
It preserves the publication-to-grant provenance in each returned grant record.
It does not retrieve policy documents or perform any association analysis.

Returned grant fields are limited to identifier, title, timing, funder, recipient
organization, and country/organization descriptors needed by the next audit and
edge-construction stages. All raw requests, responses, outputs, and manifests
are protected local data and must not be committed to GitHub.

Example:
    python code/relational/08_retrieve_linked_grant_records.py \
      --anchor-file /path/to/publication_anchor_final_run.pkl \
      --anchor-manifest-file /path/to/publication_anchor_retrieval_manifest_run.json \
      --api-key-file /path/to/dimensions_api_key.txt \
      --raw-output-dir /path/to/data/02_dimensions_raw/linked_grants_run \
      --grants-file /path/to/data/04_final_linked/linked_grants_final_run.pkl \
      --unreturned-file /path/to/data/04_final_linked/linked_grant_ids_unreturned_run.csv \
      --manifest-file /path/to/data/04_final_linked/linked_grants_retrieval_manifest_run.json
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
DEFAULT_BATCH_SIZE = 20
DEFAULT_DELAY_SECONDS = 2.1
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RETRY_ATTEMPTS = 3
EXPECTED_PUBLICATION_RECORDS = 144
USER_AGENT = "FAIRification-institutional-linkages-research/1.0 (linked-grant retrieval)"
ANCHOR_REQUIRED_COLUMNS = {"id", "supporting_grant_ids", "retain_in_final_P"}
GRANT_FIELDS = [
    "title",
    "abstract",
    "start_year",
    "start_date",
    "end_date",
    "active_year",
    "funder_orgs",
    "funder_org_name",
    "funder_org_countries",
    "research_orgs",
    "research_org_names",
    "research_org_countries",
    "research_org_types",
    "investigators",
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
    parser.add_argument("--grants-file", type=Path, required=True)
    parser.add_argument("--unreturned-file", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--dimensions-base-url", default=DEFAULT_DIMENSIONS_BASE_URL)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
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
    """Preserve list-like Dimensions values without fabricating identifiers."""
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


def grant_ids(value: Any) -> list[str]:
    identifiers: list[str] = []
    for item in parse_list(value):
        if isinstance(item, dict):
            raise ValueError("supporting_grant_ids contained an object rather than an identifier list.")
        identifier = clean_text(item)
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers


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
    for name in (
        "anchor_file", "anchor_manifest_file", "api_key_file", "raw_output_dir", "grants_file", "unreturned_file", "manifest_file"
    ):
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [args.anchor_file, args.anchor_manifest_file, args.api_key_file]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))
    final_targets = [args.grants_file, args.unreturned_file, args.manifest_file]
    if len(set(final_targets)) != len(final_targets):
        raise ValueError("Grant, unreturned, and manifest files must have distinct paths.")
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


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        try:
            frame.to_csv(handle, index=False)
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


def write_failure_status(raw_dir: Path | None, stage: str, message: str, batch: int | None = None) -> None:
    if raw_dir is None or not raw_dir.is_dir():
        return
    atomic_write_json(raw_dir / "retrieval_failure_status.json", {
        "status": "failed",
        "stage": stage,
        "batch": batch,
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


def build_dsl(ids: list[str]) -> str:
    quoted = ", ".join(json.dumps(identifier) for identifier in ids)
    fields = "+".join(["id", *GRANT_FIELDS])
    return f"search grants where id in [{quoted}] return grants[{fields}] limit 100"


def assert_complete_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("errors"):
        raise IncompleteResponse("Dimensions returned a DSL error payload.")
    grants = response.get("grants")
    if not isinstance(grants, list):
        raise IncompleteResponse("Dimensions response has no grants list; no batch was accepted.")
    if response.get("_warnings") or response.get("warnings"):
        raise IncompleteResponse("Dimensions response contains a warning; no potentially incomplete batch was accepted.")
    stats = response.get("_stats")
    if isinstance(stats, dict) and isinstance(stats.get("total_count"), int) and stats["total_count"] > len(grants):
        raise IncompleteResponse("Dimensions response reports more records than returned; reduce batch size and rerun.")
    return grants


def validate_arguments(args: argparse.Namespace) -> None:
    if args.batch_size < 1 or args.batch_size > 100:
        raise ValueError("--batch-size must be between 1 and 100.")
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
        returned_anchor_records = anchor_manifest.get("outputs", {}).get("returned_records")
        unreturned_anchor_records = anchor_manifest.get("outputs", {}).get("unreturned_records")
        if returned_anchor_records != args.expected_publication_records or unreturned_anchor_records != 0:
            raise ValueError("Publication-anchor manifest does not certify a complete frozen 144-record anchor.")

        publications_by_grant: dict[str, list[str]] = {}
        publications_with_grants = 0
        raw_publication_grant_pairs = 0
        for _, publication in anchor.iterrows():
            ids = grant_ids(publication["supporting_grant_ids"])
            if ids:
                publications_with_grants += 1
            for identifier in ids:
                publications_by_grant.setdefault(identifier, []).append(publication["id"])
                raw_publication_grant_pairs += 1
        for identifier, publication_ids in publications_by_grant.items():
            publications_by_grant[identifier] = sorted(set(publication_ids))
        unique_grant_ids = list(publications_by_grant)
        if not unique_grant_ids:
            raise ValueError("No Dimensions supporting_grant_ids were found in the frozen publication anchor.")

        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError("Dimensions API key file is empty.")
        try:
            token, auth_url = authenticate(args.dimensions_base_url, api_key, args.timeout_seconds, args.retry_attempts)
        except RequestFailure as error:
            message = redact(str(error), [api_key, token])
            write_failure_status(raw_dir, "authentication", message)
            raise RuntimeError(f"DIMENSIONS AUTHENTICATION FAILED — {message}") from error

        batches = [unique_grant_ids[index : index + args.batch_size] for index in range(0, len(unique_grant_ids), args.batch_size)]
        query_url = args.dimensions_base_url + "/api/dsl/v2"
        grants_by_id: dict[str, dict[str, Any]] = {}
        request_log: list[dict[str, Any]] = []
        for batch_number, batch in enumerate(batches, start=1):
            query = build_dsl(batch)
            query_file = raw_dir / f"request_{batch_number:03d}_query.dsl"
            response_file = raw_dir / f"request_{batch_number:03d}_response.json"
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
                grants = assert_complete_response(response)
            except (RequestFailure, IncompleteResponse) as error:
                message = redact(str(error), [api_key, token])
                write_raw_text(raw_dir / f"request_{batch_number:03d}_error.txt", message + "\n")
                write_failure_status(raw_dir, "linked_grant_retrieval", message, batch_number)
                raise RuntimeError(f"DIMENSIONS REQUEST FAILED — {message}\nFAILED QUERY FILE: {query_file}") from error
            active_ids = set(batch)
            for grant in grants:
                if not isinstance(grant, dict):
                    raise RuntimeError("Dimensions returned a non-object grant record.")
                identifier = clean_text(grant.get("id"))
                if identifier not in active_ids:
                    raise RuntimeError("Dimensions returned a grant ID outside the active request batch.")
                if identifier in grants_by_id:
                    raise RuntimeError("Dimensions returned the same grant ID more than once.")
                grants_by_id[identifier] = grant
            request_log.append({
                "batch": batch_number,
                "request_file": query_file.name,
                "request_sha256": sha256(query_file),
                "response_file": response_file.name,
                "response_sha256": sha256(response_file),
                "requested_grant_ids": len(batch),
                "returned_grants": len(grants),
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            })
            if batch_number < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)

        grant_rows: list[dict[str, Any]] = []
        unreturned_rows: list[dict[str, Any]] = []
        for identifier in unique_grant_ids:
            linked_publication_ids = publications_by_grant[identifier]
            grant = grants_by_id.get(identifier)
            if grant is None:
                unreturned_rows.append({
                    "grant_id": identifier,
                    "linked_publication_count": len(linked_publication_ids),
                    "linked_publication_ids": "; ".join(linked_publication_ids),
                    "reason": "No grant record was returned for this supporting_grant_id.",
                })
                continue
            grant_rows.append({
                "id": identifier,
                "title": clean_text(grant.get("title")),
                "abstract": clean_text(grant.get("abstract")),
                "start_year": grant.get("start_year"),
                "start_date": clean_text(grant.get("start_date")),
                "end_date": clean_text(grant.get("end_date")),
                "active_year": grant.get("active_year", []),
                "funder_orgs": grant.get("funder_orgs", []),
                "funder_org_name": grant.get("funder_org_name", []),
                "funder_org_countries": grant.get("funder_org_countries", []),
                "research_orgs": grant.get("research_orgs", []),
                "research_org_names": grant.get("research_org_names", []),
                "research_org_countries": grant.get("research_org_countries", []),
                "research_org_types": grant.get("research_org_types", []),
                "investigators": grant.get("investigators", []),
                "retrieved_from_publication_ids": linked_publication_ids,
                "retrieved_from_publication_count": len(linked_publication_ids),
                "grant_retrieval_status": "returned",
            })
        grants_frame = pd.DataFrame(grant_rows)
        unreturned_frame = pd.DataFrame(unreturned_rows, columns=[
            "grant_id", "linked_publication_count", "linked_publication_ids", "reason"
        ])
        if len(grants_frame) + len(unreturned_frame) != len(unique_grant_ids):
            raise RuntimeError("Returned plus unreturned grant records do not equal the requested grant-ID count.")
        if not grants_frame.empty and grants_frame["id"].duplicated().any():
            raise RuntimeError("The final linked-grants table has duplicate grant IDs.")
        if sha256(args.anchor_file) != input_hashes["publication_anchor"]:
            raise RuntimeError("Publication anchor changed during linked-grant retrieval.")
        if sha256(args.anchor_manifest_file) != input_hashes["publication_anchor_manifest"]:
            raise RuntimeError("Publication-anchor manifest changed during linked-grant retrieval.")

        try:
            atomic_write_pickle(args.grants_file, grants_frame)
            atomic_write_csv(args.unreturned_file, unreturned_frame)
            manifest = {
                "stage": "08_retrieve_linked_grant_records",
                "status": "complete",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "dimensions_api": {
                    "base_url": args.dimensions_base_url,
                    "authentication_endpoint": auth_url,
                    "query_endpoint": query_url,
                    "api_key_value_stored": False,
                    "query_token_stored": False,
                    "requested_fields": ["id", *GRANT_FIELDS],
                    "explicitly_not_retrieved": ["policy_documents", "policy_document content"],
                },
                "input": {
                    "publication_anchor_file": str(args.anchor_file),
                    "sha256": input_hashes["publication_anchor"],
                    "publication_records": len(anchor),
                    "publications_with_supporting_grant_ids": publications_with_grants,
                    "raw_publication_grant_pairs": raw_publication_grant_pairs,
                    "unique_supporting_grant_ids": len(unique_grant_ids),
                    "anchor_manifest_file": str(args.anchor_manifest_file),
                    "anchor_manifest_sha256": input_hashes["publication_anchor_manifest"],
                },
                "retrieval": {
                    "batch_size": args.batch_size,
                    "api_query_batches": len(batches),
                    "raw_output_directory": str(raw_dir),
                    "request_log": request_log,
                },
                "outputs": {
                    "linked_grants_file": str(args.grants_file),
                    "returned_grant_records": len(grants_frame),
                    "unreturned_file": str(args.unreturned_file),
                    "unreturned_grant_ids": len(unreturned_frame),
                },
                "interpretive_boundary": (
                    "Grant records are retrieved because Dimensions linked them to retained publications via supporting_grant_ids. "
                    "These identifier links are database-recorded relationships, not proof of causal funding effects."
                ),
                "data_boundary": "Raw responses, linked grant records, unreturned IDs, and this manifest are protected local data and must not be committed to GitHub.",
            }
            atomic_write_json(args.manifest_file, manifest)
            atomic_write_json(raw_dir / "retrieval_success_status.json", {
                "status": "complete",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "credential_values_stored": False,
                "api_query_batches": len(batches),
            })
        except Exception as error:
            message = redact(f"Final output promotion failed: {type(error).__name__}: {error}", [api_key, token])
            write_failure_status(raw_dir, "final_output_promotion", message)
            raise RuntimeError(message) from error

        print("LINKED GRANT RECORD RETRIEVAL: PASS")
        print(f"FINAL PUBLICATION ANCHOR RECORDS: {len(anchor)}")
        print(f"PUBLICATIONS WITH SUPPORTING-GRANT IDS: {publications_with_grants}")
        print(f"UNIQUE DIMENSIONS GRANT IDS REQUESTED: {len(unique_grant_ids)}")
        print(f"API QUERY BATCHES: {len(batches)}")
        print(f"RETURNED LINKED GRANT RECORDS: {len(grants_frame)}")
        print(f"GRANT IDS NOT RETURNED: {len(unreturned_frame)}")
        print(f"LINKED GRANTS WRITTEN: {args.grants_file}")
        print(f"UNRETURNED LIST WRITTEN: {args.unreturned_file}")
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

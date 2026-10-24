#!/usr/bin/env python3
"""Retrieve identity and text metadata for accepted FAIRification publications.

This script retrieves only the 144 accepted exact-DOI Dimensions publication IDs.
It does not attempt title-based recovery of the 19 unresolved source records and
does not retrieve grants, policy documents, citations, funders, organizations,
affiliations, countries, or other relational outcomes.

It creates protected local outputs: one DSL query and raw JSON response per batch,
a publication text-metadata table, an unreturned accepted-publication table, and a
retrieval manifest. It never prints or saves the API key or JWT token. The raw
output directory must be new or empty and is never deleted by this script.

Example:
    python code/matching/04_retrieve_accepted_publication_text_metadata.py \
      --accepted-file /path/to/accepted_doi_matches_run.csv \
      --api-key-file /path/to/dimensions_api_key.txt \
      --raw-output-dir /path/to/data/02_dimensions_raw/accepted_publication_text_metadata_run \
      --metadata-file /path/to/data/03_matching/accepted_doi_publication_text_metadata_run.csv \
      --unreturned-file /path/to/data/03_matching/accepted_doi_metadata_unreturned_run.csv \
      --manifest-file /path/to/data/03_matching/accepted_doi_publication_text_metadata_manifest_run.json
"""

from __future__ import annotations

import argparse
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
DEFAULT_EXPECTED_ACCEPTED_RECORDS = 144
USER_AGENT = "FAIRification-institutional-linkages-research/1.0 (accepted-publication text metadata)"
ACCEPTED_REQUIRED_COLUMNS = {
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "source_title",
    "source_year",
    "dimensions_publication_ids",
    "match_decision",
}
METADATA_COLUMNS = [
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "source_title",
    "source_year",
    "dimensions_publication_id",
    "dimensions_doi",
    "dimensions_title",
    "dimensions_abstract",
    "dimensions_year",
    "dimensions_date",
    "dimensions_document_type",
    "dimensions_type",
    "dimensions_journal_title_raw",
    "metadata_retrieval_status",
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
    parser.add_argument("--accepted-file", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--raw-output-dir", type=Path, required=True)
    parser.add_argument("--metadata-file", type=Path, required=True)
    parser.add_argument("--unreturned-file", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--dimensions-base-url", default=DEFAULT_DIMENSIONS_BASE_URL)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retry-attempts", type=int, default=DEFAULT_RETRY_ATTEMPTS)
    parser.add_argument("--expected-accepted-records", type=int, default=DEFAULT_EXPECTED_ACCEPTED_RECORDS)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of final output files; the raw-output directory must still be empty.",
    )
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


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def ensure_regular_output_target(path: Path, overwrite: bool) -> None:
    if path.exists() and (path.is_dir() or path.is_symlink()):
        raise ValueError(f"Final output path must be a regular file, not a directory or symlink: {path}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}. Re-run with --overwrite to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in (
        "accepted_file", "api_key_file", "raw_output_dir", "metadata_file", "unreturned_file", "manifest_file"
    ):
        setattr(args, name, resolved(getattr(args, name)))
    if not args.accepted_file.is_file():
        raise FileNotFoundError(f"Accepted DOI matches file not found: {args.accepted_file}")
    if not args.api_key_file.is_file():
        raise FileNotFoundError(f"Dimensions API key file not found: {args.api_key_file}")

    final_targets = [args.metadata_file, args.unreturned_file, args.manifest_file]
    if len(set(final_targets)) != len(final_targets):
        raise ValueError("Metadata, unreturned, and manifest outputs must use distinct paths.")
    inputs = [args.accepted_file, args.api_key_file]
    for target in final_targets:
        if target in inputs:
            raise ValueError(f"Final output cannot overwrite an input file: {target}")
        ensure_regular_output_target(target, args.overwrite)

    raw = args.raw_output_dir
    if raw.exists() and (raw.is_file() or raw.is_symlink()):
        raise ValueError(f"Raw output path must be a real directory: {raw}")
    for protected in [*inputs, *final_targets]:
        if is_within(protected, raw):
            raise ValueError(
                "Raw output directory must not be an ancestor of an input or final output path: "
                f"{raw}"
            )
    if raw.exists() and any(raw.iterdir()):
        raise FileExistsError(
            f"Raw output directory is not empty: {raw}. Choose a new empty directory; this script never deletes raw archives."
        )
    raw.mkdir(parents=True, exist_ok=True)
    return args


def redact(value: Any, secrets: Iterable[str]) -> str:
    text = clean_text(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*jwt\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(token\s*[:=]\s*[\"']?)[^\s,;\"']+", r"\1[REDACTED]", text)
    return text[:8000]


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_raw_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def write_raw_json(path: Path, payload: Any) -> None:
    write_raw_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_failure_status(raw_output_dir: Path | None, stage: str, message: str, batch: int | None = None) -> None:
    if raw_output_dir is None or not raw_output_dir.is_dir():
        return
    atomic_write_json(
        raw_output_dir / "retrieval_failure_status.json",
        {
            "status": "failed",
            "stage": stage,
            "batch": batch,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "credential_values_stored": False,
        },
    )


def retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    header = error.headers.get("Retry-After") if error.headers else None
    if header:
        try:
            return min(max(float(header), 0.0), 60.0)
        except ValueError:
            pass
    return min(5.0 * attempt, 30.0)


def post_json_response(
    url: str,
    data: bytes,
    headers: dict[str, str],
    timeout: int,
    retry_attempts: int,
    secrets: Iterable[str],
) -> dict[str, Any]:
    for attempt in range(1, retry_attempts + 1):
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
            transient = error.code == 429 or 500 <= error.code <= 599
            if transient and attempt < retry_attempts:
                time.sleep(retry_delay(error, attempt))
                continue
            raise RequestFailure(f"HTTP {error.code}: {redact(body, secrets)}", status_code=error.code) from error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            if attempt < retry_attempts:
                time.sleep(min(5.0 * attempt, 30.0))
                continue
            raise RequestFailure(f"Transport failure: {redact(reason, secrets)}") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestFailure(f"Invalid JSON response: {type(error).__name__}") from error
    raise AssertionError("Retry loop terminated unexpectedly.")


def authenticate(base_url: str, api_key: str, timeout: int, retry_attempts: int) -> tuple[str, str]:
    auth_url = base_url.rstrip("/") + "/api/auth"
    response = post_json_response(
        auth_url,
        json.dumps({"key": api_key}).encode("utf-8"),
        {"Content-Type": "application/json", "User-Agent": USER_AGENT},
        timeout,
        retry_attempts,
        [api_key],
    )
    token = response.get("token")
    if not isinstance(token, str) or not token.strip():
        raise RequestFailure("Authentication response did not contain a usable query token.")
    return token, auth_url


def one_dimensions_id(value: Any) -> str:
    values = [item.strip() for item in clean_text(value).split(";") if item.strip()]
    if len(values) != 1:
        raise ValueError("Each accepted DOI match must contain exactly one Dimensions publication ID.")
    return values[0]


def build_dsl(publication_ids: list[str]) -> str:
    quoted = ", ".join(json.dumps(identifier) for identifier in publication_ids)
    fields = "id+doi+title+abstract+year+date+document_type+type+journal_title_raw"
    return f"search publications where id in [{quoted}] return publications[{fields}] limit 100"


def assert_complete_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("errors"):
        raise IncompleteResponse("Dimensions returned a DSL error payload.")
    if "publications" not in response or not isinstance(response["publications"], list):
        raise IncompleteResponse("Dimensions response has no publications list; no output was accepted.")
    if response.get("_warnings") or response.get("warnings"):
        raise IncompleteResponse(
            "Dimensions response contains a truncation or extraction warning; no incomplete batch was accepted."
        )
    stats = response.get("_stats")
    if isinstance(stats, dict) and isinstance(stats.get("total_count"), int):
        if stats["total_count"] > len(response["publications"]):
            raise IncompleteResponse(
                "Dimensions response reports more records than were returned; reduce batch size and retry."
            )
    return response["publications"]


def validate_arguments(args: argparse.Namespace) -> None:
    if args.batch_size < 1 or args.batch_size > 100:
        raise ValueError("--batch-size must be between 1 and 100.")
    if args.request_delay_seconds < 0:
        raise ValueError("--request-delay-seconds cannot be negative.")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive.")
    if args.retry_attempts < 1 or args.retry_attempts > 5:
        raise ValueError("--retry-attempts must be between 1 and 5.")
    if args.expected_accepted_records < 1:
        raise ValueError("--expected-accepted-records must be positive.")
    args.dimensions_base_url = args.dimensions_base_url.strip().rstrip("/")
    if not re.fullmatch(r"https?://[^/]+(?:/[^/]+)*", args.dimensions_base_url):
        raise ValueError("--dimensions-base-url must be an http(s) base URL without an API endpoint suffix.")


def main() -> None:
    raw_output_dir: Path | None = None
    api_key = ""
    token = ""
    try:
        args = parse_args()
        validate_arguments(args)
        args = preflight_paths(args)
        raw_output_dir = args.raw_output_dir

        accepted_hash_before = sha256(args.accepted_file)
        accepted = pd.read_csv(args.accepted_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        missing = sorted(ACCEPTED_REQUIRED_COLUMNS.difference(accepted.columns))
        if missing:
            raise ValueError("Accepted-match file is missing required columns: " + ", ".join(missing))
        if len(accepted) != args.expected_accepted_records:
            raise ValueError(
                f"Expected {args.expected_accepted_records} accepted DOI matches; found {len(accepted)}."
            )
        if accepted["source_record_id"].eq("").any() or accepted["source_record_id"].duplicated().any():
            raise ValueError("Accepted-match file has blank or duplicate source_record_id values.")
        if not accepted["match_decision"].eq("accepted_doi_exact").all():
            raise ValueError("Accepted-match file contains a non-exact-DOI decision.")
        accepted = accepted.copy()
        accepted["dimensions_publication_id"] = accepted["dimensions_publication_ids"].map(one_dimensions_id)
        unique_ids = accepted["dimensions_publication_id"].tolist()
        if len(set(unique_ids)) != len(unique_ids):
            raise ValueError("Accepted-match file maps more than one source record to the same Dimensions publication ID.")

        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError("Dimensions API key file is empty.")
        try:
            token, auth_url = authenticate(
                args.dimensions_base_url, api_key, args.timeout_seconds, args.retry_attempts
            )
        except RequestFailure as error:
            message = redact(str(error), [api_key, token])
            write_failure_status(raw_output_dir, "authentication", message)
            raise RuntimeError(f"DIMENSIONS AUTHENTICATION FAILED — {message}") from error

        batches = [unique_ids[start : start + args.batch_size] for start in range(0, len(unique_ids), args.batch_size)]
        query_url = args.dimensions_base_url + "/api/dsl/v2"
        publication_by_id: dict[str, dict[str, Any]] = {}
        request_log: list[dict[str, Any]] = []
        for batch_number, batch in enumerate(batches, start=1):
            dsl = build_dsl(batch)
            query_file = raw_output_dir / f"request_{batch_number:03d}_query.dsl"
            response_file = raw_output_dir / f"request_{batch_number:03d}_response.json"
            write_raw_text(query_file, dsl + "\n")
            try:
                response = post_json_response(
                    query_url,
                    dsl.encode("utf-8"),
                    {"Authorization": f"JWT {token}", "User-Agent": USER_AGENT},
                    args.timeout_seconds,
                    args.retry_attempts,
                    [api_key, token],
                )
                write_raw_json(response_file, response)
                publications = assert_complete_response(response)
            except (RequestFailure, IncompleteResponse) as error:
                message = redact(str(error), [api_key, token])
                write_raw_text(raw_output_dir / f"request_{batch_number:03d}_error.txt", message + "\n")
                write_failure_status(raw_output_dir, "publication_text_retrieval", message, batch_number)
                raise RuntimeError(
                    f"DIMENSIONS REQUEST FAILED — {message}\nFAILED QUERY FILE: {query_file}"
                ) from error

            current_batch_ids = set(batch)
            for publication in publications:
                if not isinstance(publication, dict):
                    raise RuntimeError("Dimensions returned a non-object publication record.")
                publication_id = clean_text(publication.get("id"))
                if publication_id not in current_batch_ids:
                    raise RuntimeError(
                        "Dimensions returned a publication ID that was not in the current request batch."
                    )
                if publication_id in publication_by_id:
                    raise RuntimeError("Dimensions returned the same publication ID more than once across requests.")
                publication_by_id[publication_id] = publication
            request_log.append(
                {
                    "batch": batch_number,
                    "request_file": query_file.name,
                    "request_sha256": sha256(query_file),
                    "response_file": response_file.name,
                    "response_sha256": sha256(response_file),
                    "requested_publication_ids": len(batch),
                    "returned_publications": len(publications),
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            if batch_number < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)

        metadata_rows: list[dict[str, Any]] = []
        unreturned_rows: list[dict[str, Any]] = []
        for _, match in accepted.iterrows():
            publication_id = match["dimensions_publication_id"]
            publication = publication_by_id.get(publication_id)
            if publication is None:
                unreturned_rows.append(match.to_dict())
                continue
            metadata_rows.append(
                {
                    "source_record_id": clean_text(match["source_record_id"]),
                    "source_record_origin": clean_text(match["source_record_origin"]),
                    "source_doi": clean_text(match["source_doi"]),
                    "source_title": clean_text(match["source_title"]),
                    "source_year": clean_text(match["source_year"]),
                    "dimensions_publication_id": publication_id,
                    "dimensions_doi": clean_text(publication.get("doi")),
                    "dimensions_title": clean_text(publication.get("title")),
                    "dimensions_abstract": clean_text(publication.get("abstract")),
                    "dimensions_year": clean_text(publication.get("year")),
                    "dimensions_date": clean_text(publication.get("date")),
                    "dimensions_document_type": clean_text(publication.get("document_type")),
                    "dimensions_type": clean_text(publication.get("type")),
                    "dimensions_journal_title_raw": clean_text(publication.get("journal_title_raw")),
                    "metadata_retrieval_status": "returned",
                }
            )
        metadata = pd.DataFrame(metadata_rows, columns=METADATA_COLUMNS)
        unreturned = pd.DataFrame(unreturned_rows, columns=list(accepted.columns))
        missing_abstracts = int(metadata["dimensions_abstract"].eq("").sum())

        if sha256(args.accepted_file) != accepted_hash_before:
            raise RuntimeError("Accepted-match file changed during retrieval, which is prohibited.")
        manifest = {
            "stage": "04_retrieve_accepted_publication_text_metadata",
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "Retrieve publication identity and text metadata for accepted exact-DOI matches.",
            "dimensions_api": {
                "base_url": args.dimensions_base_url,
                "authentication_endpoint": auth_url,
                "query_endpoint": query_url,
                "api_key_value_stored": False,
                "query_token_stored": False,
                "requested_fields": [
                    "id", "doi", "title", "abstract", "year", "date", "document_type", "type", "journal_title_raw"
                ],
                "explicitly_not_requested": [
                    "supporting_grant_ids", "policy_documents", "times_cited", "funders", "authors",
                    "research_orgs", "research_org_countries", "affiliations"
                ],
            },
            "input": {
                "accepted_doi_matches_file": str(args.accepted_file),
                "sha256": accepted_hash_before,
                "accepted_source_record_matches": int(len(accepted)),
                "unique_dimensions_publication_ids": int(len(unique_ids)),
            },
            "retrieval": {
                "batch_size": args.batch_size,
                "request_delay_seconds": args.request_delay_seconds,
                "retry_attempts": args.retry_attempts,
                "api_query_batches": len(batches),
                "raw_output_directory": str(raw_output_dir),
                "request_log": request_log,
            },
            "outputs": {
                "metadata_file": str(args.metadata_file),
                "returned_source_records": int(len(metadata)),
                "records_without_abstract": missing_abstracts,
                "unreturned_file": str(args.unreturned_file),
                "source_records_not_returned": int(len(unreturned)),
            },
            "interpretive_boundary": (
                "This retrieval contains no grant, policy-document, citation, funder, institution, country, "
                "affiliation, or other relational outcome fields."
            ),
            "data_boundary": (
                "Raw responses, request DSL, returned metadata, unreturned records, and this manifest are protected "
                "local data and must not be committed to GitHub."
            ),
        }
        try:
            atomic_write_csv(args.metadata_file, metadata)
            atomic_write_csv(args.unreturned_file, unreturned)
            atomic_write_json(args.manifest_file, manifest)
            atomic_write_json(
                raw_output_dir / "retrieval_success_status.json",
                {
                    "status": "complete",
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "api_key_value_stored": False,
                    "query_token_stored": False,
                    "api_query_batches": len(batches),
                },
            )
        except Exception as error:
            message = redact(f"Final output promotion failed: {type(error).__name__}: {error}", [api_key, token])
            write_failure_status(raw_output_dir, "final_output_promotion", message)
            raise RuntimeError(message) from error

        print("DIMENSIONS PUBLICATION TEXT METADATA RETRIEVAL: PASS")
        print(f"ACCEPTED DOI SOURCE RECORDS: {len(accepted)}")
        print(f"UNIQUE DIMENSIONS PUBLICATION IDS REQUESTED: {len(unique_ids)}")
        print(f"API QUERY BATCHES: {len(batches)}")
        print(f"SOURCE RECORDS WITH RETURNED TEXT METADATA: {len(metadata)}")
        print(f"SOURCE RECORDS NOT RETURNED IN TEXT RETRIEVAL: {len(unreturned)}")
        print(f"RETURNED RECORDS WITHOUT ABSTRACT: {missing_abstracts}")
        print(f"METADATA WRITTEN: {args.metadata_file}")
        print(f"UNRETURNED LIST WRITTEN: {args.unreturned_file}")
        print(f"MANIFEST WRITTEN: {args.manifest_file}")
    except KeyboardInterrupt:
        write_failure_status(raw_output_dir, "interrupted", "Retrieval was interrupted by the user.")
        print("DIMENSIONS RETRIEVAL INTERRUPTED", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        message = redact(str(error), [api_key, token])
        write_failure_status(raw_output_dir, "failed", message)
        print(message, file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Retrieve local Dimensions publication candidates for source-cohort DOIs.

The script reads the local source registry, authenticates to the Dimensions
Analytics API using a key held in a local text file, and retrieves publication
identity metadata for each unique normalized source DOI. It writes local-only:

- one DSL query and one raw JSON response per batch;
- a source-to-candidate table;
- source DOI records with no returned candidate;
- unexpected returned records whose DOI was not requested; and
- a retrieval manifest.

It never prints, saves, or commits the API key or JWT token. All outputs are
protected local data and must not be committed to Git. The raw-output directory
must be new or empty; this script never deletes an existing raw archive.

Example:
    python code/matching/02_retrieve_doi_candidates.py \
      --registry-file /path/to/data/03_matching/source_registry.csv \
      --api-key-file /path/to/dimensions_api_key.txt \
      --raw-output-dir /path/to/data/02_dimensions_raw/doi_publication_candidates \
      --candidates-file /path/to/data/03_matching/doi_match_candidates.csv \
      --unreturned-file /path/to/data/03_matching/doi_match_unreturned_source_records.csv \
      --unmapped-file /path/to/data/03_matching/doi_match_unmapped_returned_records.csv \
      --manifest-file /path/to/data/03_matching/doi_match_retrieval_manifest.json

The API implementation follows Dimensions Analytics API documentation:
https://docs.dimensions.ai/dsl/api.html
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
DEFAULT_BATCH_SIZE = 25
DEFAULT_DELAY_SECONDS = 2.1
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RETRY_ATTEMPTS = 3
USER_AGENT = "FAIRification-institutional-linkages-research/1.0 (DOI-first matching)"
REGISTRY_REQUIRED_COLUMNS = {
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "source_doi_normalized",
    "source_title",
    "source_title_normalized",
    "source_authors",
    "source_author_surnames_normalized",
    "source_year",
    "source_journal_title",
    "source_document_type",
}
CANDIDATE_SOURCE_COLUMNS = [
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "source_doi_normalized",
    "source_title",
    "source_title_normalized",
    "source_authors",
    "source_author_surnames_normalized",
    "source_year",
    "source_journal_title",
    "source_document_type",
]
DIMENSIONS_COLUMNS = [
    "dimensions_publication_id",
    "dimensions_doi",
    "dimensions_doi_normalized",
    "dimensions_title",
    "dimensions_year",
    "dimensions_authors_json",
    "dimensions_document_type",
    "dimensions_journal_title_raw",
]
CANDIDATE_COLUMNS = [
    *CANDIDATE_SOURCE_COLUMNS,
    *DIMENSIONS_COLUMNS,
    "retrieval_batch",
    "candidate_rank_for_source_doi",
]
UNMAPPED_COLUMNS = ["retrieval_batch", *DIMENSIONS_COLUMNS, "reason"]


class RequestFailure(RuntimeError):
    """A sanitized HTTP or transport failure suitable for local logging."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class IncompleteResponse(RuntimeError):
    """Dimensions returned a response that must not be treated as complete."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-file", required=True, type=Path)
    parser.add_argument("--api-key-file", required=True, type=Path)
    parser.add_argument("--raw-output-dir", required=True, type=Path)
    parser.add_argument("--candidates-file", required=True, type=Path)
    parser.add_argument("--unreturned-file", required=True, type=Path)
    parser.add_argument("--unmapped-file", required=True, type=Path)
    parser.add_argument("--manifest-file", required=True, type=Path)
    parser.add_argument(
        "--dimensions-base-url",
        default=DEFAULT_DIMENSIONS_BASE_URL,
        help="Dimensions host URL without the API suffix (default: %(default)s).",
    )
    parser.add_argument(
        "--batch-size",
        default=DEFAULT_BATCH_SIZE,
        type=int,
        help="Unique DOIs per DSL request (default: %(default)s).",
    )
    parser.add_argument(
        "--request-delay-seconds",
        default=DEFAULT_DELAY_SECONDS,
        type=float,
        help="Minimum delay between DSL requests (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout-seconds",
        default=DEFAULT_TIMEOUT_SECONDS,
        type=int,
        help="HTTP timeout for each request (default: %(default)s).",
    )
    parser.add_argument(
        "--retry-attempts",
        default=DEFAULT_RETRY_ATTEMPTS,
        type=int,
        help="Attempts for HTTP 429/transient 5xx failures (default: %(default)s).",
    )
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
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def normalize_doi(value: Any) -> str:
    doi = clean_text(value).casefold()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi\s*:\s*", "", doi)
    return doi.strip().rstrip(".,;)")


def scalar(value: Any) -> str:
    """Serialize a Dimensions scalar/list object for a protected local CSV cell."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return clean_text(value)


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


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
    args.registry_file = resolved(args.registry_file)
    args.api_key_file = resolved(args.api_key_file)
    args.raw_output_dir = resolved(args.raw_output_dir)
    args.candidates_file = resolved(args.candidates_file)
    args.unreturned_file = resolved(args.unreturned_file)
    args.unmapped_file = resolved(args.unmapped_file)
    args.manifest_file = resolved(args.manifest_file)

    if not args.registry_file.is_file():
        raise FileNotFoundError(f"Source registry not found: {args.registry_file}")
    if not args.api_key_file.is_file():
        raise FileNotFoundError(f"Dimensions API key file not found: {args.api_key_file}")

    final_targets = [
        args.candidates_file,
        args.unreturned_file,
        args.unmapped_file,
        args.manifest_file,
    ]
    if len(set(final_targets)) != len(final_targets):
        raise ValueError("Candidates, unreturned, unmapped, and manifest outputs must use four distinct paths.")
    inputs = [args.registry_file, args.api_key_file]
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
    """Remove credential material before printing or writing an error status."""
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
    if path.parent.exists():
        path.write_text(content, encoding="utf-8")
    else:
        raise RuntimeError(f"Raw output directory disappeared: {path.parent}")


def write_raw_json(path: Path, payload: Any) -> None:
    write_raw_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_failure_status(raw_output_dir: Path | None, stage: str, message: str, batch: int | None = None) -> None:
    if raw_output_dir is None or not raw_output_dir.is_dir():
        return
    status = {
        "status": "failed",
        "stage": stage,
        "batch": batch,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "credential_values_stored": False,
    }
    atomic_write_json(raw_output_dir / "retrieval_failure_status.json", status)


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
    """POST and decode JSON, retrying rate-limit/transient server errors only."""
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
            raise RequestFailure(
                f"HTTP {error.code}: {redact(body, secrets)}", status_code=error.code
            ) from error
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
    payload = post_json_response(
        auth_url,
        json.dumps({"key": api_key}).encode("utf-8"),
        {"Content-Type": "application/json", "User-Agent": USER_AGENT},
        timeout,
        retry_attempts,
        [api_key],
    )
    token = payload.get("token")
    if not isinstance(token, str) or not token.strip():
        raise RequestFailure("Authentication response did not contain a usable query token.")
    return token, auth_url


def build_dsl(dois: list[str]) -> str:
    quoted = ", ".join(json.dumps(doi) for doi in dois)
    return (
        "search publications where doi in ["
        + quoted
        + "] return publications[id+doi+title+year+authors+document_type+journal_title_raw] limit 1000"
    )


def read_registry(path: Path) -> pd.DataFrame:
    registry = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = sorted(REGISTRY_REQUIRED_COLUMNS.difference(registry.columns))
    if missing:
        raise ValueError("Source registry is missing required columns: " + ", ".join(missing))
    if registry.empty:
        raise ValueError("Source registry has no records.")
    if registry["source_record_id"].eq("").any() or registry["source_record_id"].duplicated().any():
        raise ValueError("source_record_id values must be nonempty and unique.")
    registry["source_doi_normalized"] = registry["source_doi_normalized"].map(normalize_doi)
    doi_registry = registry.loc[registry["source_doi_normalized"].ne("")]
    if doi_registry["source_doi_normalized"].duplicated().any():
        duplicates = doi_registry.loc[
            doi_registry["source_doi_normalized"].duplicated(keep=False), "source_doi_normalized"
        ].tolist()
        raise ValueError("Source registry has duplicated normalized DOI(s): " + ", ".join(sorted(set(duplicates))))
    return registry


def dimensions_fields(record: dict[str, Any]) -> dict[str, str]:
    doi = scalar(record.get("doi"))
    return {
        "dimensions_publication_id": scalar(record.get("id")),
        "dimensions_doi": doi,
        "dimensions_doi_normalized": normalize_doi(doi),
        "dimensions_title": scalar(record.get("title")),
        "dimensions_year": scalar(record.get("year")),
        "dimensions_authors_json": scalar(record.get("authors")),
        "dimensions_document_type": scalar(record.get("document_type")),
        "dimensions_journal_title_raw": scalar(record.get("journal_title_raw")),
    }


def assert_complete_publications_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("errors"):
        raise IncompleteResponse("Dimensions returned a DSL error payload.")
    if "publications" not in response or not isinstance(response["publications"], list):
        raise IncompleteResponse("Dimensions response has no publications list; no output was accepted.")
    warnings = response.get("_warnings") or response.get("warnings")
    if warnings:
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

        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError("Dimensions API key file is empty.")

        registry_hash_before = sha256(args.registry_file)
        registry = read_registry(args.registry_file)
        doi_registry = registry.loc[registry["source_doi_normalized"].ne("")].copy()
        requested_dois = doi_registry["source_doi_normalized"].tolist()
        batches = list(chunks(requested_dois, args.batch_size))
        if not batches:
            raise ValueError("No DOI-bearing source records are available for retrieval.")

        try:
            token, auth_url = authenticate(
                args.dimensions_base_url, api_key, args.timeout_seconds, args.retry_attempts
            )
        except RequestFailure as error:
            message = redact(str(error), [api_key, token])
            write_failure_status(raw_output_dir, "authentication", message)
            raise RuntimeError(f"DIMENSIONS AUTHENTICATION FAILED — {message}") from error

        query_url = args.dimensions_base_url + "/api/dsl/v2"
        source_by_doi = {
            row["source_doi_normalized"]: row.to_dict() for _, row in doi_registry.iterrows()
        }
        candidate_rows: list[dict[str, str]] = []
        unmapped_rows: list[dict[str, str]] = []
        request_log: list[dict[str, Any]] = []

        for batch_number, doi_batch in enumerate(batches, start=1):
            dsl = build_dsl(doi_batch)
            query_path = raw_output_dir / f"request_{batch_number:03d}_query.dsl"
            response_path = raw_output_dir / f"request_{batch_number:03d}_response.json"
            write_raw_text(query_path, dsl + "\n")

            try:
                response = post_json_response(
                    query_url,
                    dsl.encode("utf-8"),
                    {"Authorization": f"JWT {token}", "User-Agent": USER_AGENT},
                    args.timeout_seconds,
                    args.retry_attempts,
                    [api_key, token],
                )
                write_raw_json(response_path, response)
                publications = assert_complete_publications_response(response)
            except (RequestFailure, IncompleteResponse) as error:
                message = redact(str(error), [api_key, token])
                write_raw_text(raw_output_dir / f"request_{batch_number:03d}_error.txt", message + "\n")
                write_failure_status(raw_output_dir, "doi_candidate_retrieval", message, batch_number)
                raise RuntimeError(
                    f"DIMENSIONS REQUEST FAILED — {message}\n"
                    f"FAILED QUERY FILE: {query_path}\n"
                    f"ERROR BODY FILE: {raw_output_dir / f'request_{batch_number:03d}_error.txt'}"
                ) from error

            current_batch_dois = set(doi_batch)
            for record in publications:
                if not isinstance(record, dict):
                    unmapped_rows.append(
                        {
                            "retrieval_batch": str(batch_number),
                            **{column: "" for column in DIMENSIONS_COLUMNS},
                            "reason": "publication_record_is_not_a_JSON_object",
                        }
                    )
                    continue
                dimensions = dimensions_fields(record)
                returned_doi = dimensions["dimensions_doi_normalized"]
                if returned_doi not in current_batch_dois:
                    unmapped_rows.append(
                        {
                            "retrieval_batch": str(batch_number),
                            **dimensions,
                            "reason": "returned_record_doi_not_in_current_batch",
                        }
                    )
                    continue
                requested_source = source_by_doi[returned_doi]
                candidate_rows.append(
                    {
                        **{
                            column: clean_text(requested_source.get(column, ""))
                            for column in CANDIDATE_SOURCE_COLUMNS
                        },
                        **dimensions,
                        "retrieval_batch": str(batch_number),
                        "candidate_rank_for_source_doi": "",
                    }
                )

            request_log.append(
                {
                    "batch": batch_number,
                    "request_file": query_path.name,
                    "request_sha256": sha256(query_path),
                    "response_file": response_path.name,
                    "response_sha256": sha256(response_path),
                    "requested_doi_count": len(doi_batch),
                    "returned_publication_count": len(publications),
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            if batch_number < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)

        candidates = pd.DataFrame(candidate_rows, columns=CANDIDATE_COLUMNS)
        if not candidates.empty:
            candidates["candidate_rank_for_source_doi"] = (
                candidates.groupby("source_doi_normalized").cumcount().add(1).astype(str)
            )
        returned_source_ids = set(candidates["source_record_id"].tolist())
        unreturned = doi_registry.loc[~doi_registry["source_record_id"].isin(returned_source_ids)].copy()
        unmapped = pd.DataFrame(unmapped_rows, columns=UNMAPPED_COLUMNS)

        if sha256(args.registry_file) != registry_hash_before:
            raise RuntimeError("The source registry changed during retrieval, which is prohibited.")

        manifest = {
            "stage": "02_retrieve_doi_candidates",
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_api": {
                "base_url": args.dimensions_base_url,
                "authentication_endpoint": auth_url,
                "query_endpoint": query_url,
                "api_key_file_readable": True,
                "api_key_value_stored": False,
                "query_token_stored": False,
            },
            "input_registry": {
                "path": str(args.registry_file),
                "sha256": registry_hash_before,
                "source_records": int(len(registry)),
                "source_records_with_doi": int(len(doi_registry)),
                "unique_normalized_dois_requested": int(len(requested_dois)),
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
                "candidates_file": str(args.candidates_file),
                "candidate_rows_retrieved": int(len(candidates)),
                "source_records_with_at_least_one_candidate": int(len(returned_source_ids)),
                "unreturned_source_records_file": str(args.unreturned_file),
                "doi_source_records_without_returned_candidate": int(len(unreturned)),
                "unmapped_returned_records_file": str(args.unmapped_file),
                "unmapped_returned_record_count": int(len(unmapped)),
            },
            "data_boundary": (
                "Raw responses, request DSL, candidates, unreturned records, unexpected returned records, "
                "and this manifest are protected local matching materials. They must not be committed to GitHub."
            ),
        }

        # Write complete final outputs only after all batches are accepted and the input hash is unchanged.
        try:
            atomic_write_csv(args.candidates_file, candidates)
            atomic_write_csv(args.unreturned_file, unreturned)
            atomic_write_csv(args.unmapped_file, unmapped)
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

        print("DIMENSIONS DOI CANDIDATE RETRIEVAL: PASS")
        print(f"SOURCE RECORDS WITH DOI: {len(doi_registry)}")
        print(f"UNIQUE DOIS REQUESTED: {len(requested_dois)}")
        print(f"API QUERY BATCHES: {len(batches)}")
        print(f"CANDIDATE ROWS RETRIEVED: {len(candidates)}")
        print(f"SOURCE RECORDS WITH AT LEAST ONE CANDIDATE: {len(returned_source_ids)}")
        print(f"DOI SOURCE RECORDS WITHOUT RETURNED CANDIDATE: {len(unreturned)}")
        print(f"UNMAPPED DIMENSIONS RECORDS: {len(unmapped)}")
        print(f"CANDIDATES WRITTEN: {args.candidates_file}")
        print(f"UNRETURNED LIST WRITTEN: {args.unreturned_file}")
        print(f"UNMAPPED LIST WRITTEN: {args.unmapped_file}")
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

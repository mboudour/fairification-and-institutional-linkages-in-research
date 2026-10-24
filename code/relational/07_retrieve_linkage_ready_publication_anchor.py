#!/usr/bin/env python3
"""Create the protected final publication anchor after the FAIRification NMF freeze.

The script verifies the frozen 144-record text-metadata set and its K=3 NMF
assignments, then retrieves only profile/linkage-ready Dimensions fields for the
same publication IDs: citation count, supporting grant IDs, author affiliation
objects, and organization/country fields. The pre-NMF title/abstract/year fields
are carried forward from the already frozen text-metadata file, not replaced by
this post-freeze retrieval.

The result is a protected local `publication_anchor_final` pickle, which carries
continuous K=3 theme shares and the fixed theme mapping. It also writes raw DSL
queries/responses, an unreturned list, and a manifest locally. The script never
prints or writes the API key or JWT token. It does not retrieve grants or policy
documents themselves; those are separate subsequent steps.

Example:
    python code/relational/07_retrieve_linkage_ready_publication_anchor.py \
      --metadata-file /path/to/accepted_doi_publication_text_metadata_run.csv \
      --metadata-unreturned-file /path/to/accepted_doi_metadata_unreturned_run.csv \
      --k3-assignments-file /path/to/publication_topic_assignments_k3.csv \
      --nmf-manifest-file /path/to/07_publication_nmf_run/manifest.json \
      --api-key-file /path/to/dimensions_api_key.txt \
      --raw-output-dir /path/to/data/02_dimensions_raw/linkage_ready_publication_anchor_run \
      --anchor-file /path/to/data/04_final_linked/publication_anchor_final_run.pkl \
      --unreturned-file /path/to/data/04_final_linked/publication_anchor_unreturned_run.csv \
      --manifest-file /path/to/data/04_final_linked/publication_anchor_retrieval_manifest_run.json
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
EXPECTED_RECORDS = 144
USER_AGENT = "FAIRification-institutional-linkages-research/1.0 (linkage-ready publication anchor)"
METADATA_REQUIRED_COLUMNS = {
    "source_record_id", "source_record_origin", "source_doi", "dimensions_publication_id",
    "dimensions_doi", "dimensions_title", "dimensions_abstract", "dimensions_year",
    "dimensions_date", "dimensions_document_type", "dimensions_type", "dimensions_journal_title_raw",
    "metadata_retrieval_status",
}
K3_REQUIRED_COLUMNS = {
    "n_topics", "id", "title", "year", "has_abstract", "dominant_topic", "dominant_topic_share",
    "normalized_topic_entropy", "topic_1_share", "topic_2_share", "topic_3_share",
}
THEME_LABELS = {
    1: "institutional_stewardship_research_data_management_open_science_practice",
    2: "technical_metadata_semantic_infrastructure_reproducible_workflows",
    3: "digital_cultural_heritage_collections_preservation",
}
THEME_LABELS_DISPLAY = {
    1: "Institutional stewardship, research-data management, and open-science practice",
    2: "Technical metadata, semantic infrastructure, and reproducible workflows",
    3: "Digital cultural heritage, collections, and preservation",
}
RELATIONAL_FIELDS = [
    "times_cited", "supporting_grant_ids", "authors", "research_orgs", "research_org_countries",
    "research_org_names", "research_org_types",
]


class RequestFailure(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class IncompleteResponse(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-file", type=Path, required=True)
    parser.add_argument("--metadata-unreturned-file", type=Path, required=True)
    parser.add_argument("--k3-assignments-file", type=Path, required=True)
    parser.add_argument("--nmf-manifest-file", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--raw-output-dir", type=Path, required=True)
    parser.add_argument("--anchor-file", type=Path, required=True)
    parser.add_argument("--unreturned-file", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--dimensions-base-url", default=DEFAULT_DIMENSIONS_BASE_URL)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--request-delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retry-attempts", type=int, default=DEFAULT_RETRY_ATTEMPTS)
    parser.add_argument("--expected-records", type=int, default=EXPECTED_RECORDS)
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
    value = html.unescape(str(value))
    if value.casefold() == "nan":
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


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
    names = [
        "metadata_file", "metadata_unreturned_file", "k3_assignments_file", "nmf_manifest_file",
        "api_key_file", "raw_output_dir", "anchor_file", "unreturned_file", "manifest_file",
    ]
    for name in names:
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [
        args.metadata_file, args.metadata_unreturned_file, args.k3_assignments_file,
        args.nmf_manifest_file, args.api_key_file,
    ]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))
    final_targets = [args.anchor_file, args.unreturned_file, args.manifest_file]
    if len(set(final_targets)) != len(final_targets):
        raise ValueError("Anchor, unreturned, and manifest files must have distinct paths.")
    for target in final_targets:
        if target in inputs:
            raise ValueError(f"Final output cannot overwrite an input: {target}")
        ensure_regular_output_target(target, args.overwrite)
    if args.raw_output_dir.exists() and (args.raw_output_dir.is_file() or args.raw_output_dir.is_symlink()):
        raise ValueError(f"Raw output path must be a real directory: {args.raw_output_dir}")
    for protected in [*inputs, *final_targets]:
        if is_within(protected, args.raw_output_dir):
            raise ValueError("Raw output directory must not be an ancestor of an input or final output: " + str(args.raw_output_dir))
    if args.raw_output_dir.exists() and any(args.raw_output_dir.iterdir()):
        raise FileExistsError(
            f"Raw output directory is not empty: {args.raw_output_dir}. Choose a new empty directory; raw archives are never deleted."
        )
    args.raw_output_dir.mkdir(parents=True, exist_ok=True)
    return args


def read_csv(path: Path, required: set[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: " + ", ".join(missing))
    return frame


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
        "status": "failed", "stage": stage, "batch": batch,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "message": message, "credential_values_stored": False,
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
    url = base_url + "/api/auth"
    response = post_json_response(
        url, json.dumps({"key": api_key}).encode("utf-8"),
        {"Content-Type": "application/json", "User-Agent": USER_AGENT}, timeout, retries, [api_key],
    )
    token = response.get("token")
    if not isinstance(token, str) or not token.strip():
        raise RequestFailure("Authentication response did not contain a usable query token.")
    return token, url


def build_dsl(ids: list[str]) -> str:
    quoted = ", ".join(json.dumps(identifier) for identifier in ids)
    fields = "+".join(["id", *RELATIONAL_FIELDS])
    return f"search publications where id in [{quoted}] return publications[{fields}] limit 100"


def assert_complete_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("errors"):
        raise IncompleteResponse("Dimensions returned a DSL error payload.")
    publications = response.get("publications")
    if not isinstance(publications, list):
        raise IncompleteResponse("Dimensions response has no publications list; no batch was accepted.")
    if response.get("_warnings") or response.get("warnings"):
        raise IncompleteResponse("Dimensions response contains a warning; no potentially incomplete batch was accepted.")
    stats = response.get("_stats")
    if isinstance(stats, dict) and isinstance(stats.get("total_count"), int) and stats["total_count"] > len(publications):
        raise IncompleteResponse("Dimensions response reports more records than returned; reduce batch size and rerun.")
    return publications


def validate_arguments(args: argparse.Namespace) -> None:
    if args.batch_size < 1 or args.batch_size > 100:
        raise ValueError("--batch-size must be between 1 and 100.")
    if args.request_delay_seconds < 0:
        raise ValueError("--request-delay-seconds cannot be negative.")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive.")
    if args.retry_attempts < 1 or args.retry_attempts > 5:
        raise ValueError("--retry-attempts must be between 1 and 5.")
    if args.expected_records < 1:
        raise ValueError("--expected-records must be positive.")
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
            "metadata": sha256(args.metadata_file),
            "metadata_unreturned": sha256(args.metadata_unreturned_file),
            "k3_assignments": sha256(args.k3_assignments_file),
            "nmf_manifest": sha256(args.nmf_manifest_file),
        }
        metadata = read_csv(args.metadata_file, METADATA_REQUIRED_COLUMNS, "Frozen publication text metadata")
        metadata_unreturned = read_csv(args.metadata_unreturned_file, {"source_record_id"}, "Text-metadata unreturned table")
        assignments = read_csv(args.k3_assignments_file, K3_REQUIRED_COLUMNS, "K=3 NMF assignments")
        nmf_manifest = json.loads(args.nmf_manifest_file.read_text(encoding="utf-8"))
        if not isinstance(nmf_manifest, dict):
            raise ValueError("NMF manifest must be a JSON object.")
        if len(metadata) != args.expected_records or len(assignments) != args.expected_records:
            raise ValueError(f"Both frozen metadata and K=3 assignments must have {args.expected_records} records.")
        if not metadata_unreturned.empty:
            raise ValueError("The frozen text-metadata retrieval includes unreturned records; final anchor cannot be constructed.")
        if metadata["dimensions_publication_id"].map(clean_text).eq("").any() or metadata["dimensions_publication_id"].duplicated().any():
            raise ValueError("Frozen metadata has blank or duplicate Dimensions publication IDs.")
        if metadata["source_record_id"].map(clean_text).eq("").any() or metadata["source_record_id"].duplicated().any():
            raise ValueError("Frozen metadata has blank or duplicate source record IDs.")
        if not metadata["metadata_retrieval_status"].map(clean_text).eq("returned").all():
            raise ValueError("Frozen metadata contains a non-returned record.")
        assignments = assignments.copy()
        assignments["id"] = assignments["id"].map(clean_text)
        if not assignments["n_topics"].map(clean_text).eq("3").all():
            raise ValueError("The NMF assignment input must contain only K=3 assignments.")
        if assignments["id"].eq("").any() or assignments["id"].duplicated().any():
            raise ValueError("K=3 assignments have blank or duplicate Dimensions publication IDs.")
        if set(assignments["id"]) != set(metadata["dimensions_publication_id"].map(clean_text)):
            raise ValueError("K=3 assignment IDs do not exactly match frozen text-metadata Dimensions IDs.")
        metadata_for_nmf_check = metadata.copy()
        metadata_for_nmf_check["dimensions_publication_id"] = metadata_for_nmf_check["dimensions_publication_id"].map(clean_text)
        metadata_for_nmf_check["dimensions_title"] = metadata_for_nmf_check["dimensions_title"].map(clean_text)
        metadata_for_nmf_check["dimensions_year"] = metadata_for_nmf_check["dimensions_year"].map(clean_text)
        metadata_for_nmf_check["dimensions_has_abstract"] = metadata_for_nmf_check["dimensions_abstract"].map(clean_text).ne("")
        assignments_for_nmf_check = assignments.copy()
        assignments_for_nmf_check["title"] = assignments_for_nmf_check["title"].map(clean_text)
        assignments_for_nmf_check["year"] = assignments_for_nmf_check["year"].map(clean_text)
        assignments_for_nmf_check["has_abstract"] = assignments_for_nmf_check["has_abstract"].map(clean_text).str.casefold().eq("true")
        nmf_check = assignments_for_nmf_check.merge(
            metadata_for_nmf_check[["dimensions_publication_id", "dimensions_title", "dimensions_year", "dimensions_has_abstract"]],
            left_on="id", right_on="dimensions_publication_id", how="left", validate="one_to_one",
        )
        if (
            nmf_check["title"].ne(nmf_check["dimensions_title"]).any()
            or nmf_check["year"].ne(nmf_check["dimensions_year"]).any()
            or nmf_check["has_abstract"].ne(nmf_check["dimensions_has_abstract"]).any()
        ):
            raise ValueError("K=3 assignments do not reproduce the frozen title/year/abstract-availability input.")
        topic_values = pd.to_numeric(assignments["dominant_topic"], errors="coerce")
        if topic_values.isna().any() or not set(topic_values.astype(int)).issubset(THEME_LABELS):
            raise ValueError("K=3 dominant_topic values must be integers in {1, 2, 3}.")
        if int(nmf_manifest.get("records", -1)) != args.expected_records or 3 not in nmf_manifest.get("topics_tested", []):
            raise ValueError("NMF manifest does not certify the expected 144-record K=3 diagnostic.")

        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError("Dimensions API key file is empty.")
        try:
            token, auth_url = authenticate(args.dimensions_base_url, api_key, args.timeout_seconds, args.retry_attempts)
        except RequestFailure as error:
            message = redact(str(error), [api_key, token])
            write_failure_status(raw_dir, "authentication", message)
            raise RuntimeError(f"DIMENSIONS AUTHENTICATION FAILED — {message}") from error

        ids = metadata["dimensions_publication_id"].map(clean_text).tolist()
        batches = [ids[i : i + args.batch_size] for i in range(0, len(ids), args.batch_size)]
        query_url = args.dimensions_base_url + "/api/dsl/v2"
        details_by_id: dict[str, dict[str, Any]] = {}
        request_log: list[dict[str, Any]] = []
        for batch_number, batch in enumerate(batches, start=1):
            query = build_dsl(batch)
            query_file = raw_dir / f"request_{batch_number:03d}_query.dsl"
            response_file = raw_dir / f"request_{batch_number:03d}_response.json"
            write_raw_text(query_file, query + "\n")
            try:
                response = post_json_response(
                    query_url, query.encode("utf-8"),
                    {"Authorization": f"JWT {token}", "User-Agent": USER_AGENT},
                    args.timeout_seconds, args.retry_attempts, [api_key, token],
                )
                write_raw_json(response_file, response)
                publications = assert_complete_response(response)
            except (RequestFailure, IncompleteResponse) as error:
                message = redact(str(error), [api_key, token])
                write_raw_text(raw_dir / f"request_{batch_number:03d}_error.txt", message + "\n")
                write_failure_status(raw_dir, "linkage_ready_anchor_retrieval", message, batch_number)
                raise RuntimeError(f"DIMENSIONS REQUEST FAILED — {message}\nFAILED QUERY FILE: {query_file}") from error
            for publication in publications:
                if not isinstance(publication, dict):
                    raise RuntimeError("Dimensions returned a non-object publication record.")
                identifier = clean_text(publication.get("id"))
                if identifier not in set(batch):
                    raise RuntimeError("Dimensions returned a publication ID outside the active request batch.")
                if identifier in details_by_id:
                    raise RuntimeError("Dimensions returned the same publication ID more than once.")
                details_by_id[identifier] = publication
            request_log.append({
                "batch": batch_number, "request_file": query_file.name, "request_sha256": sha256(query_file),
                "response_file": response_file.name, "response_sha256": sha256(response_file),
                "requested_publication_ids": len(batch), "returned_publications": len(publications),
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            })
            if batch_number < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)

        assignment_by_id = assignments.set_index("id", drop=False)
        anchor_rows: list[dict[str, Any]] = []
        unreturned_rows: list[dict[str, Any]] = []
        for _, base in metadata.iterrows():
            identifier = clean_text(base["dimensions_publication_id"])
            details = details_by_id.get(identifier)
            if details is None:
                unreturned_rows.append(base.to_dict())
                continue
            theme = int(pd.to_numeric(assignment_by_id.loc[identifier, "dominant_topic"]))
            assignment = assignment_by_id.loc[identifier]
            anchor_rows.append({
                "id": identifier,
                "source_record_id": clean_text(base["source_record_id"]),
                "source_record_origin": clean_text(base["source_record_origin"]),
                "source_doi": clean_text(base["source_doi"]),
                "doi": clean_text(base["dimensions_doi"]),
                "title": clean_text(base["dimensions_title"]),
                "abstract": clean_text(base["dimensions_abstract"]),
                "year": clean_text(base["dimensions_year"]),
                "date": clean_text(base["dimensions_date"]),
                "document_type": clean_text(base["dimensions_document_type"]),
                "type": clean_text(base["dimensions_type"]),
                "journal_title_raw": clean_text(base["dimensions_journal_title_raw"]),
                "times_cited": details.get("times_cited"),
                "supporting_grant_ids": details.get("supporting_grant_ids", []),
                "authors": details.get("authors", []),
                "research_orgs": details.get("research_orgs", []),
                "research_org_countries": details.get("research_org_countries", []),
                "research_org_names": details.get("research_org_names", []),
                "research_org_types": details.get("research_org_types", []),
                "retain_in_final_P": True,
                "nmf_primary_k": 3,
                "nmf_dominant_theme": theme,
                "nmf_dominant_theme_label": THEME_LABELS[theme],
                "nmf_dominant_theme_label_display": THEME_LABELS_DISPLAY[theme],
                "nmf_dominant_theme_share": float(assignment["dominant_topic_share"]),
                "nmf_normalized_topic_entropy": float(assignment["normalized_topic_entropy"]),
                "nmf_topic_1_share": float(assignment["topic_1_share"]),
                "nmf_topic_2_share": float(assignment["topic_2_share"]),
                "nmf_topic_3_share": float(assignment["topic_3_share"]),
                "text_metadata_retrieval_status": "returned",
                "linkage_ready_retrieval_status": "returned",
            })
        anchor = pd.DataFrame(anchor_rows)
        unreturned = pd.DataFrame(unreturned_rows, columns=list(metadata.columns))
        if len(anchor) + len(unreturned) != args.expected_records:
            raise RuntimeError("Returned plus unreturned anchor records do not equal the frozen P denominator.")
        if sha256(args.metadata_file) != input_hashes["metadata"] or sha256(args.k3_assignments_file) != input_hashes["k3_assignments"]:
            raise RuntimeError("Frozen metadata or K=3 assignments changed during retrieval.")

        try:
            atomic_write_pickle(args.anchor_file, anchor)
            atomic_write_csv(args.unreturned_file, unreturned)
            manifest = {
                "stage": "07_retrieve_linkage_ready_publication_anchor", "status": "complete",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "dimensions_api": {
                    "base_url": args.dimensions_base_url, "authentication_endpoint": auth_url,
                    "query_endpoint": query_url, "api_key_value_stored": False, "query_token_stored": False,
                    "requested_fields": ["id", *RELATIONAL_FIELDS],
                    "explicitly_not_retrieved": ["grants", "policy_documents", "policy_document content"],
                },
                "frozen_inputs": {
                    "text_metadata_file": {"path": str(args.metadata_file), "sha256": input_hashes["metadata"], "records": len(metadata)},
                    "k3_assignments_file": {"path": str(args.k3_assignments_file), "sha256": input_hashes["k3_assignments"], "records": len(assignments)},
                    "nmf_manifest_file": {"path": str(args.nmf_manifest_file), "sha256": input_hashes["nmf_manifest"]},
                },
                "theme_mapping": {str(key): value for key, value in THEME_LABELS.items()},
                "retrieval": {"batch_size": args.batch_size, "api_query_batches": len(batches), "raw_output_directory": str(raw_dir), "request_log": request_log},
                "outputs": {
                    "publication_anchor_file": str(args.anchor_file), "returned_records": len(anchor), "unreturned_file": str(args.unreturned_file), "unreturned_records": len(unreturned),
                },
                "interpretive_boundary": "The retrieved supporting_grant_ids are Dimensions-recorded links, not evidence of causal funding effects. Grant and policy-document records have not yet been retrieved.",
                "data_boundary": "Raw responses, linkage-ready anchor records, unreturned records, and this manifest are protected local data and must not be committed to GitHub.",
            }
            atomic_write_json(args.manifest_file, manifest)
            atomic_write_json(raw_dir / "retrieval_success_status.json", {
                "status": "complete", "created_utc": datetime.now(timezone.utc).isoformat(),
                "credential_values_stored": False, "api_query_batches": len(batches),
            })
        except Exception as error:
            message = redact(f"Final output promotion failed: {type(error).__name__}: {error}", [api_key, token])
            write_failure_status(raw_dir, "final_output_promotion", message)
            raise RuntimeError(message) from error

        support_count = int(anchor["supporting_grant_ids"].map(bool).sum())
        print("LINKAGE-READY PUBLICATION ANCHOR RETRIEVAL: PASS")
        print(f"FROZEN DIMENSIONS PUBLICATIONS: {args.expected_records}")
        print(f"UNIQUE PUBLICATION IDS REQUESTED: {len(ids)}")
        print(f"API QUERY BATCHES: {len(batches)}")
        print(f"RETURNED LINKAGE-READY ANCHOR RECORDS: {len(anchor)}")
        print(f"ANCHOR RECORDS NOT RETURNED: {len(unreturned)}")
        print(f"ANCHOR RECORDS WITH DIMENSIONS SUPPORTING-GRANT IDS: {support_count}")
        print(f"ANCHOR WRITTEN: {args.anchor_file}")
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

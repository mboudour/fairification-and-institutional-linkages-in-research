#!/usr/bin/env python3
"""Validate DOI-first Dimensions publication candidates without querying Dimensions.

The script validates the protected local outputs of
`02_retrieve_doi_candidates.py`. It accepts a match only where one unique source
DOI maps one-to-one to a returned Dimensions publication with the same normalized
DOI. Title similarity and publication-year agreement are descriptive audit flags;
they do not replace the DOI identity rule.

It writes a local decision table, a local accepted-match table, and a local
manifest. It makes zero Dimensions requests. All inputs and outputs are
record-level matching material and must not be committed to Git.

Example:
    python code/matching/03_validate_doi_matches.py \
      --registry-file /path/to/data/03_matching/source_registry.csv \
      --candidates-file /path/to/data/03_matching/doi_match_candidates_run.csv \
      --unreturned-file /path/to/data/03_matching/doi_match_unreturned_source_records_run.csv \
      --unmapped-file /path/to/data/03_matching/doi_match_unmapped_returned_records_run.csv \
      --decisions-file /path/to/data/03_matching/doi_match_decisions_run.csv \
      --accepted-file /path/to/data/03_matching/accepted_doi_matches_run.csv \
      --manifest-file /path/to/data/03_matching/doi_match_validation_manifest_run.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.90
DEFAULT_EXPECTED_SOURCE_RECORDS = 163
DEFAULT_EXPECTED_DOI_RECORDS = 148
REGISTRY_REQUIRED_COLUMNS = {
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "source_doi_normalized",
    "source_title",
    "source_year",
}
CANDIDATE_REQUIRED_COLUMNS = {
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "source_doi_normalized",
    "source_title",
    "source_year",
    "dimensions_publication_id",
    "dimensions_doi",
    "dimensions_title",
    "dimensions_year",
}
UNRETURNED_REQUIRED_COLUMNS = REGISTRY_REQUIRED_COLUMNS
UNMAPPED_REQUIRED_COLUMNS = {"retrieval_batch", "reason"}
DECISION_COLUMNS = [
    "source_record_id",
    "source_record_origin",
    "source_doi",
    "normalized_doi",
    "source_title",
    "source_year",
    "candidate_rows_returned",
    "dimensions_publication_ids",
    "dimensions_dois",
    "dimensions_titles",
    "dimensions_years",
    "title_similarity",
    "title_validation_status",
    "year_validation_status",
    "match_decision",
    "match_reason",
    "review_flag",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-file", required=True, type=Path)
    parser.add_argument("--candidates-file", required=True, type=Path)
    parser.add_argument("--unreturned-file", required=True, type=Path)
    parser.add_argument("--unmapped-file", required=True, type=Path)
    parser.add_argument("--decisions-file", required=True, type=Path)
    parser.add_argument("--accepted-file", required=True, type=Path)
    parser.add_argument("--manifest-file", required=True, type=Path)
    parser.add_argument(
        "--title-similarity-threshold",
        type=float,
        default=DEFAULT_TITLE_SIMILARITY_THRESHOLD,
        help="Flag a non-exact title below this ratio; it does not alter DOI acceptance (default: %(default)s).",
    )
    parser.add_argument(
        "--expected-source-records",
        type=int,
        default=DEFAULT_EXPECTED_SOURCE_RECORDS,
        help="Expected frozen curated source-cohort size (default: %(default)s).",
    )
    parser.add_argument(
        "--expected-doi-records",
        type=int,
        default=DEFAULT_EXPECTED_DOI_RECORDS,
        help="Expected DOI-bearing source-record count (default: %(default)s).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of existing final output files after all validations pass.",
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


def normalize_doi(value: Any) -> str:
    doi = clean_text(value).casefold()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi\s*:\s*", "", doi)
    return doi.strip().rstrip(".,;)")


def normalize_title(value: Any) -> str:
    title = clean_text(value).casefold()
    title = re.sub(r"[^\w\s]", " ", title, flags=re.UNICODE)
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(left: str, right: str) -> float | None:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)
    if not left_normalized or not right_normalized:
        return None
    return round(SequenceMatcher(None, left_normalized, right_normalized).ratio(), 4)


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def ensure_regular_output_target(path: Path, overwrite: bool) -> None:
    if path.exists() and (path.is_dir() or path.is_symlink()):
        raise ValueError(f"Final output path must be a regular file, not a directory or symlink: {path}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}. Re-run with --overwrite to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in (
        "registry_file",
        "candidates_file",
        "unreturned_file",
        "unmapped_file",
        "decisions_file",
        "accepted_file",
        "manifest_file",
    ):
        setattr(args, name, resolved(getattr(args, name)))

    input_paths = [args.registry_file, args.candidates_file, args.unreturned_file, args.unmapped_file]
    missing = [str(path) for path in input_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))

    final_paths = [args.decisions_file, args.accepted_file, args.manifest_file]
    if len(set(final_paths)) != len(final_paths):
        raise ValueError("Decision, accepted-match, and manifest outputs must use distinct paths.")
    for path in final_paths:
        if path in input_paths:
            raise ValueError(f"Final output cannot overwrite an input file: {path}")
        ensure_regular_output_target(path, args.overwrite)
    return args


def read_csv(path: Path, required_columns: set[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = sorted(required_columns.difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: " + ", ".join(missing))
    return frame


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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
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


def unique_nonempty_values(values: pd.Series, normalizer: callable | None = None) -> list[str]:
    observed: list[str] = []
    for value in values:
        cleaned = normalizer(value) if normalizer else clean_text(value)
        if cleaned and cleaned not in observed:
            observed.append(cleaned)
    return observed


def validate_input_relationships(
    registry: pd.DataFrame,
    candidates: pd.DataFrame,
    unreturned: pd.DataFrame,
    unmapped: pd.DataFrame,
    expected_source_records: int,
    expected_doi_records: int,
) -> pd.DataFrame:
    if len(registry) != expected_source_records:
        raise ValueError(f"Expected {expected_source_records} source records; found {len(registry)}.")
    if registry["source_record_id"].eq("").any() or registry["source_record_id"].duplicated().any():
        raise ValueError("The source registry has blank or duplicate source_record_id values.")

    registry = registry.copy()
    registry["source_doi_normalized"] = registry["source_doi_normalized"].map(normalize_doi)
    doi_source = registry.loc[registry["source_doi_normalized"].ne("")].copy()
    if len(doi_source) != expected_doi_records:
        raise ValueError(f"Expected {expected_doi_records} DOI-bearing source records; found {len(doi_source)}.")
    if doi_source["source_doi_normalized"].duplicated().any():
        raise ValueError("Duplicate normalized source DOI(s) prevent automatic DOI acceptance.")

    source_by_id = doi_source.set_index("source_record_id", drop=False)
    candidate_ids = set(candidates["source_record_id"].map(clean_text))
    unreturned_ids = set(unreturned["source_record_id"].map(clean_text))
    if "" in candidate_ids or "" in unreturned_ids:
        raise ValueError("Candidate or unreturned file contains a blank source_record_id.")
    if not candidate_ids.issubset(set(source_by_id.index)):
        raise ValueError("Candidate file includes source records outside the DOI-bearing registry subset.")
    if not unreturned_ids.issubset(set(source_by_id.index)):
        raise ValueError("Unreturned file includes source records outside the DOI-bearing registry subset.")
    if candidate_ids.intersection(unreturned_ids):
        raise ValueError("A source record appears in both candidates and unreturned files.")
    if candidate_ids.union(unreturned_ids) != set(source_by_id.index):
        raise ValueError("Candidates plus unreturned source records do not exactly cover the DOI-bearing registry subset.")
    if unreturned["source_record_id"].map(clean_text).duplicated().any():
        raise ValueError("Unreturned file has duplicate source_record_id values.")
    if not unmapped.empty:
        raise ValueError(
            "The retrieval reported unexpected/unmapped Dimensions records. Resolve that output before validating matches."
        )

    for _, candidate in candidates.iterrows():
        source = source_by_id.loc[clean_text(candidate["source_record_id"])]
        if normalize_doi(candidate["source_doi_normalized"]) != source["source_doi_normalized"]:
            raise ValueError("Candidate table source DOI does not agree with the source registry.")
        if clean_text(candidate["source_record_origin"]) != clean_text(source["source_record_origin"]):
            raise ValueError("Candidate table source-record origin does not agree with the source registry.")
    return doi_source


def build_decisions(
    doi_source: pd.DataFrame,
    candidates: pd.DataFrame,
    title_threshold: float,
) -> pd.DataFrame:
    candidate_groups = {
        source_id: frame.copy()
        for source_id, frame in candidates.groupby("source_record_id", sort=False)
    }
    global_dim_id_sources: dict[str, set[str]] = {}
    for _, candidate in candidates.iterrows():
        dimensions_id = clean_text(candidate["dimensions_publication_id"])
        source_id = clean_text(candidate["source_record_id"])
        if dimensions_id:
            global_dim_id_sources.setdefault(dimensions_id, set()).add(source_id)

    rows: list[dict[str, Any]] = []
    for _, source in doi_source.iterrows():
        source_id = clean_text(source["source_record_id"])
        source_doi = normalize_doi(source["source_doi_normalized"])
        group = candidate_groups.get(source_id, pd.DataFrame())
        if group.empty:
            row = {
                "source_record_id": source_id,
                "source_record_origin": clean_text(source["source_record_origin"]),
                "source_doi": clean_text(source["source_doi"]),
                "normalized_doi": source_doi,
                "source_title": clean_text(source["source_title"]),
                "source_year": clean_text(source["source_year"]),
                "candidate_rows_returned": 0,
                "dimensions_publication_ids": "",
                "dimensions_dois": "",
                "dimensions_titles": "",
                "dimensions_years": "",
                "title_similarity": "",
                "title_validation_status": "not_available",
                "year_validation_status": "not_available",
                "match_decision": "no_doi_candidate_returned",
                "match_reason": "No Dimensions publication was returned for this queried DOI.",
                "review_flag": True,
            }
            rows.append(row)
            continue

        dimensions_ids = unique_nonempty_values(group["dimensions_publication_id"])
        dimensions_dois = unique_nonempty_values(group["dimensions_doi"], normalize_doi)
        dimensions_titles = unique_nonempty_values(group["dimensions_title"])
        dimensions_years = unique_nonempty_values(group["dimensions_year"])
        first = group.iloc[0]
        similarity = title_similarity(source["source_title"], first["dimensions_title"])
        if similarity is None:
            title_status = "not_available"
        elif similarity == 1:
            title_status = "exact_normalized_title"
        elif similarity >= title_threshold:
            title_status = "high_similarity_title"
        else:
            title_status = "low_similarity_title"

        source_year = clean_text(source["source_year"])
        dimensions_year = clean_text(first["dimensions_year"])
        if not source_year or not dimensions_year:
            year_status = "not_available"
        elif source_year == dimensions_year:
            year_status = "exact_year"
        else:
            year_status = "year_difference"

        exact_doi = len(dimensions_dois) == 1 and dimensions_dois[0] == source_doi
        unique_dimension_record = len(dimensions_ids) == 1
        no_cross_source_id_reuse = unique_dimension_record and len(
            global_dim_id_sources.get(dimensions_ids[0], set())
        ) == 1
        if exact_doi and unique_dimension_record and no_cross_source_id_reuse:
            decision = "accepted_doi_exact"
            reason = (
                "One source record with a unique normalized DOI mapped to one Dimensions publication "
                "with the same normalized DOI."
            )
            review_flag = title_status == "low_similarity_title"
        else:
            decision = "doi_candidate_requires_review"
            reasons: list[str] = []
            if not exact_doi:
                reasons.append("returned DOI is not one exact normalized match")
            if not unique_dimension_record:
                reasons.append("candidate set does not contain one Dimensions publication ID")
            if unique_dimension_record and not no_cross_source_id_reuse:
                reasons.append("Dimensions publication ID is associated with more than one source record")
            reason = "; ".join(reasons) + "."
            review_flag = True

        rows.append(
            {
                "source_record_id": source_id,
                "source_record_origin": clean_text(source["source_record_origin"]),
                "source_doi": clean_text(source["source_doi"]),
                "normalized_doi": source_doi,
                "source_title": clean_text(source["source_title"]),
                "source_year": source_year,
                "candidate_rows_returned": int(len(group)),
                "dimensions_publication_ids": "; ".join(dimensions_ids),
                "dimensions_dois": "; ".join(dimensions_dois),
                "dimensions_titles": " || ".join(dimensions_titles),
                "dimensions_years": "; ".join(dimensions_years),
                "title_similarity": similarity if similarity is not None else "",
                "title_validation_status": title_status,
                "year_validation_status": year_status,
                "match_decision": decision,
                "match_reason": reason,
                "review_flag": review_flag,
            }
        )
    return pd.DataFrame(rows, columns=DECISION_COLUMNS)


def main() -> None:
    args = parse_args()
    if not 0 < args.title_similarity_threshold <= 1:
        raise SystemExit("--title-similarity-threshold must be in (0, 1].")
    if args.expected_source_records < 1 or args.expected_doi_records < 1:
        raise SystemExit("Expected-record counts must be positive.")

    args = preflight_paths(args)
    input_hashes_before = {
        "source_registry": sha256(args.registry_file),
        "doi_candidates": sha256(args.candidates_file),
        "unreturned_doi_source_records": sha256(args.unreturned_file),
        "unmapped_returned_records": sha256(args.unmapped_file),
    }
    registry = read_csv(args.registry_file, REGISTRY_REQUIRED_COLUMNS, "Source registry")
    candidates = read_csv(args.candidates_file, CANDIDATE_REQUIRED_COLUMNS, "DOI candidates")
    unreturned = read_csv(args.unreturned_file, UNRETURNED_REQUIRED_COLUMNS, "Unreturned DOI source records")
    unmapped = read_csv(args.unmapped_file, UNMAPPED_REQUIRED_COLUMNS, "Unmapped returned records")

    doi_source = validate_input_relationships(
        registry,
        candidates,
        unreturned,
        unmapped,
        args.expected_source_records,
        args.expected_doi_records,
    )
    decisions = build_decisions(doi_source, candidates, args.title_similarity_threshold)
    accepted = decisions.loc[decisions["match_decision"].eq("accepted_doi_exact")].copy()

    observed_unreturned = set(
        decisions.loc[decisions["match_decision"].eq("no_doi_candidate_returned"), "source_record_id"]
    )
    reported_unreturned = set(unreturned["source_record_id"].map(clean_text))
    if observed_unreturned != reported_unreturned:
        raise RuntimeError("Unreturned-source list does not agree with the DOI-validation decision table.")

    for label, path in {
        "source_registry": args.registry_file,
        "doi_candidates": args.candidates_file,
        "unreturned_doi_source_records": args.unreturned_file,
        "unmapped_returned_records": args.unmapped_file,
    }.items():
        if sha256(path) != input_hashes_before[label]:
            raise RuntimeError(f"Input changed during validation: {path}")

    decision_counts = Counter(decisions["match_decision"])
    title_counts = Counter(decisions["title_validation_status"])
    year_counts = Counter(decisions["year_validation_status"])
    manifest = {
        "stage": "03_validate_doi_matches",
        "status": "complete",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dimensions_requests_made": 0,
        "identity_rule": (
            "Accept only where a unique source DOI maps to exactly one Dimensions publication ID "
            "with the same normalized DOI and that Dimensions ID maps to no other source record."
        ),
        "audit_flags": {
            "title_similarity_method": "difflib.SequenceMatcher on deterministic normalized titles",
            "low_similarity_threshold": args.title_similarity_threshold,
            "year_difference_definition": "nonempty source and Dimensions publication years are not identical",
            "title_and_year_flags_change_doi_acceptance": False,
        },
        "input_files": {
            name: {"path": str(path), "sha256": input_hashes_before[name]}
            for name, path in {
                "source_registry": args.registry_file,
                "doi_candidates": args.candidates_file,
                "unreturned_doi_source_records": args.unreturned_file,
                "unmapped_returned_records": args.unmapped_file,
            }.items()
        },
        "input_counts": {
            "source_registry_records": int(len(registry)),
            "doi_bearing_source_records": int(len(doi_source)),
            "candidate_rows": int(len(candidates)),
            "unreturned_doi_source_records": int(len(unreturned)),
            "unmapped_returned_records": int(len(unmapped)),
        },
        "outputs": {
            "decisions_file": str(args.decisions_file),
            "decision_rows": int(len(decisions)),
            "accepted_matches_file": str(args.accepted_file),
            "accepted_exact_doi_matches": int(len(accepted)),
        },
        "decision_counts": dict(decision_counts),
        "title_validation_counts": dict(title_counts),
        "year_validation_counts": dict(year_counts),
        "interpretive_boundary": (
            "This validates publication identity for DOI matching only. No grants, policy documents, citations, "
            "funders, institutions, countries, or other relational outcomes were used or retrieved."
        ),
        "data_boundary": (
            "All validation inputs, decisions, accepted-match records, and this manifest are protected local data "
            "and must not be committed to GitHub."
        ),
    }

    try:
        atomic_write_csv(args.decisions_file, decisions)
        atomic_write_csv(args.accepted_file, accepted)
        atomic_write_json(args.manifest_file, manifest)
    except Exception as error:
        raise RuntimeError(f"Final output promotion failed: {type(error).__name__}: {error}") from error

    print("DOI MATCH VALIDATION: PASS")
    print(f"DOI SOURCE RECORDS VALIDATED: {len(decisions)}")
    print(f"ACCEPTED EXACT DOI MATCHES: {len(accepted)}")
    print(f"DOI CANDIDATES REQUIRING REVIEW: {decision_counts['doi_candidate_requires_review']}")
    print(f"DOI SOURCE RECORDS WITH NO RETURNED CANDIDATE: {decision_counts['no_doi_candidate_returned']}")
    print(f"LOW TITLE-SIMILARITY FLAGS: {title_counts['low_similarity_title']}")
    print(f"YEAR-DIFFERENCE FLAGS: {year_counts['year_difference']}")
    print("DIMENSIONS REQUESTS: 0")
    print(f"DECISIONS WRITTEN: {args.decisions_file}")
    print(f"ACCEPTED MATCHES WRITTEN: {args.accepted_file}")
    print(f"MANIFEST WRITTEN: {args.manifest_file}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the local source registry for DOI-first Dimensions matching.

This script reads the frozen, curated FAIRification source cohort and writes:

1. a row-level local source registry with stable FAIR-S identifiers and matching
   fields; and
2. a local JSON manifest with hashes, counts, and validation results.

It does not call Dimensions, read `dimensions_api_key.txt`, or alter the source
CSV. The input, registry, and manifest are protected local data and must not be
committed to Git.

Example:
    python code/matching/01_build_source_registry.py \
      --source-file /path/to/libraries_dataset_nq_with_wilkinson_2016.csv \
      --output-file /path/to/data/03_matching/source_registry.csv \
      --manifest-file /path/to/data/03_matching/source_registry_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


MANUAL_ADDITION_DOI = "10.1038/sdata.2016.18"
REQUIRED_SOURCE_COLUMNS = {
    "Authors",
    "Title",
    "Year",
    "Source title",
    "DOI",
    "Document Type",
    "Source",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-file",
        type=Path,
        required=True,
        help="Frozen curated source CSV (163 records); it is read but never modified.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="Local source-registry CSV to create.",
    )
    parser.add_argument(
        "--manifest-file",
        type=Path,
        required=True,
        help="Local source-registry manifest JSON to create.",
    )
    parser.add_argument(
        "--record-prefix",
        default="FAIR-S",
        help="Stable source-record identifier prefix (default: FAIR-S).",
    )
    parser.add_argument(
        "--manual-addition-doi",
        default=MANUAL_ADDITION_DOI,
        help="Normalized DOI identifying the documented manual addition.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: Any) -> str:
    """Return a display-safe scalar without changing source values on disk."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def normalize_text(value: Any) -> str:
    """Produce a deterministic title/author comparison key."""
    text = clean_text(value).casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_doi(value: Any) -> str:
    """Normalize DOI text without inferring a DOI when none is supplied."""
    doi = clean_text(value).casefold()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi\s*:\s*", "", doi)
    return doi.strip().rstrip(".,;)")


def normalize_author_surnames(value: Any) -> str:
    """Derive a conservative semicolon-delimited surname key from Scopus authors."""
    authors = clean_text(value)
    if not authors:
        return ""
    surnames: list[str] = []
    for person in re.split(r"\s*;\s*", authors):
        person = person.strip()
        if not person:
            continue
        surname = person.split(",", maxsplit=1)[0].strip()
        if not surname:
            surname = person.split(maxsplit=1)[0].strip()
        normalized = normalize_text(surname)
        if normalized:
            surnames.append(normalized)
    return "; ".join(surnames)


def source_value(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a clean string Series; optional source columns may be absent."""
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].map(clean_text)


def build_registry(source: pd.DataFrame, prefix: str, manual_doi: str) -> pd.DataFrame:
    title = source_value(source, "Title")
    doi = source_value(source, "DOI")
    authors = source_value(source, "Authors")

    registry = pd.DataFrame(
        {
            "source_record_id": [f"{prefix}-{index:04d}" for index in range(1, len(source) + 1)],
            "source_row_1_indexed": range(1, len(source) + 1),
            "source_record_origin": "original_export",
            "source_doi": doi,
            "source_doi_normalized": doi.map(normalize_doi),
            "source_title": title,
            "source_title_normalized": title.map(normalize_text),
            "source_authors": authors,
            "source_author_surnames_normalized": authors.map(normalize_author_surnames),
            "source_year": source_value(source, "Year"),
            "source_journal_title": source_value(source, "Source title"),
            "source_document_type": source_value(source, "Document Type"),
            "source_volume": source_value(source, "Volume"),
            "source_issue": source_value(source, "Issue"),
            "source_article_number": source_value(source, "Art. No."),
            "source_page_start": source_value(source, "Page start"),
            "source_page_end": source_value(source, "Page end"),
            "source_has_abstract": source_value(source, "Abstract").ne(""),
            "source_has_author_keywords": source_value(source, "Author Keywords").ne(""),
            "source_database": source_value(source, "Source"),
            "source_eid": source_value(source, "EID"),
        }
    )

    manual_rows = registry["source_doi_normalized"].eq(manual_doi)
    if int(manual_rows.sum()) != 1:
        raise ValueError(
            "The documented manual-addition DOI must occur exactly once in the curated cohort; "
            f"found {int(manual_rows.sum())}."
        )
    registry.loc[manual_rows, "source_record_origin"] = "documented_manual_addition"
    return registry


def validate_registry(registry: pd.DataFrame, expected_rows: int) -> dict[str, Any]:
    checks = {
        "registry_row_count_matches_source": len(registry) == expected_rows,
        "source_record_id_is_unique": registry["source_record_id"].is_unique,
        "source_record_id_is_nonempty": registry["source_record_id"].ne("").all(),
        "source_title_is_nonempty": registry["source_title"].ne("").all(),
        "source_doi_normalized_is_unique_when_present": (
            registry.loc[registry["source_doi_normalized"].ne(""), "source_doi_normalized"].is_unique
        ),
        "one_documented_manual_addition": (
            registry["source_record_origin"].eq("documented_manual_addition").sum() == 1
        ),
    }
    failed = [name for name, passed in checks.items() if not bool(passed)]
    if failed:
        raise ValueError("Source-registry validation failed: " + ", ".join(failed))
    return {name: bool(passed) for name, passed in checks.items()}


def main() -> None:
    args = parse_args()
    if not args.source_file.is_file():
        raise SystemExit(f"Source file not found: {args.source_file}")

    manual_doi = normalize_doi(args.manual_addition_doi)
    if not manual_doi:
        raise SystemExit("--manual-addition-doi must normalize to a nonempty DOI.")
    prefix = re.sub(r"\s+", "", args.record_prefix).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_-]*", prefix):
        raise SystemExit("--record-prefix must begin with A-Z and contain only A-Z, 0-9, _ or -.")

    source_hash_before = sha256(args.source_file)
    source = pd.read_csv(args.source_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    source.columns = [str(column).lstrip("\ufeff") for column in source.columns]
    missing = sorted(REQUIRED_SOURCE_COLUMNS.difference(source.columns))
    if missing:
        raise SystemExit("Source CSV is missing required columns: " + ", ".join(missing))
    if source.empty:
        raise SystemExit("Source CSV has no records.")

    registry = build_registry(source, prefix, manual_doi)
    checks = validate_registry(registry, len(source))

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    registry.to_csv(args.output_file, index=False, encoding="utf-8-sig")
    if sha256(args.source_file) != source_hash_before:
        raise RuntimeError("The frozen source CSV changed during the run, which is prohibited.")

    origin_counts = {
        str(key): int(value)
        for key, value in registry["source_record_origin"].value_counts().sort_index().items()
    }
    manifest = {
        "stage": "01_build_source_registry",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(args.source_file),
            "sha256": source_hash_before,
            "rows": int(len(source)),
            "columns": list(source.columns),
        },
        "output": {
            "path": str(args.output_file),
            "sha256": sha256(args.output_file),
            "rows": int(len(registry)),
            "columns": list(registry.columns),
        },
        "source_registry_definition": {
            "record_prefix": prefix,
            "manual_addition_doi_normalized": manual_doi,
            "origin_counts": origin_counts,
            "source_records_with_doi": int(registry["source_doi_normalized"].ne("").sum()),
            "source_records_without_doi": int(registry["source_doi_normalized"].eq("").sum()),
        },
        "validation": checks,
        "data_boundary": (
            "This registry is a local, record-level matching artifact. It must not be committed "
            "to GitHub or redistributed outside the authorized project workspace."
        ),
    }
    args.manifest_file.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("SOURCE REGISTRY: PASS")
    print(f"CURATED RECORDS: {len(registry)}")
    print(
        "ORIGIN COUNTS: "
        + "; ".join(f"{name}={count}" for name, count in origin_counts.items())
    )
    print(f"DOI COVERAGE: {manifest['source_registry_definition']['source_records_with_doi']} with DOI; "
          f"{manifest['source_registry_definition']['source_records_without_doi']} without DOI")
    print("DIMENSIONS REQUESTS: 0")
    print(f"REGISTRY WRITTEN: {args.output_file}")
    print(f"MANIFEST WRITTEN: {args.manifest_file}")


if __name__ == "__main__":
    main()

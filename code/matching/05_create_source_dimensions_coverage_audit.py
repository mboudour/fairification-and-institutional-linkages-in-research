#!/usr/bin/env python3
"""Create the protected local FAIRification source-to-Dimensions coverage audit.

This script makes zero API requests. It compares the frozen 163-record source
registry, DOI match decisions, and text metadata for the accepted matched
publications. It retains every source record in the audit, including the 19 that
were not recovered by the prespecified DOI-first procedure. Those unresolved
records are not classified as absent from Dimensions.

The script writes a record-level audit, aggregate summaries, subgroup summaries,
and a manifest to one new or empty local output directory. None of these outputs
may be committed to GitHub.

Example:
    python code/matching/05_create_source_dimensions_coverage_audit.py \
      --registry-file /path/to/source_registry.csv \
      --decisions-file /path/to/doi_match_decisions_run.csv \
      --metadata-file /path/to/accepted_doi_publication_text_metadata_run.csv \
      --metadata-unreturned-file /path/to/accepted_doi_metadata_unreturned_run.csv \
      --output-dir /path/to/data/03_matching/coverage_audit_run
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


EXPECTED_SOURCE_RECORDS = 163
EXPECTED_ACCEPTED_RECORDS = 144
EXPECTED_UNRESOLVED_RECORDS = 19
REGISTRY_REQUIRED_COLUMNS = {
    "source_record_id",
    "source_row_1_indexed",
    "source_record_origin",
    "source_doi",
    "source_doi_normalized",
    "source_title",
    "source_year",
    "source_document_type",
    "source_database",
    "source_has_abstract",
}
DECISIONS_REQUIRED_COLUMNS = {"source_record_id", "match_decision"}
METADATA_REQUIRED_COLUMNS = {
    "source_record_id",
    "source_record_origin",
    "dimensions_publication_id",
    "dimensions_abstract",
    "metadata_retrieval_status",
}
OUTPUT_FILES = {
    "record_level": "source_dimensions_coverage_record_level.csv",
    "overall": "source_dimensions_coverage_overall.csv",
    "by_year": "source_dimensions_coverage_by_year.csv",
    "by_document_type": "source_dimensions_coverage_by_document_type.csv",
    "by_doi": "source_dimensions_coverage_by_doi_availability.csv",
    "by_source_abstract": "source_dimensions_coverage_by_source_abstract.csv",
    "by_origin": "source_dimensions_coverage_by_source_origin.csv",
    "text_coverage": "dimensions_subset_text_coverage.csv",
    "manifest": "source_dimensions_coverage_audit_manifest.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-file", type=Path, required=True)
    parser.add_argument("--decisions-file", type=Path, required=True)
    parser.add_argument("--metadata-file", type=Path, required=True)
    parser.add_argument("--metadata-unreturned-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source-records", type=int, default=EXPECTED_SOURCE_RECORDS)
    parser.add_argument("--expected-accepted-records", type=int, default=EXPECTED_ACCEPTED_RECORDS)
    parser.add_argument("--expected-unresolved-records", type=int, default=EXPECTED_UNRESOLVED_RECORDS)
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


def bool_from_text(value: Any) -> bool:
    return clean_text(value).casefold() in {"true", "1", "yes"}


def category(value: Any, missing_label: str = "Missing") -> str:
    return clean_text(value) or missing_label


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in ("registry_file", "decisions_file", "metadata_file", "metadata_unreturned_file", "output_dir"):
        setattr(args, name, resolved(getattr(args, name)))
    input_paths = [args.registry_file, args.decisions_file, args.metadata_file, args.metadata_unreturned_file]
    missing = [str(path) for path in input_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))
    if args.output_dir.exists() and (args.output_dir.is_file() or args.output_dir.is_symlink()):
        raise ValueError(f"Output path must be a real directory: {args.output_dir}")
    for input_path in input_paths:
        if is_within(input_path, args.output_dir):
            raise ValueError("Output directory must not be an ancestor of an input file: " + str(args.output_dir))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {args.output_dir}. Choose a new empty directory; this script never deletes audit outputs."
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


def read_csv(path: Path, required: set[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = sorted(required.difference(frame.columns))
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


def group_summary(frame: pd.DataFrame, variable: str, variable_label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for level, group in frame.groupby(variable, dropna=False, sort=True):
        total = len(group)
        recovered = int(group["in_dimensions_analytic_subset"].sum())
        rows.append(
            {
                "variable": variable_label,
                "level": category(level),
                "source_records": total,
                "dimensions_recovered_records": recovered,
                "not_recovered_by_doi_first_procedure": total - recovered,
                "recovery_rate_pct": round(100 * recovered / total, 3) if total else "",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    if min(args.expected_source_records, args.expected_accepted_records, args.expected_unresolved_records) < 1:
        raise SystemExit("Expected record counts must be positive.")
    args = preflight_paths(args)
    input_hashes = {
        "source_registry": sha256(args.registry_file),
        "doi_match_decisions": sha256(args.decisions_file),
        "accepted_publication_text_metadata": sha256(args.metadata_file),
        "accepted_metadata_unreturned": sha256(args.metadata_unreturned_file),
    }

    registry = read_csv(args.registry_file, REGISTRY_REQUIRED_COLUMNS, "Source registry")
    decisions = read_csv(args.decisions_file, DECISIONS_REQUIRED_COLUMNS, "DOI decision table")
    metadata = read_csv(args.metadata_file, METADATA_REQUIRED_COLUMNS, "Publication text metadata")
    metadata_unreturned = read_csv(
        args.metadata_unreturned_file, {"source_record_id"}, "Text-metadata unreturned table"
    )

    if len(registry) != args.expected_source_records:
        raise ValueError(f"Expected {args.expected_source_records} source records; found {len(registry)}.")
    if registry["source_record_id"].eq("").any() or registry["source_record_id"].duplicated().any():
        raise ValueError("Source registry has blank or duplicate source_record_id values.")
    if len(decisions) != int(registry["source_doi_normalized"].map(clean_text).ne("").sum()):
        raise ValueError("DOI decision-table rows do not equal the DOI-bearing source-record count.")
    if decisions["source_record_id"].eq("").any() or decisions["source_record_id"].duplicated().any():
        raise ValueError("DOI decision table has blank or duplicate source_record_id values.")
    if not set(decisions["source_record_id"]).issubset(set(registry["source_record_id"])):
        raise ValueError("DOI decision table contains a source_record_id absent from the registry.")
    doi_registry_ids = set(
        registry.loc[registry["source_doi_normalized"].map(clean_text).ne(""), "source_record_id"].map(clean_text)
    )
    if set(decisions["source_record_id"].map(clean_text)) != doi_registry_ids:
        raise ValueError("DOI decision table does not exactly cover the DOI-bearing source-record set.")

    accepted_decision_ids = set(
        decisions.loc[decisions["match_decision"].eq("accepted_doi_exact"), "source_record_id"].map(clean_text)
    )
    if len(accepted_decision_ids) != args.expected_accepted_records:
        raise ValueError(
            f"Expected {args.expected_accepted_records} accepted DOI decisions; found {len(accepted_decision_ids)}."
        )
    if len(metadata) != args.expected_accepted_records:
        raise ValueError(
            f"Expected {args.expected_accepted_records} returned text-metadata records; found {len(metadata)}."
        )
    if not metadata_unreturned.empty:
        raise ValueError("Accepted-publication text retrieval has unreturned records; resolve before freezing the coverage audit.")
    if metadata["source_record_id"].eq("").any() or metadata["source_record_id"].duplicated().any():
        raise ValueError("Publication text metadata has blank or duplicate source_record_id values.")
    if metadata["dimensions_publication_id"].eq("").any() or metadata["dimensions_publication_id"].duplicated().any():
        raise ValueError("Publication text metadata has blank or duplicate Dimensions publication IDs.")
    metadata_ids = set(metadata["source_record_id"].map(clean_text))
    if metadata_ids != accepted_decision_ids:
        raise ValueError("Text-metadata source IDs do not exactly equal the accepted exact-DOI match set.")

    decision_by_id = decisions.set_index("source_record_id", drop=False)
    metadata_by_id = metadata.set_index("source_record_id", drop=False)
    rows: list[dict[str, Any]] = []
    for _, source in registry.iterrows():
        source_id = clean_text(source["source_record_id"])
        included = source_id in metadata_ids
        has_doi = bool(clean_text(source["source_doi_normalized"]))
        if included:
            dimensions = metadata_by_id.loc[source_id]
            status = "dimensions_recovered_exact_doi"
            reason = "Accepted one-to-one exact normalized DOI match; publication text metadata returned."
            dimensions_id = clean_text(dimensions["dimensions_publication_id"])
            has_dimensions_abstract: bool | str = bool(clean_text(dimensions["dimensions_abstract"]))
        elif not has_doi:
            status = "unresolved_source_doi_missing"
            reason = "No source DOI was available; title-based fallback was not used for the primary matching decision."
            dimensions_id = ""
            has_dimensions_abstract = ""
        else:
            decision = clean_text(decision_by_id.loc[source_id, "match_decision"])
            if decision == "no_doi_candidate_returned":
                status = "unresolved_doi_not_returned_by_dimensions"
                reason = "The source DOI was queried but no Dimensions publication candidate was returned."
            else:
                status = "unresolved_other_doi_matching_status"
                reason = f"DOI matching decision: {decision}."
            dimensions_id = ""
            has_dimensions_abstract = ""
        rows.append(
            {
                "source_record_id": source_id,
                "source_row_1_indexed": clean_text(source["source_row_1_indexed"]),
                "source_record_origin": category(source["source_record_origin"]),
                "source_doi": clean_text(source["source_doi"]),
                "source_title": clean_text(source["source_title"]),
                "source_year": category(source["source_year"]),
                "source_document_type": category(source["source_document_type"]),
                "source_database": category(source["source_database"]),
                "has_source_doi": has_doi,
                "has_source_abstract": bool_from_text(source["source_has_abstract"]),
                "in_dimensions_analytic_subset": included,
                "dimensions_publication_id": dimensions_id,
                "has_dimensions_abstract": has_dimensions_abstract,
                "coverage_status": status,
                "coverage_reason": reason,
            }
        )
    audit = pd.DataFrame(rows)
    recovered = int(audit["in_dimensions_analytic_subset"].sum())
    unresolved = int((~audit["in_dimensions_analytic_subset"]).sum())
    if recovered != args.expected_accepted_records or unresolved != args.expected_unresolved_records:
        raise RuntimeError("Coverage audit does not match the expected recovered/unresolved denominators.")
    manual_addition = audit.loc[audit["source_record_origin"].eq("documented_manual_addition")]
    if len(manual_addition) != 1:
        raise RuntimeError("The coverage audit must contain exactly one documented manual addition.")
    if not bool(manual_addition.iloc[0]["in_dimensions_analytic_subset"]):
        raise RuntimeError("The documented manual addition was not recovered in the Dimensions analytic subset.")

    audit["source_year_group"] = audit["source_year"].map(category)
    audit["source_document_type_group"] = audit["source_document_type"].map(category)
    audit["source_doi_availability_group"] = audit["has_source_doi"].map(
        {True: "DOI available", False: "DOI missing"}
    )
    audit["source_abstract_availability_group"] = audit["has_source_abstract"].map(
        {True: "Abstract available", False: "Abstract missing"}
    )
    included = audit.loc[audit["in_dimensions_analytic_subset"]].copy()
    overall = pd.DataFrame(
        [{
            "source_cohort_records": len(audit),
            "dimensions_recovered_analytic_records": recovered,
            "not_recovered_by_doi_first_procedure": unresolved,
            "dimensions_recovery_rate_pct": round(100 * recovered / len(audit), 3),
            "source_records_with_doi": int(audit["has_source_doi"].sum()),
            "source_records_without_doi": int((~audit["has_source_doi"]).sum()),
            "unresolved_source_doi_missing": int(audit["coverage_status"].eq("unresolved_source_doi_missing").sum()),
            "unresolved_doi_not_returned_by_dimensions": int(
                audit["coverage_status"].eq("unresolved_doi_not_returned_by_dimensions").sum()
            ),
            "manual_addition_source_records": int(audit["source_record_origin"].eq("documented_manual_addition").sum()),
            "manual_addition_recovered": bool(manual_addition.iloc[0]["in_dimensions_analytic_subset"]),
        }]
    )
    text_coverage = pd.DataFrame(
        [{
            "dimensions_analytic_records": len(included),
            "records_with_dimensions_abstract": int(included["has_dimensions_abstract"].map(bool).sum()),
            "records_without_dimensions_abstract": int((~included["has_dimensions_abstract"].map(bool)).sum()),
            "dimensions_abstract_coverage_pct": round(100 * included["has_dimensions_abstract"].map(bool).mean(), 3),
            "NMF_text_rule": "Use Dimensions title twice plus abstract when available; use title twice alone when the Dimensions abstract is absent.",
        }]
    )
    outputs = {
        "record_level": audit,
        "overall": overall,
        "by_year": group_summary(audit, "source_year_group", "source_publication_year"),
        "by_document_type": group_summary(audit, "source_document_type_group", "source_document_type"),
        "by_doi": group_summary(audit, "source_doi_availability_group", "source_doi_availability"),
        "by_source_abstract": group_summary(audit, "source_abstract_availability_group", "source_abstract_availability"),
        "by_origin": group_summary(audit, "source_record_origin", "source_record_origin"),
        "text_coverage": text_coverage,
    }

    for name, path in {
        "source_registry": args.registry_file,
        "doi_match_decisions": args.decisions_file,
        "accepted_publication_text_metadata": args.metadata_file,
        "accepted_metadata_unreturned": args.metadata_unreturned_file,
    }.items():
        if sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during coverage audit: {path}")

    output_paths = {name: args.output_dir / filename for name, filename in OUTPUT_FILES.items()}
    try:
        for name, frame in outputs.items():
            atomic_write_csv(output_paths[name], frame)
        manifest = {
            "stage": "05_create_source_dimensions_coverage_audit",
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "purpose": "Describe recovery of the 144-record Dimensions analytic subset relative to the frozen 163-record source cohort.",
            "input_files": {
                name: {"path": str(path), "sha256": input_hashes[name]}
                for name, path in {
                    "source_registry": args.registry_file,
                    "doi_match_decisions": args.decisions_file,
                    "accepted_publication_text_metadata": args.metadata_file,
                    "accepted_metadata_unreturned": args.metadata_unreturned_file,
                }.items()
            },
            "denominators": {
                "frozen_source_cohort": len(audit),
                "dimensions_recovered_analytic_subset": recovered,
                "not_recovered_by_doi_first_procedure": unresolved,
            },
            "manual_addition": {
                "source_record_origin": "documented_manual_addition",
                "dimensions_recovered": True,
            },
            "outputs": {
                name: {"path": str(path), "sha256": sha256(path), "rows": int(len(outputs[name]))}
                for name, path in output_paths.items() if name != "manifest"
            },
            "interpretive_boundary": (
                "The audit describes recovery by the prespecified DOI-first procedure. The 19 unresolved records "
                "are retained in the audit and are not classified as absent from Dimensions."
            ),
            "data_boundary": "All audit outputs are protected local data and must not be committed to GitHub.",
        }
        atomic_write_json(output_paths["manifest"], manifest)
    except Exception as error:
        raise RuntimeError(f"Audit-output write failed: {type(error).__name__}: {error}") from error

    without_abstract = int((~included["has_dimensions_abstract"].map(bool)).sum())
    print("SOURCE-TO-DIMENSIONS COVERAGE AUDIT: PASS")
    print(f"SOURCE COHORT: {len(audit)}")
    print(f"DIMENSIONS-RECOVERED ANALYTIC SUBSET: {recovered}")
    print(f"RECOVERY RATE: {100 * recovered / len(audit):.3f}%")
    print(f"UNRESOLVED SOURCE RECORDS RETAINED IN AUDIT: {unresolved}")
    print(f"DIMENSIONS SUBSET RECORDS WITHOUT ABSTRACT: {without_abstract}")
    print("DOCUMENTED MANUAL ADDITION RECOVERED: True")
    print("DIMENSIONS REQUESTS: 0")
    print(f"RECORD-LEVEL AUDIT: {output_paths['record_level']}")
    print(f"OVERALL SUMMARY: {output_paths['overall']}")
    print(f"MANIFEST: {output_paths['manifest']}")


if __name__ == "__main__":
    main()

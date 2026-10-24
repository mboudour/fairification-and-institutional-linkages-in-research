#!/usr/bin/env python3
"""Prepare the protected local input file for FAIRification publication-only NMF.

This script makes zero Dimensions requests and fits no model. It validates the
144 returned accepted-publication text-metadata records against the local text
coverage audit, then writes the four generic fields expected by
`publication_topic_model_diagnostic.py`: id, title, abstract, and year.

No grant, policy document, citation, funder, organization, country, affiliation,
or other relational field is read. The pickle and manifest are protected local
data and must not be committed to GitHub.

Example:
    python code/thematic/prepare_nmf_input.py \
      --metadata-file /path/to/accepted_doi_publication_text_metadata_run.csv \
      --metadata-unreturned-file /path/to/accepted_doi_metadata_unreturned_run.csv \
      --text-coverage-file /path/to/dimensions_subset_text_coverage.csv \
      --output-pickle /path/to/computations/inputs/publication_anchor_for_nmf_run.pkl \
      --manifest-file /path/to/computations/inputs/publication_anchor_for_nmf_manifest_run.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


EXPECTED_RECORDS = 144
EXPECTED_RECORDS_WITHOUT_ABSTRACT = 4
METADATA_REQUIRED_COLUMNS = {
    "source_record_id",
    "dimensions_publication_id",
    "dimensions_title",
    "dimensions_abstract",
    "dimensions_year",
    "metadata_retrieval_status",
}
TEXT_COVERAGE_REQUIRED_COLUMNS = {
    "dimensions_analytic_records",
    "records_without_dimensions_abstract",
    "NMF_text_rule",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-file", type=Path, required=True)
    parser.add_argument("--metadata-unreturned-file", type=Path, required=True)
    parser.add_argument("--text-coverage-file", type=Path, required=True)
    parser.add_argument("--output-pickle", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--expected-records", type=int, default=EXPECTED_RECORDS)
    parser.add_argument(
        "--expected-records-without-abstract",
        type=int,
        default=EXPECTED_RECORDS_WITHOUT_ABSTRACT,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of existing final outputs after all validations pass.",
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
    result = str(value).strip()
    return "" if result.casefold() == "nan" else result


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
        "metadata_file", "metadata_unreturned_file", "text_coverage_file", "output_pickle", "manifest_file"
    ):
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [args.metadata_file, args.metadata_unreturned_file, args.text_coverage_file]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))
    if args.output_pickle == args.manifest_file:
        raise ValueError("NMF input pickle and manifest must use distinct paths.")
    for output in [args.output_pickle, args.manifest_file]:
        if output in inputs:
            raise ValueError(f"Final output cannot overwrite an input file: {output}")
        ensure_regular_output_target(output, args.overwrite)
    return args


def read_csv(path: Path, required: set[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: " + ", ".join(missing))
    return frame


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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
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


def main() -> None:
    args = parse_args()
    if args.expected_records < 1 or args.expected_records_without_abstract < 0:
        raise SystemExit("Expected record counts must be non-negative, with --expected-records positive.")
    args = preflight_paths(args)
    input_hashes = {
        "accepted_publication_text_metadata": sha256(args.metadata_file),
        "accepted_metadata_unreturned": sha256(args.metadata_unreturned_file),
        "dimensions_subset_text_coverage": sha256(args.text_coverage_file),
    }

    metadata = read_csv(args.metadata_file, METADATA_REQUIRED_COLUMNS, "Publication text metadata")
    unreturned = read_csv(args.metadata_unreturned_file, {"source_record_id"}, "Text-metadata unreturned table")
    text_coverage = read_csv(args.text_coverage_file, TEXT_COVERAGE_REQUIRED_COLUMNS, "Text-coverage audit")
    if len(metadata) != args.expected_records:
        raise ValueError(f"Expected {args.expected_records} text-metadata records; found {len(metadata)}.")
    if not unreturned.empty:
        raise ValueError("Text-metadata unreturned table is nonempty; NMF input cannot be frozen.")
    if len(text_coverage) != 1:
        raise ValueError("Text-coverage audit must have exactly one summary row.")
    coverage_row = text_coverage.iloc[0]
    try:
        audited_records = int(clean_text(coverage_row["dimensions_analytic_records"]))
        audited_missing_abstracts = int(clean_text(coverage_row["records_without_dimensions_abstract"]))
    except ValueError as error:
        raise ValueError("Text-coverage audit has non-integer record counts.") from error
    if audited_records != args.expected_records:
        raise ValueError("Text-coverage audit record count disagrees with the expected NMF population.")
    if audited_missing_abstracts != args.expected_records_without_abstract:
        raise ValueError("Text-coverage audit abstract-missing count disagrees with the expected NMF specification.")

    metadata = metadata.copy()
    for column in ["source_record_id", "dimensions_publication_id", "dimensions_title", "dimensions_abstract", "dimensions_year"]:
        metadata[column] = metadata[column].map(clean_text)
    if metadata["source_record_id"].eq("").any() or metadata["source_record_id"].duplicated().any():
        raise ValueError("Text metadata has blank or duplicate source_record_id values.")
    if metadata["dimensions_publication_id"].eq("").any() or metadata["dimensions_publication_id"].duplicated().any():
        raise ValueError("Text metadata has blank or duplicate Dimensions publication IDs.")
    if metadata["dimensions_title"].eq("").any():
        raise ValueError("Every Dimensions publication must have a nonempty title for the NMF input.")
    if not metadata["metadata_retrieval_status"].map(clean_text).eq("returned").all():
        raise ValueError("Text metadata contains a record without metadata_retrieval_status=returned.")
    observed_missing_abstracts = int(metadata["dimensions_abstract"].eq("").sum())
    if observed_missing_abstracts != args.expected_records_without_abstract:
        raise ValueError(
            f"Expected {args.expected_records_without_abstract} title-only records; found {observed_missing_abstracts}."
        )

    nmf_input = metadata.loc[:, [
        "dimensions_publication_id", "dimensions_title", "dimensions_abstract", "dimensions_year"
    ]].rename(columns={
        "dimensions_publication_id": "id",
        "dimensions_title": "title",
        "dimensions_abstract": "abstract",
        "dimensions_year": "year",
    })
    if sha256(args.metadata_file) != input_hashes["accepted_publication_text_metadata"]:
        raise RuntimeError("Publication text metadata changed during NMF-input preparation.")
    if sha256(args.metadata_unreturned_file) != input_hashes["accepted_metadata_unreturned"]:
        raise RuntimeError("Text-metadata unreturned table changed during NMF-input preparation.")
    if sha256(args.text_coverage_file) != input_hashes["dimensions_subset_text_coverage"]:
        raise RuntimeError("Text-coverage audit changed during NMF-input preparation.")

    try:
        atomic_write_pickle(args.output_pickle, nmf_input)
        manifest = {
            "stage": "06_prepare_nmf_input",
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "purpose": "Prepare the frozen accepted-publication text metadata for outcome-blind NMF.",
            "input_files": {
                name: {"path": str(path), "sha256": input_hashes[name]}
                for name, path in {
                    "accepted_publication_text_metadata": args.metadata_file,
                    "accepted_metadata_unreturned": args.metadata_unreturned_file,
                    "dimensions_subset_text_coverage": args.text_coverage_file,
                }.items()
            },
            "population": {
                "dimensions_publication_records": len(nmf_input),
                "records_with_abstract": int(len(nmf_input) - observed_missing_abstracts),
                "title_only_records": observed_missing_abstracts,
                "text_construction": "Dimensions title repeated twice plus available abstract; title repeated twice alone when abstract is absent.",
            },
            "output": {
                "pickle_path": str(args.output_pickle),
                "sha256": sha256(args.output_pickle),
                "columns": nmf_input.columns.tolist(),
                "rows": int(len(nmf_input)),
            },
            "pre_outcome_boundary": (
                "No grant, policy-document, citation, funder, organization, country, affiliation, or other relational "
                "outcome field was read or written."
            ),
            "data_boundary": "The NMF input pickle and manifest are protected local data and must not be committed to GitHub.",
        }
        atomic_write_json(args.manifest_file, manifest)
    except Exception as error:
        raise RuntimeError(f"NMF-input write failed: {type(error).__name__}: {error}") from error

    print("FAIRIFICATION NMF INPUT PREPARATION: PASS")
    print(f"DIMENSIONS METADATA RECORDS: {len(nmf_input)}")
    print(f"RECORDS WITH ABSTRACT: {len(nmf_input) - observed_missing_abstracts}")
    print(f"TITLE-ONLY RECORDS: {observed_missing_abstracts}")
    print("DIMENSIONS REQUESTS: 0")
    print(f"NMF INPUT WRITTEN: {args.output_pickle}")
    print(f"MANIFEST WRITTEN: {args.manifest_file}")


if __name__ == "__main__":
    main()

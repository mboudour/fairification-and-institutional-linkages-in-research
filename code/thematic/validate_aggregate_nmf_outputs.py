#!/usr/bin/env python3
"""Validate the reviewed non-record-level NMF release tables.

Run from the repository root:
    python code/thematic/validate_aggregate_nmf_outputs.py

This checker verifies expected schemas and rejects table columns that would
indicate raw or record-level bibliographic/Dimensions content.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "derived_outputs" / "thematic"
REQUIRED_COLUMNS = {
    "topic_model_summary.csv": {
        "n_topics",
        "reconstruction_error",
        "mean_component_cosine_similarity",
        "mean_dominant_assignment_agreement",
    },
    "topic_sizes.csv": {
        "n_topics",
        "dominant_topic",
        "n_publications",
        "pct_of_P",
        "top_10_terms",
    },
    "topic_terms.csv": {"n_topics", "topic", "rank", "term", "term_weight"},
    "topic_stability_detail.csv": {
        "n_topics",
        "replicate",
        "full_topic",
        "component_cosine_similarity",
        "dominant_assignment_agreement_all_P",
    },
    "bipole_screen.csv": {
        "n_topics",
        "automatic_screen_status",
        "both_topics_at_least_30pct",
    },
    "validation_checks.csv": {"check", "failures"},
    "topic_2_to_3_crosswalk.csv": {"k2_topic", "k3_topic", "n_publications"},
}
FORBIDDEN_COLUMN_MARKERS = (
    "doi",
    "title",
    "abstract",
    "author",
    "publication_id",
    "dimensions_id",
    "source_record",
    "organization",
    "institution",
    "funder",
    "policy",
    "grant",
    "edge",
)


def main() -> None:
    failures: list[str] = []
    for filename, required in REQUIRED_COLUMNS.items():
        path = OUTPUT / filename
        if not path.is_file():
            failures.append(f"missing required file: {path.relative_to(ROOT)}")
            continue
        frame = pd.read_csv(path)
        missing = sorted(required.difference(frame.columns))
        if missing:
            failures.append(f"{filename}: missing columns {', '.join(missing)}")
        unsafe = [
            column
            for column in frame.columns
            if any(marker in column.casefold() for marker in FORBIDDEN_COLUMN_MARKERS)
        ]
        if unsafe:
            failures.append(f"{filename}: record-level column markers {', '.join(unsafe)}")

    if failures:
        print("AGGREGATE NMF RELEASE: FAIL")
        print("\n".join(f"- {failure}" for failure in failures))
        raise SystemExit(1)

    print("AGGREGATE NMF RELEASE: PASS")
    print("All expected NMF output tables are present and contain no prohibited column markers.")


if __name__ == "__main__":
    main()

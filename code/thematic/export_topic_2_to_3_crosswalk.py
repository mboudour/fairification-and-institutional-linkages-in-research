#!/usr/bin/env python3
"""Export a non-record-level K=2-to-K=3 topic-assignment cross-tab.

Example, run only in a private local workspace where both assignment files are
available:
    python code/thematic/export_topic_2_to_3_crosswalk.py \
      /private/path/publication_topic_assignments_k2.csv \
      /private/path/publication_topic_assignments_k3.csv

The script writes only topic-level counts. It does not copy source IDs, DOIs,
titles, abstracts, Dimensions identifiers, or other record-level fields.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "derived_outputs" / "thematic" / "topic_2_to_3_crosswalk.csv"
ID_COLUMN = "source_record_id"
TOPIC_COLUMN = "dominant_topic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("k2_assignments", type=Path)
    parser.add_argument("k3_assignments", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def read_assignments(path: Path, expected_k: int, topic_name: str) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=["n_topics", ID_COLUMN, TOPIC_COLUMN])
    required = {"n_topics", ID_COLUMN, TOPIC_COLUMN}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path.name} missing required columns: {sorted(missing)}")
    if not frame["n_topics"].eq(expected_k).all():
        raise ValueError(f"{path.name} is not a K={expected_k} assignment file")
    if frame[ID_COLUMN].isna().any() or frame[ID_COLUMN].duplicated().any():
        raise ValueError(f"{path.name} must have nonmissing, unique source-record identifiers")
    return frame[[ID_COLUMN, TOPIC_COLUMN]].rename(columns={TOPIC_COLUMN: topic_name})


def main() -> None:
    args = parse_args()
    k2 = read_assignments(args.k2_assignments, 2, "k2_topic")
    k3 = read_assignments(args.k3_assignments, 3, "k3_topic")
    merged = k2.merge(k3, on=ID_COLUMN, how="outer", validate="one_to_one", indicator=True)
    if not merged["_merge"].eq("both").all():
        raise ValueError("K=2 and K=3 assignment files do not have the same source-record set")

    output = (
        merged.groupby(["k2_topic", "k3_topic"], as_index=False)
        .size()
        .rename(columns={"size": "n_publications"})
        .sort_values(["k2_topic", "k3_topic"])
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    print(f"Safe aggregate crosswalk written: {args.output}")
    print(f"Publications summarized: {int(output['n_publications'].sum())}")


if __name__ == "__main__":
    main()

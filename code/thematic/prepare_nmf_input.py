#!/usr/bin/env python3
"""Prepare a private Dimensions text-metadata CSV for the NMF diagnostic.

This script is intended for a local, untracked workspace. It reads the private
CSV produced after accepted DOI matching and writes an untracked pickle with the
four generic fields expected by publication_topic_model_diagnostic.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REQUIRED = {
    "dimensions_publication_id": "id",
    "dimensions_title": "title",
    "dimensions_abstract": "abstract",
    "dimensions_year": "year",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_pickle", type=Path)
    args = parser.parse_args()

    source = pd.read_csv(args.input_csv, dtype=str, keep_default_na=False)
    missing = sorted(set(REQUIRED).difference(source.columns))
    if missing:
        raise SystemExit("Missing required columns: " + ", ".join(missing))

    output = source[list(REQUIRED)].rename(columns=REQUIRED).copy()
    output["id"] = output["id"].astype(str).str.strip()
    output["title"] = output["title"].astype(str).str.strip()
    output["abstract"] = output["abstract"].astype(str).str.strip()
    output["year"] = output["year"].astype(str).str.strip()

    if output["id"].eq("").any() or output["id"].duplicated().any():
        raise SystemExit("Publication IDs must be nonempty and unique.")
    if output["title"].eq("").any():
        raise SystemExit("Every publication must have a nonempty title.")

    args.output_pickle.parent.mkdir(parents=True, exist_ok=True)
    output.to_pickle(args.output_pickle)
    print(f"NMF input written locally: {args.output_pickle}")
    print(f"Records: {len(output)}")


if __name__ == "__main__":
    main()

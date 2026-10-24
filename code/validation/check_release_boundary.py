#!/usr/bin/env python3
"""Fail if staged files violate the repository's data-free release boundary.

Run from the repository root after staging intended files:
    python code/validation/check_release_boundary.py

The tool checks staged filenames and a small set of content markers. It is a
safeguard, not a substitute for human review of `git diff --cached`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "data/",
    "derived_outputs/",
    "figures/",
    "manuscript/",
)
ALLOWED_READMES = {
    "data/README.md",
    "derived_outputs/README.md",
    "derived_outputs/thematic/README.md",
    "figures/README.md",
    "manuscript/README.md",
}
ALLOWED_AGGREGATE_OUTPUTS = {
    "derived_outputs/thematic/topic_model_summary.csv",
    "derived_outputs/thematic/topic_sizes.csv",
    "derived_outputs/thematic/topic_terms.csv",
    "derived_outputs/thematic/topic_stability_detail.csv",
    "derived_outputs/thematic/bipole_screen.csv",
    "derived_outputs/thematic/validation_checks.csv",
    "derived_outputs/thematic/topic_2_to_3_crosswalk.csv",
}
FORBIDDEN_SUFFIXES = (
    ".csv", ".tsv", ".xlsx", ".xls", ".json", ".pkl", ".pickle",
    ".parquet", ".feather", ".sqlite", ".db", ".zip", ".pdf", ".png",
    ".jpg", ".jpeg", ".svg",
)
SECRET_PATTERNS = (
    re.compile(r"dimensions_api_key\s*=\s*['\"]?\S+", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*jwt\s+[a-z0-9._-]+", re.IGNORECASE),
    re.compile(r"\bghu_[a-z0-9]{20,}\b", re.IGNORECASE),
    re.compile(r"\bgithub_pat_[a-z0-9_]{20,}\b", re.IGNORECASE),
)


def staged_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        text=True,
        capture_output=True,
    )
    return [Path(line) for line in completed.stdout.splitlines() if line.strip()]


def main() -> None:
    violations: list[str] = []
    for path in staged_files():
        name = path.as_posix()
        if name in ALLOWED_READMES or name in ALLOWED_AGGREGATE_OUTPUTS:
            continue
        if name.startswith(FORBIDDEN_PREFIXES):
            violations.append(f"protected directory: {name}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            violations.append(f"forbidden data/output suffix: {name}")
        if path.is_file() and path.suffix.casefold() in {".md", ".py", ".txt", ".dsl", ".yml", ".yaml"}:
            body = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(body) for pattern in SECRET_PATTERNS):
                violations.append(f"possible secret marker: {name}")

    if violations:
        print("RELEASE BOUNDARY: FAIL")
        for item in sorted(set(violations)):
            print(f"- {item}")
        raise SystemExit(1)

    print("RELEASE BOUNDARY: PASS")
    print("No prohibited data/output file or obvious credential marker was detected.")


if __name__ == "__main__":
    main()

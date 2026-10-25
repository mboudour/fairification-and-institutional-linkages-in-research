#!/usr/bin/env python3
"""Check staged files against the FAIRification aggregate-only release boundary.

The repository excludes all source, record-level, and manuscript material. A
narrow, reviewed exception permits named aggregate result tables and figures
after human review.
"""

from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

RELEASED_RESULT_FILES = {
    "00_certified_results_overview.csv",
    "A01_source_to_Dimensions_coverage_summary.csv",
    "A02_recorded_relation_edge_summary.csv",
    "B01_overall_recorded_linkage_outcomes.csv",
    "B02_linkage_outcomes_by_dominant_K3_theme_supplementary.csv",
    "B03_frozen_policy_observation_window_samples.csv",
    "C01_association_model_diagnostics.csv",
    "C02_association_model_coefficients.csv",
    "C03_association_event_adequacy_assessment.csv",
    "C04_policy_link_event_limited_descriptives.csv",
    "D01_record_year_difference_summary.csv",
    "D02_temporal_policy_observation_window_samples.csv",
    "E01_role_separated_network_basic_statistics.csv",
    "E02_role_separated_network_degree_concentration.csv",
    "E03_organization_role_attribute_coverage.csv",
    "F01_NMF_candidate_stability_summary.csv",
    "F02_NMF_component_stability_summary.csv",
    "F03_Wilkinson_leave_one_out_K2_reproduction_summary.csv",
    "F04_grant_association_sensitivity_comparison.csv",
    "F05_policy_window_event_adequacy_accounting.csv",
    "F06_robustness_scope_and_limitations.csv",
    "G01_observed_P_G_P_D_configurations.csv",
    "G02_year_stratified_cross_relation_null_summary.csv",
    "G03_issuer_attribution_coverage.csv",
    "H01_role_separated_institution_country_scope.csv",
    "results_bundle_index.csv",
    "results_bundle_validation_checks.csv",
}
FIGURE_STEMS = {
    "figure_1_study_scope_and_relation_layers",
    "figure_2_supplementary_K3_theme_linkage_rates",
    "figure_3_primary_grant_link_associations",
    "figure_4_record_year_context_and_policy_adequacy",
    "figure_5_cross_relation_configurations",
    "figure_6_country_landscapes",
    "figure_7_institution_landscapes",
}
ALLOWED_READMES = {
    "data/README.md",
    "derived_outputs/README.md",
    "derived_outputs/thematic/README.md",
    "derived_outputs/released_results/README.md",
    "figures/README.md",
}
ALLOWED_AGGREGATE_OUTPUTS = {
    "derived_outputs/thematic/topic_model_summary.csv",
    "derived_outputs/thematic/topic_sizes.csv",
    "derived_outputs/thematic/topic_terms.csv",
    "derived_outputs/thematic/topic_stability_detail.csv",
    "derived_outputs/thematic/bipole_screen.csv",
    "derived_outputs/thematic/validation_checks.csv",
    "derived_outputs/thematic/topic_2_to_3_crosswalk.csv",
} | {f"derived_outputs/released_results/{name}" for name in RELEASED_RESULT_FILES}
ALLOWED_PUBLIC_FILES = {
    "docs/release/AGGREGATE_RESULTS_RELEASE.md",
    "docs/release/INSTITUTION_COUNTRY_RESULTS_RELEASE.md",
    "figures/manuscript/figure_captions.md",
}
ALLOWED_PUBLIC_FILES |= {
    f"figures/manuscript/{stem}.{suffix}"
    for stem in FIGURE_STEMS
    for suffix in ("png", "pdf")
}
FORBIDDEN_PREFIXES = ("data/", "derived_outputs/", "figures/", "manuscript/")
FORBIDDEN_SUFFIXES = (
    ".csv", ".tsv", ".xlsx", ".xls", ".json", ".pkl", ".pickle",
    ".parquet", ".feather", ".sqlite", ".db", ".zip", ".pdf", ".png",
    ".jpg", ".jpeg", ".svg",
)
FORBIDDEN_HEADER_MARKERS = (
    "doi", "publication_id", "grant_id", "policy_document_id", "policy_issuer_id",
    "source_record_id", "organization_id", "affiliation_id", "title", "abstract",
    "author", "authors", "organization_name", "issuer_name", "country_name", "edge_list",
    "node_list",
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


def aggregate_headers_are_safe(path: Path) -> tuple[bool, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    normalized = [value.strip().casefold() for value in header]
    bad = [value for value in normalized if value in FORBIDDEN_HEADER_MARKERS]
    if bad:
        return False, ", ".join(bad)
    return True, ""


def main() -> None:
    violations: list[str] = []
    for path in staged_files():
        name = path.as_posix()
        approved = name in ALLOWED_READMES or name in ALLOWED_AGGREGATE_OUTPUTS or name in ALLOWED_PUBLIC_FILES
        if name.startswith(FORBIDDEN_PREFIXES) and not approved:
            violations.append(f"protected directory: {name}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES and not approved:
            violations.append(f"forbidden data/output suffix: {name}")
        if name.startswith("derived_outputs/released_results/") and path.suffix.casefold() == ".csv":
            safe, detail = aggregate_headers_are_safe(path)
            if not safe:
                violations.append(f"identifier-bearing aggregate header(s) in {name}: {detail}")
        if path.is_file() and path.suffix.casefold() in {".md", ".py", ".txt", ".dsl", ".yml", ".yaml", ".tex", ".bib"}:
            body = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(body) for pattern in SECRET_PATTERNS):
                violations.append(f"possible secret marker: {name}")

    if violations:
        print("RELEASE BOUNDARY: FAIL")
        for item in sorted(set(violations)):
            print(f"- {item}")
        raise SystemExit(1)

    print("RELEASE BOUNDARY: PASS")
    print("Only named reviewed aggregate outputs and reviewed figures are staged.")


if __name__ == "__main__":
    main()

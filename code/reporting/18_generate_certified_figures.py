#!/usr/bin/env python3
"""Generate local FAIRification manuscript figures from a certified aggregate bundle.

This script accepts only the output directory created by
``17_build_certified_results_bundle.py``. It verifies every input table against
that bundle's SHA-256 manifest, does not access any raw or record-level output,
and creates a local-only figure directory outside the Git worktree. Narrative
captions are supplied by the manuscript TeX source rather than embedded in the
figure files.

Example:
    python code/reporting/18_generate_certified_figures.py \
        --bundle-dir /path/to/17_certified_results_bundle_run \
        --output-dir /path/to/18_certified_figures_run
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd


SCRIPT_VERSION = "18_generate_certified_figures_1.2"
REQUIRED_BUNDLE_STAGE = "17_build_certified_results_bundle_1.0"
EXPECTED_SOURCE_RECORDS = 163
EXPECTED_PUBLICATION_RECORDS = 144
EXPECTED_GRANT_LINKED_PUBLICATIONS = 52
EXPECTED_POLICY_LINKED_PUBLICATIONS = 4
EXPECTED_PRIMARY_POLICY_PUBLICATIONS = 72
EXPECTED_PRIMARY_POLICY_EVENTS = 3
EXPECTED_PRIMARY_POLICY_REQUIRED_EVENTS = 30
PRIMARY_NULL = "publication_year_stratified_P_endpoint_permutation"

TEXT = "#1C2733"
MUTED = "#5F6B78"
NAVY = "#174A63"
TEAL = "#178B89"
GOLD = "#DB9A34"
PURPLE = "#8063A8"
RED = "#B94A48"
LIGHT_BLUE = "#D9EBF4"
LIGHT_TEAL = "#DDF1EF"
LIGHT_GOLD = "#F8E7C9"
LIGHT_PURPLE = "#E8E0F1"
GRAY = "#D9DEE3"
DPI = 400

STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.labelcolor": TEXT,
    "xtick.color": TEXT,
    "ytick.color": TEXT,
    "text.color": TEXT,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#AAB2BD",
    "grid.color": "#D8DEE6",
    "grid.linewidth": 0.7,
}

REQUIRED_INPUTS = {
    "coverage": "A01_source_to_Dimensions_coverage_summary.csv",
    "edges": "A02_recorded_relation_edge_summary.csv",
    "overall_outcomes": "B01_overall_recorded_linkage_outcomes.csv",
    "theme_outcomes": "B02_linkage_outcomes_by_dominant_K3_theme_supplementary.csv",
    "association_diagnostics": "C01_association_model_diagnostics.csv",
    "association_coefficients": "C02_association_model_coefficients.csv",
    "timing": "D01_record_year_difference_summary.csv",
    "policy_adequacy": "F05_policy_window_event_adequacy_accounting.csv",
    "configurations": "G01_observed_P_G_P_D_configurations.csv",
    "configuration_null": "G02_year_stratified_cross_relation_null_summary.csv",
}

EXPECTED_SCRIPT17_OUTPUTS = frozenset({
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
    "results_bundle_index.csv",
    "results_bundle_validation_checks.csv",
    "README.md",
})

EXPECTED_CERTIFIED_STAGE_MANIFESTS = frozenset({
    "relational_audit", "analysis_base", "associations", "temporal", "networks", "robustness", "configuration",
})

EXPECTED_LINEAGE_HASHES = frozenset({
    "relational_summary_manifest", "analysis_base_manifest", "association_manifest", "temporal_manifest",
    "publication_grant_edges", "publication_policy_edges", "policy_issuer_publication_edges",
    "publication_linkage_analysis_base",
})

MAX_INPUT_ROWS = {
    "coverage": 1,
    "edges": 3,
    "overall_outcomes": 2,
    "theme_outcomes": 6,
    "association_diagnostics": 10,
    "association_coefficients": 50,
    "timing": 2,
    "policy_adequacy": 3,
    "configurations": 4,
    "configuration_null": 10,
}

FORBIDDEN_COLUMN_TOKENS = {
    "publication_id", "grant_id", "policy_document_id", "source_record_id", "doi", "title", "abstract",
    "author", "authors", "issuer_id", "issuer_name", "organization_id", "organization_name",
    "research_org_id", "research_org_name", "policy_document_ids", "publication_ids", "grant_ids",
}

THEMES = (
    (
        "Institutional stewardship, research-data management, and open-science practice",
        "Institutional stewardship /\nopen-science practice",
        NAVY,
    ),
    (
        "Technical metadata, semantic infrastructure, and reproducible workflows",
        "Technical metadata /\nsemantic workflows",
        TEAL,
    ),
    (
        "Digital cultural heritage, collections, and preservation",
        "Digital heritage /\ncollections / preservation",
        PURPLE,
    ),
)


class FigureGenerationFailure(RuntimeError):
    """Raised when the certified bundle cannot support a safe figure run."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def repository_root() -> Path | None:
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True, help="Completed Script 17 certified results bundle.")
    parser.add_argument("--output-dir", type=Path, required=True, help="New empty local directory for figures.")
    return parser.parse_args()


def read_json_snapshot(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise FigureGenerationFailure(f"{label} must be a JSON object: {path}")
    return payload, raw


def require_columns(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise FigureGenerationFailure(f"{label} is missing required column(s): {', '.join(missing)}")


def scalar_one(frame: pd.DataFrame, column: str, label: str) -> float:
    require_columns(frame, {column}, label)
    if len(frame) != 1:
        raise FigureGenerationFailure(f"{label} must contain exactly one row.")
    value = pd.to_numeric(frame.iloc[0][column], errors="coerce")
    if pd.isna(value) or not math.isfinite(float(value)):
        raise FigureGenerationFailure(f"{label}.{column} must be finite and numeric.")
    return float(value)


def integer_one(frame: pd.DataFrame, column: str, label: str) -> int:
    value = scalar_one(frame, column, label)
    if not value.is_integer():
        raise FigureGenerationFailure(f"{label}.{column} must be an exact integer.")
    return int(value)


def parse_boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise FigureGenerationFailure(f"{label} must be a Boolean value.")


def normalized_column(column: object) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(column).strip())
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def assert_aggregate_safe(frame: pd.DataFrame, key: str, filename: str) -> None:
    if len(frame) > MAX_INPUT_ROWS[key]:
        raise FigureGenerationFailure(f"Certified aggregate table exceeds its row ceiling: {filename}.")
    normalized = {normalized_column(column) for column in frame.columns}
    forbidden = set(FORBIDDEN_COLUMN_TOKENS.intersection(normalized))
    patterns = (
        r"(^|_)(publication|grant|policy_document|source_record|record|issuer|organization|research_org)(_)?(id|ids|identifier|identifiers)$",
        r"(^|_)(doi|dois|title|titles|abstract|abstracts|author|authors|full_text|text|content|url|urls)$",
        r"(^|_)(issuer|organization|research_org|country|node)(_)?name(s)?$",
        r"(^|_)(edge|edges)(_)?(id|ids|source|target|list|table)$",
    )
    for column in normalized:
        if column == "id" or column.endswith("_id") or column.endswith("_ids") or any(re.search(pattern, column) for pattern in patterns):
            forbidden.add(column)
    if forbidden:
        raise FigureGenerationFailure(
            f"Certified aggregate table has prohibited record-level or textual column(s) in {filename}: {', '.join(sorted(forbidden))}."
        )


def require_sha256(value: object, label: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise FigureGenerationFailure(f"{label} must be a lowercase SHA-256 digest.")


def validate_script17_manifest_contract(manifest: dict[str, Any], bundle_dir: Path) -> dict[str, bytes]:
    """Verify complete Script 17 provenance before consuming any figure inputs."""
    if manifest.get("stage") != REQUIRED_BUNDLE_STAGE or manifest.get("status") != "complete":
        raise FigureGenerationFailure("Figure generation requires a completed Script 17 certified-results bundle, not a generic manifest.")
    if "aggregate-only" not in str(manifest.get("purpose", "")).casefold() or "must not be committed" not in str(manifest.get("data_boundary", "")).casefold():
        raise FigureGenerationFailure("Results-bundle manifest lacks the Script 17 aggregate-only and local-data boundary declarations.")
    input_files = manifest.get("input_files")
    if not isinstance(input_files, dict) or len(input_files) < 23:
        raise FigureGenerationFailure("Results-bundle manifest lacks the complete Script 17 selected-input provenance set.")
    for label, entry in input_files.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise FigureGenerationFailure(f"Results-bundle input provenance entry is malformed: {label}.")
        require_sha256(entry.get("sha256"), f"Results-bundle input hash for {label}")
    output_files = manifest.get("output_files")
    if not isinstance(output_files, dict) or set(output_files) != EXPECTED_SCRIPT17_OUTPUTS:
        raise FigureGenerationFailure("Results-bundle manifest does not have the complete fixed Script 17 output contract.")
    stage_manifests = manifest.get("certified_stage_manifests")
    if not isinstance(stage_manifests, dict) or set(stage_manifests) != EXPECTED_CERTIFIED_STAGE_MANIFESTS:
        raise FigureGenerationFailure("Results-bundle manifest lacks the complete certified-stage manifest chain.")
    lineage = manifest.get("cross_stage_lineage_hashes")
    if not isinstance(lineage, dict) or set(lineage) != EXPECTED_LINEAGE_HASHES:
        raise FigureGenerationFailure("Results-bundle manifest lacks the complete cross-stage lineage hash chain.")
    for label, entry in stage_manifests.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise FigureGenerationFailure(f"Certified-stage manifest entry is malformed: {label}.")
        require_sha256(entry.get("sha256"), f"Certified-stage manifest hash for {label}")
    for label, digest in lineage.items():
        require_sha256(digest, f"Lineage hash for {label}")

    validated_bytes: dict[str, bytes] = {}
    for filename, entry in output_files.items():
        path = bundle_dir / filename
        if path.is_symlink() or not path.is_file() or not isinstance(entry, dict):
            raise FigureGenerationFailure(f"Results-bundle output is missing or unsafe: {filename}.")
        require_sha256(entry.get("sha256"), f"Results-bundle output hash for {filename}")
        raw = path.read_bytes()
        if sha256_bytes(raw) != entry["sha256"]:
            raise FigureGenerationFailure(f"Results-bundle output hash mismatch: {filename}.")
        validated_bytes[filename] = raw

    validation = pd.read_csv(io.BytesIO(validated_bytes["results_bundle_validation_checks.csv"]), encoding="utf-8-sig")
    require_columns(validation, {"check", "passed"}, "Results-bundle validation checks")
    if validation.empty or not validation["passed"].map(lambda value: parse_boolean(value, "Results-bundle validation result")).all():
        raise FigureGenerationFailure("Results-bundle validation checks are incomplete or contain a failed result.")
    index = pd.read_csv(io.BytesIO(validated_bytes["results_bundle_index.csv"]), encoding="utf-8-sig")
    require_columns(index, {"bundle_file", "aggregate_only_release_check"}, "Results-bundle index")
    indexed_files = set(index["bundle_file"].astype(str))
    if not set(REQUIRED_INPUTS.values()).issubset(indexed_files) or not index["aggregate_only_release_check"].eq("pass").all():
        raise FigureGenerationFailure("Results-bundle index does not certify the requested aggregate figure inputs.")
    return validated_bytes


def preflight(args: argparse.Namespace) -> argparse.Namespace:
    args.bundle_dir = resolved(args.bundle_dir)
    args.output_dir = resolved(args.output_dir)
    if not args.bundle_dir.is_dir():
        raise FileNotFoundError(f"Certified results bundle directory does not exist: {args.bundle_dir}")
    if args.output_dir.exists() and (args.output_dir.is_file() or args.output_dir.is_symlink()):
        raise ValueError(f"Output path must be a real directory: {args.output_dir}")
    repo = repository_root()
    if repo is not None and is_within(args.output_dir, repo):
        raise ValueError(f"Figure output directory must be outside the Git worktree: {repo}")
    if is_within(args.output_dir, args.bundle_dir) or is_within(args.bundle_dir, args.output_dir):
        raise ValueError("Figure output directory must not contain, or be contained by, the certified results bundle.")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {args.output_dir}; choose a new empty directory.")
    return args


def load_certified_bundle(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, pd.DataFrame], dict[str, str]]:
    manifest_path = bundle_dir / "results_bundle_manifest.json"
    manifest, manifest_raw = read_json_snapshot(manifest_path, "certified results-bundle manifest")
    validated_bytes = validate_script17_manifest_contract(manifest, bundle_dir)
    source_denominators = manifest.get("source_denominators")
    if not isinstance(source_denominators, dict):
        raise FigureGenerationFailure("Certified results-bundle manifest lacks source_denominators.")
    expected_denominators = {
        "frozen_curated_source_cohort_records": EXPECTED_SOURCE_RECORDS,
        "Dimensions_recovered_analytic_subset_records": EXPECTED_PUBLICATION_RECORDS,
        "recorded_grant_linked_publications": EXPECTED_GRANT_LINKED_PUBLICATIONS,
        "recorded_policy_linked_publications": EXPECTED_POLICY_LINKED_PUBLICATIONS,
        "primary_policy_window_publications": EXPECTED_PRIMARY_POLICY_PUBLICATIONS,
        "primary_policy_window_events": EXPECTED_PRIMARY_POLICY_EVENTS,
    }
    for key, expected in expected_denominators.items():
        if source_denominators.get(key) != expected:
            raise FigureGenerationFailure(f"Certified bundle denominator mismatch for {key}; expected {expected}.")
    output_files = manifest["output_files"]

    tables: dict[str, pd.DataFrame] = {}
    hashes: dict[str, str] = {"results_bundle_manifest.json": sha256_bytes(manifest_raw)}
    for key, filename in REQUIRED_INPUTS.items():
        entry = output_files.get(filename)
        if not isinstance(entry, dict) or "rows" not in entry:
            raise FigureGenerationFailure(f"Certified results bundle lacks the required manifest entry for {filename}.")
        raw = validated_bytes[filename]
        digest = sha256_bytes(raw)
        frame = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
        if int(entry["rows"]) != len(frame):
            raise FigureGenerationFailure(f"Certified results input row count mismatch: {filename}.")
        assert_aggregate_safe(frame, key, filename)
        tables[key] = frame
        hashes[filename] = digest
    return manifest, tables, hashes


def require_single_row(frame: pd.DataFrame, column: str, value: str, label: str) -> pd.Series:
    require_columns(frame, {column}, label)
    subset = frame.loc[frame[column].astype(str).eq(value)]
    if len(subset) != 1:
        raise FigureGenerationFailure(f"{label} must contain exactly one row where {column} is {value!r}.")
    return subset.iloc[0]


def validate_figure_inputs(tables: dict[str, pd.DataFrame]) -> None:
    coverage = tables["coverage"]
    require_columns(
        coverage,
        {
            "frozen_source_cohort_records", "dimensions_recovered_analytic_subset_records",
            "not_recovered_by_doi_first_procedure", "dimensions_recovery_rate_pct",
        },
        "Coverage summary",
    )
    if (
        integer_one(coverage, "frozen_source_cohort_records", "Coverage summary") != EXPECTED_SOURCE_RECORDS
        or integer_one(coverage, "dimensions_recovered_analytic_subset_records", "Coverage summary") != EXPECTED_PUBLICATION_RECORDS
        or integer_one(coverage, "not_recovered_by_doi_first_procedure", "Coverage summary") != 19
        or not math.isclose(scalar_one(coverage, "dimensions_recovery_rate_pct", "Coverage summary"), 100 * EXPECTED_PUBLICATION_RECORDS / EXPECTED_SOURCE_RECORDS, abs_tol=0.001, rel_tol=0)
    ):
        raise FigureGenerationFailure("Coverage summary does not reconcile to the frozen 163-to-144 study scope.")

    edge_summary = tables["edges"]
    require_columns(edge_summary, {"network", "edges"}, "Relation edge summary")
    if edge_summary["network"].duplicated().any():
        raise FigureGenerationFailure("Relation edge summary has duplicate relation-layer rows.")
    edge_counts = edge_summary.set_index("network")["edges"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
    if edge_counts.to_dict() != {
        "publication_grant": 163,
        "publication_policy_document": 223,
        "policy_issuer_publication": 47,
    }:
        raise FigureGenerationFailure("Relation edge summary does not reconcile to the frozen FAIRification relation layers.")

    outcomes = tables["overall_outcomes"]
    require_columns(outcomes, {"outcome", "n_publications", "n_linked_publications", "linkage_rate_pct"}, "Overall linkage outcomes")
    if outcomes["outcome"].duplicated().any() or set(outcomes["outcome"]) != {"has_grant_link", "has_policy_document_link"}:
        raise FigureGenerationFailure("Overall linkage outcomes must contain exactly the grant and policy rows.")
    if not (pd.to_numeric(outcomes["n_publications"], errors="coerce") == EXPECTED_PUBLICATION_RECORDS).all():
        raise FigureGenerationFailure("Overall linkage outcome denominators must all equal the 144-publication anchor.")
    outcome_counts = outcomes.set_index("outcome")["n_linked_publications"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
    if outcome_counts.to_dict() != {"has_grant_link": 52, "has_policy_document_link": 4}:
        raise FigureGenerationFailure("Overall linkage outcomes do not reconcile to the frozen result.")

    theme_outcomes = tables["theme_outcomes"]
    require_columns(
        theme_outcomes,
        {"group_variable", "group_level", "outcome", "n_publications", "n_linked_publications", "linkage_rate_pct", "wilson_ci_95_low_pct", "wilson_ci_95_high_pct"},
        "K=3 theme outcome summary",
    )
    themed = theme_outcomes.loc[theme_outcomes["group_variable"].eq("dominant_K3_theme__supplementary")].copy()
    if (
        len(themed) != 6
        or themed.duplicated(["group_level", "outcome"]).any()
        or set(themed["outcome"]) != {"has_grant_link", "has_policy_document_link"}
    ):
        raise FigureGenerationFailure("K=3 theme outcome summary is not the expected six-row supplementary table.")
    expected_theme_sizes = {THEMES[0][0]: 51, THEMES[1][0]: 80, THEMES[2][0]: 13}
    for theme, _, _ in THEMES:
        subset = themed.loc[themed["group_level"].eq(theme)]
        if len(subset) != 2:
            raise FigureGenerationFailure(f"K=3 theme outcome summary lacks the frozen theme: {theme}")
        denominators = pd.to_numeric(subset["n_publications"], errors="coerce")
        if denominators.isna().any() or set(denominators.astype(int)) != {expected_theme_sizes[theme]}:
            raise FigureGenerationFailure(f"K=3 theme denominator is inconsistent for {theme}.")
        for _, row in subset.iterrows():
            total = int(pd.to_numeric(row["n_publications"], errors="raise"))
            events = int(pd.to_numeric(row["n_linked_publications"], errors="raise"))
            rate = float(pd.to_numeric(row["linkage_rate_pct"], errors="raise"))
            low = float(pd.to_numeric(row["wilson_ci_95_low_pct"], errors="raise"))
            high = float(pd.to_numeric(row["wilson_ci_95_high_pct"], errors="raise"))
            if not (0 <= events <= total and math.isclose(rate, 100 * events / total, abs_tol=0.001, rel_tol=0) and 0 <= low <= rate <= high <= 100):
                raise FigureGenerationFailure(f"K=3 theme linkage rate or Wilson interval is inconsistent for {theme}.")
    theme_event_totals = themed.groupby("outcome")["n_linked_publications"].sum().map(lambda value: int(pd.to_numeric(value, errors="raise")))
    if theme_event_totals.to_dict() != {"has_grant_link": EXPECTED_GRANT_LINKED_PUBLICATIONS, "has_policy_document_link": EXPECTED_POLICY_LINKED_PUBLICATIONS}:
        raise FigureGenerationFailure("K=3 supplementary event totals do not reconcile to the overall linkage outcomes.")

    diagnostics = tables["association_diagnostics"]
    require_columns(diagnostics, {"model_label", "model_status", "n_events"}, "Association diagnostics")
    grant = require_single_row(diagnostics, "model_label", "grant_primary__continuous_K3_shares__year_adjusted", "Association diagnostics")
    policy = require_single_row(diagnostics, "model_label", "policy_primary_window__continuous_K3_shares__year_adjusted", "Association diagnostics")
    if str(grant["model_status"]) != "fit" or str(policy["model_status"]) != "not_fit" or int(pd.to_numeric(policy["n_events"], errors="raise")) != EXPECTED_PRIMARY_POLICY_EVENTS:
        raise FigureGenerationFailure("Association diagnostics do not support the frozen grant/policy figure specification.")

    coefficients = tables["association_coefficients"]
    require_columns(coefficients, {"model_label", "term", "odds_ratio", "ci_95_odds_ratio_low", "ci_95_odds_ratio_high"}, "Association coefficients")
    primary = coefficients.loc[coefficients["model_label"].eq("grant_primary__continuous_K3_shares__year_adjusted")]
    terms = set(primary["term"])
    required_terms = {"nmf_topic_1_share_per_10pp", "nmf_topic_3_share_per_10pp"}
    if not required_terms.issubset(terms):
        raise FigureGenerationFailure("Primary grant coefficients lack one or both frozen NMF exposure terms.")

    timing = tables["timing"]
    require_columns(
        timing,
        {
            "relation", "n_edges", "n_edges_with_both_record_years", "n_edges_missing_at_least_one_record_year",
            "n_negative_record_year_differences", "n_zero_record_year_differences", "n_positive_record_year_differences",
            "median_record_year_difference",
        },
        "Record-year difference summary",
    )
    if set(timing["relation"]) != {"publication_grant", "publication_policy_document"}:
        raise FigureGenerationFailure("Record-year summary must contain P--G and P--D relation rows only.")
    if timing["relation"].duplicated().any():
        raise FigureGenerationFailure("Record-year summary has duplicate relation rows.")
    expected_timing_edges = {"publication_grant": 163, "publication_policy_document": 223}
    for _, row in timing.iterrows():
        counts = [int(pd.to_numeric(row[column], errors="raise")) for column in ("n_negative_record_year_differences", "n_zero_record_year_differences", "n_positive_record_year_differences")]
        total_edges = int(pd.to_numeric(row["n_edges"], errors="raise"))
        dated_edges = int(pd.to_numeric(row["n_edges_with_both_record_years"], errors="raise"))
        missing_year_edges = int(pd.to_numeric(row["n_edges_missing_at_least_one_record_year"], errors="raise"))
        if (
            total_edges != expected_timing_edges[str(row["relation"])]
            or any(value < 0 for value in (*counts, dated_edges, missing_year_edges))
            or sum(counts) != dated_edges
            or dated_edges + missing_year_edges != total_edges
        ):
            raise FigureGenerationFailure("Record-year category counts do not reconcile to Stage 13's dated-pair and missing-year denominators.")
        median = float(pd.to_numeric(row["median_record_year_difference"], errors="raise"))
        if not math.isfinite(median):
            raise FigureGenerationFailure("Record-year median must be finite.")

    policy_adequacy = tables["policy_adequacy"]
    require_columns(
        policy_adequacy,
        {"policy_window", "association_model_label", "n_publications", "n_policy_linked_publications", "required_events_for_multivariable_model", "event_adequacy_passes", "association_model_status", "withheld_model_reason"},
        "Policy event-adequacy accounting",
    )
    expected_policy_windows = {
        "primary_policy_window": ("policy_primary_window__continuous_K3_shares__year_adjusted", EXPECTED_PRIMARY_POLICY_PUBLICATIONS, EXPECTED_PRIMARY_POLICY_EVENTS),
        "longer_window_robustness": ("policy_longer_window_robustness__continuous_K3_shares__year_adjusted", 0, 0),
        "all_final_P__policy_window_sensitivity": ("policy_all_final_P_window_sensitivity__continuous_K3_shares__year_adjusted", EXPECTED_PUBLICATION_RECORDS, EXPECTED_POLICY_LINKED_PUBLICATIONS),
    }
    if policy_adequacy["policy_window"].duplicated().any() or set(policy_adequacy["policy_window"]) != set(expected_policy_windows):
        raise FigureGenerationFailure("Policy event-adequacy accounting must contain exactly the three predeclared policy windows.")
    for window, (label, expected_n, expected_events) in expected_policy_windows.items():
        row = require_single_row(policy_adequacy, "policy_window", window, "Policy event-adequacy accounting")
        n_publications = int(pd.to_numeric(row["n_publications"], errors="raise"))
        n_events = int(pd.to_numeric(row["n_policy_linked_publications"], errors="raise"))
        requirement = int(pd.to_numeric(row["required_events_for_multivariable_model"], errors="raise"))
        if (
            str(row["association_model_label"]) != label
            or (expected_n and n_publications != expected_n)
            or (expected_events and n_events != expected_events)
            or requirement != EXPECTED_PRIMARY_POLICY_REQUIRED_EVENTS
            or n_events >= requirement
            or parse_boolean(row["event_adequacy_passes"], f"Policy event adequacy ({window})")
            or str(row["association_model_status"]) != "not_fit"
            or not str(row["withheld_model_reason"]).strip()
        ):
            raise FigureGenerationFailure(f"Policy event-adequacy accounting does not support the withheld-model figure for {window}.")

    configurations = tables["configurations"]
    require_columns(configurations, {"configuration", "n_publications", "share_of_final_P"}, "Observed configuration summary")
    if configurations["configuration"].duplicated().any():
        raise FigureGenerationFailure("Observed configuration summary has duplicate configuration rows.")
    configuration_counts = configurations.set_index("configuration")["n_publications"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
    if configuration_counts.to_dict() != {"P_G_only": 50, "P_D_only": 2, "both": 2, "neither": 90}:
        raise FigureGenerationFailure("Observed configuration counts do not reconcile to the frozen FAIRification result.")
    shares = pd.to_numeric(configurations["share_of_final_P"], errors="coerce")
    expected_shares = pd.to_numeric(configurations["n_publications"], errors="raise") / EXPECTED_PUBLICATION_RECORDS
    if shares.isna().any() or not np.allclose(shares.to_numpy(dtype=float), expected_shares.to_numpy(dtype=float), atol=1e-10, rtol=0) or not math.isclose(float(shares.sum()), 1.0, abs_tol=1e-10, rel_tol=0):
        raise FigureGenerationFailure("Observed configuration shares do not reconcile to the 144-publication anchor.")

    null_summary = tables["configuration_null"]
    require_columns(
        null_summary,
        {"null_scheme", "statistic", "observed", "null_mean", "null_interval_2_5", "null_interval_97_5", "null_variation_status", "permutation_p_enrichment_upper_tail", "observed_to_null_mean_enrichment"},
        "Configuration null summary",
    )
    primary_null = null_summary.loc[null_summary["null_scheme"].eq(PRIMARY_NULL)]
    for statistic, expected_observed in (("N_both", 2), ("intensive_degree_product_sum", 3040)):
        row = require_single_row(primary_null, "statistic", statistic, "Primary configuration null summary")
        mean = float(pd.to_numeric(row["null_mean"], errors="raise"))
        low = float(pd.to_numeric(row["null_interval_2_5"], errors="raise"))
        high = float(pd.to_numeric(row["null_interval_97_5"], errors="raise"))
        p_value = float(pd.to_numeric(row["permutation_p_enrichment_upper_tail"], errors="raise"))
        enrichment = float(pd.to_numeric(row["observed_to_null_mean_enrichment"], errors="raise"))
        if (
            int(pd.to_numeric(row["observed"], errors="raise")) != expected_observed
            or str(row["null_variation_status"]) != "monte_carlo_variation_observed"
            or not all(math.isfinite(value) for value in (mean, low, high, p_value, enrichment))
            or not (low <= mean <= high and 0 <= p_value <= 1 and mean > 0)
            or not math.isclose(enrichment, expected_observed / mean, rel_tol=1e-9, abs_tol=1e-12)
        ):
            raise FigureGenerationFailure(f"Primary configuration null summary does not support the expected {statistic} panel.")


def save_figure(fig: plt.Figure, output_dir: Path, basename: str) -> list[Path]:
    if not getattr(fig, "_fairification_layout_is_manual", False):
        fig.tight_layout()
    paths = [output_dir / f"{basename}.png", output_dir / f"{basename}.pdf"]
    fig.savefig(paths[0], dpi=DPI, bbox_inches="tight", facecolor="white")
    fig.savefig(paths[1], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return paths


def draw_box(ax: plt.Axes, x: float, y: float, width: float, height: float, text: str, face: str, fontsize: float = 9.5) -> None:
    box = FancyBboxPatch(
        (x, y), width, height, boxstyle="round,pad=0.025,rounding_size=0.035",
        linewidth=1.2, edgecolor=NAVY, facecolor=face,
    )
    ax.add_patch(box)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=fontsize, color=TEXT, wrap=True)


def arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float]) -> None:
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=13, linewidth=1.25, color=NAVY))


def figure_1_scope_and_layers(tables: dict[str, pd.DataFrame], output_dir: Path) -> list[Path]:
    coverage = tables["coverage"].iloc[0]
    edges = tables["edges"].set_index("network")["edges"]
    outcomes = tables["overall_outcomes"].set_index("outcome")
    source_n = int(coverage["frozen_source_cohort_records"])
    recovered_n = int(coverage["dimensions_recovered_analytic_subset_records"])
    recovery = float(coverage["dimensions_recovery_rate_pct"])
    grant_n = int(outcomes.loc["has_grant_link", "n_linked_publications"])
    policy_n = int(outcomes.loc["has_policy_document_link", "n_linked_publications"])

    fig, ax = plt.subplots(figsize=(12.8, 6.5))
    ax.set_xlim(0, 12.8)
    ax.set_ylim(0, 7.1)
    ax.axis("off")
    ax.set_title("Study scope and Dimensions-recorded relation layers", loc="left", pad=12, fontsize=13)

    draw_box(ax, 0.45, 5.25, 2.25, 1.1, f"Frozen curated source cohort\n{source_n} publications", LIGHT_BLUE)
    draw_box(ax, 3.45, 5.25, 2.55, 1.1, f"Exact DOI-matched\nDimensions anchor P\n{recovered_n} publications", LIGHT_TEAL)
    arrow(ax, (2.73, 5.8), (3.4, 5.8))
    ax.text(3.05, 6.15, f"{recovery:.3f}% recovered", ha="center", fontsize=8.5, color=MUTED)

    draw_box(ax, 2.0, 1.5, 2.35, 1.13, f"Grant-linked P\n{grant_n} publications", LIGHT_GOLD)
    draw_box(ax, 6.0, 1.5, 2.35, 1.13, f"Policy-linked P\n{policy_n} publications", LIGHT_PURPLE)
    draw_box(ax, 10.45, 1.5, 2.0, 1.13, "Policy issuers\nrole-separated context", "#E6ECF2")
    arrow(ax, (4.35, 5.25), (3.18, 2.67))
    arrow(ax, (5.25, 5.25), (7.18, 2.67))
    arrow(ax, (8.38, 2.06), (10.40, 2.06))

    ax.text(2.25, 3.65, f"P–G: {int(edges['publication_grant'])} recorded\nidentifier edges", ha="center", va="center", fontsize=9, color=NAVY, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#B4C4D1"))
    ax.text(7.62, 3.65, f"P–D: {int(edges['publication_policy_document'])} recorded\nidentifier edges", ha="center", va="center", fontsize=9, color=NAVY, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#B4C4D1"))
    ax.text(9.40, 2.95, f"Issuer–P: {int(edges['policy_issuer_publication'])}\nunique role-separated edges", ha="center", va="center", fontsize=8.5, color=NAVY, bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#B4C4D1"))
    return save_figure(fig, output_dir, "figure_1_study_scope_and_relation_layers")


def ordered_theme_rows(theme_outcomes: pd.DataFrame, outcome: str) -> pd.DataFrame:
    frame = theme_outcomes.loc[
        theme_outcomes["group_variable"].eq("dominant_K3_theme__supplementary")
        & theme_outcomes["outcome"].eq(outcome)
    ].copy()
    rows: list[pd.Series] = []
    for full_label, _, _ in THEMES:
        selected = frame.loc[frame["group_level"].eq(full_label)]
        if len(selected) != 1:
            raise FigureGenerationFailure(f"Expected exactly one {outcome} row for {full_label}.")
        rows.append(selected.iloc[0])
    return pd.DataFrame(rows)


def figure_2_supplementary_theme_rates(tables: dict[str, pd.DataFrame], output_dir: Path) -> list[Path]:
    source = tables["theme_outcomes"]
    grant = ordered_theme_rows(source, "has_grant_link")
    policy = ordered_theme_rows(source, "has_policy_document_link")
    short_labels = [short for _, short, _ in THEMES]
    colors = [color for _, _, color in THEMES]
    population = grant["n_publications"].to_numpy(dtype=float)
    x = np.arange(len(THEMES))

    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.4), gridspec_kw={"width_ratios": [0.86, 1.14]})
    bars = axes[0].bar(x, population, color=colors, width=0.68)
    axes[0].set_xticks(x, short_labels, fontsize=8.3)
    axes[0].set_ylabel("Publications")
    axes[0].set_title("A. Supplementary hard-assignment sizes", loc="left", fontsize=10.5)
    axes[0].grid(axis="y")
    for bar, value in zip(bars, population):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + max(population) * 0.025, f"{int(value)}\n({100 * value / EXPECTED_PUBLICATION_RECORDS:.1f}%)", ha="center", va="bottom", fontsize=8.6)

    width = 0.35
    for offset, frame, label, color in [(-width / 2, grant, "Recorded grant link", GOLD), (width / 2, policy, "Recorded policy link", PURPLE)]:
        rates = frame["linkage_rate_pct"].to_numpy(dtype=float)
        lower = frame["wilson_ci_95_low_pct"].to_numpy(dtype=float)
        upper = frame["wilson_ci_95_high_pct"].to_numpy(dtype=float)
        bars = axes[1].bar(x + offset, rates, width, label=label, color=color, alpha=0.92)
        axes[1].errorbar(x + offset, rates, yerr=np.vstack([rates - lower, upper - rates]), fmt="none", ecolor=TEXT, capsize=3, linewidth=1)
        for bar, events, total, rate in zip(bars, frame["n_linked_publications"], frame["n_publications"], rates):
            axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.7, f"{int(events)}/{int(total)}\n{rate:.1f}%", ha="center", va="bottom", fontsize=7.6)
    axes[1].set_xticks(x, short_labels, fontsize=8.3)
    axes[1].set_ylabel("Recorded-linkage rate (%)")
    axes[1].set_title("B. Supplementary descriptive rates by dominant K=3 theme", loc="left", fontsize=10.5)
    axes[1].grid(axis="y")
    axes[1].legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.suptitle("K=3 FAIRification themes and recorded-linkage patterns", x=0.01, y=1.03, ha="left", fontsize=13, fontweight="bold")
    return save_figure(fig, output_dir, "figure_2_supplementary_K3_theme_linkage_rates")


def figure_3_primary_grant_associations(tables: dict[str, pd.DataFrame], output_dir: Path) -> list[Path]:
    coefficients = tables["association_coefficients"]
    primary = coefficients.loc[coefficients["model_label"].eq("grant_primary__continuous_K3_shares__year_adjusted")].copy()
    display = [
        ("nmf_topic_1_share_per_10pp", "Institutional stewardship / open-science practice"),
        ("nmf_topic_3_share_per_10pp", "Digital heritage / collections / preservation"),
    ]
    rows: list[pd.Series] = []
    labels: list[str] = []
    for term, label in display:
        subset = primary.loc[primary["term"].eq(term)]
        if len(subset) != 1:
            raise FigureGenerationFailure(f"Primary grant association coefficients lack exactly one {term} term.")
        rows.append(subset.iloc[0])
        labels.append(label)
    data = pd.DataFrame(rows)
    values = data["odds_ratio"].to_numpy(dtype=float)
    low = data["ci_95_odds_ratio_low"].to_numpy(dtype=float)
    high = data["ci_95_odds_ratio_high"].to_numpy(dtype=float)
    if (values <= 0).any() or (low <= 0).any() or (high <= 0).any():
        raise FigureGenerationFailure("Primary grant odds ratios and confidence intervals must be positive.")

    fig, ax = plt.subplots(figsize=(9.6, 4.9))
    y = np.arange(len(data))[::-1]
    ax.errorbar(values, y, xerr=np.vstack([values - low, high - values]), fmt="o", color=NAVY, ecolor=NAVY, capsize=4, markersize=7)
    ax.axvline(1, color=MUTED, linewidth=1.15, linestyle="--")
    ax.set_xscale("log")
    minimum = max(0.1, float(low.min()) * 0.75)
    maximum = max(2.0, float(high.max()) * 1.35)
    ax.set_xlim(minimum, maximum)
    tick_values = [value for value in (0.25, 0.5, 1.0, 2.0, 4.0) if minimum <= value <= maximum]
    ax.set_xticks(tick_values, [f"{value:g}" for value in tick_values])
    ax.minorticks_off()
    ax.set_yticks(y, labels)
    ax.set_xlabel("Adjusted odds ratio per +10 percentage points of NMF share (log scale)")
    ax.set_title("Primary conditional associations with a recorded grant link", loc="left", fontsize=12)
    ax.grid(axis="x")
    for yy, estimate, lower, upper in zip(y, values, low, high):
        ax.text(maximum * 0.98, yy, f"{estimate:.2f} [{lower:.2f}, {upper:.2f}]", ha="right", va="center", fontsize=8.6)
    fig.subplots_adjust(left=0.34, right=0.97, bottom=0.16, top=0.84)
    fig._fairification_layout_is_manual = True
    return save_figure(fig, output_dir, "figure_3_primary_grant_link_associations")


def figure_4_timing_and_policy_adequacy(tables: dict[str, pd.DataFrame], output_dir: Path) -> list[Path]:
    timing = tables["timing"].copy()
    order = ["publication_grant", "publication_policy_document"]
    labels = ["P–G", "P–D"]
    timing = timing.set_index("relation").reindex(order).reset_index()
    categories = [
        ("n_negative_record_year_differences", "Linked record earlier", RED),
        ("n_zero_record_year_differences", "Same record year", GRAY),
        ("n_positive_record_year_differences", "Linked record later", TEAL),
    ]
    policy = tables["policy_adequacy"].copy()
    window_order = ["primary_policy_window", "longer_window_robustness", "all_final_P__policy_window_sensitivity"]
    policy = policy.set_index("policy_window").reindex(window_order).reset_index()
    if policy.isna().any().any():
        raise FigureGenerationFailure("Policy event-adequacy accounting lacks a predeclared policy window.")

    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.2), gridspec_kw={"width_ratios": [1.02, 0.98]})
    bottom = np.zeros(len(timing))
    for column, label, color in categories:
        values = timing[column].to_numpy(dtype=float)
        axes[0].bar(labels, values, bottom=bottom, color=color, width=0.62, label=label)
        bottom += values
    axes[0].set_ylabel("Dated recorded relation edges")
    axes[0].set_title("A. Record-year ordering is descriptive", loc="left", fontsize=10.5)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    axes[0].grid(axis="y")
    for index, row in timing.iterrows():
        axes[0].text(index, bottom[index] + max(bottom) * 0.025, f"Median: {float(row['median_record_year_difference']):+.1f} years", ha="center", fontsize=8.3)
        axes[0].text(index, -max(bottom) * 0.085, f"{int(row['n_edges_with_both_record_years'])}/{int(row['n_edges'])} with both years", ha="center", fontsize=7.8, color=MUTED)

    window_labels = ["Primary\nthrough 2022", "Longer-window\nthrough 2021", "All final P\nsensitivity"]
    events = policy["n_policy_linked_publications"].to_numpy(dtype=float)
    required = policy["required_events_for_multivariable_model"].to_numpy(dtype=float)
    x = np.arange(len(policy))
    bars = axes[1].bar(x, required, width=0.62, color=LIGHT_GOLD, edgecolor=GOLD, label="Predeclared required events")
    axes[1].bar(x, events, width=0.40, color=PURPLE, label="Observed policy-link events")
    axes[1].set_xticks(x, window_labels, fontsize=8.6)
    axes[1].set_ylabel("Events")
    axes[1].set_title("B. Policy models are correctly withheld", loc="left", fontsize=10.5)
    axes[1].set_ylim(0, max(required) * 1.2)
    axes[1].legend(frameon=False, fontsize=8.1, loc="upper right")
    axes[1].grid(axis="y")
    for index, (event, requirement, n_publications) in enumerate(zip(events, required, policy["n_publications"])):
        axes[1].text(index, event + 1.0, f"{int(event)}/{int(n_publications)}\nnot fit", ha="center", va="bottom", fontsize=8.2, color=PURPLE)
        axes[1].text(index, requirement + 1.0, f"{int(requirement)} required", ha="center", va="bottom", fontsize=7.6, color=GOLD)
    fig.suptitle("Record-year context and policy-link event adequacy", x=0.01, y=1.03, ha="left", fontsize=13, fontweight="bold")
    return save_figure(fig, output_dir, "figure_4_record_year_context_and_policy_adequacy")


def null_panel(ax: plt.Axes, row: pd.Series, title: str, xlabel: str) -> None:
    observed = float(row["observed"])
    mean = float(row["null_mean"])
    low = float(row["null_interval_2_5"])
    high = float(row["null_interval_97_5"])
    p_value = float(row["permutation_p_enrichment_upper_tail"])
    enrichment = float(row["observed_to_null_mean_enrichment"])
    ax.hlines(0, low, high, color=LIGHT_BLUE, linewidth=12, zorder=1, label="Null 95% interval")
    ax.plot(mean, 0, "o", color=NAVY, markersize=7, zorder=3, label="Null mean")
    ax.plot(observed, 0, "o", color=RED, markersize=8, zorder=4, label="Observed")
    ax.set_yticks([])
    ax.set_xlabel(xlabel)
    ax.set_title(title, loc="left", fontsize=10)
    ax.grid(axis="x")
    ax.legend(frameon=False, fontsize=7.7, loc="upper left")
    ax.text(0.98, 0.88, f"Upper-tail p = {p_value:.3f}\nObserved/null mean = {enrichment:.2f}", transform=ax.transAxes, ha="right", va="top", fontsize=8.0, bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#B4C4D1"))


def figure_5_cross_relation_configurations(tables: dict[str, pd.DataFrame], output_dir: Path) -> list[Path]:
    configurations = tables["configurations"].set_index("configuration")
    order = ["P_G_only", "P_D_only", "both", "neither"]
    labels = ["P–G only", "P–D only", "Both", "Neither"]
    colors = [NAVY, TEAL, GOLD, GRAY]
    values = configurations.loc[order, "n_publications"].to_numpy(dtype=float)
    shares = configurations.loc[order, "share_of_final_P"].to_numpy(dtype=float)
    null_summary = tables["configuration_null"]
    primary = null_summary.loc[null_summary["null_scheme"].eq(PRIMARY_NULL)].set_index("statistic")
    n_both = primary.loc["N_both"]
    intensity = primary.loc["intensive_degree_product_sum"]

    fig, axes = plt.subplots(1, 3, figsize=(16.0, 5.1), gridspec_kw={"width_ratios": [1.1, 0.92, 0.98]})
    bars = axes[0].bar(labels, values, color=colors, width=0.68)
    axes[0].set_ylabel("Final-P publications")
    axes[0].set_title("A. Observed local configurations", loc="left", fontsize=10.5)
    axes[0].grid(axis="y")
    axes[0].set_ylim(0, max(values) * 1.2)
    for bar, value, share in zip(bars, values, shares):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + max(values) * 0.025, f"{int(value)}\n({100 * share:.1f}%)", ha="center", va="bottom", fontsize=8.3)
    null_panel(axes[1], n_both, "B. Extensive-margin alignment", "Publications with both P–G and P–D links")
    null_panel(axes[2], intensity, "C. Intensive-margin alignment", r"$\sum_p d_{PG}(p) d_{PD}(p)$")
    fig.suptitle("Year-stratified cross-relation configuration test", x=0.01, y=1.03, ha="left", fontsize=13, fontweight="bold")
    return save_figure(fig, output_dir, "figure_5_cross_relation_configurations")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
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


def atomic_write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def main() -> None:
    temporary_output: Path | None = None
    try:
        args = preflight(parse_args())
        _, tables, input_hashes = load_certified_bundle(args.bundle_dir)
        validate_figure_inputs(tables)

        args.output_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = Path(tempfile.mkdtemp(prefix=f".{args.output_dir.name}.building.", dir=args.output_dir.parent))

        with plt.rc_context(STYLE):
            generated = []
            generated.extend(figure_1_scope_and_layers(tables, temporary_output))
            generated.extend(figure_2_supplementary_theme_rates(tables, temporary_output))
            generated.extend(figure_3_primary_grant_associations(tables, temporary_output))
            generated.extend(figure_4_timing_and_policy_adequacy(tables, temporary_output))
            generated.extend(figure_5_cross_relation_configurations(tables, temporary_output))
        output_hashes = {
            path.name: {"path": str(args.output_dir / path.name), "sha256": sha256(path)}
            for path in sorted(generated)
        }
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "input_bundle": {"path": str(args.bundle_dir), "manifest_sha256": input_hashes["results_bundle_manifest.json"]},
            "input_files": {name: {"path": str(args.bundle_dir / name), "sha256": digest} for name, digest in input_hashes.items() if name != "results_bundle_manifest.json"},
            "figure_files": [path.name for path in sorted(generated)],
            "output_files": output_hashes,
            "frozen_scope": {
                "source_cohort_records": EXPECTED_SOURCE_RECORDS,
                "dimensions_anchor_publications": EXPECTED_PUBLICATION_RECORDS,
                "grant_linked_publications": EXPECTED_GRANT_LINKED_PUBLICATIONS,
                "policy_linked_publications": EXPECTED_POLICY_LINKED_PUBLICATIONS,
                "primary_policy_window": f"{EXPECTED_PRIMARY_POLICY_EVENTS} events among {EXPECTED_PRIMARY_POLICY_PUBLICATIONS} publications; model withheld below {EXPECTED_PRIMARY_POLICY_REQUIRED_EVENTS} required events",
            },
            "interpretive_boundary": "Figures reproduce only certified aggregate outputs. Grant and policy results are Dimensions-recorded identifier links, not causal effects, funding intent, policy endorsement, uptake, impact, institutional influence, or topical similarity. Record-year quantities are descriptive stored dates; the cross-relation test is structural rather than causal.",
            "data_boundary": "Figures are protected local derived outputs. They must not be committed to GitHub before a deliberate release decision. No raw or record-level data were read.",
        }
        atomic_write_json(temporary_output / "figure_manifest.json", manifest)
        os.replace(temporary_output, args.output_dir)
        temporary_output = None

        print("FAIRIFICATION CERTIFIED FIGURES: PASS")
        print(f"CERTIFIED BUNDLE: {args.bundle_dir}")
        print("FIGURES: 5 PNG + 5 PDF")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'figure_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        if temporary_output is not None and temporary_output.exists():
            shutil.rmtree(temporary_output, ignore_errors=True)


if __name__ == "__main__":
    main()

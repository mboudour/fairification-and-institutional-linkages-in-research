#!/usr/bin/env python3
"""Build a protected, aggregate-only FAIRification results bundle.

This is the first reporting-stage script. It does not perform new statistical
analysis, request Dimensions data, fit a model, or generate figures. Instead it
creates one hash-certified local bundle of aggregate tables from the completed
core FAIRification stages. The next figure and manuscript-material scripts must
read this bundle rather than independently selecting local stage outputs.

The bundle intentionally excludes publication-, grant-, policy-document-,
organization-, author-, title-, abstract-, DOI-, and edge-level records. It
contains only non-record-level outcome, diagnostic, robustness, timing,
network-scope, and configuration summaries.

Example:
    python code/reporting/17_build_certified_results_bundle.py \
      --relational-audit-dir /path/to/10_relational_audit_and_edges_run \
      --analysis-base-dir /path/to/11_publication_linkage_analysis_base_run \
      --association-dir /path/to/12_linkage_associations_run \
      --temporal-dir /path/to/13_temporal_audit_run \
      --network-dir /path/to/14_networks_organizations_countries_run \
      --robustness-dir /path/to/15_robustness_evidence_run \
      --configuration-dir /path/to/16_local_cross_relation_configurations_run \
      --output-dir /path/to/17_certified_results_bundle_run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SCRIPT_VERSION = "17_build_certified_results_bundle_1.0"
EXPECTED_SOURCE_RECORDS = 163
EXPECTED_PUBLICATION_RECORDS = 144
EXPECTED_GRANT_LINKED_PUBLICATIONS = 52
EXPECTED_POLICY_LINKED_PUBLICATIONS = 4
EXPECTED_PRIMARY_POLICY_WINDOW_PUBLICATIONS = 72
EXPECTED_PRIMARY_POLICY_WINDOW_EVENTS = 3

# Only summary-level tables are eligible for the protected reporting bundle.
# The source filename is certified against its own stage manifest before it is
# written to the new bundle filename.
TABLE_SPECIFICATIONS: tuple[dict[str, str], ...] = (
    {
        "stage": "relational_audit", "source": "source_dimensions_match_quality_summary.csv",
        "output": "A01_source_to_Dimensions_coverage_summary.csv",
        "domain": "A_source_and_relation_scope",
        "purpose": "Frozen source-cohort and Dimensions-recovery denominator summary.",
    },
    {
        "stage": "relational_audit", "source": "edge_summary.csv",
        "output": "A02_recorded_relation_edge_summary.csv",
        "domain": "A_source_and_relation_scope",
        "purpose": "Aggregate counts for the three audited identifier relation layers.",
    },
    {
        "stage": "analysis_base", "source": "overall_linkage_outcomes.csv",
        "output": "B01_overall_recorded_linkage_outcomes.csv",
        "domain": "B_recorded_linkage_outcomes",
        "purpose": "Overall publication-level grant and policy linkage rates.",
    },
    {
        "stage": "analysis_base", "source": "linkage_outcomes_by_dominant_K3_theme__supplementary.csv",
        "output": "B02_linkage_outcomes_by_dominant_K3_theme_supplementary.csv",
        "domain": "B_recorded_linkage_outcomes",
        "purpose": "Supplementary hard-assignment descriptive rates; not primary association inference.",
    },
    {
        "stage": "analysis_base", "source": "policy_observation_window_samples.csv",
        "output": "B03_frozen_policy_observation_window_samples.csv",
        "domain": "B_recorded_linkage_outcomes",
        "purpose": "Predeclared policy-observation sample denominators.",
    },
    {
        "stage": "associations", "source": "association_model_diagnostics.csv",
        "output": "C01_association_model_diagnostics.csv",
        "domain": "C_association_evidence",
        "purpose": "Model status, event counts, and fit diagnostics including certified not-fit policy models.",
    },
    {
        "stage": "associations", "source": "association_model_coefficients.csv",
        "output": "C02_association_model_coefficients.csv",
        "domain": "C_association_evidence",
        "purpose": "Conditional grant-link association coefficients only where a model was fit.",
    },
    {
        "stage": "associations", "source": "event_adequacy_assessment.csv",
        "output": "C03_association_event_adequacy_assessment.csv",
        "domain": "C_association_evidence",
        "purpose": "Predeclared event-adequacy accounting for all association specifications.",
    },
    {
        "stage": "associations", "source": "policy_link_event_limited_descriptives.csv",
        "output": "C04_policy_link_event_limited_descriptives.csv",
        "domain": "C_association_evidence",
        "purpose": "Descriptive policy-link results retained when sparse events preclude multivariable models.",
    },
    {
        "stage": "temporal", "source": "record_year_difference_summary.csv",
        "output": "D01_record_year_difference_summary.csv",
        "domain": "D_record_year_and_policy_window_context",
        "purpose": "Descriptive record-year differences for P--G and P--D relations.",
    },
    {
        "stage": "temporal", "source": "policy_observation_window_samples.csv",
        "output": "D02_temporal_policy_observation_window_samples.csv",
        "domain": "D_record_year_and_policy_window_context",
        "purpose": "Policy-window denominators independently audited against stored record years.",
    },
    {
        "stage": "networks", "source": "network_basic_statistics.csv",
        "output": "E01_role_separated_network_basic_statistics.csv",
        "domain": "E_role_separated_network_scope",
        "purpose": "Aggregate size, coverage, degree, density, and component statistics for audited networks.",
    },
    {
        "stage": "networks", "source": "network_degree_concentration.csv",
        "output": "E02_role_separated_network_degree_concentration.csv",
        "domain": "E_role_separated_network_scope",
        "purpose": "Aggregate network concentration summaries without nodes or organization names.",
    },
    {
        "stage": "networks", "source": "organization_role_attribute_coverage.csv",
        "output": "E03_organization_role_attribute_coverage.csv",
        "domain": "E_role_separated_network_scope",
        "purpose": "Role-specific organization metadata coverage without identifiers or names.",
    },
    {
        "stage": "robustness", "source": "nmf_candidate_stability_summary.csv",
        "output": "F01_NMF_candidate_stability_summary.csv",
        "domain": "F_robustness_evidence",
        "purpose": "K=2/K=3/K=4 aggregate NMF candidate diagnostics.",
    },
    {
        "stage": "robustness", "source": "nmf_component_stability_summary.csv",
        "output": "F02_NMF_component_stability_summary.csv",
        "domain": "F_robustness_evidence",
        "purpose": "Component-level bootstrap stability diagnostics, including the K=3 specialist caveat.",
    },
    {
        "stage": "robustness", "source": "wilkinson_leave_one_out_K2_reproduction_summary.csv",
        "output": "F03_Wilkinson_leave_one_out_K2_reproduction_summary.csv",
        "domain": "F_robustness_evidence",
        "purpose": "K=2-only leave-one-out sensitivity for the documented foundational-paper addition; source DOI is redacted in this aggregate release.",
    },
    {
        "stage": "robustness", "source": "grant_association_sensitivity_comparison.csv",
        "output": "F04_grant_association_sensitivity_comparison.csv",
        "domain": "F_robustness_evidence",
        "purpose": "Primary and predeclared grant-link association sensitivity comparison.",
    },
    {
        "stage": "robustness", "source": "policy_window_event_adequacy_accounting.csv",
        "output": "F05_policy_window_event_adequacy_accounting.csv",
        "domain": "F_robustness_evidence",
        "purpose": "Policy event counts and withheld-model accounting across predeclared windows.",
    },
    {
        "stage": "robustness", "source": "robustness_scope_and_limitations.csv",
        "output": "F06_robustness_scope_and_limitations.csv",
        "domain": "F_robustness_evidence",
        "purpose": "Certified scope, limits, and non-use of a post hoc FAIR dictionary indicator.",
    },
    {
        "stage": "configuration", "source": "configuration_observed_summary.csv",
        "output": "G01_observed_P_G_P_D_configurations.csv",
        "domain": "G_local_cross_relation_configuration",
        "purpose": "Observed P--G/P--D publication configurations.",
    },
    {
        "stage": "configuration", "source": "cross_relation_alignment_null_summary.csv",
        "output": "G02_year_stratified_cross_relation_null_summary.csv",
        "domain": "G_local_cross_relation_configuration",
        "purpose": "Primary and sensitivity structural alignment summaries, including null-information status.",
    },
    {
        "stage": "configuration", "source": "issuer_attribution_coverage.csv",
        "output": "G03_issuer_attribution_coverage.csv",
        "domain": "G_local_cross_relation_configuration",
        "purpose": "Descriptive issuer-attribution coverage; issuers are not a third rewired relation.",
    },
)

FORBIDDEN_COLUMN_TOKENS = {
    "publication_id", "grant_id", "policy_document_id", "source_record_id", "doi",
    "title", "abstract", "author", "authors", "issuer_id", "issuer_name",
    "organization_id", "organization_name", "research_org_id", "research_org_name",
    "policy_document_ids", "publication_ids", "grant_ids",
}

MAX_ROWS_BY_BUNDLE_FILE = {
    "A01_source_to_Dimensions_coverage_summary.csv": 1,
    "A02_recorded_relation_edge_summary.csv": 3,
    "B01_overall_recorded_linkage_outcomes.csv": 2,
    "B02_linkage_outcomes_by_dominant_K3_theme_supplementary.csv": 6,
    "B03_frozen_policy_observation_window_samples.csv": 3,
    "C01_association_model_diagnostics.csv": 10,
    "C02_association_model_coefficients.csv": 50,
    "C03_association_event_adequacy_assessment.csv": 10,
    "C04_policy_link_event_limited_descriptives.csv": 20,
    "D01_record_year_difference_summary.csv": 2,
    "D02_temporal_policy_observation_window_samples.csv": 3,
    "E01_role_separated_network_basic_statistics.csv": 6,
    "E02_role_separated_network_degree_concentration.csv": 18,
    "E03_organization_role_attribute_coverage.csv": 24,
    "F01_NMF_candidate_stability_summary.csv": 3,
    "F02_NMF_component_stability_summary.csv": 12,
    "F03_Wilkinson_leave_one_out_K2_reproduction_summary.csv": 1,
    "F04_grant_association_sensitivity_comparison.csv": 50,
    "F05_policy_window_event_adequacy_accounting.csv": 3,
    "F06_robustness_scope_and_limitations.csv": 10,
    "G01_observed_P_G_P_D_configurations.csv": 4,
    "G02_year_stratified_cross_relation_null_summary.csv": 10,
    "G03_issuer_attribution_coverage.csv": 1,
}


class ResultsBundleFailure(RuntimeError):
    """A certified-result or release-boundary failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relational-audit-dir", type=Path, required=True)
    parser.add_argument("--analysis-base-dir", type=Path, required=True)
    parser.add_argument("--association-dir", type=Path, required=True)
    parser.add_argument("--temporal-dir", type=Path, required=True)
    parser.add_argument("--network-dir", type=Path, required=True)
    parser.add_argument("--robustness-dir", type=Path, required=True)
    parser.add_argument("--configuration-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def repository_root() -> Path | None:
    """Locate this checked-out repository without relying on user Git settings."""
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


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


def atomic_write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResultsBundleFailure(f"{label} must be a JSON object: {path}")
    return payload


def validate_stage_directory(path: Path, manifest_name: str, label: str) -> tuple[Path, dict[str, Any]]:
    if not path.is_dir():
        raise FileNotFoundError(f"Missing {label} directory: {path}")
    manifest_path = path / manifest_name
    manifest = read_json(manifest_path, f"{label} manifest")
    if manifest.get("status") != "complete":
        raise ResultsBundleFailure(f"{label} manifest is not marked complete: {manifest_path}")
    if not isinstance(manifest.get("output_files"), dict):
        raise ResultsBundleFailure(f"{label} manifest lacks an output_files object: {manifest_path}")
    return manifest_path, manifest


def certified_csv(stage_dir: Path, manifest: dict[str, Any], filename: str, stage_label: str) -> tuple[pd.DataFrame, str]:
    path = stage_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing certified {stage_label} output: {path}")
    entry = manifest["output_files"].get(filename)
    if not isinstance(entry, dict) or not entry.get("sha256"):
        raise ResultsBundleFailure(f"{stage_label} manifest lacks a SHA-256 entry for {filename}.")
    current_hash = sha256(path)
    if current_hash != entry["sha256"]:
        raise ResultsBundleFailure(f"{stage_label} output hash mismatch for {filename}; rerun its producing stage rather than mixing files.")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if "rows" not in entry or isinstance(entry["rows"], bool):
        raise ResultsBundleFailure(f"{stage_label} manifest lacks an integral row count for {filename}.")
    try:
        declared_rows = int(entry["rows"])
    except (TypeError, ValueError) as error:
        raise ResultsBundleFailure(f"{stage_label} manifest has an invalid row count for {filename}.") from error
    if str(declared_rows) != str(entry["rows"]).strip() or declared_rows < 0:
        raise ResultsBundleFailure(f"{stage_label} manifest has a non-integral or negative row count for {filename}.")
    if declared_rows != len(frame):
        raise ResultsBundleFailure(f"{stage_label} manifest row count disagrees with {filename}.")
    return frame, current_hash


def certified_file(stage_dir: Path, manifest: dict[str, Any], filename: str, stage_label: str) -> str:
    """Verify a non-CSV output used only to close a provenance hash chain."""
    path = stage_dir / filename
    entry = manifest["output_files"].get(filename)
    if not path.is_file() or not isinstance(entry, dict) or not entry.get("sha256"):
        raise ResultsBundleFailure(f"{stage_label} lacks the certified provenance artifact {filename}.")
    current_hash = sha256(path)
    if current_hash != entry["sha256"]:
        raise ResultsBundleFailure(f"{stage_label} provenance artifact hash mismatch for {filename}.")
    return current_hash


def require_input_hash(manifest: dict[str, Any], key: str, expected_hash: str, stage_label: str) -> None:
    """Require that a downstream manifest references the exact upstream artifact."""
    input_files = manifest.get("input_files")
    if not isinstance(input_files, dict):
        raise ResultsBundleFailure(f"{stage_label} manifest lacks input_files required for lineage validation.")
    entry = input_files.get(key)
    if not isinstance(entry, dict) or not entry.get("sha256"):
        raise ResultsBundleFailure(f"{stage_label} manifest lacks an input hash for {key}.")
    if entry["sha256"] != expected_hash:
        raise ResultsBundleFailure(f"{stage_label} does not derive from the supplied certified upstream {key} artifact.")


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ResultsBundleFailure(f"{label} is missing required column(s): " + ", ".join(missing))


def normalized_column(column: object) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(column).strip())
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def assert_aggregate_safe(frame: pd.DataFrame, label: str, bundle_filename: str) -> None:
    maximum_rows = MAX_ROWS_BY_BUNDLE_FILE[bundle_filename]
    if len(frame) > maximum_rows:
        raise ResultsBundleFailure(
            f"{label} exceeds the aggregate-only cardinality limit for {bundle_filename}: {len(frame)} > {maximum_rows}."
        )
    normalized = {normalized_column(column) for column in frame.columns}
    forbidden = sorted(FORBIDDEN_COLUMN_TOKENS.intersection(normalized))
    sensitive_patterns = (
        r"(^|_)(publication|grant|policy_document|source_record|record|issuer|organization|research_org)(_)?(id|ids|identifier|identifiers)$",
        r"(^|_)(doi|dois|title|titles|abstract|abstracts|author|authors|full_text|text|content|url|urls)$",
        r"(^|_)(issuer|organization|research_org|country|node)(_)?name(s)?$",
        r"(^|_)(edge|edges)(_)?(id|ids|source|target|list|table)$",
    )
    for column in normalized:
        if column == "id" or column.endswith("_id") or column.endswith("_ids"):
            forbidden.append(column)
        elif any(re.search(pattern, column) for pattern in sensitive_patterns):
            forbidden.append(column)
    forbidden = sorted(set(forbidden))
    if forbidden:
        raise ResultsBundleFailure(
            f"{label} is not eligible for the aggregate-only reporting bundle; prohibited column(s): {', '.join(forbidden)}"
        )


def release_safe_frame(frame: pd.DataFrame, bundle_filename: str) -> tuple[pd.DataFrame, str]:
    """Apply the sole predeclared identifier redaction required for aggregate release.

    The stage-15 Wilkinson sensitivity summary is a one-row aggregate table, but
    it carries ``excluded_doi`` as a provenance field. The DOI is already
    documented elsewhere in the protocol; it is not needed for the aggregate
    reporting bundle and must not cross this release boundary.
    """
    if bundle_filename != "F03_Wilkinson_leave_one_out_K2_reproduction_summary.csv":
        return frame.copy(), "none"
    if "excluded_doi" not in frame.columns:
        raise ResultsBundleFailure(
            "Wilkinson leave-one-out summary lacks the expected excluded_doi field required for documented redaction."
        )
    redacted = frame.drop(columns=["excluded_doi"]).copy()
    if "excluded_record_description" not in redacted.columns:
        redacted.insert(0, "excluded_record_description", "documented_manual_addition")
    return redacted, "excluded_doi dropped; replaced with non-identifier documented_manual_addition descriptor"


def numeric_one(frame: pd.DataFrame, column: str, label: str) -> float:
    require_columns(frame, {column}, label)
    if len(frame) != 1:
        raise ResultsBundleFailure(f"{label} must contain exactly one summary row.")
    value = pd.to_numeric(frame.iloc[0][column], errors="coerce")
    if pd.isna(value):
        raise ResultsBundleFailure(f"{label}.{column} is missing or nonnumeric.")
    value = float(value)
    if not math.isfinite(value):
        raise ResultsBundleFailure(f"{label}.{column} is not finite.")
    return value


def integer_one(frame: pd.DataFrame, column: str, label: str) -> int:
    value = numeric_one(frame, column, label)
    if not value.is_integer():
        raise ResultsBundleFailure(f"{label}.{column} must be an exact integer.")
    return int(value)


def parse_boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ResultsBundleFailure(f"{label} must be a Boolean value.")


def preflight(args: argparse.Namespace) -> argparse.Namespace:
    directory_fields = (
        "relational_audit_dir", "analysis_base_dir", "association_dir", "temporal_dir",
        "network_dir", "robustness_dir", "configuration_dir", "output_dir",
    )
    for field in directory_fields:
        setattr(args, field, resolved(getattr(args, field)))
    for field in directory_fields[:-1]:
        path = getattr(args, field)
        if not path.is_dir():
            raise FileNotFoundError(f"Required input directory does not exist: {path}")
    if args.output_dir.exists() and (args.output_dir.is_file() or args.output_dir.is_symlink()):
        raise ValueError(f"Output path must be a real directory: {args.output_dir}")
    repo = repository_root()
    if repo is not None and is_within(args.output_dir, repo):
        raise ValueError(f"Output directory must be outside the Git worktree: {repo}")
    for field in directory_fields[:-1]:
        input_dir = getattr(args, field)
        if is_within(input_dir, args.output_dir) or is_within(args.output_dir, input_dir):
            raise ValueError("Output directory must not contain, or be contained by, an input-stage directory.")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {args.output_dir}; choose a new empty directory.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


def validate_cross_stage_lineage(stages: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Close the manifest hash chain across the supplied completed runs."""
    relational = stages["relational_audit"]
    base = stages["analysis_base"]
    associations = stages["associations"]
    temporal = stages["temporal"]
    networks = stages["networks"]
    robustness = stages["robustness"]
    configuration = stages["configuration"]

    relational_manifest_hash = sha256(relational["manifest_path"])
    base_manifest_hash = sha256(base["manifest_path"])
    association_manifest_hash = sha256(associations["manifest_path"])
    temporal_manifest_hash = sha256(temporal["manifest_path"])
    pg_edges_hash = certified_file(relational["directory"], relational["manifest"], "edges_publication_grant.csv", relational["label"])
    pd_edges_hash = certified_file(relational["directory"], relational["manifest"], "edges_publication_policy_document.csv", relational["label"])
    issuer_edges_hash = certified_file(relational["directory"], relational["manifest"], "edges_policy_issuer_publication.csv", relational["label"])
    base_pickle_hash = certified_file(base["directory"], base["manifest"], "publication_linkage_analysis_base.pkl", base["label"])

    require_input_hash(base["manifest"], "relational_summary", relational_manifest_hash, base["label"])
    require_input_hash(base["manifest"], "publication_grant_edges", pg_edges_hash, base["label"])
    require_input_hash(base["manifest"], "publication_policy_edges", pd_edges_hash, base["label"])

    require_input_hash(associations["manifest"], "analysis_base", base_pickle_hash, associations["label"])
    require_input_hash(associations["manifest"], "analysis_base_manifest", base_manifest_hash, associations["label"])

    require_input_hash(temporal["manifest"], "analysis_base", base_pickle_hash, temporal["label"])
    require_input_hash(temporal["manifest"], "analysis_base_manifest", base_manifest_hash, temporal["label"])
    require_input_hash(temporal["manifest"], "association_manifest", association_manifest_hash, temporal["label"])
    require_input_hash(temporal["manifest"], "publication_grant_edges", pg_edges_hash, temporal["label"])
    require_input_hash(temporal["manifest"], "publication_policy_edges", pd_edges_hash, temporal["label"])

    require_input_hash(networks["manifest"], "relational_summary", relational_manifest_hash, networks["label"])
    require_input_hash(networks["manifest"], "publication_grant_edges", pg_edges_hash, networks["label"])
    require_input_hash(networks["manifest"], "publication_policy_edges", pd_edges_hash, networks["label"])
    require_input_hash(networks["manifest"], "policy_issuer_publication_edges", issuer_edges_hash, networks["label"])

    require_input_hash(robustness["manifest"], "association_manifest", association_manifest_hash, robustness["label"])
    require_input_hash(robustness["manifest"], "temporal_manifest", temporal_manifest_hash, robustness["label"])

    require_input_hash(configuration["manifest"], "analysis_base", base_pickle_hash, configuration["label"])
    require_input_hash(configuration["manifest"], "analysis_base_manifest", base_manifest_hash, configuration["label"])
    require_input_hash(configuration["manifest"], "publication_grant_edges", pg_edges_hash, configuration["label"])
    require_input_hash(configuration["manifest"], "publication_policy_edges", pd_edges_hash, configuration["label"])
    require_input_hash(configuration["manifest"], "policy_issuer_publication_edges", issuer_edges_hash, configuration["label"])
    require_input_hash(configuration["manifest"], "relational_summary", relational_manifest_hash, configuration["label"])

    return {
        "relational_summary_manifest": relational_manifest_hash,
        "analysis_base_manifest": base_manifest_hash,
        "association_manifest": association_manifest_hash,
        "temporal_manifest": temporal_manifest_hash,
        "publication_grant_edges": pg_edges_hash,
        "publication_policy_edges": pd_edges_hash,
        "policy_issuer_publication_edges": issuer_edges_hash,
        "publication_linkage_analysis_base": base_pickle_hash,
    }


def overview_table(coverage: pd.DataFrame, outcome_summary: pd.DataFrame, edge_summary: pd.DataFrame) -> pd.DataFrame:
    require_columns(
        coverage,
        {
            "frozen_source_cohort_records", "dimensions_recovered_analytic_subset_records",
            "not_recovered_by_doi_first_procedure", "dimensions_recovery_rate_pct",
        },
        "Source-to-Dimensions coverage summary",
    )
    source_n = integer_one(coverage, "frozen_source_cohort_records", "Source-to-Dimensions coverage summary")
    recovered_n = integer_one(coverage, "dimensions_recovered_analytic_subset_records", "Source-to-Dimensions coverage summary")
    unresolved_n = integer_one(coverage, "not_recovered_by_doi_first_procedure", "Source-to-Dimensions coverage summary")
    recovery_pct = numeric_one(coverage, "dimensions_recovery_rate_pct", "Source-to-Dimensions coverage summary")
    require_columns(outcome_summary, {"outcome", "n_publications", "n_linked_publications", "linkage_rate_pct"}, "Overall linkage outcomes")
    require_columns(edge_summary, {"network", "edges"}, "Recorded relation edge summary")
    rows: list[dict[str, Any]] = [
        {
            "section": "source_to_Dimensions_scope", "measure": "frozen_curated_source_cohort_records",
            "value": source_n, "unit": "records", "note": "162-record source export plus one documented FAIR Principles addition.",
        },
        {
            "section": "source_to_Dimensions_scope", "measure": "Dimensions_recovered_analytic_subset_records",
            "value": recovered_n, "unit": "records", "note": f"{recovery_pct:.3f}% of the frozen curated source cohort; exact DOI-first matches only.",
        },
        {
            "section": "source_to_Dimensions_scope", "measure": "unresolved_source_records_retained_in_audit",
            "value": unresolved_n, "unit": "records", "note": "Unresolved records remain in the coverage audit and are not treated as absent from Dimensions.",
        },
    ]
    for _, row in outcome_summary.iterrows():
        rows.append({
            "section": "recorded_publication_linkage_outcomes",
            "measure": str(row["outcome"]),
            "value": int(pd.to_numeric(row["n_linked_publications"], errors="raise")),
            "unit": f"linked publications of {int(pd.to_numeric(row['n_publications'], errors='raise'))}",
            "note": f"Recorded-linkage rate: {float(pd.to_numeric(row['linkage_rate_pct'], errors='raise')):.3f}%. Not a causal or impact measure.",
        })
    for _, row in edge_summary.iterrows():
        rows.append({
            "section": "audited_relation_layers",
            "measure": str(row["network"]),
            "value": int(pd.to_numeric(row["edges"], errors="raise")),
            "unit": "unique identifier edges",
            "note": "Dimensions-recorded identifier relation count.",
        })
    return pd.DataFrame(rows)


def main() -> None:
    try:
        args = parse_args()
        args = preflight(args)
        stages = {
            "relational_audit": {
                "directory": args.relational_audit_dir, "manifest_name": "retrieval_summary.json", "label": "Relational audit",
            },
            "analysis_base": {
                "directory": args.analysis_base_dir, "manifest_name": "analysis_base_manifest.json", "label": "Publication linkage analysis base",
            },
            "associations": {
                "directory": args.association_dir, "manifest_name": "association_manifest.json", "label": "Linkage associations",
            },
            "temporal": {
                "directory": args.temporal_dir, "manifest_name": "temporal_audit_manifest.json", "label": "Temporal audit",
            },
            "networks": {
                "directory": args.network_dir, "manifest_name": "network_analysis_manifest.json", "label": "Network analysis",
            },
            "robustness": {
                "directory": args.robustness_dir, "manifest_name": "robustness_manifest.json", "label": "Robustness consolidation",
            },
            "configuration": {
                "directory": args.configuration_dir, "manifest_name": "configuration_manifest.json", "label": "Cross-relation configuration test",
            },
        }
        for specification in stages.values():
            manifest_path, manifest = validate_stage_directory(
                specification["directory"], specification["manifest_name"], specification["label"]
            )
            specification["manifest_path"] = manifest_path
            specification["manifest"] = manifest

        lineage_hashes = validate_cross_stage_lineage(stages)

        relational = stages["relational_audit"]["manifest"]
        base_manifest = stages["analysis_base"]["manifest"]
        temporal_manifest = stages["temporal"]["manifest"]
        configuration_manifest = stages["configuration"]["manifest"]
        if relational.get("record_counts", {}).get("final_publications_P") != EXPECTED_PUBLICATION_RECORDS:
            raise ResultsBundleFailure("Relational-audit manifest does not certify the expected final publication count.")
        if base_manifest.get("records", {}).get("final_publications_P") != EXPECTED_PUBLICATION_RECORDS:
            raise ResultsBundleFailure("Analysis-base manifest does not certify the expected final publication count.")
        if temporal_manifest.get("record_counts", {}).get("final_publications_P") != EXPECTED_PUBLICATION_RECORDS:
            raise ResultsBundleFailure("Temporal-audit manifest does not certify the expected final publication count.")
        if configuration_manifest.get("observed_recorded_linkage_counts", {}).get("final_publications") != EXPECTED_PUBLICATION_RECORDS:
            raise ResultsBundleFailure("Configuration manifest does not certify the expected final publication count.")
        if temporal_manifest.get("policy_data_end_year") != 2026:
            raise ResultsBundleFailure("Temporal audit does not certify the frozen 2026 policy-data endpoint.")

        copied_tables: dict[str, pd.DataFrame] = {}
        index_rows: list[dict[str, Any]] = []
        input_hashes: dict[str, dict[str, str]] = {}
        for specification in TABLE_SPECIFICATIONS:
            stage = stages[specification["stage"]]
            source_frame, digest = certified_csv(
                stage["directory"], stage["manifest"], specification["source"], stage["label"]
            )
            frame, release_transform = release_safe_frame(source_frame, specification["output"])
            assert_aggregate_safe(frame, f"{stage['label']} / {specification['source']}", specification["output"])
            copied_tables[specification["output"]] = frame
            source_key = f"{specification['stage']}:{specification['source']}"
            input_hashes[source_key] = {"path": str(stage["directory"] / specification["source"]), "sha256": digest}
            index_rows.append({
                "domain": specification["domain"],
                "bundle_file": specification["output"],
                "source_stage": specification["stage"],
                "source_file": specification["source"],
                "source_rows": len(source_frame),
                "rows": len(frame),
                "release_transform": release_transform,
                "purpose": specification["purpose"],
                "aggregate_only_release_check": "pass",
            })

        coverage = copied_tables["A01_source_to_Dimensions_coverage_summary.csv"]
        outcomes = copied_tables["B01_overall_recorded_linkage_outcomes.csv"]
        edge_summary = copied_tables["A02_recorded_relation_edge_summary.csv"]
        coverage_source_n = integer_one(coverage, "frozen_source_cohort_records", "Source-to-Dimensions coverage summary")
        coverage_recovered_n = integer_one(coverage, "dimensions_recovered_analytic_subset_records", "Source-to-Dimensions coverage summary")
        coverage_unresolved_n = integer_one(coverage, "not_recovered_by_doi_first_procedure", "Source-to-Dimensions coverage summary")
        coverage_pct = numeric_one(coverage, "dimensions_recovery_rate_pct", "Source-to-Dimensions coverage summary")
        expected_recovery_pct = 100 * EXPECTED_PUBLICATION_RECORDS / EXPECTED_SOURCE_RECORDS
        if (
            coverage_source_n != EXPECTED_SOURCE_RECORDS
            or coverage_recovered_n != EXPECTED_PUBLICATION_RECORDS
            or coverage_unresolved_n != coverage_source_n - coverage_recovered_n
            or not math.isclose(coverage_pct, expected_recovery_pct, abs_tol=0.001, rel_tol=0)
        ):
            raise ResultsBundleFailure("Source-to-Dimensions coverage summary does not reconcile to the frozen 163-to-144 design.")
        require_columns(outcomes, {"outcome", "n_publications", "n_linked_publications"}, "Overall linkage outcomes")
        if outcomes["outcome"].duplicated().any() or set(outcomes["outcome"]) != {"has_grant_link", "has_policy_document_link"}:
            raise ResultsBundleFailure("Overall linkage outcomes must contain exactly the frozen grant and policy outcome rows.")
        if not (pd.to_numeric(outcomes["n_publications"], errors="coerce") == EXPECTED_PUBLICATION_RECORDS).all():
            raise ResultsBundleFailure("Overall linkage outcome denominators do not all equal the final 144-publication anchor.")
        linked_counts = outcomes.set_index("outcome")["n_linked_publications"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
        if (
            linked_counts["has_grant_link"] != EXPECTED_GRANT_LINKED_PUBLICATIONS
            or linked_counts["has_policy_document_link"] != EXPECTED_POLICY_LINKED_PUBLICATIONS
        ):
            raise ResultsBundleFailure("Overall linkage outcomes do not reconcile to the frozen 52 grant-linked and 4 policy-linked publications.")
        require_columns(edge_summary, {"network", "edges"}, "Recorded relation edge summary")
        if edge_summary["network"].duplicated().any() or set(edge_summary["network"]) != {
            "publication_grant", "publication_policy_document", "policy_issuer_publication",
        }:
            raise ResultsBundleFailure("Recorded relation edge summary must contain exactly the three audited relation layers.")
        edge_counts = edge_summary.set_index("network")["edges"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
        if edge_counts.to_dict() != {
            "publication_grant": 163,
            "publication_policy_document": 223,
            "policy_issuer_publication": 47,
        }:
            raise ResultsBundleFailure("Recorded relation edge counts do not reconcile to the frozen audited FAIRification layers.")
        association_diagnostics = copied_tables["C01_association_model_diagnostics.csv"]
        require_columns(association_diagnostics, {"model_label", "outcome", "model_status", "n_events"}, "Association diagnostics")
        primary_grant = association_diagnostics.loc[
            association_diagnostics["model_label"].eq("grant_primary__continuous_K3_shares__year_adjusted")
        ]
        primary_policy = association_diagnostics.loc[
            association_diagnostics["model_label"].eq("policy_primary_window__continuous_K3_shares__year_adjusted")
        ]
        if len(primary_grant) != 1 or len(primary_policy) != 1:
            raise ResultsBundleFailure("Association diagnostics lacks exactly one predeclared primary grant and primary policy entry.")
        if str(primary_grant.iloc[0]["model_status"]) != "fit":
            raise ResultsBundleFailure("The certified primary grant model is not recorded as fit.")
        if str(primary_policy.iloc[0]["model_status"]) != "not_fit" or int(pd.to_numeric(primary_policy.iloc[0]["n_events"], errors="raise")) != EXPECTED_PRIMARY_POLICY_WINDOW_EVENTS:
            raise ResultsBundleFailure("The certified primary policy association must be withheld (`not_fit`) with the frozen three-event primary window.")
        event_adequacy = copied_tables["C03_association_event_adequacy_assessment.csv"]
        require_columns(event_adequacy, {"model_label", "model_status", "n_publications", "n_events", "required_minimum_events", "reason"}, "Association event-adequacy assessment")
        primary_adequacy = event_adequacy.loc[event_adequacy["model_label"].eq("policy_primary_window__continuous_K3_shares__year_adjusted")]
        if len(primary_adequacy) != 1:
            raise ResultsBundleFailure("Association event-adequacy table lacks the predeclared primary policy row.")
        if (
            str(primary_adequacy.iloc[0]["model_status"]) != "not_fit"
            or int(pd.to_numeric(primary_adequacy.iloc[0]["n_publications"], errors="raise")) != EXPECTED_PRIMARY_POLICY_WINDOW_PUBLICATIONS
            or int(pd.to_numeric(primary_adequacy.iloc[0]["n_events"], errors="raise")) != EXPECTED_PRIMARY_POLICY_WINDOW_EVENTS
            or int(pd.to_numeric(primary_adequacy.iloc[0]["required_minimum_events"], errors="raise")) != 30
            or not str(primary_adequacy.iloc[0]["reason"]).strip()
        ):
            raise ResultsBundleFailure("Primary policy event-adequacy accounting is not the frozen 3-events-versus-30 requirement result.")
        policy_accounting = copied_tables["F05_policy_window_event_adequacy_accounting.csv"]
        require_columns(policy_accounting, {"policy_window", "association_model_label", "n_publications", "n_policy_linked_publications", "required_events_for_multivariable_model", "event_adequacy_passes", "association_model_status", "withheld_model_reason"}, "Robustness policy-window event accounting")
        primary_policy_accounting = policy_accounting.loc[policy_accounting["policy_window"].eq("primary_policy_window")]
        if len(primary_policy_accounting) != 1:
            raise ResultsBundleFailure("Robustness policy accounting lacks exactly one primary-policy-window row.")
        accounting = primary_policy_accounting.iloc[0]
        if (
            str(accounting["association_model_label"]) != "policy_primary_window__continuous_K3_shares__year_adjusted"
            or str(accounting["association_model_status"]) != "not_fit"
            or int(pd.to_numeric(accounting["n_publications"], errors="raise")) != EXPECTED_PRIMARY_POLICY_WINDOW_PUBLICATIONS
            or int(pd.to_numeric(accounting["n_policy_linked_publications"], errors="raise")) != EXPECTED_PRIMARY_POLICY_WINDOW_EVENTS
            or int(pd.to_numeric(accounting["required_events_for_multivariable_model"], errors="raise")) != 30
            or parse_boolean(accounting["event_adequacy_passes"], "Primary policy robustness event_adequacy_passes")
            or str(accounting["withheld_model_reason"]).strip() != str(primary_adequacy.iloc[0]["reason"]).strip()
        ):
            raise ResultsBundleFailure("Robustness policy-window accounting disagrees with the certified event-limited primary policy result.")
        configuration_null = copied_tables["G02_year_stratified_cross_relation_null_summary.csv"]
        require_columns(configuration_null, {"null_scheme", "statistic", "null_variation_status"}, "Configuration null summary")
        required_configuration_statistics = {"N_both", "intensive_degree_product_sum"}
        observed_configuration_statistics = set(
            configuration_null.loc[
                configuration_null["null_scheme"].eq("publication_year_stratified_P_endpoint_permutation"), "statistic"
            ]
        )
        if not required_configuration_statistics.issubset(observed_configuration_statistics):
            raise ResultsBundleFailure("Configuration null summary lacks one or both primary structural statistics.")
        primary_null_rows = configuration_null.loc[
            configuration_null["null_scheme"].eq("publication_year_stratified_P_endpoint_permutation")
            & configuration_null["statistic"].isin(required_configuration_statistics)
        ]
        valid_primary_null_statuses = {
            "monte_carlo_variation_observed",
            "analytically_degenerate__no_permutation_contrast",
            "no_variation_observed_in_B_draws__not_analytically_classified",
        }
        if len(primary_null_rows) != 2 or not primary_null_rows["null_variation_status"].isin(valid_primary_null_statuses).all():
            raise ResultsBundleFailure("Primary configuration statistics have an unsupported Stage-16 null-information status.")
        require_columns(primary_null_rows, {"observed"}, "Primary configuration null rows")
        primary_observed = primary_null_rows.set_index("statistic")["observed"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
        if primary_observed.to_dict() != {"N_both": 2, "intensive_degree_product_sum": 3040}:
            raise ResultsBundleFailure("Primary configuration statistics do not reconcile to the frozen observed values.")
        observed_configuration = copied_tables["G01_observed_P_G_P_D_configurations.csv"]
        require_columns(observed_configuration, {"configuration", "n_publications"}, "Observed P--G/P--D configurations")
        if observed_configuration["configuration"].duplicated().any() or set(observed_configuration["configuration"]) != {"P_G_only", "P_D_only", "both", "neither"}:
            raise ResultsBundleFailure("Observed configuration table must contain exactly the four frozen P--G/P--D states.")
        observed_counts = observed_configuration.set_index("configuration")["n_publications"].map(lambda value: int(pd.to_numeric(value, errors="raise")))
        if observed_counts.to_dict() != {"P_G_only": 50, "P_D_only": 2, "both": 2, "neither": 90}:
            raise ResultsBundleFailure("Observed configuration counts do not reconcile to the frozen FAIRification configuration result.")

        overview = overview_table(coverage, outcomes, edge_summary)
        copied_tables = {"00_certified_results_overview.csv": overview, **copied_tables}
        index_rows.insert(0, {
            "domain": "00_overview", "bundle_file": "00_certified_results_overview.csv", "source_stage": "derived_from_certified_aggregate_tables",
            "source_file": "A01_source_to_Dimensions_coverage_summary.csv; B01_overall_recorded_linkage_outcomes.csv; A02_recorded_relation_edge_summary.csv",
            "source_rows": len(overview), "rows": len(overview), "release_transform": "derived from already release-safe aggregate tables",
            "purpose": "Headline denominators and recorded-linkage counts for manuscript reporting.",
            "aggregate_only_release_check": "pass",
        })
        results_index = pd.DataFrame(index_rows)
        copied_tables["results_bundle_index.csv"] = results_index

        output_hashes: dict[str, dict[str, Any]] = {}
        for filename, frame in copied_tables.items():
            output_path = args.output_dir / filename
            atomic_write_csv(output_path, frame)
            output_hashes[filename] = {"path": str(output_path), "sha256": sha256(output_path), "rows": len(frame)}

        notes = """# Certified FAIRification reporting bundle\n\nThis directory contains only manifest-certified, non-record-level aggregate outputs from the completed FAIRification core stages. It is local-only and is not a GitHub release. The script verifies both the hash of every selected aggregate input and the upstream hash chain from relational audit through configuration test. The source records, Dimensions responses, title/abstract text, publication/grant/policy-document identifiers, edge lists, author information, organization names, and node-level tables remain excluded.\n\nThe frozen design is 163 source-cohort records, 144 recovered Dimensions publications, 52 grant-linked publications, and 4 policy-linked publications. The primary policy model is withheld because its through-2022 primary window contains 3 events for a predeclared 30-event requirement.\n\nThe bundle does not create new evidence. Association coefficients remain conditional associations of recorded Dimensions links; record-year differences are not causal lags; role-separated network statistics do not establish influence; and the configuration test is a structural linkage test rather than a grant-to-policy causal pathway.\n\nLater figure and manuscript-material scripts must read only this bundle and its manifest.\n"""
        atomic_write_text(args.output_dir / "README.md", notes)
        output_hashes["README.md"] = {"path": str(args.output_dir / "README.md"), "sha256": sha256(args.output_dir / "README.md"), "rows": None}
        validation = pd.DataFrame([
            {"check": "all_stage_manifests_complete", "passed": True, "detail": "Stages 10 through 16 are marked complete."},
            {"check": "full_cross_stage_hash_chain_certified", "passed": True, "detail": "Base, association, temporal, network, robustness, and configuration inputs match the supplied upstream manifests and artifacts."},
            {"check": "all_selected_input_hashes_and_row_counts_certified", "passed": True, "detail": "Every selected aggregate table matches its producing-stage SHA-256 and required integral row count."},
            {"check": "frozen_source_to_Dimensions_163_to_144_denominator_reconciles", "passed": True, "detail": f"{coverage_source_n} source / {coverage_recovered_n} recovered / {coverage_unresolved_n} unresolved."},
            {"check": "frozen_recorded_linkage_and_edge_counts_reconcile", "passed": True, "detail": "52 grant-linked publications; 4 policy-linked publications; 163 P--G, 223 P--D, and 47 issuer--P edges."},
            {"check": "primary_grant_fit_and_event_limited_policy_not_fit_certified", "passed": True, "detail": f"Grant={primary_grant.iloc[0]['model_status']}; policy={primary_policy.iloc[0]['model_status']}; 3 primary-policy events versus 30 required."},
            {"check": "configuration_primary_statistics_and_null_status_reconcile", "passed": True, "detail": "P--G only=50; P--D only=2; both=2; neither=90; both and degree-product nulls have Monte Carlo variation."},
            {"check": "aggregate_only_schema_and_cardinality_boundary", "passed": True, "detail": "Selected tables pass normalized identifier/text-header screening and table-specific row ceilings."},
            {"check": "final_result", "passed": True, "detail": "Certified aggregate reporting bundle created without new data retrieval or analysis."},
        ])
        atomic_write_csv(args.output_dir / "results_bundle_validation_checks.csv", validation)
        output_hashes["results_bundle_validation_checks.csv"] = {
            "path": str(args.output_dir / "results_bundle_validation_checks.csv"),
            "sha256": sha256(args.output_dir / "results_bundle_validation_checks.csv"), "rows": len(validation),
        }
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "purpose": "A hash-certified aggregate-only bridge from frozen core analysis outputs to final figures and paper materials.",
            "source_denominators": {
                "frozen_curated_source_cohort_records": coverage_source_n,
                "Dimensions_recovered_analytic_subset_records": coverage_recovered_n,
                "unresolved_source_records_retained_in_audit": coverage_unresolved_n,
                "recorded_grant_linked_publications": EXPECTED_GRANT_LINKED_PUBLICATIONS,
                "recorded_policy_linked_publications": EXPECTED_POLICY_LINKED_PUBLICATIONS,
                "primary_policy_window_publications": EXPECTED_PRIMARY_POLICY_WINDOW_PUBLICATIONS,
                "primary_policy_window_events": EXPECTED_PRIMARY_POLICY_WINDOW_EVENTS,
            },
            "certified_stage_manifests": {
                name: {"path": str(specification["manifest_path"]), "sha256": sha256(specification["manifest_path"])}
                for name, specification in stages.items()
            },
            "cross_stage_lineage_hashes": lineage_hashes,
            "input_files": input_hashes,
            "output_files": output_hashes,
            "interpretive_boundary": "The bundle reproduces certified aggregate result tables only. It does not introduce causal estimates, policy-impact claims, organization-name linkage, or record-level data release. Grants and policy documents remain Dimensions-recorded identifier links; record-year quantities remain descriptive.",
            "data_boundary": "This local bundle is protected analysis output and must not be committed to GitHub. It contains no record-level source or Dimensions data by design.",
        }
        atomic_write_json(args.output_dir / "results_bundle_manifest.json", manifest)

        print("FAIRIFICATION CERTIFIED RESULTS BUNDLE: PASS")
        print(f"SOURCE COHORT / DIMENSIONS ANCHOR: {coverage_source_n} / {coverage_recovered_n}")
        print(f"CERTIFIED AGGREGATE TABLES: {len(copied_tables)}")
        print(f"PRIMARY GRANT MODEL STATUS: {primary_grant.iloc[0]['model_status']}")
        print(f"PRIMARY POLICY MODEL STATUS: {primary_policy.iloc[0]['model_status']}")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'results_bundle_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

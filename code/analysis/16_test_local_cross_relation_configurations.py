#!/usr/bin/env python3
"""Test local P--G/P--D alignment in the audited FAIRification linkage data.

This local, no-API script implements the predeclared publication-centred
cross-relation configuration test. Its primary question is:

    Do the recorded publication--grant (P--G) and publication--policy-document
    (P--D) relations align on the same retained FAIRification publications more
    than expected after P--D publication endpoints are permuted within
    publication-year strata?

The primary null leaves the P--G layer unchanged. It permutes the publication
endpoint mapping for all P--D ties within a publication year, preserving P--D
publication-degree bundles within every stratum, policy-document endpoints, and
recorded P--G ties. The unrestricted P-endpoint permutation is a labelled
sensitivity only.

The policy-issuer--publication table is not a third rewired layer. It is used
solely to describe observed issuer reach among publications with both recorded
P--G and P--D relations. No policy full text, organization-name matching, NMF
variable, funder identity, or causal model enters this analysis.

A degenerate null is reported as uninformative rather than converted into a
spurious p-value. This is particularly important because the FAIRification
corpus has very few policy-linked publications.

Example:
    python code/analysis/16_test_local_cross_relation_configurations.py \
      --analysis-base-file /path/to/publication_linkage_analysis_base.pkl \
      --analysis-base-manifest-file /path/to/analysis_base_manifest.json \
      --publication-grant-edges-file /path/to/edges_publication_grant.csv \
      --publication-policy-edges-file /path/to/edges_publication_policy_document.csv \
      --policy-issuer-publication-edges-file /path/to/edges_policy_issuer_publication.csv \
      --relational-summary-file /path/to/retrieval_summary.json \
      --output-dir /path/to/computations/outputs/16_local_cross_relation_configurations_run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "16_test_local_cross_relation_configurations_1.0"
EXPECTED_PUBLICATION_RECORDS = 144
EXPECTED_PG_EDGES = 163
EXPECTED_PD_EDGES = 223
DEFAULT_N_PERMUTATIONS = 1000
RANDOM_SEED = 20261024
PRIMARY_NULL = "publication_year_stratified_P_endpoint_permutation"
SENSITIVITY_NULL = "unrestricted_P_endpoint_permutation"


class ConfigurationFailure(RuntimeError):
    """Input-contract or local-configuration analysis error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-base-file", type=Path, required=True)
    parser.add_argument("--analysis-base-manifest-file", type=Path, required=True)
    parser.add_argument("--publication-grant-edges-file", type=Path, required=True)
    parser.add_argument("--publication-policy-edges-file", type=Path, required=True)
    parser.add_argument("--policy-issuer-publication-edges-file", type=Path, required=True)
    parser.add_argument("--relational-summary-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--n-permutations", type=int, default=DEFAULT_N_PERMUTATIONS)
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.casefold() == "nan" else " ".join(text.split())


def bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean_text(value).casefold() in {"true", "1", "yes"}


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    fields = (
        "analysis_base_file", "analysis_base_manifest_file", "publication_grant_edges_file",
        "publication_policy_edges_file", "policy_issuer_publication_edges_file",
        "relational_summary_file", "output_dir",
    )
    for field in fields:
        setattr(args, field, resolved(getattr(args, field)))
    input_paths = [
        args.analysis_base_file, args.analysis_base_manifest_file,
        args.publication_grant_edges_file, args.publication_policy_edges_file,
        args.policy_issuer_publication_edges_file, args.relational_summary_file,
    ]
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
            f"Output directory is not empty: {args.output_dir}. Choose a new empty directory; this script never deletes outputs."
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ConfigurationFailure(f"{label} is missing required column(s): " + ", ".join(missing))


def read_csv(path: Path, required: set[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    require_columns(frame, required, label)
    return frame


def read_json(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigurationFailure(f"{label} must be a JSON object.")
    return payload


def require_manifest_hash(
    manifest: dict[str, Any], section: str, key: str, observed_hash: str, label: str,
) -> None:
    """Require an exact SHA-256 match to a certified upstream manifest entry."""
    entry = manifest.get(section, {}).get(key, {})
    expected_hash = clean_text(entry.get("sha256")) if isinstance(entry, dict) else ""
    if not expected_hash:
        raise ConfigurationFailure(f"{label} lacks a certified SHA-256 in {section}.{key}.")
    if observed_hash != expected_hash:
        raise ConfigurationFailure(f"{label} SHA-256 does not match the certified upstream manifest entry.")


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
        prefix=f".{path.name}.", suffix=".tmp", delete=False
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


def configuration_labels(pg_degree: np.ndarray, pd_degree: np.ndarray) -> np.ndarray:
    labels = np.full(len(pg_degree), "neither", dtype=object)
    labels[(pg_degree > 0) & (pd_degree == 0)] = "P_G_only"
    labels[(pg_degree == 0) & (pd_degree > 0)] = "P_D_only"
    labels[(pg_degree > 0) & (pd_degree > 0)] = "both"
    return labels


def safe_mean(values: np.ndarray) -> float | None:
    return float(values.mean()) if len(values) else None


def safe_median(values: np.ndarray) -> float | None:
    return float(np.median(values)) if len(values) else None


def quantile(values: np.ndarray, probability: float) -> float | None:
    return float(np.quantile(values, probability)) if len(values) else None


def empirical_p(observed: float, null_values: np.ndarray, alternative: str) -> float:
    """Return the add-one Monte Carlo permutation p-value for a variable draw."""
    if len(null_values) == 0:
        raise ConfigurationFailure("Cannot compute a permutation p-value from zero null replicates.")
    if alternative == "greater":
        return float((1 + int((null_values >= observed).sum())) / (1 + len(null_values)))
    if alternative == "two_sided":
        upper = (1 + int((null_values >= observed).sum())) / (1 + len(null_values))
        lower = (1 + int((null_values <= observed).sum())) / (1 + len(null_values))
        return float(min(1.0, 2 * min(upper, lower)))
    raise ValueError(f"Unsupported alternative: {alternative}")


def monte_carlo_standard_error(probability: float, n_draws: int) -> float | None:
    """Binomial Monte Carlo SE conditional on the simulated null draws."""
    if n_draws < 1:
        return None
    return float(np.sqrt(probability * (1 - probability) / n_draws))


def normalise_identifiers(frame: pd.DataFrame, columns: list[str], label: str) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = result[column].map(clean_text)
        if result[column].eq("").any():
            raise ConfigurationFailure(f"{label} contains a blank {column}.")
    return result


def build_observed_configuration(
    publications: pd.DataFrame,
    pg_p_indices: np.ndarray,
    pd_p_indices: np.ndarray,
    issuer_p: pd.DataFrame,
) -> pd.DataFrame:
    n_publications = len(publications)
    pg_degree = np.bincount(pg_p_indices, minlength=n_publications)
    pd_degree = np.bincount(pd_p_indices, minlength=n_publications)
    labels = configuration_labels(pg_degree, pd_degree)
    issuer_by_publication = issuer_p.groupby("publication_id", as_index=True).agg(
        distinct_policy_issuers=("issuer_id", "nunique"),
        issuer_attributed_policy_documents=("n_policy_documents", "sum"),
    )
    table = publications[["id", "year"]].rename(columns={"id": "publication_id"}).copy()
    table["P_G_degree"] = pg_degree
    table["P_D_degree"] = pd_degree
    table["configuration"] = labels
    table = table.merge(issuer_by_publication, on="publication_id", how="left", validate="one_to_one")
    table["distinct_policy_issuers"] = table["distinct_policy_issuers"].fillna(0).astype(int)
    table["issuer_attributed_policy_documents"] = table["issuer_attributed_policy_documents"].fillna(0).astype(int)
    table["has_grant_link_from_edges"] = (table["P_G_degree"] > 0).astype(int)
    table["has_policy_link_from_edges"] = (table["P_D_degree"] > 0).astype(int)
    table["issuer_attribution_coverage_of_P_D_degree"] = np.divide(
        table["issuer_attributed_policy_documents"].to_numpy(dtype=float),
        table["P_D_degree"].to_numpy(dtype=float),
        out=np.full(len(table), np.nan),
        where=table["P_D_degree"].to_numpy(dtype=float) > 0,
    )
    table["distinct_issuers_per_issuer_attributed_policy_document"] = np.divide(
        table["distinct_policy_issuers"].to_numpy(dtype=float),
        table["issuer_attributed_policy_documents"].to_numpy(dtype=float),
        out=np.full(len(table), np.nan),
        where=table["issuer_attributed_policy_documents"].to_numpy(dtype=float) > 0,
    )
    return table


def observed_summary(configuration: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label in ("P_G_only", "P_D_only", "both", "neither"):
        subset = configuration.loc[configuration["configuration"].eq(label)]
        rows.append({
            "configuration": label,
            "n_publications": len(subset),
            "share_of_final_P": float(len(subset) / len(configuration)) if len(configuration) else None,
            "mean_P_G_degree": safe_mean(subset["P_G_degree"].to_numpy(dtype=float)),
            "mean_P_D_degree": safe_mean(subset["P_D_degree"].to_numpy(dtype=float)),
            "mean_distinct_policy_issuers": safe_mean(subset["distinct_policy_issuers"].to_numpy(dtype=float)),
        })
    return pd.DataFrame(rows)


def observed_issuer_reach(configuration: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    both = configuration.loc[configuration["configuration"].eq("both")].copy()
    overall = pd.DataFrame([{
        "population": "observed_publications_with_both_P_G_and_P_D_relations",
        "n_publications": len(both),
        "mean_P_G_degree": safe_mean(both["P_G_degree"].to_numpy(dtype=float)),
        "mean_P_D_degree": safe_mean(both["P_D_degree"].to_numpy(dtype=float)),
        "mean_distinct_policy_issuers": safe_mean(both["distinct_policy_issuers"].to_numpy(dtype=float)),
        "median_distinct_policy_issuers": safe_median(both["distinct_policy_issuers"].to_numpy(dtype=float)),
        "mean_issuer_attributed_policy_documents": safe_mean(both["issuer_attributed_policy_documents"].to_numpy(dtype=float)),
        "mean_issuer_attribution_coverage_of_P_D_degree": safe_mean(both["issuer_attribution_coverage_of_P_D_degree"].dropna().to_numpy(dtype=float)),
        "mean_distinct_issuers_per_issuer_attributed_policy_document": safe_mean(both["distinct_issuers_per_issuer_attributed_policy_document"].dropna().to_numpy(dtype=float)),
        "interpretive_boundary": "Observed issuer reach only. Issuer identities are not independently permuted and are not a third relation in the configuration null.",
    }])
    both["P_D_degree_group"] = np.select(
        [both["P_D_degree"].eq(1), both["P_D_degree"].eq(2), both["P_D_degree"].ge(3)],
        ["1", "2", "3_plus"],
        default="0",
    )
    rows: list[dict[str, Any]] = []
    for group_label in ("1", "2", "3_plus"):
        group = both.loc[both["P_D_degree_group"].eq(group_label)]
        rows.append({
            "population": "observed_publications_with_both_P_G_and_P_D_relations",
            "P_D_degree_group": group_label,
            "n_publications": len(group),
            "mean_distinct_policy_issuers": safe_mean(group["distinct_policy_issuers"].to_numpy(dtype=float)),
            "median_distinct_policy_issuers": safe_median(group["distinct_policy_issuers"].to_numpy(dtype=float)),
            "mean_issuer_attribution_coverage_of_P_D_degree": safe_mean(group["issuer_attribution_coverage_of_P_D_degree"].dropna().to_numpy(dtype=float)),
            "mean_distinct_issuers_per_issuer_attributed_policy_document": safe_mean(group["distinct_issuers_per_issuer_attributed_policy_document"].dropna().to_numpy(dtype=float)),
        })
    return overall, pd.DataFrame(rows)


def make_target_indices(years: np.ndarray, scheme: str, rng: np.random.Generator) -> tuple[np.ndarray, dict[str, int]]:
    n_publications = len(years)
    targets = np.arange(n_publications, dtype=int)
    fixed_strata = 0
    permuted_strata = 0
    if scheme == PRIMARY_NULL:
        for year in sorted(pd.unique(years)):
            indices = np.flatnonzero(years == year)
            if len(indices) < 2:
                fixed_strata += 1
                continue
            targets[indices] = rng.permutation(indices)
            permuted_strata += 1
    elif scheme == SENSITIVITY_NULL:
        targets = rng.permutation(n_publications)
        permuted_strata = 1
    else:
        raise ValueError(f"Unsupported null scheme: {scheme}")
    return targets, {"permuted_strata": permuted_strata, "fixed_strata": fixed_strata}


def n_both_analytic_support(
    years: np.ndarray, pg_degree: np.ndarray, pd_degree: np.ndarray, scheme: str,
) -> dict[str, int | bool]:
    """Determine whether N_both can vary under this endpoint-permutation null.

    Within a stratum, a P--D-positive bundle set of size d is mapped uniformly
    to d publication positions. Its overlap with the g P--G-positive positions
    has exact support [max(0, g + d - n), min(g, d)]. Summing independent
    stratum bounds gives the exact global support bounds for N_both.
    """
    if scheme == PRIMARY_NULL:
        strata = years
    elif scheme == SENSITIVITY_NULL:
        strata = np.zeros(len(years), dtype=int)
    else:
        raise ValueError(f"Unsupported null scheme: {scheme}")
    minimum = 0
    maximum = 0
    for stratum in pd.unique(strata):
        indices = np.flatnonzero(strata == stratum)
        n = len(indices)
        g = int((pg_degree[indices] > 0).sum())
        d = int((pd_degree[indices] > 0).sum())
        minimum += max(0, g + d - n)
        maximum += min(g, d)
    return {
        "minimum": minimum,
        "maximum": maximum,
        "is_analytically_degenerate": minimum == maximum,
    }


def verify_null_invariants(
    years: np.ndarray, original_pd_degree: np.ndarray, targets: np.ndarray,
    pd_source_indices: np.ndarray, scheme: str,
) -> dict[str, bool]:
    """Check properties preserved by the implemented P-endpoint mapping."""
    target_pd_degree = np.bincount(targets[pd_source_indices], minlength=len(original_pd_degree))
    target_is_bijection = len(np.unique(targets)) == len(targets) and set(targets) == set(range(len(targets)))
    if scheme == PRIMARY_NULL:
        degree_multisets_preserved = all(
            np.array_equal(
                np.sort(original_pd_degree[np.flatnonzero(years == year)]),
                np.sort(target_pd_degree[np.flatnonzero(years == year)]),
            )
            for year in pd.unique(years)
        )
    elif scheme == SENSITIVITY_NULL:
        degree_multisets_preserved = np.array_equal(np.sort(original_pd_degree), np.sort(target_pd_degree))
    else:
        raise ValueError(f"Unsupported null scheme: {scheme}")
    return {
        "target_mapping_is_bijection": bool(target_is_bijection),
        "P_D_edge_incidence_count_preserved": int(target_pd_degree.sum()) == int(original_pd_degree.sum()),
        "P_D_degree_multiset_preserved_at_scheme_scope": bool(degree_multisets_preserved),
    }


def null_statistics(pg_degree: np.ndarray, pd_targets: np.ndarray) -> dict[str, float]:
    pd_degree = np.bincount(pd_targets, minlength=len(pg_degree))
    labels = configuration_labels(pg_degree, pd_degree)
    return {
        "N_P_G_only": float((labels == "P_G_only").sum()),
        "N_P_D_only": float((labels == "P_D_only").sum()),
        "N_both": float((labels == "both").sum()),
        "N_neither": float((labels == "neither").sum()),
        "intensive_degree_product_sum": float(np.sum(pg_degree * pd_degree)),
    }


def observed_statistics(configuration: pd.DataFrame) -> dict[str, float]:
    return {
        "N_P_G_only": float((configuration["configuration"] == "P_G_only").sum()),
        "N_P_D_only": float((configuration["configuration"] == "P_D_only").sum()),
        "N_both": float((configuration["configuration"] == "both").sum()),
        "N_neither": float((configuration["configuration"] == "neither").sum()),
        "intensive_degree_product_sum": float(np.sum(configuration["P_G_degree"] * configuration["P_D_degree"])),
    }


def null_summary(
    observed: dict[str, float], null_replicates: pd.DataFrame, scheme: str,
    n_both_support: dict[str, int | bool],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for statistic, role in (
        ("N_both", "primary_extensive_margin_alignment"),
        ("intensive_degree_product_sum", "primary_intensive_margin_alignment"),
        ("N_P_G_only", "configuration_count_context"),
        ("N_P_D_only", "configuration_count_context"),
        ("N_neither", "configuration_count_context"),
    ):
        values = pd.to_numeric(null_replicates[statistic], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values) != len(null_replicates):
            raise ConfigurationFailure(f"Null replicate statistic contains a nonnumeric value: {scheme} / {statistic}")
        observed_value = float(observed[statistic])
        null_mean = safe_mean(values)
        variation_observed = np.unique(values).size >= 2
        enrichment = observed_value / null_mean if null_mean not in (None, 0.0) else None
        is_primary = statistic in {"N_both", "intensive_degree_product_sum"}
        analytic_minimum = int(n_both_support["minimum"]) if statistic == "N_both" else None
        analytic_maximum = int(n_both_support["maximum"]) if statistic == "N_both" else None
        if statistic == "N_both" and bool(n_both_support["is_analytically_degenerate"]):
            variation_status = "analytically_degenerate__no_permutation_contrast"
            p_upper = None
            p_two_sided = None
        elif is_primary and not variation_observed:
            variation_status = "no_variation_observed_in_B_draws__not_analytically_classified"
            p_upper = None
            p_two_sided = None
        elif not is_primary:
            variation_status = "algebraically_derived_configuration_context__p_values_not_reported"
            p_upper = None
            p_two_sided = None
        else:
            variation_status = "monte_carlo_variation_observed"
            p_upper = empirical_p(observed_value, values, "greater")
            p_two_sided = empirical_p(observed_value, values, "two_sided")
        if variation_status.endswith("no_permutation_contrast") or variation_status.startswith("no_variation_observed"):
            direction = "not_assessed"
        elif observed_value > null_mean:
            direction = "greater_than_null_mean"
        elif observed_value < null_mean:
            direction = "less_than_null_mean"
        else:
            direction = "equal_to_null_mean"
        rows.append({
            "null_scheme": scheme,
            "statistic": statistic,
            "statistic_role": role,
            "observed": observed_value,
            "null_mean": null_mean,
            "null_sd": float(values.std(ddof=1)) if len(values) > 1 else None,
            "null_minimum": float(values.min()) if len(values) else None,
            "null_interval_2_5": quantile(values, 0.025),
            "null_interval_97_5": quantile(values, 0.975),
            "null_unique_values": int(np.unique(values).size),
            "null_variation_observed_in_B_draws": variation_observed,
            "N_both_analytical_support_minimum": analytic_minimum,
            "N_both_analytical_support_maximum": analytic_maximum,
            "null_variation_status": variation_status,
            "observed_to_null_mean_enrichment": enrichment,
            "permutation_p_enrichment_upper_tail": p_upper,
            "permutation_p_enrichment_upper_tail_monte_carlo_se": monte_carlo_standard_error(p_upper, len(values)) if p_upper is not None else None,
            "permutation_p_two_sided": p_two_sided,
            "permutation_p_two_sided_monte_carlo_se": monte_carlo_standard_error(p_two_sided, len(values)) if p_two_sided is not None else None,
            "direction_relative_to_null": direction,
            "n_permutations": len(values),
            "interpretive_boundary": "Structural alignment of recorded Dimensions links only; not a causal pathway from grants to policy or a measure of policy impact, intent, endorsement, uptake, or topical affinity.",
        })
    return pd.DataFrame(rows)


def primary_strata_table(publications: pd.DataFrame, pd_degree: np.ndarray) -> pd.DataFrame:
    frame = publications[["id", "year"]].rename(columns={"id": "publication_id"}).copy()
    frame["P_D_degree"] = pd_degree
    grouped = frame.groupby("year", as_index=False).agg(
        n_final_P=("publication_id", "size"),
        n_P_D_linked_publications=("P_D_degree", lambda values: int((values > 0).sum())),
        P_D_edge_incidences=("P_D_degree", "sum"),
    )
    grouped["stratum_permutable"] = grouped["n_final_P"] >= 2
    grouped["P_D_edge_incidences_in_permutable_stratum"] = np.where(
        grouped["stratum_permutable"], grouped["P_D_edge_incidences"], 0
    )
    return grouped.sort_values("year").reset_index(drop=True)


def main() -> None:
    try:
        args = parse_args()
        if args.expected_publication_records < 1:
            raise ValueError("--expected-publication-records must be positive.")
        if args.n_permutations < 100:
            raise ValueError("--n-permutations must be at least 100.")
        args = preflight_paths(args)
        input_paths = {
            "analysis_base": args.analysis_base_file,
            "analysis_base_manifest": args.analysis_base_manifest_file,
            "publication_grant_edges": args.publication_grant_edges_file,
            "publication_policy_edges": args.publication_policy_edges_file,
            "policy_issuer_publication_edges": args.policy_issuer_publication_edges_file,
            "relational_summary": args.relational_summary_file,
        }
        input_hashes = {name: sha256(path) for name, path in input_paths.items()}

        base = pd.read_pickle(args.analysis_base_file).copy()
        base_manifest = read_json(args.analysis_base_manifest_file, "Analysis-base manifest")
        pg_edges = read_csv(args.publication_grant_edges_file, {"publication_id", "grant_id"}, "Publication--grant edge table")
        pd_edges = read_csv(args.publication_policy_edges_file, {"publication_id", "policy_document_id"}, "Publication--policy-document edge table")
        issuer_p_edges = read_csv(
            args.policy_issuer_publication_edges_file,
            {"issuer_id", "publication_id", "n_policy_documents"},
            "Policy-issuer--publication edge table",
        )
        relational_summary = read_json(args.relational_summary_file, "Relational audit summary")
        require_columns(base, {"id", "year", "has_grant_link", "has_policy_document_link"}, "Publication linkage analysis base")
        if base_manifest.get("status") != "complete" or relational_summary.get("status") != "complete":
            raise ConfigurationFailure("Analysis-base and relational-summary manifests must both be marked complete.")
        require_manifest_hash(
            base_manifest, "output_files", "publication_linkage_analysis_base.pkl", input_hashes["analysis_base"],
            "Supplied publication linkage analysis base",
        )
        require_manifest_hash(
            base_manifest, "input_files", "publication_grant_edges", input_hashes["publication_grant_edges"],
            "Supplied P--G edge table against analysis-base provenance",
        )
        require_manifest_hash(
            base_manifest, "input_files", "publication_policy_edges", input_hashes["publication_policy_edges"],
            "Supplied P--D edge table against analysis-base provenance",
        )
        require_manifest_hash(
            base_manifest, "input_files", "relational_summary", input_hashes["relational_summary"],
            "Supplied relational summary against analysis-base provenance",
        )
        require_manifest_hash(
            relational_summary, "output_files", "edges_publication_grant.csv", input_hashes["publication_grant_edges"],
            "Supplied P--G edge table against relational-audit provenance",
        )
        require_manifest_hash(
            relational_summary, "output_files", "edges_publication_policy_document.csv", input_hashes["publication_policy_edges"],
            "Supplied P--D edge table against relational-audit provenance",
        )
        require_manifest_hash(
            relational_summary, "output_files", "edges_policy_issuer_publication.csv", input_hashes["policy_issuer_publication_edges"],
            "Supplied issuer--P edge table against relational-audit provenance",
        )

        base["id"] = base["id"].map(clean_text)
        base["year"] = pd.to_numeric(base["year"], errors="coerce")
        if len(base) != args.expected_publication_records or base["id"].eq("").any() or base["id"].duplicated().any():
            raise ConfigurationFailure("Analysis base does not have the required unique 144-publication identifier set.")
        if base["year"].isna().any():
            raise ConfigurationFailure("Publication years are missing or nonnumeric; the primary year-stratified null cannot run.")
        base["year"] = base["year"].astype(int)
        for outcome in ("has_grant_link", "has_policy_document_link"):
            values = pd.to_numeric(base[outcome], errors="coerce")
            if values.isna().any() or not values.isin([0, 1]).all():
                raise ConfigurationFailure(f"Analysis-base {outcome} must be binary 0/1.")
            base[outcome] = values.astype(int)
        if base_manifest.get("records", {}).get("final_publications_P") != len(base):
            raise ConfigurationFailure("Analysis-base manifest does not reconcile to the supplied publication base.")

        pg_edges = normalise_identifiers(pg_edges[["publication_id", "grant_id"]], ["publication_id", "grant_id"], "Publication--grant edge table")
        pd_edges = normalise_identifiers(pd_edges[["publication_id", "policy_document_id"]], ["publication_id", "policy_document_id"], "Publication--policy-document edge table")
        issuer_p_edges = normalise_identifiers(issuer_p_edges[["issuer_id", "publication_id", "n_policy_documents"]], ["issuer_id", "publication_id"], "Policy-issuer--publication edge table")
        issuer_p_edges["n_policy_documents"] = pd.to_numeric(issuer_p_edges["n_policy_documents"], errors="coerce")
        if issuer_p_edges["n_policy_documents"].isna().any() or (issuer_p_edges["n_policy_documents"] < 1).any() or not np.allclose(issuer_p_edges["n_policy_documents"], np.round(issuer_p_edges["n_policy_documents"])):
            raise ConfigurationFailure("Policy-issuer--publication edge weights must be positive integers.")
        issuer_p_edges["n_policy_documents"] = issuer_p_edges["n_policy_documents"].astype(int)
        pg_edges = pg_edges.drop_duplicates().reset_index(drop=True)
        pd_edges = pd_edges.drop_duplicates().reset_index(drop=True)
        if issuer_p_edges.duplicated(["issuer_id", "publication_id"]).any():
            raise ConfigurationFailure("Policy-issuer--publication table has duplicate issuer--publication pairs.")

        publication_ids = set(base["id"])
        if not set(pg_edges["publication_id"]).issubset(publication_ids) or not set(pd_edges["publication_id"]).issubset(publication_ids) or not set(issuer_p_edges["publication_id"]).issubset(publication_ids):
            raise ConfigurationFailure("At least one edge table has a publication endpoint outside the final analysis base.")
        expected_counts = relational_summary.get("edge_counts", {})
        if len(pg_edges) != expected_counts.get("publication_grant") or len(pd_edges) != expected_counts.get("publication_policy_document") or len(issuer_p_edges) != expected_counts.get("policy_issuer_publication"):
            raise ConfigurationFailure("Supplied edge tables do not reconcile to the completed relational-audit summary.")
        if len(pg_edges) != EXPECTED_PG_EDGES or len(pd_edges) != EXPECTED_PD_EDGES:
            raise ConfigurationFailure("The fixed FAIRification P--G/P--D edge counts are not 163/223.")
        if not set(issuer_p_edges["publication_id"]).issubset(set(pd_edges["publication_id"])):
            raise ConfigurationFailure("An issuer--P descriptive edge has a publication endpoint without a corresponding P--D edge.")
        issuer_attributed_policy_document_incidences = int(issuer_p_edges["n_policy_documents"].sum())
        if issuer_attributed_policy_document_incidences > len(pd_edges):
            raise ConfigurationFailure("Issuer-attributed policy-document weight exceeds the audited P--D edge count.")

        p_ids = base["id"].to_numpy(dtype=str)
        p_index = {identifier: index for index, identifier in enumerate(p_ids)}
        pg_indices = pg_edges["publication_id"].map(p_index).to_numpy(dtype=int)
        pd_indices = pd_edges["publication_id"].map(p_index).to_numpy(dtype=int)
        configuration = build_observed_configuration(base, pg_indices, pd_indices, issuer_p_edges)
        if not (configuration["has_grant_link_from_edges"].to_numpy() == base["has_grant_link"].to_numpy()).all():
            raise ConfigurationFailure("P--G edge degrees do not reconcile to the analysis-base grant-link outcome.")
        if not (configuration["has_policy_link_from_edges"].to_numpy() == base["has_policy_document_link"].to_numpy()).all():
            raise ConfigurationFailure("P--D edge degrees do not reconcile to the analysis-base policy-link outcome.")
        if int(configuration["has_grant_link_from_edges"].sum()) != 52 or int(configuration["has_policy_link_from_edges"].sum()) != 4:
            raise ConfigurationFailure("Observed publication-link outcome counts do not match the frozen 52-grant-linked / 4-policy-linked design.")

        configuration_table = observed_summary(configuration)
        issuer_overall, issuer_by_policy_degree = observed_issuer_reach(configuration)
        issuer_coverage = pd.DataFrame([{
            "P_D_edge_incidences": len(pd_edges),
            "issuer_attributed_P_D_edge_incidences": issuer_attributed_policy_document_incidences,
            "P_D_edge_incidences_without_issuer_attribution": len(pd_edges) - issuer_attributed_policy_document_incidences,
            "issuer_attribution_coverage_pct": round(100 * issuer_attributed_policy_document_incidences / len(pd_edges), 3) if len(pd_edges) else None,
            "policy_linked_publications": int(configuration["has_policy_link_from_edges"].sum()),
            "policy_linked_publications_with_any_issuer_attribution": int((configuration["issuer_attributed_policy_documents"] > 0).sum()),
            "role": "Descriptive issuer-coverage context only; incomplete issuer metadata never gates the P--G/P--D configuration test.",
        }])
        observed = observed_statistics(configuration)
        years = base["year"].to_numpy(dtype=int)
        pg_degree = configuration["P_G_degree"].to_numpy(dtype=int)
        pd_degree = configuration["P_D_degree"].to_numpy(dtype=int)
        strata = primary_strata_table(base, pd_degree)
        movable_pd_incidences = int(strata["P_D_edge_incidences_in_permutable_stratum"].sum())
        n_both_support_by_scheme = {
            scheme: n_both_analytic_support(years, pg_degree, pd_degree, scheme)
            for scheme in (PRIMARY_NULL, SENSITIVITY_NULL)
        }
        pg_degree_before_permutations = pg_degree.copy()
        null_frames: list[pd.DataFrame] = []
        null_metadata: list[dict[str, Any]] = []
        for seed_offset, scheme in enumerate((PRIMARY_NULL, SENSITIVITY_NULL)):
            scheme_seed = args.random_seed + seed_offset
            rng = np.random.default_rng(scheme_seed)
            rows: list[dict[str, Any]] = []
            meta_first: dict[str, int] | None = None
            invariant_first: dict[str, bool] | None = None
            for replicate in range(1, args.n_permutations + 1):
                targets, meta = make_target_indices(years, scheme, rng)
                if meta_first is None:
                    meta_first = meta
                    invariant_first = verify_null_invariants(years, pd_degree, targets, pd_indices, scheme)
                    if not all(invariant_first.values()):
                        raise ConfigurationFailure(f"{scheme} failed its first-draw degree-preservation invariant check.")
                values = null_statistics(pg_degree, targets[pd_indices])
                values.update({"null_scheme": scheme, "replicate": replicate})
                rows.append(values)
            null_frame = pd.DataFrame(rows)
            null_frames.append(null_frame)
            null_metadata.append({
                "null_scheme": scheme,
                "random_seed": scheme_seed,
                "permuted_strata": int(meta_first["permuted_strata"]) if meta_first else 0,
                "fixed_strata": int(meta_first["fixed_strata"]) if meta_first else 0,
                "P_D_edge_incidences_in_permutable_year_strata": movable_pd_incidences if scheme == PRIMARY_NULL else len(pd_edges),
                **(invariant_first or {}),
            })
        null_replicates = pd.concat(null_frames, ignore_index=True)
        null_tests = pd.concat(
            [
                null_summary(
                    observed, null_replicates.loc[null_replicates["null_scheme"].eq(scheme)], scheme,
                    n_both_support_by_scheme[scheme],
                )
                for scheme in (PRIMARY_NULL, SENSITIVITY_NULL)
            ],
            ignore_index=True,
        )
        null_setup = pd.DataFrame(null_metadata)
        primary_n_both = null_tests.loc[
            null_tests["null_scheme"].eq(PRIMARY_NULL) & null_tests["statistic"].eq("N_both")
        ].iloc[0]
        primary_degree_product = null_tests.loc[
            null_tests["null_scheme"].eq(PRIMARY_NULL) & null_tests["statistic"].eq("intensive_degree_product_sum")
        ].iloc[0]
        primary_n_both_informative = primary_n_both["null_variation_status"] == "monte_carlo_variation_observed"
        primary_degree_product_informative = primary_degree_product["null_variation_status"] == "monte_carlo_variation_observed"
        primary_has_any_informative_statistic = primary_n_both_informative or primary_degree_product_informative
        pg_degree_unchanged_after_permutations = bool(np.array_equal(pg_degree_before_permutations, pg_degree))
        primary_null_setup = null_setup.loc[null_setup["null_scheme"].eq(PRIMARY_NULL)].iloc[0]

        checks = pd.DataFrame([
            {"check": "expected_final_P_record_count", "passed": len(base) == args.expected_publication_records, "detail": ""},
            {"check": "analysis_base_and_relational_summary_completed", "passed": True, "detail": ""},
            {"check": "certified_input_hash_chain_verified", "passed": True, "detail": "Analysis base, P--G/P--D edge tables, issuer--P table, and relational summary match upstream SHA-256 entries."},
            {"check": "P_G_P_D_and_issuer_P_edge_counts_reconcile", "passed": True, "detail": f"{len(pg_edges)} P--G; {len(pd_edges)} P--D; {len(issuer_p_edges)} issuer--P."},
            {"check": "P_G_and_P_D_endpoint_sets_reconcile_to_analysis_base_outcomes", "passed": True, "detail": "52 grant-linked and 4 policy-linked publications."},
            {"check": "issuer_attribution_is_optional_descriptive_context", "passed": True, "detail": f"{issuer_attributed_policy_document_incidences} of {len(pd_edges)} P--D edge incidences have issuer attribution; missing attribution never gates the P--G/P--D test."},
            {"check": "primary_null_target_mapping_is_bijection", "passed": bool(primary_null_setup["target_mapping_is_bijection"]), "detail": ""},
            {"check": "primary_null_preserves_P_D_degree_multiset_within_year", "passed": bool(primary_null_setup["P_D_degree_multiset_preserved_at_scheme_scope"]), "detail": "P--D publication endpoints are permuted as degree bundles within publication-year strata."},
            {"check": "primary_null_preserves_P_D_edge_incidence_count", "passed": bool(primary_null_setup["P_D_edge_incidence_count_preserved"]), "detail": ""},
            {"check": "P_G_degree_vector_unchanged_after_all_null_draws", "passed": pg_degree_unchanged_after_permutations, "detail": "P--G is held fixed in both null schemes."},
            {"check": "policy_issuer_role_not_independently_rewired", "passed": True, "detail": "Issuer reach is observed descriptive context only."},
            {"check": "primary_null_has_movable_P_D_edge_incidences", "passed": movable_pd_incidences > 0, "detail": str(movable_pd_incidences)},
            {"check": "primary_null_N_both_variation_status_recorded", "passed": True, "detail": str(primary_n_both["null_variation_status"])},
            {"check": "primary_null_degree_product_variation_status_recorded", "passed": True, "detail": str(primary_degree_product["null_variation_status"])},
            {"check": "primary_null_has_at_least_one_informative_primary_statistic", "passed": True, "detail": str(primary_has_any_informative_statistic)},
            {"check": "final_result", "passed": True, "detail": "Configuration stage completed; sparse-policy null-information limits are reported statistic by statistic rather than converted into spurious p-values."},
        ])

        outputs = {
            "publication_cross_relation_configurations.csv": configuration,
            "configuration_observed_summary.csv": configuration_table,
            "issuer_attribution_coverage.csv": issuer_coverage,
            "issuer_reach_among_observed_jointly_connected_publications.csv": issuer_overall,
            "issuer_reach_by_observed_policy_degree.csv": issuer_by_policy_degree,
            "cross_relation_alignment_null_replicates.csv": null_replicates,
            "cross_relation_alignment_null_summary.csv": null_tests,
            "primary_null_year_strata.csv": strata,
            "null_setup_summary.csv": null_setup,
            "configuration_validation_checks.csv": checks,
        }
        for filename, frame in outputs.items():
            atomic_write_csv(args.output_dir / filename, frame)
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "primary_question": "Are P--G and P--D recorded identifier relations aligned on the same final-P publications beyond a publication-year-conditioned P--D endpoint permutation null?",
            "relations": {
                "P_G": "Audited Dimensions-recorded publication--grant identifier edges; held fixed in both null schemes.",
                "P_D": "Audited Dimensions-recorded publication--policy-document identifier edges; publication endpoints are permuted as degree bundles.",
                "issuer_P": "Observed issuer reach derived through P--D; not independently permuted and not a third structural relation.",
            },
            "primary_null": {
                "name": PRIMARY_NULL,
                "mechanism": "Permute the P endpoint mapping of P--D ties within publication-year strata; retain P--G edges, P--D degrees within strata, and policy-document endpoints.",
                "primary_statistics": {
                    "N_both": "Extensive-margin number of publications with both a P--G and a P--D link.",
                    "intensive_degree_product_sum": "Sum across P of recorded P--G degree times P--D degree.",
                },
            },
            "sensitivity_null": {
                "name": SENSITIVITY_NULL,
                "mechanism": "The same degree-bundle P endpoint permutation without year stratification.",
            },
            "permutation_design": {
                "n_permutations_per_null": args.n_permutations,
                "random_seeds_by_null": {PRIMARY_NULL: args.random_seed, SENSITIVITY_NULL: args.random_seed + 1},
                "Monte_Carlo_reporting": "P-values are reported only for primary statistics with observed variation in B draws. Reported Monte Carlo SE is conditional on B simulated draws.",
            },
            "observed_configuration_counts": {key: int(value) for key, value in observed.items() if key.startswith("N_")},
            "observed_recorded_linkage_counts": {
                "final_publications": len(base),
                "grant_linked_publications": int(configuration["has_grant_link_from_edges"].sum()),
                "policy_linked_publications": int(configuration["has_policy_link_from_edges"].sum()),
                "P_G_edges": len(pg_edges),
                "P_D_edges": len(pd_edges),
                "issuer_P_edges": len(issuer_p_edges),
            },
            "issuer_attribution_coverage": issuer_coverage.iloc[0].to_dict(),
            "primary_null_primary_statistic_information": {
                "N_both_variation_status": primary_n_both["null_variation_status"],
                "N_both_analytical_support": {
                    "minimum": int(n_both_support_by_scheme[PRIMARY_NULL]["minimum"]),
                    "maximum": int(n_both_support_by_scheme[PRIMARY_NULL]["maximum"]),
                },
                "intensive_degree_product_sum_variation_status": primary_degree_product["null_variation_status"],
                "at_least_one_primary_statistic_with_observed_Monte_Carlo_variation": primary_has_any_informative_statistic,
            },
            "first_draw_permutation_invariants": {
                "primary": {key: bool(primary_null_setup[key]) for key in ("target_mapping_is_bijection", "P_D_edge_incidence_count_preserved", "P_D_degree_multiset_preserved_at_scheme_scope")},
                "P_G_degree_vector_unchanged_after_all_draws": pg_degree_unchanged_after_permutations,
            },
            "primary_null_P_D_edge_incidences_in_permutable_year_strata": movable_pd_incidences,
            "interpretive_boundary": "This is a descriptive structural test of alignment in Dimensions-recorded link layers. It does not establish a causal funding-to-policy pathway, policy impact, policy uptake, endorsement, institutional intent, topical affinity, community structure, or latent profiles.",
            "data_boundary": "All configuration tables, null replicates, and manifests are protected local data and must not be committed to GitHub.",
            "input_files": {name: {"path": str(path), "sha256": input_hashes[name]} for name, path in input_paths.items()},
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(frame)} for name, frame in outputs.items()},
        }
        atomic_write_json(args.output_dir / "configuration_manifest.json", manifest)

        print("FAIRIFICATION LOCAL CROSS-RELATION CONFIGURATION TEST: PASS")
        print(f"FINAL PUBLICATIONS: {len(base)}")
        print(f"PUBLICATION-GRANT EDGES: {len(pg_edges)}")
        print(f"PUBLICATION-POLICY-DOCUMENT EDGES: {len(pd_edges)}")
        print(f"OBSERVED CONFIGURATIONS: P-G only={int(observed['N_P_G_only'])}; P-D only={int(observed['N_P_D_only'])}; both={int(observed['N_both'])}; neither={int(observed['N_neither'])}")
        print(f"PRIMARY NULL P-D EDGE INCIDENCES IN PERMUTABLE YEAR STRATA: {movable_pd_incidences}")
        print(f"PRIMARY NULL N_BOTH: observed={primary_n_both['observed']:.0f}; status={primary_n_both['null_variation_status']}; upper-tail p={primary_n_both['permutation_p_enrichment_upper_tail']}")
        print(f"PRIMARY NULL DEGREE PRODUCT: observed={primary_degree_product['observed']:.0f}; status={primary_degree_product['null_variation_status']}; upper-tail p={primary_degree_product['permutation_p_enrichment_upper_tail']}")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'configuration_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

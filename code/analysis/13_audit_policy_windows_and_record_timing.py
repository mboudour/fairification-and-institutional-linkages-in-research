#!/usr/bin/env python3
"""Audit policy windows and Dimensions record-year differences for FAIRification.

This no-API script adapts the temporal-accounting parts of the prior project's
policy-window stage. It does not fit another policy-link regression: the guarded
association stage already decides whether the predeclared event-adequacy rule
permits one.

The script reports only differences between years stored in linked Dimensions
records. A positive value means that one record is dated later than the other;
it is not a causal lag, time to impact, proof of policy uptake, endorsement, or
knowledge translation. Negative differences are retained and counted.

Example:
    python code/analysis/13_audit_policy_windows_and_record_timing.py \
      --anchor-file /path/to/publication_anchor_final_run.pkl \
      --grants-file /path/to/linked_grants_final_run.pkl \
      --policy-file /path/to/linked_policy_documents_final_run.pkl \
      --publication-grant-edges-file /path/to/edges_publication_grant.csv \
      --publication-policy-edges-file /path/to/edges_publication_policy_document.csv \
      --analysis-base-file /path/to/publication_linkage_analysis_base.pkl \
      --analysis-base-manifest-file /path/to/analysis_base_manifest.json \
      --association-manifest-file /path/to/association_manifest.json \
      --output-dir /path/to/computations/outputs/13_temporal_audit_run
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

import pandas as pd


SCRIPT_VERSION = "13_audit_policy_windows_and_record_timing_1.0"
EXPECTED_PUBLICATION_RECORDS = 144
ANCHOR_REQUIRED_COLUMNS = {"id", "year", "retain_in_final_P"}
GRANTS_REQUIRED_COLUMNS = {"id", "start_year"}
POLICY_REQUIRED_COLUMNS = {"id", "year"}
PG_REQUIRED_COLUMNS = {"publication_id", "grant_id"}
PD_REQUIRED_COLUMNS = {"publication_id", "policy_document_id"}
BASE_REQUIRED_COLUMNS = {
    "id", "year", "has_grant_link", "has_policy_document_link", "n_linked_grants",
    "n_linked_policy_documents", "in_primary_policy_window", "in_robustness_policy_window",
    "observed_policy_calendar_years_through_data_end", "policy_data_end_year",
}


class TemporalAuditFailure(RuntimeError):
    """Input-contract or timing reconciliation error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-file", type=Path, required=True)
    parser.add_argument("--grants-file", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--publication-grant-edges-file", type=Path, required=True)
    parser.add_argument("--publication-policy-edges-file", type=Path, required=True)
    parser.add_argument("--analysis-base-file", type=Path, required=True)
    parser.add_argument("--analysis-base-manifest-file", type=Path, required=True)
    parser.add_argument("--association-manifest-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() == "nan" else text


def bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean_id(value).casefold() in {"true", "1", "yes"}


def require_columns(frame: pd.DataFrame, label: str, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise TemporalAuditFailure(f"{label} is missing required columns: " + ", ".join(missing))


def normalise_unique_ids(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    output = frame.copy()
    output["id"] = output["id"].map(clean_id)
    if output["id"].eq("").any() or output["id"].duplicated().any():
        raise TemporalAuditFailure(f"{label} contains blank or duplicate identifiers.")
    return output


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    names = (
        "anchor_file", "grants_file", "policy_file", "publication_grant_edges_file", "publication_policy_edges_file",
        "analysis_base_file", "analysis_base_manifest_file", "association_manifest_file", "output_dir",
    )
    for name in names:
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [
        args.anchor_file, args.grants_file, args.policy_file, args.publication_grant_edges_file,
        args.publication_policy_edges_file, args.analysis_base_file, args.analysis_base_manifest_file,
        args.association_manifest_file,
    ]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing))
    if args.output_dir.exists() and (args.output_dir.is_file() or args.output_dir.is_symlink()):
        raise ValueError(f"Output path must be a real directory: {args.output_dir}")
    for input_path in inputs:
        if is_within(input_path, args.output_dir):
            raise ValueError("Output directory must not be an ancestor of an input file: " + str(args.output_dir))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {args.output_dir}. Choose a new empty directory; this script never deletes outputs."
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


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


def timing_summary(frame: pd.DataFrame, relation: str, difference_column: str) -> dict[str, Any]:
    available = pd.to_numeric(frame[difference_column], errors="coerce").dropna()
    nonnegative = available.loc[available >= 0]
    negative = available.loc[available < 0]
    return {
        "relation": relation,
        "n_edges": len(frame),
        "n_edges_with_both_record_years": len(available),
        "n_edges_missing_at_least_one_record_year": int(frame[difference_column].isna().sum()),
        "n_negative_record_year_differences": len(negative),
        "n_zero_record_year_differences": int((available == 0).sum()),
        "n_positive_record_year_differences": int((available > 0).sum()),
        "minimum_record_year_difference": int(available.min()) if len(available) else None,
        "median_record_year_difference": float(available.median()) if len(available) else None,
        "maximum_record_year_difference": int(available.max()) if len(available) else None,
        "median_nonnegative_record_year_difference": float(nonnegative.median()) if len(nonnegative) else None,
        "p25_nonnegative_record_year_difference": float(nonnegative.quantile(0.25)) if len(nonnegative) else None,
        "p75_nonnegative_record_year_difference": float(nonnegative.quantile(0.75)) if len(nonnegative) else None,
        "interpretive_boundary": "Difference between years stored in linked Dimensions records only; not a causal lag, time to impact, policy uptake, endorsement, or proof of knowledge translation.",
    }


def policy_window_summary(base: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    samples = [
        ("all_final_P__policy_window_sensitivity", pd.Series(True, index=base.index), "All final P; sensitivity because newer publications have fewer observed policy-record years."),
        ("primary_policy_window", base["in_primary_policy_window"], "Primary policy-link observation cohort fixed before association modeling."),
        ("longer_window_robustness", base["in_robustness_policy_window"], "Longer-observation policy-window robustness cohort."),
    ]
    for label, mask, purpose in samples:
        subset = base.loc[mask].copy()
        rows.append({
            "analysis_sample": label,
            "n_final_publications": len(subset),
            "n_policy_linked_publications": int(subset["has_policy_document_link"].sum()),
            "policy_linkage_rate_pct": round(100 * float(subset["has_policy_document_link"].mean()), 3) if len(subset) else None,
            "minimum_observed_policy_calendar_years": int(subset["observed_policy_calendar_years_through_data_end"].min()) if len(subset) else None,
            "maximum_observed_policy_calendar_years": int(subset["observed_policy_calendar_years_through_data_end"].max()) if len(subset) else None,
            "low_event_flag": bool(subset["has_policy_document_link"].sum() < 5),
            "purpose": purpose,
        })
    return pd.DataFrame(rows)


def main() -> None:
    try:
        args = parse_args()
        if args.expected_publication_records < 1:
            raise ValueError("--expected-publication-records must be positive.")
        args = preflight_paths(args)
        input_paths = {
            "publication_anchor": args.anchor_file,
            "linked_grants": args.grants_file,
            "linked_policy_documents": args.policy_file,
            "publication_grant_edges": args.publication_grant_edges_file,
            "publication_policy_edges": args.publication_policy_edges_file,
            "analysis_base": args.analysis_base_file,
            "analysis_base_manifest": args.analysis_base_manifest_file,
            "association_manifest": args.association_manifest_file,
        }
        input_hashes = {name: sha256(path) for name, path in input_paths.items()}

        P = normalise_unique_ids(pd.read_pickle(args.anchor_file), "Publication anchor")
        G = normalise_unique_ids(pd.read_pickle(args.grants_file), "Linked grants")
        D = normalise_unique_ids(pd.read_pickle(args.policy_file), "Linked policy documents")
        pg_edges = pd.read_csv(args.publication_grant_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        pd_edges = pd.read_csv(args.publication_policy_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        base = pd.read_pickle(args.analysis_base_file).copy()
        base_manifest = json.loads(args.analysis_base_manifest_file.read_text(encoding="utf-8"))
        association_manifest = json.loads(args.association_manifest_file.read_text(encoding="utf-8"))
        if not isinstance(base_manifest, dict) or base_manifest.get("status") != "complete":
            raise TemporalAuditFailure("Analysis-base manifest must be complete.")
        if not isinstance(association_manifest, dict) or association_manifest.get("status") != "complete":
            raise TemporalAuditFailure("Association manifest must be complete.")
        require_columns(P, "Publication anchor", ANCHOR_REQUIRED_COLUMNS)
        require_columns(G, "Linked grants", GRANTS_REQUIRED_COLUMNS)
        require_columns(D, "Linked policy documents", POLICY_REQUIRED_COLUMNS)
        require_columns(pg_edges, "Publication-grant edges", PG_REQUIRED_COLUMNS)
        require_columns(pd_edges, "Publication-policy edges", PD_REQUIRED_COLUMNS)
        require_columns(base, "Publication linkage analysis base", BASE_REQUIRED_COLUMNS)
        if len(P) != args.expected_publication_records or len(base) != args.expected_publication_records:
            raise TemporalAuditFailure("Publication anchor and analysis base must each contain the expected 144 records.")
        if not P["retain_in_final_P"].map(bool_from).all():
            raise TemporalAuditFailure("Publication anchor includes a record outside final P.")
        base["id"] = base["id"].map(clean_id)
        if base["id"].eq("").any() or base["id"].duplicated().any() or set(base["id"]) != set(P["id"]):
            raise TemporalAuditFailure("Publication linkage analysis base is not one-to-one with final P.")
        if base_manifest.get("records", {}).get("final_publications_P") != len(P):
            raise TemporalAuditFailure("Analysis-base manifest does not reconcile to final P.")

        for frame, columns in [(pg_edges, ["publication_id", "grant_id"]), (pd_edges, ["publication_id", "policy_document_id"])]:
            for column in columns:
                frame[column] = frame[column].map(clean_id)
            if frame[columns].eq("").any().any():
                raise TemporalAuditFailure("Edge table contains a blank endpoint ID.")
        pg_edges = pg_edges.drop_duplicates().reset_index(drop=True)
        pd_edges = pd_edges.drop_duplicates().reset_index(drop=True)
        P_ids, G_ids, D_ids = set(P["id"]), set(G["id"]), set(D["id"])
        if not set(pg_edges["publication_id"]).issubset(P_ids) or not set(pg_edges["grant_id"]).issubset(G_ids):
            raise TemporalAuditFailure("Publication-grant edges are not contained in final P and G.")
        if not set(pd_edges["publication_id"]).issubset(P_ids) or not set(pd_edges["policy_document_id"]).issubset(D_ids):
            raise TemporalAuditFailure("Publication-policy edges are not contained in final P and D.")

        P_years = P[["id", "year"]].rename(columns={"id": "publication_id", "year": "publication_year"})
        G_years = G[["id", "start_year"]].rename(columns={"id": "grant_id", "start_year": "grant_start_year"})
        D_years = D[["id", "year"]].rename(columns={"id": "policy_document_id", "year": "policy_document_year"})
        for frame, field in [(P_years, "publication_year"), (G_years, "grant_start_year"), (D_years, "policy_document_year")]:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
        base["year"] = pd.to_numeric(base["year"], errors="coerce")
        if base["year"].isna().any() or P_years["publication_year"].isna().any():
            raise TemporalAuditFailure("Publication-year values are missing or nonnumeric in final P or the analysis base.")
        base["year"] = base["year"].astype(int)
        P_year_lookup = P_years.set_index("publication_id")["publication_year"].astype(int)
        if not base["id"].map(P_year_lookup).eq(base["year"]).all():
            raise TemporalAuditFailure("Publication-year values in the analysis base do not reconcile by identifier to final P.")
        base["has_grant_link"] = pd.to_numeric(base["has_grant_link"], errors="coerce").astype("Int64")
        base["has_policy_document_link"] = pd.to_numeric(base["has_policy_document_link"], errors="coerce").astype("Int64")
        base["n_linked_grants"] = pd.to_numeric(base["n_linked_grants"], errors="coerce").astype("Int64")
        base["n_linked_policy_documents"] = pd.to_numeric(base["n_linked_policy_documents"], errors="coerce").astype("Int64")
        if base[["has_grant_link", "has_policy_document_link", "n_linked_grants", "n_linked_policy_documents"]].isna().any().any():
            raise TemporalAuditFailure("Analysis base has missing linkage outcomes or counts.")
        if not set(base["has_grant_link"]).issubset({0, 1}) or not set(base["has_policy_document_link"]).issubset({0, 1}):
            raise TemporalAuditFailure("Analysis-base linkage outcomes must be binary.")
        base["in_primary_policy_window"] = base["in_primary_policy_window"].map(bool_from)
        base["in_robustness_policy_window"] = base["in_robustness_policy_window"].map(bool_from)
        base["observed_policy_calendar_years_through_data_end"] = pd.to_numeric(base["observed_policy_calendar_years_through_data_end"], errors="coerce")
        policy_end_values = pd.to_numeric(base["policy_data_end_year"], errors="coerce")
        if policy_end_values.isna().any() or policy_end_values.nunique() != 1:
            raise TemporalAuditFailure("Analysis base must contain one valid policy data-end year.")
        policy_end_year = int(policy_end_values.iloc[0])
        policy_design = base_manifest.get("policy_observation_design", {})
        primary_cutoff = policy_design.get("primary_publication_year_cutoff")
        robustness_cutoff = policy_design.get("robustness_publication_year_cutoff")
        if not isinstance(primary_cutoff, int) or not isinstance(robustness_cutoff, int):
            raise TemporalAuditFailure("Analysis-base manifest lacks frozen integer policy-window cutoffs.")
        if not (robustness_cutoff <= primary_cutoff <= policy_end_year):
            raise TemporalAuditFailure("Frozen policy-window cutoffs are not ordered correctly.")
        expected_observed_years = policy_end_year - base["year"] + 1
        if not base["observed_policy_calendar_years_through_data_end"].eq(expected_observed_years).all():
            raise TemporalAuditFailure("Observed policy-calendar-year counts do not match the frozen data-end year and publication years.")
        if not base["in_primary_policy_window"].eq(base["year"] <= primary_cutoff).all():
            raise TemporalAuditFailure("Primary policy-window flag does not match the frozen cutoff.")
        if not base["in_robustness_policy_window"].eq(base["year"] <= robustness_cutoff).all():
            raise TemporalAuditFailure("Robustness policy-window flag does not match the frozen cutoff.")
        if D_years["policy_document_year"].dropna().gt(policy_end_year).any():
            raise TemporalAuditFailure("A linked policy-document record is dated later than the frozen policy data-end year.")

        pg_timing = (
            pg_edges.merge(P_years, on="publication_id", how="left", validate="many_to_one")
            .merge(G_years, on="grant_id", how="left", validate="many_to_one")
        )
        pg_timing["grant_start_minus_publication_year"] = pg_timing["grant_start_year"] - pg_timing["publication_year"]
        pd_timing = (
            pd_edges.merge(P_years, on="publication_id", how="left", validate="many_to_one")
            .merge(D_years, on="policy_document_id", how="left", validate="many_to_one")
        )
        pd_timing["policy_document_minus_publication_year"] = pd_timing["policy_document_year"] - pd_timing["publication_year"]

        grant_counts = pg_edges.groupby("publication_id")["grant_id"].nunique()
        policy_counts = pd_edges.groupby("publication_id")["policy_document_id"].nunique()
        derived_grants = base["id"].map(grant_counts).fillna(0).astype(int)
        derived_policies = base["id"].map(policy_counts).fillna(0).astype(int)
        if not derived_grants.eq(base["n_linked_grants"].astype(int)).all():
            raise TemporalAuditFailure("Publication-grant edge counts do not reconcile to the analysis base.")
        if not derived_policies.eq(base["n_linked_policy_documents"].astype(int)).all():
            raise TemporalAuditFailure("Publication-policy edge counts do not reconcile to the analysis base.")
        if not ((derived_grants > 0).astype(int).eq(base["has_grant_link"].astype(int))).all():
            raise TemporalAuditFailure("Publication-grant outcomes do not reconcile to edge counts.")
        if not ((derived_policies > 0).astype(int).eq(base["has_policy_document_link"].astype(int))).all():
            raise TemporalAuditFailure("Publication-policy outcomes do not reconcile to edge counts.")

        timing_summary_frame = pd.DataFrame([
            timing_summary(pg_timing, "publication_grant", "grant_start_minus_publication_year"),
            timing_summary(pd_timing, "publication_policy_document", "policy_document_minus_publication_year"),
        ])
        policy_by_publication = (
            pd_timing.groupby("publication_id", as_index=False)
            .agg(
                n_linked_policy_documents=("policy_document_id", "nunique"),
                earliest_linked_policy_document_year=("policy_document_year", "min"),
                latest_linked_policy_document_year=("policy_document_year", "max"),
                minimum_policy_record_year_difference=("policy_document_minus_publication_year", "min"),
                maximum_policy_record_year_difference=("policy_document_minus_publication_year", "max"),
            )
        )
        nonnegative_minimum = (
            pd_timing.loc[pd_timing["policy_document_minus_publication_year"] >= 0]
            .groupby("publication_id")["policy_document_minus_publication_year"].min()
        )
        policy_by_publication["minimum_nonnegative_policy_record_year_difference"] = policy_by_publication["publication_id"].map(nonnegative_minimum)
        policy_by_publication = policy_by_publication.merge(
            P_years, on="publication_id", how="left", validate="one_to_one"
        )

        policy_by_year_rows: list[dict[str, Any]] = []
        for publication_year, subset in base.groupby("year", sort=True):
            events = int(subset["has_policy_document_link"].sum())
            policy_by_year_rows.append({
                "publication_year": int(publication_year),
                "n_final_publications": len(subset),
                "n_policy_linked_publications": events,
                "policy_linkage_rate_pct": round(100 * events / len(subset), 3) if len(subset) else None,
                "observed_policy_calendar_years_through_data_end": int(subset["observed_policy_calendar_years_through_data_end"].iloc[0]),
                "low_event_flag": bool(events < 5),
            })
        policy_by_year = pd.DataFrame(policy_by_year_rows)
        policy_windows = policy_window_summary(base)

        validation = pd.DataFrame([
            {"check": "final_P_and_analysis_base_identical_ID_set", "passed": set(P["id"]) == set(base["id"]), "detail": ""},
            {"check": "publication_grant_edges_reconcile_to_analysis_base", "passed": True, "detail": ""},
            {"check": "publication_policy_edges_reconcile_to_analysis_base", "passed": True, "detail": ""},
            {"check": "grant_timing_endpoints_have_record_years", "passed": int(pg_timing[["publication_year", "grant_start_year"]].isna().any(axis=1).sum()) == 0, "detail": "Missing years are reported, not imputed."},
            {"check": "policy_timing_endpoints_have_record_years", "passed": int(pd_timing[["publication_year", "policy_document_year"]].isna().any(axis=1).sum()) == 0, "detail": "Missing years are reported, not imputed."},
            {"check": "policy_records_not_later_than_frozen_data_end_year", "passed": True, "detail": ""},
            {"check": "negative_record_year_differences_retained", "passed": True, "detail": "Negative differences are counted and kept in edge-level outputs."},
            {"check": "final_result", "passed": True, "detail": "Temporal audit completed; timing quantities are descriptive record-year differences only."},
        ])

        outputs = {
            "publication_grant_record_year_differences.csv": pg_timing,
            "publication_policy_record_year_differences.csv": pd_timing,
            "record_year_difference_summary.csv": timing_summary_frame,
            "policy_record_timing_by_publication.csv": policy_by_publication,
            "policy_linkage_by_publication_year.csv": policy_by_year,
            "policy_observation_window_samples.csv": policy_windows,
            "temporal_validation_checks.csv": validation,
        }
        for filename, frame in outputs.items():
            atomic_write_csv(args.output_dir / filename, frame)
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "input_files": {name: {"path": str(path), "sha256": input_hashes[name]} for name, path in input_paths.items()},
            "policy_data_end_year": policy_end_year,
            "record_counts": {
                "final_publications_P": len(P),
                "linked_grants_G": len(G),
                "linked_policy_documents_D": len(D),
                "publication_grant_edges": len(pg_edges),
                "publication_policy_document_edges": len(pd_edges),
            },
            "policy_window_definition": {
                "primary": "The predeclared primary cohort stored in the frozen analysis base.",
                "robustness": "The predeclared longer-window cohort stored in the frozen analysis base.",
                "all_final_P": "Sensitivity because newer publications have fewer observed policy-document years.",
            },
            "temporal_measure": "Difference between years stored in linked Dimensions records.",
            "interpretive_boundary": "Record-year differences are descriptive database timing quantities only. They do not establish causal order, funding effects, policy influence, policy uptake, policy impact, endorsement, institutional selection, or knowledge translation.",
            "data_boundary": "All timing tables and the manifest are protected local data and must not be committed to GitHub.",
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(frame)} for name, frame in outputs.items()},
        }
        atomic_write_json(args.output_dir / "temporal_audit_manifest.json", manifest)

        grant_timing = timing_summary_frame.loc[timing_summary_frame["relation"].eq("publication_grant")].iloc[0]
        policy_timing = timing_summary_frame.loc[timing_summary_frame["relation"].eq("publication_policy_document")].iloc[0]
        primary_window = policy_windows.loc[policy_windows["analysis_sample"].eq("primary_policy_window")].iloc[0]
        print("FAIRIFICATION POLICY-WINDOW AND RECORD-TIMING AUDIT: PASS")
        print(f"FINAL PUBLICATIONS: {len(P)}")
        print(f"PUBLICATION-GRANT RECORD-YEAR PAIRS: {len(pg_timing)}")
        print(f"PUBLICATION-POLICY-DOCUMENT RECORD-YEAR PAIRS: {len(pd_timing)}")
        print(f"GRANT PAIRS WITH NEGATIVE RECORD-YEAR DIFFERENCE: {int(grant_timing['n_negative_record_year_differences'])}")
        print(f"POLICY PAIRS WITH NEGATIVE RECORD-YEAR DIFFERENCE: {int(policy_timing['n_negative_record_year_differences'])}")
        print(f"PRIMARY POLICY WINDOW: {int(primary_window['n_policy_linked_publications'])} policy-linked / {int(primary_window['n_final_publications'])} publications")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'temporal_audit_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

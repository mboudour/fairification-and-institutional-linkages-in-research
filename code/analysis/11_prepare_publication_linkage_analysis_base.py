#!/usr/bin/env python3
"""Build the protected publication-level FAIRification linkage analysis base.

This no-API script follows the completed relational audit. It deliberately does
not transfer the AI-mental-health project's ethics/performance indicators or
manual mental-health concept families. The frozen K=3 outcome-blind NMF
representation is the primary FAIRification thematic exposure:
  1. institutional stewardship/RDM/open-science practice;
  2. technical metadata/semantic infrastructure/reproducible workflows; and
  3. digital cultural heritage/collections/preservation.

The script constructs only recorded Dimensions linkage outcomes from the audited
edge lists, preserves continuous K=3 shares and assignment uncertainty, and
predefines policy-observation samples before any association model is fitted.
It makes zero Dimensions requests and does not estimate models.

Example:
    python code/analysis/11_prepare_publication_linkage_analysis_base.py \
      --anchor-file /path/to/publication_anchor_final_run.pkl \
      --publication-grant-edges-file /path/to/edges_publication_grant.csv \
      --publication-policy-edges-file /path/to/edges_publication_policy_document.csv \
      --relational-summary-file /path/to/retrieval_summary.json \
      --output-dir /path/to/computations/outputs/11_publication_linkage_analysis_base_run
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "11_prepare_publication_linkage_analysis_base_1.0"
EXPECTED_PUBLICATION_RECORDS = 144
DEFAULT_POLICY_DATA_END_YEAR = 2026
DEFAULT_PRIMARY_POLICY_CUTOFF_YEAR = 2022
DEFAULT_ROBUSTNESS_POLICY_CUTOFF_YEAR = 2021
DEFAULT_LOW_MARGIN_THRESHOLD = 0.10
THEME_LABELS = {
    1: "institutional_stewardship_research_data_management_open_science_practice",
    2: "technical_metadata_semantic_infrastructure_reproducible_workflows",
    3: "digital_cultural_heritage_collections_preservation",
}
THEME_LABELS_DISPLAY = {
    1: "Institutional stewardship, research-data management, and open-science practice",
    2: "Technical metadata, semantic infrastructure, and reproducible workflows",
    3: "Digital cultural heritage, collections, and preservation",
}
ANCHOR_REQUIRED_COLUMNS = {
    "id", "year", "times_cited", "retain_in_final_P", "nmf_primary_k", "nmf_dominant_theme",
    "nmf_dominant_theme_label", "nmf_dominant_theme_share", "nmf_normalized_topic_entropy",
    "nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share",
}
PG_REQUIRED_COLUMNS = {"publication_id", "grant_id"}
PD_REQUIRED_COLUMNS = {"publication_id", "policy_document_id"}


class BasePreparationFailure(RuntimeError):
    """Input-contract or publication-level linkage-base error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-file", type=Path, required=True)
    parser.add_argument("--publication-grant-edges-file", type=Path, required=True)
    parser.add_argument("--publication-policy-edges-file", type=Path, required=True)
    parser.add_argument("--relational-summary-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
    parser.add_argument("--policy-data-end-year", type=int, default=DEFAULT_POLICY_DATA_END_YEAR)
    parser.add_argument("--primary-policy-cutoff-year", type=int, default=DEFAULT_PRIMARY_POLICY_CUTOFF_YEAR)
    parser.add_argument("--robustness-policy-cutoff-year", type=int, default=DEFAULT_ROBUSTNESS_POLICY_CUTOFF_YEAR)
    parser.add_argument("--low-margin-threshold", type=float, default=DEFAULT_LOW_MARGIN_THRESHOLD)
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
    text = html.unescape(str(value))
    if text.casefold() == "nan":
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean_text(value).casefold() in {"true", "1", "yes"}


def require_columns(frame: pd.DataFrame, label: str, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise BasePreparationFailure(f"{label} is missing required columns: " + ", ".join(missing))


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in (
        "anchor_file", "publication_grant_edges_file", "publication_policy_edges_file", "relational_summary_file", "output_dir"
    ):
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [
        args.anchor_file, args.publication_grant_edges_file, args.publication_policy_edges_file, args.relational_summary_file
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


def wilson_interval(events: int, total: int) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    z = 1.959963984540054
    proportion = events / total
    denominator = 1 + z**2 / total
    centre = (proportion + z**2 / (2 * total)) / denominator
    half_width = z * np.sqrt((proportion * (1 - proportion) + z**2 / (4 * total)) / total) / denominator
    return 100 * (centre - half_width), 100 * (centre + half_width)


def outcome_summary(frame: pd.DataFrame, group_variable: str, group_label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for level, group in frame.groupby(group_variable, dropna=False, sort=True):
        for outcome, count_column in [
            ("has_grant_link", "n_linked_grants"),
            ("has_policy_document_link", "n_linked_policy_documents"),
        ]:
            total = len(group)
            events = int(group[outcome].sum())
            lower, upper = wilson_interval(events, total)
            rows.append({
                "group_variable": group_label,
                "group_level": clean_text(level),
                "outcome": outcome,
                "n_publications": total,
                "n_linked_publications": events,
                "linkage_rate_pct": round(100 * events / total, 3) if total else None,
                "wilson_ci_95_low_pct": round(lower, 3) if lower is not None else None,
                "wilson_ci_95_high_pct": round(upper, 3) if upper is not None else None,
                "mean_number_of_recorded_links": round(float(group[count_column].mean()), 4) if total else None,
                "low_denominator_flag": bool(total < 30),
                "low_event_flag": bool(events < 5),
            })
    return pd.DataFrame(rows)


def main() -> None:
    try:
        args = parse_args()
        if args.expected_publication_records < 1:
            raise ValueError("--expected-publication-records must be positive.")
        if not (0 < args.low_margin_threshold < 1):
            raise ValueError("--low-margin-threshold must be strictly between 0 and 1.")
        if not (args.robustness_policy_cutoff_year <= args.primary_policy_cutoff_year <= args.policy_data_end_year):
            raise ValueError("Policy cutoff years must satisfy robustness <= primary <= policy data-end year.")
        args = preflight_paths(args)
        input_paths = {
            "publication_anchor": args.anchor_file,
            "publication_grant_edges": args.publication_grant_edges_file,
            "publication_policy_edges": args.publication_policy_edges_file,
            "relational_summary": args.relational_summary_file,
        }
        input_hashes = {name: sha256(path) for name, path in input_paths.items()}

        anchor = pd.read_pickle(args.anchor_file).copy()
        pg_edges = pd.read_csv(args.publication_grant_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        pd_edges = pd.read_csv(args.publication_policy_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        relational_summary = json.loads(args.relational_summary_file.read_text(encoding="utf-8"))
        if not isinstance(relational_summary, dict) or relational_summary.get("status") != "complete":
            raise BasePreparationFailure("Relational audit summary must be a completed JSON object.")
        require_columns(anchor, "Publication anchor", ANCHOR_REQUIRED_COLUMNS)
        require_columns(pg_edges, "Publication-grant edges", PG_REQUIRED_COLUMNS)
        require_columns(pd_edges, "Publication-policy edges", PD_REQUIRED_COLUMNS)

        anchor["id"] = anchor["id"].map(clean_text)
        if len(anchor) != args.expected_publication_records or anchor["id"].eq("").any() or anchor["id"].duplicated().any():
            raise BasePreparationFailure("Publication anchor does not have the required unique 144-record identifier set.")
        if not anchor["retain_in_final_P"].map(bool_from).all():
            raise BasePreparationFailure("Publication anchor contains a record outside final P.")
        if not anchor["nmf_primary_k"].map(lambda value: clean_text(value) == "3").all():
            raise BasePreparationFailure("Publication anchor does not contain only the frozen primary K=3 NMF specification.")
        anchor["nmf_dominant_theme"] = pd.to_numeric(anchor["nmf_dominant_theme"], errors="coerce")
        if anchor["nmf_dominant_theme"].isna().any() or not set(anchor["nmf_dominant_theme"].astype(int)).issubset(THEME_LABELS):
            raise BasePreparationFailure("Publication anchor contains invalid K=3 dominant-theme values.")
        anchor["year"] = pd.to_numeric(anchor["year"], errors="coerce")
        if anchor["year"].isna().any() or (anchor["year"] > args.policy_data_end_year).any():
            raise BasePreparationFailure("Publication years are missing, nonnumeric, or later than the policy-data endpoint.")
        anchor["year"] = anchor["year"].astype(int)
        theme_share_columns = ["nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share"]
        for column in theme_share_columns + ["nmf_dominant_theme_share", "nmf_normalized_topic_entropy"]:
            anchor[column] = pd.to_numeric(anchor[column], errors="coerce")
        if anchor[theme_share_columns].isna().any().any():
            raise BasePreparationFailure("Publication anchor contains missing continuous K=3 theme shares.")
        if ((anchor[theme_share_columns] < -1e-12) | (anchor[theme_share_columns] > 1 + 1e-12)).any().any():
            raise BasePreparationFailure("K=3 theme shares must lie in [0, 1].")
        anchor["nmf_theme_share_sum"] = anchor[theme_share_columns].sum(axis=1)
        if not np.allclose(anchor["nmf_theme_share_sum"], 1.0, atol=1e-8, rtol=0):
            raise BasePreparationFailure("K=3 continuous theme shares do not sum to one for every publication.")
        expected_labels = anchor["nmf_dominant_theme"].astype(int).map(THEME_LABELS)
        if not anchor["nmf_dominant_theme_label"].map(clean_text).eq(expected_labels).all():
            raise BasePreparationFailure("Publication anchor NMF labels do not match the frozen K=3 mapping.")

        pg_edges["publication_id"] = pg_edges["publication_id"].map(clean_text)
        pg_edges["grant_id"] = pg_edges["grant_id"].map(clean_text)
        pd_edges["publication_id"] = pd_edges["publication_id"].map(clean_text)
        pd_edges["policy_document_id"] = pd_edges["policy_document_id"].map(clean_text)
        if (pg_edges[["publication_id", "grant_id"]].eq("").any().any() or pd_edges[["publication_id", "policy_document_id"]].eq("").any().any()):
            raise BasePreparationFailure("Edge table contains a blank endpoint identifier.")
        pg_edges = pg_edges.drop_duplicates().reset_index(drop=True)
        pd_edges = pd_edges.drop_duplicates().reset_index(drop=True)
        anchor_ids = set(anchor["id"])
        if not set(pg_edges["publication_id"]).issubset(anchor_ids) or not set(pd_edges["publication_id"]).issubset(anchor_ids):
            raise BasePreparationFailure("An audited edge points to a publication outside the final anchor.")
        summary_counts = relational_summary.get("record_counts", {})
        summary_edges = relational_summary.get("edge_counts", {})
        if summary_counts.get("final_publications_P") != len(anchor):
            raise BasePreparationFailure("Relational summary does not reconcile to the anchor record count.")
        if summary_edges.get("publication_grant") != len(pg_edges) or summary_edges.get("publication_policy_document") != len(pd_edges):
            raise BasePreparationFailure("Relational summary edge counts do not reconcile to supplied edge files.")

        grant_counts = pg_edges.groupby("publication_id")["grant_id"].nunique().rename("n_linked_grants")
        policy_counts = pd_edges.groupby("publication_id")["policy_document_id"].nunique().rename("n_linked_policy_documents")
        base = anchor.copy().set_index("id", drop=False)
        base = base.join(grant_counts, how="left").join(policy_counts, how="left")
        base["n_linked_grants"] = base["n_linked_grants"].fillna(0).astype(int)
        base["n_linked_policy_documents"] = base["n_linked_policy_documents"].fillna(0).astype(int)
        base["has_grant_link"] = (base["n_linked_grants"] > 0).astype(int)
        base["has_policy_document_link"] = (base["n_linked_policy_documents"] > 0).astype(int)
        base["publication_year_centered"] = base["year"] - float(base["year"].mean())
        base["times_cited_numeric"] = pd.to_numeric(base["times_cited"], errors="coerce")
        if (base["times_cited_numeric"].dropna() < 0).any():
            raise BasePreparationFailure("Publication anchor contains a negative citation count.")
        base["times_cited_available"] = base["times_cited_numeric"].notna()
        base["log1p_times_cited"] = np.where(base["times_cited_available"], np.log1p(base["times_cited_numeric"]), np.nan)
        shares = base[theme_share_columns].to_numpy(dtype=float)
        sorted_shares = np.sort(shares, axis=1)
        base["nmf_assignment_margin"] = sorted_shares[:, -1] - sorted_shares[:, -2]
        base["nmf_low_margin_at_threshold"] = base["nmf_assignment_margin"] < args.low_margin_threshold
        base["policy_data_end_year"] = args.policy_data_end_year
        base["observed_policy_calendar_years_through_data_end"] = args.policy_data_end_year - base["year"] + 1
        base["in_primary_policy_window"] = base["year"] <= args.primary_policy_cutoff_year
        base["in_robustness_policy_window"] = base["year"] <= args.robustness_policy_cutoff_year
        base["nmf_dominant_theme"] = base["nmf_dominant_theme"].astype(int)
        base["nmf_dominant_theme_label_display"] = base["nmf_dominant_theme"].map(THEME_LABELS_DISPLAY)
        base = base.reset_index(drop=True)

        if not set(base["has_grant_link"]).issubset({0, 1}) or not set(base["has_policy_document_link"]).issubset({0, 1}):
            raise BasePreparationFailure("Derived linkage outcomes are not binary.")
        if (base["n_linked_grants"] < 0).any() or (base["n_linked_policy_documents"] < 0).any():
            raise BasePreparationFailure("Derived linkage counts are negative.")

        overall_group = base.assign(overall="All final P")
        overall_summary = outcome_summary(overall_group, "overall", "overall")
        theme_summary = outcome_summary(base, "nmf_dominant_theme_label_display", "dominant_K3_theme__supplementary")
        year_summary = outcome_summary(base, "year", "publication_year")
        margin_summary = pd.DataFrame([{
            "low_margin_threshold": args.low_margin_threshold,
            "n_publications": len(base),
            "n_low_margin_publications": int(base["nmf_low_margin_at_threshold"].sum()),
            "share_low_margin_pct": round(100 * float(base["nmf_low_margin_at_threshold"].mean()), 3),
            "purpose": "Predeclared sensitivity flag only; the primary association representation uses continuous K=3 shares for all final P publications.",
        }])
        policy_windows = []
        for label, mask, purpose in [
            ("all_final_P__policy_window_sensitivity", pd.Series(True, index=base.index), "Sensitivity only: recent publications have fewer observed policy-record years."),
            (f"primary_policy_window__publication_year_through_{args.primary_policy_cutoff_year}", base["in_primary_policy_window"], "Primary policy-link association sample."),
            (f"robustness_policy_window__publication_year_through_{args.robustness_policy_cutoff_year}", base["in_robustness_policy_window"], "Longer-observation-window robustness sample."),
        ]:
            subset = base.loc[mask]
            policy_windows.append({
                "analysis_sample": label,
                "policy_data_end_year": args.policy_data_end_year,
                "publication_year_rule": "all years" if label.startswith("all_final") else f"year <= {args.primary_policy_cutoff_year if 'primary_' in label else args.robustness_policy_cutoff_year}",
                "n_publications": len(subset),
                "n_policy_linked_publications": int(subset["has_policy_document_link"].sum()),
                "policy_linkage_rate_pct": round(100 * float(subset["has_policy_document_link"].mean()), 3) if len(subset) else None,
                "minimum_observed_policy_calendar_years": int(subset["observed_policy_calendar_years_through_data_end"].min()) if len(subset) else None,
                "purpose": purpose,
            })
        policy_window_summary = pd.DataFrame(policy_windows)

        validation = pd.DataFrame([
            {"check": "expected_final_P_record_count", "passed": len(base) == args.expected_publication_records, "detail": ""},
            {"check": "relational_summary_reconciles", "passed": True, "detail": ""},
            {"check": "all_edge_publication_endpoints_in_final_P", "passed": True, "detail": ""},
            {"check": "frozen_K3_theme_shares_sum_to_one", "passed": bool(np.allclose(base["nmf_theme_share_sum"], 1.0, atol=1e-8, rtol=0)), "detail": ""},
            {"check": "derived_linkage_outcomes_are_binary", "passed": True, "detail": ""},
            {"check": "policy_window_order_valid", "passed": args.robustness_policy_cutoff_year <= args.primary_policy_cutoff_year <= args.policy_data_end_year, "detail": ""},
            {"check": "final_result", "passed": True, "detail": ""},
        ])

        outputs = {
            "publication_linkage_analysis_base.pkl": base,
            "publication_linkage_analysis_base.csv": base,
            "overall_linkage_outcomes.csv": overall_summary,
            "linkage_outcomes_by_dominant_K3_theme__supplementary.csv": theme_summary,
            "linkage_outcomes_by_publication_year.csv": year_summary,
            "nmf_assignment_margin_summary.csv": margin_summary,
            "policy_observation_window_samples.csv": policy_window_summary,
            "validation_checks.csv": validation,
        }
        for filename, output in outputs.items():
            path = args.output_dir / filename
            if filename.endswith(".pkl"):
                atomic_write_pickle(path, output)
            else:
                atomic_write_csv(path, output)

        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "input_files": {name: {"path": str(path), "sha256": input_hashes[name]} for name, path in input_paths.items()},
            "records": {"final_publications_P": len(base), "publication_grant_edges": len(pg_edges), "publication_policy_document_edges": len(pd_edges)},
            "frozen_thematic_specification": {
                "primary_k": 3,
                "theme_mapping": {str(key): value for key, value in THEME_LABELS.items()},
                "primary_exposure_representation": "Continuous K=3 component shares. Association models will include Topic 1 and Topic 3 shares with Topic 2 omitted as the compositional reference.",
                "hard_assignment_role": "Supplementary descriptive summaries only.",
                "separate_FAIR_text_indicator_layer": "Not constructed. The frozen outcome-blind K=3 NMF already represents the relevant FAIRification orientations; adding a post hoc overlapping dictionary score is not justified for the primary analysis.",
                "low_margin_sensitivity": {"threshold": args.low_margin_threshold, "role": "Repeat key association models after excluding low-margin hard assignments; never use this exclusion to choose the primary thematic specification."},
            },
            "outcomes": {
                "has_grant_link": "At least one audited Dimensions-recorded P-G identifier edge.",
                "has_policy_document_link": "At least one audited Dimensions-recorded P-D identifier edge.",
                "interpretive_boundary": "Both are recorded database-linkage outcomes, not causal effects, funding intent, policy endorsement, policy uptake, or policy impact.",
            },
            "planned_association_adjustment": {
                "primary": "Publication year centered. Citation count is not a primary adjustment variable because it accumulates after publication and may be related to visibility and recorded link opportunities.",
                "citation_sensitivity": "A separately labelled sensitivity may add log1p(times_cited) for records with an observed citation count. It remains a conditional association, not a causal model.",
            },
            "policy_observation_design": {
                "policy_data_end_year": args.policy_data_end_year,
                "primary_publication_year_cutoff": args.primary_policy_cutoff_year,
                "robustness_publication_year_cutoff": args.robustness_policy_cutoff_year,
                "rationale": "The 2026 policy retrieval endpoint is fixed before association modeling. Publications through 2022 form the primary policy sample; publications through 2021 provide a longer-window robustness cohort. All final P is a clearly labelled sensitivity because recent records have fewer observed policy-document years.",
                "time_measure_boundary": "Publication and policy years are record years. They do not establish causal timing or knowledge translation.",
            },
            "data_boundary": "The publication-level analysis base and all tables are protected local data and must not be committed to GitHub.",
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(output)} for name, output in outputs.items()},
        }
        atomic_write_json(args.output_dir / "analysis_base_manifest.json", manifest)

        print("FAIRIFICATION PUBLICATION LINKAGE ANALYSIS BASE: PASS")
        print(f"FINAL PUBLICATIONS: {len(base)}")
        print(f"PUBLICATIONS WITH RECORDED GRANT LINK: {int(base['has_grant_link'].sum())}")
        print(f"PUBLICATIONS WITH RECORDED POLICY-DOCUMENT LINK: {int(base['has_policy_document_link'].sum())}")
        print(f"POLICY DATA END YEAR: {args.policy_data_end_year}")
        print(f"PRIMARY POLICY WINDOW: publication year <= {args.primary_policy_cutoff_year}")
        print(f"ROBUSTNESS POLICY WINDOW: publication year <= {args.robustness_policy_cutoff_year}")
        print(f"LOW-MARGIN ASSIGNMENTS AT {args.low_margin_threshold:.2f}: {int(base['nmf_low_margin_at_threshold'].sum())}")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'analysis_base_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

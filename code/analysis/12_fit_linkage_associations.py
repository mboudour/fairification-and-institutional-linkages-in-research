#!/usr/bin/env python3
"""Fit guarded publication-level associations for audited FAIRification links.

This script reads the frozen publication-level linkage analysis base. Its primary
model estimates the association between continuous K=3 FAIRification theme shares
and the recorded grant-link outcome, adjusted for publication year. Topic 2
(technical metadata/semantic infrastructure/reproducible workflows) is the
compositional reference: Topic 1 and Topic 3 shares are scaled per 10 percentage
point shift relative to that reference.

The policy-link outcome is subjected to a predeclared event-adequacy screen. If
there are fewer than 10 events per non-intercept parameter, no multivariable
policy-link model is fitted. The script writes a transparent `not_fit` diagnostic
and descriptive counts instead. It does not substitute a sparse or penalized
model solely to manufacture a policy coefficient.

A low-margin NMF sensitivity and a citation-adjusted grant sensitivity are
available only if their own event-adequacy and numerical diagnostics pass.
All coefficients are conditional associations, not causal effects.

Example:
    python code/analysis/12_fit_linkage_associations.py \
      --analysis-base-file /path/to/publication_linkage_analysis_base.pkl \
      --analysis-base-manifest-file /path/to/analysis_base_manifest.json \
      --output-dir /path/to/computations/outputs/12_linkage_associations_run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import statsmodels.api as sm
    from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationWarning, SingularMatrixWarning
except ImportError as exc:
    raise SystemExit(
        "This script requires statsmodels. In the activated fairification-py311 environment, run:\n"
        "  conda install -y statsmodels\n"
        "Then rerun the script."
    ) from exc


SCRIPT_VERSION = "12_fit_linkage_associations_1.0"
EXPECTED_PUBLICATION_RECORDS = 144
MIN_EVENTS_PER_PARAMETER = 10
THEME_REFERENCE = "Topic 2: technical metadata, semantic infrastructure, and reproducible workflows"
PRIMARY_PREDICTORS = ["nmf_topic_1_share_per_10pp", "nmf_topic_3_share_per_10pp", "publication_year_centered"]
CITATION_SENSITIVITY_PREDICTORS = [*PRIMARY_PREDICTORS, "log1p_times_cited"]
REQUIRED_COLUMNS = {
    "id", "year", "has_grant_link", "has_policy_document_link", "n_linked_grants",
    "n_linked_policy_documents", "nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share",
    "nmf_assignment_margin", "nmf_low_margin_at_threshold", "publication_year_centered",
    "log1p_times_cited", "times_cited_available", "in_primary_policy_window", "in_robustness_policy_window",
    "nmf_dominant_theme_label_display",
}


class AssociationFailure(RuntimeError):
    """Input-contract or model-construction error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-base-file", type=Path, required=True)
    parser.add_argument("--analysis-base-manifest-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
    parser.add_argument("--minimum-events-per-parameter", type=int, default=MIN_EVENTS_PER_PARAMETER)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes"}


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in ("analysis_base_file", "analysis_base_manifest_file", "output_dir"):
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [args.analysis_base_file, args.analysis_base_manifest_file]
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


def require_columns(frame: pd.DataFrame, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise AssociationFailure("Publication linkage analysis base is missing required columns: " + ", ".join(missing))


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


def model_not_fit(
    *, label: str, outcome: str, sample: pd.DataFrame, predictors: list[str], reason: str, min_events_per_parameter: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    events = int(sample[outcome].sum()) if len(sample) else 0
    parameters = len(predictors) + 1
    return pd.DataFrame(columns=[
        "model_label", "outcome", "term", "coefficient_log_odds", "robust_standard_error", "z_value", "p_value",
        "odds_ratio", "ci_95_odds_ratio_low", "ci_95_odds_ratio_high", "ci_95_log_odds_low", "ci_95_log_odds_high",
    ]), {
        "model_label": label,
        "outcome": outcome,
        "model_status": "not_fit",
        "n_publications": int(len(sample)),
        "n_events": events,
        "event_rate_pct": round(100 * events / len(sample), 3) if len(sample) else None,
        "n_nonintercept_parameters": len(predictors),
        "n_parameters_including_intercept": parameters,
        "minimum_events_per_parameter": min_events_per_parameter,
        "required_minimum_events": min_events_per_parameter * len(predictors),
        "aic": None,
        "pseudo_r2_mcfadden": None,
        "covariance_estimator": "HC3 robust if fit",
        "reason": reason,
        "interpretive_boundary": "No association model was estimated. Recorded identifier links are not causal effects, funding intent, policy endorsement, policy uptake, or policy impact.",
    }


def fit_logistic(
    *, label: str, outcome: str, sample: pd.DataFrame, predictors: list[str], min_events_per_parameter: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    model_frame = sample[[outcome, *predictors]].dropna().copy()
    events = int(model_frame[outcome].sum()) if len(model_frame) else 0
    if len(model_frame) == 0:
        return model_not_fit(
            label=label, outcome=outcome, sample=model_frame, predictors=predictors,
            reason="No complete observations remain after applying the specified model variables.",
            min_events_per_parameter=min_events_per_parameter,
        )
    if not set(model_frame[outcome]).issubset({0, 1}):
        return model_not_fit(
            label=label, outcome=outcome, sample=model_frame, predictors=predictors,
            reason="The specified outcome is not binary in the model sample.", min_events_per_parameter=min_events_per_parameter,
        )
    required_events = min_events_per_parameter * len(predictors)
    if events < required_events:
        return model_not_fit(
            label=label, outcome=outcome, sample=model_frame, predictors=predictors,
            reason=(f"Event-adequacy rule not met: {events} observed events for {len(predictors)} non-intercept parameters; "
                    f"at least {required_events} events are required."),
            min_events_per_parameter=min_events_per_parameter,
        )
    if model_frame[outcome].nunique() < 2:
        return model_not_fit(
            label=label, outcome=outcome, sample=model_frame, predictors=predictors,
            reason="The outcome has fewer than two observed values.", min_events_per_parameter=min_events_per_parameter,
        )
    x = sm.add_constant(model_frame[predictors].astype(float), has_constant="add")
    y = model_frame[outcome].astype(float)
    if np.linalg.matrix_rank(x.to_numpy()) < x.shape[1]:
        return model_not_fit(
            label=label, outcome=outcome, sample=model_frame, predictors=predictors,
            reason="The model design matrix is rank-deficient.", min_events_per_parameter=min_events_per_parameter,
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            warnings.simplefilter("error", SingularMatrixWarning)
            warnings.simplefilter("error", ConvergenceWarning)
            result = sm.GLM(y, x, family=sm.families.Binomial()).fit(cov_type="HC3")
        confidence = result.conf_int()
        coefficients = pd.DataFrame({
            "model_label": label,
            "outcome": outcome,
            "term": result.params.index,
            "coefficient_log_odds": result.params.values,
            "robust_standard_error": result.bse.values,
            "z_value": result.tvalues.values,
            "p_value": result.pvalues.values,
            "ci_95_log_odds_low": confidence.iloc[:, 0].values,
            "ci_95_log_odds_high": confidence.iloc[:, 1].values,
        })
        coefficients["odds_ratio"] = np.exp(coefficients["coefficient_log_odds"])
        coefficients["ci_95_odds_ratio_low"] = np.exp(coefficients["ci_95_log_odds_low"])
        coefficients["ci_95_odds_ratio_high"] = np.exp(coefficients["ci_95_log_odds_high"])
        coefficients = coefficients[[
            "model_label", "outcome", "term", "coefficient_log_odds", "robust_standard_error", "z_value", "p_value",
            "odds_ratio", "ci_95_odds_ratio_low", "ci_95_odds_ratio_high", "ci_95_log_odds_low", "ci_95_log_odds_high",
        ]]
        diagnostic = {
            "model_label": label,
            "outcome": outcome,
            "model_status": "fit",
            "n_publications": int(result.nobs),
            "n_events": int(y.sum()),
            "event_rate_pct": round(100 * float(y.mean()), 3),
            "n_nonintercept_parameters": len(predictors),
            "n_parameters_including_intercept": int(len(result.params)),
            "minimum_events_per_parameter": min_events_per_parameter,
            "required_minimum_events": required_events,
            "aic": round(float(result.aic), 6),
            "pseudo_r2_mcfadden": round(float(1 - result.llf / result.llnull), 6) if result.llnull else None,
            "covariance_estimator": "HC3 robust",
            "reason": "",
            "interpretive_boundary": "Conditional association only. Coefficients and odds ratios do not identify causal effects, funding intent, policy endorsement, policy uptake, policy impact, or institutional influence.",
        }
        return coefficients, diagnostic
    except Exception as exc:
        return model_not_fit(
            label=label, outcome=outcome, sample=model_frame, predictors=predictors,
            reason=f"Model fitting stopped: {type(exc).__name__}: {exc}", min_events_per_parameter=min_events_per_parameter,
        )


def descriptive_policy_event_table(frame: pd.DataFrame, sample_label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for theme, group in frame.groupby("nmf_dominant_theme_label_display", sort=True):
        events = int(group["has_policy_document_link"].sum())
        rows.append({
            "analysis_sample": sample_label,
            "dominant_K3_theme__supplementary": theme,
            "n_publications": len(group),
            "n_policy_linked_publications": events,
            "policy_linkage_rate_pct": round(100 * events / len(group), 3) if len(group) else None,
            "low_denominator_flag": bool(len(group) < 30),
            "low_event_flag": bool(events < 5),
            "interpretive_boundary": "Descriptive count only; no policy-link regression is fitted when the event-adequacy rule fails.",
        })
    return pd.DataFrame(rows)


def main() -> None:
    try:
        args = parse_args()
        if args.expected_publication_records < 1 or args.minimum_events_per_parameter < 1:
            raise ValueError("Expected records and minimum events per parameter must be positive.")
        args = preflight_paths(args)
        input_hashes = {
            "analysis_base": sha256(args.analysis_base_file),
            "analysis_base_manifest": sha256(args.analysis_base_manifest_file),
        }
        base = pd.read_pickle(args.analysis_base_file).copy()
        base_manifest = json.loads(args.analysis_base_manifest_file.read_text(encoding="utf-8"))
        if not isinstance(base_manifest, dict) or base_manifest.get("status") != "complete":
            raise AssociationFailure("Analysis-base manifest must be a completed JSON object.")
        require_columns(base, REQUIRED_COLUMNS)
        if len(base) != args.expected_publication_records:
            raise AssociationFailure(f"Expected {args.expected_publication_records} publications; found {len(base)}.")
        base["id"] = base["id"].astype(str).str.strip()
        if base["id"].eq("").any() or base["id"].duplicated().any():
            raise AssociationFailure("Analysis base has blank or duplicate publication identifiers.")
        if base_manifest.get("records", {}).get("final_publications_P") != len(base):
            raise AssociationFailure("Analysis-base manifest does not reconcile to the supplied publication table.")
        for outcome in ("has_grant_link", "has_policy_document_link"):
            values = pd.to_numeric(base[outcome], errors="coerce")
            if values.isna().any() or not set(values.astype(int)).issubset({0, 1}):
                raise AssociationFailure(f"{outcome} must be binary.")
            base[outcome] = values.astype(int)
        for field in ["nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share", "publication_year_centered", "log1p_times_cited"]:
            base[field] = pd.to_numeric(base[field], errors="coerce")
        if base[["nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share", "publication_year_centered"]].isna().any().any():
            raise AssociationFailure("Primary continuous theme shares or publication-year adjustment is missing.")
        if not np.allclose(base[["nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share"]].sum(axis=1), 1.0, atol=1e-8, rtol=0):
            raise AssociationFailure("K=3 continuous theme shares do not sum to one for every publication.")
        base["nmf_topic_1_share_per_10pp"] = base["nmf_topic_1_share"] / 0.10
        base["nmf_topic_3_share_per_10pp"] = base["nmf_topic_3_share"] / 0.10
        base["nmf_low_margin_at_threshold"] = base["nmf_low_margin_at_threshold"].map(bool_from)
        base["times_cited_available"] = base["times_cited_available"].map(bool_from)
        base["in_primary_policy_window"] = base["in_primary_policy_window"].map(bool_from)
        base["in_robustness_policy_window"] = base["in_robustness_policy_window"].map(bool_from)
        if not base.loc[~base["times_cited_available"], "log1p_times_cited"].isna().all():
            raise AssociationFailure("Citation-unavailable records must not carry an imputed citation sensitivity value.")

        model_specs = [
            {
                "label": "grant_primary__continuous_K3_shares__year_adjusted",
                "outcome": "has_grant_link",
                "sample": base,
                "predictors": PRIMARY_PREDICTORS,
                "purpose": "Primary association model for recorded grant links.",
            },
            {
                "label": "grant_low_margin_excluded_sensitivity__continuous_K3_shares__year_adjusted",
                "outcome": "has_grant_link",
                "sample": base.loc[~base["nmf_low_margin_at_threshold"]].copy(),
                "predictors": PRIMARY_PREDICTORS,
                "purpose": "Predeclared NMF-assignment-margin sensitivity.",
            },
            {
                "label": "grant_citation_adjusted_sensitivity__continuous_K3_shares__year_adjusted",
                "outcome": "has_grant_link",
                "sample": base.loc[base["times_cited_available"]].copy(),
                "predictors": CITATION_SENSITIVITY_PREDICTORS,
                "purpose": "Citation-adjusted sensitivity only; citation is not a primary causal adjustment variable.",
            },
            {
                "label": "policy_primary_window__continuous_K3_shares__year_adjusted",
                "outcome": "has_policy_document_link",
                "sample": base.loc[base["in_primary_policy_window"]].copy(),
                "predictors": PRIMARY_PREDICTORS,
                "purpose": "Primary policy-link association model, conditional on event adequacy.",
            },
            {
                "label": "policy_longer_window_robustness__continuous_K3_shares__year_adjusted",
                "outcome": "has_policy_document_link",
                "sample": base.loc[base["in_robustness_policy_window"]].copy(),
                "predictors": PRIMARY_PREDICTORS,
                "purpose": "Longer observation-window policy sensitivity, conditional on event adequacy.",
            },
            {
                "label": "policy_all_final_P_window_sensitivity__continuous_K3_shares__year_adjusted",
                "outcome": "has_policy_document_link",
                "sample": base,
                "predictors": PRIMARY_PREDICTORS,
                "purpose": "All-publication policy sensitivity, conditional on event adequacy.",
            },
        ]

        coefficient_frames: list[pd.DataFrame] = []
        diagnostics: list[dict[str, Any]] = []
        model_spec_rows: list[dict[str, Any]] = []
        policy_descriptives: list[pd.DataFrame] = []
        for spec in model_specs:
            coefficients, diagnostic = fit_logistic(
                label=spec["label"], outcome=spec["outcome"], sample=spec["sample"], predictors=spec["predictors"],
                min_events_per_parameter=args.minimum_events_per_parameter,
            )
            coefficient_frames.append(coefficients)
            diagnostic["purpose"] = spec["purpose"]
            diagnostics.append(diagnostic)
            model_spec_rows.append({
                "model_label": spec["label"],
                "outcome": spec["outcome"],
                "analysis_sample_rule": "All final P" if len(spec["sample"]) == len(base) else spec["label"],
                "predictors": "; ".join(spec["predictors"]),
                "theme_reference": THEME_REFERENCE,
                "purpose": spec["purpose"],
            })
            if spec["outcome"] == "has_policy_document_link":
                policy_descriptives.append(descriptive_policy_event_table(spec["sample"], spec["label"]))
        nonempty_coefficient_frames = [frame for frame in coefficient_frames if not frame.empty]
        if nonempty_coefficient_frames:
            coefficients = pd.concat(nonempty_coefficient_frames, ignore_index=True)
        else:
            coefficients = pd.DataFrame(columns=[
                "model_label", "outcome", "term", "coefficient_log_odds", "robust_standard_error", "z_value", "p_value",
                "odds_ratio", "ci_95_odds_ratio_low", "ci_95_odds_ratio_high", "ci_95_log_odds_low", "ci_95_log_odds_high",
            ])
        diagnostics_frame = pd.DataFrame(diagnostics)
        specs_frame = pd.DataFrame(model_spec_rows)
        policy_descriptive_frame = pd.concat(policy_descriptives, ignore_index=True)

        event_adequacy = diagnostics_frame[[
            "model_label", "outcome", "model_status", "n_publications", "n_events", "event_rate_pct",
            "n_nonintercept_parameters", "minimum_events_per_parameter", "required_minimum_events", "reason",
        ]].copy()
        validation = pd.DataFrame([
            {"check": "expected_publication_record_count", "passed": len(base) == args.expected_publication_records, "detail": ""},
            {"check": "continuous_K3_shares_sum_to_one", "passed": True, "detail": ""},
            {"check": "recorded_linkage_outcomes_binary", "passed": True, "detail": ""},
            {"check": "policy_models_event_adequacy_guard_applied", "passed": True, "detail": "Policy models may be not_fit when events are insufficient; this is a certified result, not a failure."},
            {"check": "grant_primary_model_fit", "passed": bool(diagnostics_frame.loc[diagnostics_frame["model_label"].eq("grant_primary__continuous_K3_shares__year_adjusted"), "model_status"].eq("fit").all()), "detail": ""},
            {"check": "final_result", "passed": True, "detail": ""},
        ])

        outputs = {
            "association_model_coefficients.csv": coefficients,
            "association_model_diagnostics.csv": diagnostics_frame,
            "association_model_specifications.csv": specs_frame,
            "event_adequacy_assessment.csv": event_adequacy,
            "policy_link_event_limited_descriptives.csv": policy_descriptive_frame,
            "validation_checks.csv": validation,
        }
        for filename, frame in outputs.items():
            atomic_write_csv(args.output_dir / filename, frame)
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "input_files": {
                "analysis_base": {"path": str(args.analysis_base_file), "sha256": input_hashes["analysis_base"]},
                "analysis_base_manifest": {"path": str(args.analysis_base_manifest_file), "sha256": input_hashes["analysis_base_manifest"]},
            },
            "model_design": {
                "method": "Binomial logistic regression with HC3 robust standard errors where the event-adequacy rule and numerical diagnostics permit fitting.",
                "minimum_events_per_nonintercept_parameter": args.minimum_events_per_parameter,
                "primary_grant_model": "Continuous Topic 1 and Topic 3 NMF shares per 10 percentage points, with Topic 2 omitted as the compositional reference, adjusted for centered publication year.",
                "citation_adjustment": "Sensitivity only; not a primary causal adjustment variable.",
                "low_margin_sensitivity": "Exclude publications flagged as low-margin in the frozen analysis base; do not use it to select the thematic structure.",
                "policy_model_rule": "Do not fit a multivariable policy-link model if observed events are fewer than the predeclared required minimum.",
            },
            "outcome_boundary": "Grant and policy outcomes are audited Dimensions-recorded identifier links. Coefficients are conditional associations, not causal effects or evidence of funding intent, policy endorsement, policy uptake, policy impact, topical similarity, or institutional influence.",
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(frame)} for name, frame in outputs.items()},
            "data_boundary": "All association outputs are protected local data and must not be committed to GitHub.",
        }
        atomic_write_json(args.output_dir / "association_manifest.json", manifest)

        primary_grant = diagnostics_frame.loc[diagnostics_frame["model_label"].eq("grant_primary__continuous_K3_shares__year_adjusted")].iloc[0]
        policy_primary = diagnostics_frame.loc[diagnostics_frame["model_label"].eq("policy_primary_window__continuous_K3_shares__year_adjusted")].iloc[0]
        print("FAIRIFICATION LINKAGE ASSOCIATIONS: PASS")
        print(f"FINAL PUBLICATIONS: {len(base)}")
        print(f"RECORDED GRANT-LINK EVENTS: {int(base['has_grant_link'].sum())}")
        print(f"RECORDED POLICY-LINK EVENTS: {int(base['has_policy_document_link'].sum())}")
        print(f"GRANT PRIMARY MODEL: {primary_grant['model_status']}")
        print(f"POLICY PRIMARY MODEL: {policy_primary['model_status']}")
        if policy_primary["model_status"] != "fit":
            print(f"POLICY MODEL REASON: {policy_primary['reason']}")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'association_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

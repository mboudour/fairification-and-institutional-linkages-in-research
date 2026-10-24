#!/usr/bin/env python3
"""Compute and consolidate predeclared FAIRification robustness evidence.

This local, no-API script consolidates diagnostics and sensitivities already
produced by earlier stages. It also reproduces the one missing robustness
calculation from the local NMF run: a K=2 leave-one-out NMF comparison excluding
Wilkinson et al. (2016), DOI 10.1038/sdata.2016.18.

The leave-one-out calculation uses the frozen 144-publication anchor and imports
the preprocessing and NMF functions from this repository's published
`code/thematic/publication_topic_model_diagnostic.py`. It fits K=2 to the full
frozen corpus and to the 143-publication corpus with the Wilkinson record
excluded, retaining the primary-corpus TF--IDF vocabulary. It is strictly a K=2
broad-structure sensitivity; it does not test or establish invariance of the
primary K=3 heritage/preservation component.

The script additionally summarizes:

* candidate K=2/K=3/K=4 NMF diagnostics and component-level bootstraps;
* primary, low-NMF-assignment-margin, and citation-adjusted grant associations;
* the predeclared 2022 primary, 2021 longer-window, and all-publication policy
  event accounting; and
* the explicit predeclared decision not to add a redundant FAIR dictionary score.

It does not refit grant or policy association models, alter the corpus, add FAIR
keywords, or substitute a sparse policy regression. Association comparisons are
conditional associations in Dimensions-recorded links, not causal estimates.

Example:
    python code/analysis/15_consolidate_robustness_evidence.py \
      --publication-anchor-file /path/to/publication_anchor_final_run.pkl \
      --nmf-output-dir /path/to/07_publication_nmf_run \
      --association-output-dir /path/to/12_linkage_associations_run \
      --temporal-output-dir /path/to/13_temporal_audit_run \
      --output-dir /path/to/computations/outputs/15_robustness_consolidation_run
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "15_consolidate_robustness_evidence_2.0_with_local_K2_leave_one_out"
EXPECTED_PUBLICATION_RECORDS = 144
EXPECTED_TOPICS = {2, 3, 4}
EXPECTED_BOOTSTRAPS = 8
EXPECTED_SAMPLE_FRACTION = 0.80
WILKINSON_DOI = "10.1038/sdata.2016.18"
THEME_LABELS = {
    1: "Institutional stewardship, research-data management, and open-science practice",
    2: "Technical metadata, semantic infrastructure, and reproducible workflows",
    3: "Digital cultural heritage, collections, and preservation",
}
GRANT_MODEL_ROLES = {
    "grant_primary__continuous_K3_shares__year_adjusted": "primary_year_adjusted",
    "grant_low_margin_excluded_sensitivity__continuous_K3_shares__year_adjusted": "low_NMF_assignment_margin_excluded_sensitivity",
    "grant_citation_adjusted_sensitivity__continuous_K3_shares__year_adjusted": "citation_adjusted_sensitivity",
}
POLICY_MODEL_TO_WINDOW = {
    "policy_primary_window__continuous_K3_shares__year_adjusted": "primary_policy_window",
    "policy_longer_window_robustness__continuous_K3_shares__year_adjusted": "longer_window_robustness",
    "policy_all_final_P_window_sensitivity__continuous_K3_shares__year_adjusted": "all_final_P__policy_window_sensitivity",
}
TARGET_GRANT_TERMS = ("nmf_topic_1_share_per_10pp", "nmf_topic_3_share_per_10pp")


class RobustnessFailure(RuntimeError):
    """Input-contract or cross-stage reconciliation error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-anchor-file", type=Path, required=True)
    parser.add_argument("--nmf-output-dir", type=Path, required=True)
    parser.add_argument("--association-output-dir", type=Path, required=True)
    parser.add_argument("--temporal-output-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
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


def normalize_doi(value: Any) -> str:
    value = clean_text(value).casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.strip().rstrip(".")


def bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean_text(value).casefold() in {"true", "1", "yes"}


def direction(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "not_estimated"
    return "positive" if numeric > 0 else "negative" if numeric < 0 else "zero"


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in ("publication_anchor_file", "nmf_output_dir", "association_output_dir", "temporal_output_dir", "output_dir"):
        setattr(args, name, resolved(getattr(args, name)))
    if not args.publication_anchor_file.is_file():
        raise FileNotFoundError(f"Publication anchor file was not found: {args.publication_anchor_file}")
    for directory in (args.nmf_output_dir, args.association_output_dir, args.temporal_output_dir):
        if not directory.is_dir():
            raise FileNotFoundError(f"Required input directory was not found: {directory}")
    if args.output_dir.exists() and (args.output_dir.is_file() or args.output_dir.is_symlink()):
        raise ValueError(f"Output path must be a real directory: {args.output_dir}")
    protected_inputs = [args.publication_anchor_file, args.nmf_output_dir, args.association_output_dir, args.temporal_output_dir]
    for input_path in protected_inputs:
        if is_within(input_path, args.output_dir):
            raise ValueError("Output directory must not be an ancestor of an input: " + str(args.output_dir))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {args.output_dir}. Choose a new empty directory; this script never deletes outputs."
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


def read_csv(path: Path, required: set[str], label: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Required {label} was not found: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise RobustnessFailure(f"{label} is missing required columns: " + ", ".join(missing))
    return frame


def read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required {label} was not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RobustnessFailure(f"{label} must be a JSON object.")
    return payload


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


def nmf_manifest_path(directory: Path) -> Path:
    candidates = [directory / "nmf_manifest.json", directory / "manifest.json"]
    present = [candidate for candidate in candidates if candidate.is_file()]
    if len(present) != 1:
        raise RobustnessFailure(
            f"NMF output directory must contain exactly one recognized manifest (nmf_manifest.json or manifest.json): {directory}"
        )
    return present[0]


def load_nmf_module() -> Any:
    module_path = Path(__file__).resolve().parents[1] / "thematic" / "publication_topic_model_diagnostic.py"
    if not module_path.is_file():
        raise RobustnessFailure(f"Published NMF implementation was not found: {module_path}")
    specification = importlib.util.spec_from_file_location("fairification_published_nmf", module_path)
    if specification is None or specification.loader is None:
        raise RobustnessFailure("Could not load the published FAIRification NMF implementation.")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def required_nmf_configuration(manifest: dict[str, Any], module: Any) -> tuple[int, int, float, int]:
    representation = manifest.get("text_representation", {})
    model = manifest.get("topic_model", {})
    try:
        ngram_range = tuple(int(value) for value in representation["ngram_range"])
        min_df = int(representation["min_df"])
        max_df = float(representation["max_df"])
        max_features = int(representation["max_features"])
        title_repetition = int(representation["title_repetition"])
        init = clean_text(model["init"])
        # The published local NMF script fixes solver="cd" in fit_nmf(), but
        # its manifest intentionally records only the non-default parameters.
        # Older run manifests may explicitly repeat the solver; otherwise this
        # immutable published setting is inferred rather than guessed.
        solver = clean_text(model.get("solver", "cd"))
        max_iter = int(model["max_iter"])
        random_seed = int(model["random_seed"])
    except (KeyError, TypeError, ValueError) as error:
        raise RobustnessFailure("NMF manifest lacks the complete published preprocessing and model configuration.") from error
    expected = {
        "ngram_range": (1, 2), "min_df": 2, "max_df": 0.80, "max_features": 15000,
        "title_repetition": 2, "init": "nndsvda", "solver": "cd", "max_iter": 300,
        "random_seed": int(module.RANDOM_SEED),
    }
    observed = {
        "ngram_range": ngram_range, "min_df": min_df, "max_df": max_df, "max_features": max_features,
        "title_repetition": title_repetition, "init": init, "solver": solver, "max_iter": max_iter,
        "random_seed": random_seed,
    }
    if observed != expected:
        raise RobustnessFailure(
            "NMF manifest configuration does not match the published FAIRification NMF implementation required for the leave-one-out replication."
        )
    return min_df, max_features, max_df, max_iter


def aggregate_component_stability(detail: pd.DataFrame, sizes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (n_topics, full_topic), group in detail.groupby(["n_topics", "full_topic"], sort=True):
        n_topics_int, topic_int = int(n_topics), int(full_topic)
        matching_size = sizes.loc[(sizes["n_topics"] == n_topics_int) & (sizes["dominant_topic"] == topic_int)]
        if len(matching_size) != 1:
            raise RobustnessFailure(f"Topic-size record does not uniquely match NMF K={n_topics_int}, topic {topic_int}.")
        size_row = matching_size.iloc[0]
        values = pd.to_numeric(group["component_cosine_similarity"], errors="coerce")
        agreements = pd.to_numeric(group["dominant_assignment_agreement_all_P"], errors="coerce")
        if values.isna().any() or agreements.isna().any():
            raise RobustnessFailure("NMF stability table contains nonnumeric similarities or assignment-agreement values.")
        rows.append({
            "n_topics": n_topics_int,
            "full_topic": topic_int,
            "primary_K3_theme_label": THEME_LABELS.get(topic_int, "not_applicable_for_non_K3_solution") if n_topics_int == 3 else "not_primary_K3_solution",
            "hard_assigned_publications": int(pd.to_numeric(size_row["n_publications"], errors="raise")),
            "hard_assigned_pct_of_P": float(pd.to_numeric(size_row["pct_of_P"], errors="raise")),
            "bootstrap_component_comparisons": len(group),
            "mean_component_cosine_similarity": float(values.mean()),
            "minimum_component_cosine_similarity": float(values.min()),
            "n_component_cosines_below_0_50": int((values < 0.50).sum()),
            "n_component_cosines_at_least_0_90": int((values >= 0.90).sum()),
            "mean_dominant_assignment_agreement": float(agreements.mean()),
            "minimum_dominant_assignment_agreement": float(agreements.min()),
            "interpretive_note": (
                "Primary K=3 component; report its observed bootstrap pattern without treating bootstrap values as confidence intervals."
                if n_topics_int == 3 else "Candidate-solution diagnostic only; not the primary linked-data thematic representation."
            ),
        })
    return pd.DataFrame(rows)


def leave_one_out_k2(
    *, anchor: pd.DataFrame, reference_assignments: pd.DataFrame, module: Any,
    min_df: int, max_features: int, max_df: float, max_iter: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recreate the K=2 leave-one-out comparison using the frozen full vocabulary."""
    required_anchor = {"id", "title", "abstract", "year"}
    missing = sorted(required_anchor.difference(anchor.columns))
    if missing:
        raise RobustnessFailure("Publication anchor is missing required NMF fields: " + ", ".join(missing))
    anchor = anchor.copy()
    anchor["id"] = anchor["id"].map(clean_text)
    if anchor["id"].eq("").any() or anchor["id"].duplicated().any():
        raise RobustnessFailure("Publication anchor has blank or duplicate publication IDs.")
    doi_columns = [column for column in ("doi", "source_doi") if column in anchor.columns]
    if not doi_columns:
        raise RobustnessFailure("Publication anchor lacks doi and source_doi columns needed to locate Wilkinson et al.")
    matches = pd.Series(False, index=anchor.index)
    for column in doi_columns:
        matches = matches | anchor[column].map(normalize_doi).eq(WILKINSON_DOI)
    if int(matches.sum()) != 1:
        raise RobustnessFailure("Expected exactly one Wilkinson DOI record in the frozen publication anchor.")
    excluded_index = anchor.index[matches][0]
    documents: list[str] = []
    abstract_flags: list[bool] = []
    for title, abstract in zip(anchor["title"], anchor["abstract"]):
        document, has_abstract = module.make_document_text(title, abstract)
        if not clean_text(document):
            raise RobustnessFailure("A frozen publication becomes empty after published anchor-phrase removal.")
        documents.append(document)
        abstract_flags.append(has_abstract)
    stopwords = sorted(set(module.ENGLISH_STOP_WORDS).union(module.CUSTOM_STOPWORDS))
    vectorizer = module.TfidfVectorizer(
        lowercase=True,
        stop_words=stopwords,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b",
        ngram_range=(1, 2),
        min_df=min_df,
        max_df=max_df,
        max_features=max_features,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform(documents)
    if matrix.shape[0] != len(anchor) or matrix.shape[1] == 0:
        raise RobustnessFailure("The leave-one-out TF--IDF reconstruction failed.")
    full_model = module.fit_nmf(matrix, 2, int(module.RANDOM_SEED) + 2, max_iter)
    retain_positions = np.array([position for position, index in enumerate(anchor.index) if index != excluded_index], dtype=int)
    loo_model = module.fit_nmf(matrix[retain_positions], 2, int(module.RANDOM_SEED) + 2, max_iter)

    required_assignment = {"n_topics", "id", "dominant_topic"}
    missing_assignment = sorted(required_assignment.difference(reference_assignments.columns))
    if missing_assignment:
        raise RobustnessFailure("Saved K=2 NMF assignments are missing required columns: " + ", ".join(missing_assignment))
    reference = reference_assignments.copy()
    reference["n_topics"] = pd.to_numeric(reference["n_topics"], errors="coerce")
    reference["dominant_topic"] = pd.to_numeric(reference["dominant_topic"], errors="coerce")
    reference["id"] = reference["id"].map(clean_text)
    reference = reference.loc[reference["n_topics"].eq(2)].copy()
    if len(reference) != len(anchor) or reference["id"].eq("").any() or reference["id"].duplicated().any() or set(reference["id"]) != set(anchor["id"]):
        raise RobustnessFailure("Saved K=2 assignments do not exactly reconcile to the frozen publication anchor.")
    if not set(reference["dominant_topic"].astype(int)).issubset({1, 2}):
        raise RobustnessFailure("Saved K=2 assignments contain an invalid dominant-topic label.")
    reference_topic_by_id = reference.set_index("id")["dominant_topic"].astype(int)
    reference_topics = anchor["id"].map(reference_topic_by_id).to_numpy(dtype=int) - 1
    full_weights = full_model.transform(matrix)
    full_shares = np.divide(full_weights, full_weights.sum(axis=1, keepdims=True), out=np.zeros_like(full_weights), where=full_weights.sum(axis=1, keepdims=True) > 0)
    full_topics = np.argmax(full_shares, axis=1)
    overlap = np.zeros((2, 2), dtype=int)
    for fitted_topic in range(2):
        for saved_topic in range(2):
            overlap[fitted_topic, saved_topic] = int(((full_topics == fitted_topic) & (reference_topics == saved_topic)).sum())
    full_indices, saved_indices = module.linear_sum_assignment(-overlap)
    full_to_saved = {int(fitted): int(saved) for fitted, saved in zip(full_indices, saved_indices)}
    remapped_full_topics = np.array([full_to_saved[int(topic)] for topic in full_topics], dtype=int)
    full_assignment_agreement = float((remapped_full_topics == reference_topics).mean())
    if full_assignment_agreement < 0.95:
        raise RobustnessFailure(
            f"The local K=2 reconstruction has only {full_assignment_agreement:.3f} dominant-assignment agreement with the saved K=2 output; stopping rather than mixing non-equivalent NMF runs."
        )
    similarities = module.cosine_similarity(full_model.components_, loo_model.components_)
    matched_full, matched_loo = module.linear_sum_assignment(-similarities)
    rows: list[dict[str, Any]] = []
    for fitted_full_topic, loo_topic in zip(matched_full, matched_loo):
        saved_topic = full_to_saved[int(fitted_full_topic)] + 1
        rows.append({
            "primary_n_topics": 2,
            "primary_topic": saved_topic,
            "leave_one_out_excluded_doi": WILKINSON_DOI,
            "leave_one_out_topic": int(loo_topic) + 1,
            "component_cosine_similarity": float(similarities[fitted_full_topic, loo_topic]),
            "full_K2_to_saved_K2_dominant_assignment_agreement": full_assignment_agreement,
            "full_corpus_records": len(anchor),
            "leave_one_out_records": len(retain_positions),
            "full_vocabulary_features": int(matrix.shape[1]),
            "vocabulary_rule": "TF--IDF vocabulary was fitted once on the full 144-publication corpus and retained for the 143-publication sensitivity fit.",
            "scope_limit": "K=2 only. This does not test or establish invariance of the primary K=3 heritage/preservation component.",
        })
    detail = pd.DataFrame(rows).sort_values("primary_topic").reset_index(drop=True)
    reproduction = pd.DataFrame([{
        "full_corpus_records": len(anchor),
        "excluded_records": 1,
        "leave_one_out_records": len(retain_positions),
        "excluded_doi": WILKINSON_DOI,
        "tfidf_features": int(matrix.shape[1]),
        "full_K2_to_saved_K2_dominant_assignment_agreement": full_assignment_agreement,
        "minimum_matched_component_cosine_similarity": float(detail["component_cosine_similarity"].min()),
        "maximum_matched_component_cosine_similarity": float(detail["component_cosine_similarity"].max()),
        "scope_limit": "K=2-only broad-structure sensitivity; no K=3 leave-one-out inference is made.",
    }])
    return detail, reproduction


def grant_sensitivity_comparison(diagnostics: pd.DataFrame, coefficients: pd.DataFrame) -> pd.DataFrame:
    diagnostic_by_label = diagnostics.set_index("model_label", drop=False)
    primary_label = "grant_primary__continuous_K3_shares__year_adjusted"
    if primary_label not in diagnostic_by_label.index:
        raise RobustnessFailure("Association diagnostics lack the primary grant model.")
    if clean_text(diagnostic_by_label.loc[primary_label, "model_status"]) != "fit":
        raise RobustnessFailure("The primary grant model is not certified as fit; sensitivity comparison cannot be anchored.")
    coefficient_keys = coefficients[["model_label", "term"]].astype(str)
    if coefficient_keys.duplicated().any():
        raise RobustnessFailure("Association coefficients contain duplicate model-label and term combinations.")
    coefficient_lookup = coefficients.set_index(["model_label", "term"], drop=False)
    rows: list[dict[str, Any]] = []
    for label, role in GRANT_MODEL_ROLES.items():
        if label not in diagnostic_by_label.index:
            raise RobustnessFailure(f"Association diagnostics lack required grant model: {label}")
        diagnostic = diagnostic_by_label.loc[label]
        status = clean_text(diagnostic["model_status"])
        for term in TARGET_GRANT_TERMS:
            current = coefficient_lookup.loc[(label, term)] if (label, term) in coefficient_lookup.index else None
            primary = coefficient_lookup.loc[(primary_label, term)] if (primary_label, term) in coefficient_lookup.index else None
            if primary is None:
                raise RobustnessFailure(f"Primary grant model lacks the required coefficient: {term}")
            coefficient = float(pd.to_numeric(current["coefficient_log_odds"], errors="raise")) if current is not None else None
            primary_coefficient = float(pd.to_numeric(primary["coefficient_log_odds"], errors="raise"))
            rows.append({
                "model_label": label,
                "robustness_role": role,
                "model_status": status,
                "term": term,
                "theme_shift_interpretation": "10 percentage-point shift toward Topic 1 versus Topic 2" if term.endswith("topic_1_share_per_10pp") else "10 percentage-point shift toward Topic 3 versus Topic 2",
                "n_publications": int(pd.to_numeric(diagnostic["n_publications"], errors="raise")),
                "n_grant_link_events": int(pd.to_numeric(diagnostic["n_events"], errors="raise")),
                "coefficient_log_odds": coefficient,
                "odds_ratio": float(pd.to_numeric(current["odds_ratio"], errors="raise")) if current is not None else None,
                "ci_95_odds_ratio_low": float(pd.to_numeric(current["ci_95_odds_ratio_low"], errors="raise")) if current is not None else None,
                "ci_95_odds_ratio_high": float(pd.to_numeric(current["ci_95_odds_ratio_high"], errors="raise")) if current is not None else None,
                "p_value": float(pd.to_numeric(current["p_value"], errors="raise")) if current is not None else None,
                "coefficient_direction": direction(coefficient),
                "primary_coefficient_log_odds": primary_coefficient,
                "primary_coefficient_direction": direction(primary_coefficient),
                "same_direction_as_primary": (direction(coefficient) == direction(primary_coefficient)) if coefficient is not None else None,
                "model_reason_if_not_fit": clean_text(diagnostic.get("reason")),
                "interpretive_boundary": "Conditional association in Dimensions-recorded grant links only; not a causal funding effect or institutional-selection estimate.",
            })
    return pd.DataFrame(rows)


def policy_window_accounting(diagnostics: pd.DataFrame, temporal_windows: pd.DataFrame) -> pd.DataFrame:
    diagnostic_by_label = diagnostics.set_index("model_label", drop=False)
    temporal_by_label = temporal_windows.set_index("analysis_sample", drop=False)
    rows: list[dict[str, Any]] = []
    for model_label, window_label in POLICY_MODEL_TO_WINDOW.items():
        if model_label not in diagnostic_by_label.index:
            raise RobustnessFailure(f"Association diagnostics lack required policy model: {model_label}")
        if window_label not in temporal_by_label.index:
            raise RobustnessFailure(f"Temporal audit lacks required policy window: {window_label}")
        diagnostic = diagnostic_by_label.loc[model_label]
        window = temporal_by_label.loc[window_label]
        model_n = int(pd.to_numeric(diagnostic["n_publications"], errors="raise"))
        model_events = int(pd.to_numeric(diagnostic["n_events"], errors="raise"))
        window_n = int(pd.to_numeric(window["n_final_publications"], errors="raise"))
        window_events = int(pd.to_numeric(window["n_policy_linked_publications"], errors="raise"))
        required_events = int(pd.to_numeric(diagnostic["required_minimum_events"], errors="raise"))
        status = clean_text(diagnostic["model_status"])
        if status not in {"fit", "not_fit"}:
            raise RobustnessFailure(f"Policy model has an unsupported status: {status}")
        if (model_n, model_events) != (window_n, window_events):
            raise RobustnessFailure(f"Policy association and temporal-window counts disagree for {window_label}.")
        rows.append({
            "policy_window": window_label,
            "association_model_label": model_label,
            "n_publications": model_n,
            "n_policy_linked_publications": model_events,
            "policy_linkage_rate_pct": float(pd.to_numeric(window["policy_linkage_rate_pct"], errors="raise")),
            "minimum_observed_policy_calendar_years": int(pd.to_numeric(window["minimum_observed_policy_calendar_years"], errors="raise")),
            "maximum_observed_policy_calendar_years": int(pd.to_numeric(window["maximum_observed_policy_calendar_years"], errors="raise")),
            "required_events_for_multivariable_model": required_events,
            "event_adequacy_passes": model_events >= required_events,
            "association_model_status": status,
            "withheld_model_reason": clean_text(diagnostic.get("reason")),
            "interpretive_boundary": "Policy-link outcomes are sparse Dimensions-recorded links. A withheld model is reported as a limitation, not replaced with an opportunistic sparse regression.",
        })
    return pd.DataFrame(rows)


def main() -> None:
    try:
        args = parse_args()
        if args.expected_publication_records < 1:
            raise ValueError("--expected-publication-records must be positive.")
        args = preflight_paths(args)
        nmf_module = load_nmf_module()
        nmf_manifest_file = nmf_manifest_path(args.nmf_output_dir)
        nmf_files = {
            "nmf_manifest": nmf_manifest_file,
            "topic_model_summary": args.nmf_output_dir / "topic_model_summary.csv",
            "topic_stability_detail": args.nmf_output_dir / "topic_stability_detail.csv",
            "topic_sizes": args.nmf_output_dir / "topic_sizes.csv",
            "nmf_validation_checks": args.nmf_output_dir / "validation_checks.csv",
            "saved_K2_assignments": args.nmf_output_dir / "publication_topic_assignments_k2.csv",
        }
        association_files = {
            "association_manifest": args.association_output_dir / "association_manifest.json",
            "association_coefficients": args.association_output_dir / "association_model_coefficients.csv",
            "association_diagnostics": args.association_output_dir / "association_model_diagnostics.csv",
        }
        temporal_files = {
            "temporal_manifest": args.temporal_output_dir / "temporal_audit_manifest.json",
            "policy_windows": args.temporal_output_dir / "policy_observation_window_samples.csv",
        }
        input_paths = {"publication_anchor": args.publication_anchor_file, **nmf_files, **association_files, **temporal_files}
        missing_inputs = [str(path) for path in input_paths.values() if not path.is_file()]
        if missing_inputs:
            raise FileNotFoundError("Missing required input file(s):\n" + "\n".join(missing_inputs))
        input_hashes = {name: sha256(path) for name, path in input_paths.items()}

        anchor = pd.read_pickle(args.publication_anchor_file).copy()
        nmf_manifest = read_json(nmf_files["nmf_manifest"], "NMF manifest")
        model_summary = read_csv(nmf_files["topic_model_summary"], {"n_topics", "bootstraps", "mean_component_cosine_similarity", "minimum_component_cosine_similarity", "mean_dominant_assignment_agreement", "minimum_dominant_assignment_agreement", "smallest_topic_share"}, "NMF model summary")
        stability_detail = read_csv(nmf_files["topic_stability_detail"], {"n_topics", "replicate", "full_topic", "component_cosine_similarity", "dominant_assignment_agreement_all_P", "sample_fraction", "sample_size"}, "NMF stability detail")
        topic_sizes = read_csv(nmf_files["topic_sizes"], {"n_topics", "dominant_topic", "n_publications", "pct_of_P"}, "NMF topic sizes")
        nmf_validation = read_csv(nmf_files["nmf_validation_checks"], {"check"}, "NMF validation checks")
        saved_K2_assignments = read_csv(nmf_files["saved_K2_assignments"], {"n_topics", "id", "dominant_topic"}, "Saved K=2 assignments")
        association_manifest = read_json(association_files["association_manifest"], "Association manifest")
        coefficients = read_csv(association_files["association_coefficients"], {"model_label", "outcome", "term", "coefficient_log_odds", "odds_ratio", "ci_95_odds_ratio_low", "ci_95_odds_ratio_high", "p_value"}, "Association coefficients")
        diagnostics = read_csv(association_files["association_diagnostics"], {"model_label", "outcome", "model_status", "n_publications", "n_events", "required_minimum_events", "reason"}, "Association diagnostics")
        temporal_manifest = read_json(temporal_files["temporal_manifest"], "Temporal audit manifest")
        temporal_windows = read_csv(temporal_files["policy_windows"], {"analysis_sample", "n_final_publications", "n_policy_linked_publications", "policy_linkage_rate_pct", "minimum_observed_policy_calendar_years", "maximum_observed_policy_calendar_years"}, "Policy-window table")

        if len(anchor) != args.expected_publication_records:
            raise RobustnessFailure(f"Expected {args.expected_publication_records} anchor publications; found {len(anchor)}.")
        if "retain_in_final_P" in anchor.columns and not anchor["retain_in_final_P"].map(bool_from).all():
            raise RobustnessFailure("Publication anchor includes a record outside final P.")
        if int(nmf_manifest.get("records", -1)) != args.expected_publication_records:
            raise RobustnessFailure("NMF manifest does not certify the expected 144-publication corpus.")
        topics_tested = {int(value) for value in nmf_manifest.get("topics_tested", [])}
        if topics_tested != EXPECTED_TOPICS:
            raise RobustnessFailure("NMF manifest must certify exactly the K=2, K=3, and K=4 candidate solutions.")
        stability_spec = nmf_manifest.get("stability", {})
        if int(stability_spec.get("bootstrap_replicates", -1)) != EXPECTED_BOOTSTRAPS or not np.isclose(float(stability_spec.get("publication_sample_fraction", np.nan)), EXPECTED_SAMPLE_FRACTION):
            raise RobustnessFailure("NMF manifest does not certify the expected eight 80% bootstrap replicates.")
        min_df, max_features, max_df, max_iter = required_nmf_configuration(nmf_manifest, nmf_module)
        if "failures" in nmf_validation.columns:
            failures = pd.to_numeric(nmf_validation["failures"], errors="coerce")
            if failures.isna().any() or not failures.eq(0).all():
                raise RobustnessFailure("NMF validation table contains a failed check.")
        elif "passed" in nmf_validation.columns:
            if not nmf_validation["passed"].map(bool_from).all():
                raise RobustnessFailure("NMF validation table contains a failed check.")
        else:
            raise RobustnessFailure("NMF validation table must contain either failures or passed.")

        for frame, column in ((model_summary, "n_topics"), (stability_detail, "n_topics"), (topic_sizes, "n_topics")):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame[column].isna().any():
                raise RobustnessFailure("NMF output contains a nonnumeric topic count.")
            frame[column] = frame[column].astype(int)
        model_summary = model_summary.loc[model_summary["n_topics"].isin(EXPECTED_TOPICS)].copy()
        if set(model_summary["n_topics"]) != EXPECTED_TOPICS or model_summary["n_topics"].duplicated().any():
            raise RobustnessFailure("NMF model summary must have exactly one row for K=2, K=3, and K=4.")
        stability_detail["full_topic"] = pd.to_numeric(stability_detail["full_topic"], errors="coerce")
        stability_detail["replicate"] = pd.to_numeric(stability_detail["replicate"], errors="coerce")
        if stability_detail[["full_topic", "replicate"]].isna().any().any():
            raise RobustnessFailure("NMF stability detail has nonnumeric topic or replicate fields.")
        stability_detail[["full_topic", "replicate"]] = stability_detail[["full_topic", "replicate"]].astype(int)
        expected_detail_rows = EXPECTED_BOOTSTRAPS * sum(EXPECTED_TOPICS)
        if len(stability_detail) != expected_detail_rows:
            raise RobustnessFailure(f"Expected {expected_detail_rows} NMF bootstrap component comparisons; found {len(stability_detail)}.")
        for k in EXPECTED_TOPICS:
            subset = stability_detail.loc[stability_detail["n_topics"].eq(k)]
            if len(subset) != EXPECTED_BOOTSTRAPS * k or set(subset["full_topic"]) != set(range(1, k + 1)):
                raise RobustnessFailure(f"NMF bootstrap comparisons do not reconcile for K={k}.")
        topic_sizes["dominant_topic"] = pd.to_numeric(topic_sizes["dominant_topic"], errors="coerce")
        topic_sizes["n_publications"] = pd.to_numeric(topic_sizes["n_publications"], errors="coerce")
        topic_sizes["pct_of_P"] = pd.to_numeric(topic_sizes["pct_of_P"], errors="coerce")
        if topic_sizes[["dominant_topic", "n_publications", "pct_of_P"]].isna().any().any():
            raise RobustnessFailure("NMF topic sizes contain nonnumeric values.")
        topic_sizes[["dominant_topic", "n_publications"]] = topic_sizes[["dominant_topic", "n_publications"]].astype(int)
        for k in EXPECTED_TOPICS:
            subset = topic_sizes.loc[topic_sizes["n_topics"].eq(k)]
            if len(subset) != k or set(subset["dominant_topic"]) != set(range(1, k + 1)) or int(subset["n_publications"].sum()) != args.expected_publication_records:
                raise RobustnessFailure(f"NMF hard-assignment sizes do not reconcile for K={k}.")

        if association_manifest.get("status") != "complete" or temporal_manifest.get("status") != "complete":
            raise RobustnessFailure("Association and temporal manifests must both be marked complete.")
        if int(temporal_manifest.get("policy_data_end_year", -1)) != 2026:
            raise RobustnessFailure("Temporal audit does not certify the frozen 2026 policy endpoint.")
        if diagnostics["model_label"].duplicated().any():
            raise RobustnessFailure("Association diagnostics contain duplicate model labels.")
        if not set(GRANT_MODEL_ROLES).issubset(set(diagnostics["model_label"])) or not set(POLICY_MODEL_TO_WINDOW).issubset(set(diagnostics["model_label"])):
            raise RobustnessFailure("Association diagnostics do not contain all predeclared grant and policy model labels.")

        component_stability = aggregate_component_stability(stability_detail, topic_sizes)
        model_summary["candidate_solution_role"] = model_summary["n_topics"].map({
            2: "coarsened_two-orientation_sensitivity",
            3: "primary_frozen_thematic_representation",
            4: "rejected_candidate_diagnostic",
        })
        candidate_summary = model_summary.sort_values("n_topics").copy()
        leave_one_out_detail, leave_one_out_reproduction = leave_one_out_k2(
            anchor=anchor, reference_assignments=saved_K2_assignments, module=nmf_module,
            min_df=min_df, max_features=max_features, max_df=max_df, max_iter=max_iter,
        )
        grant_comparison = grant_sensitivity_comparison(diagnostics, coefficients)
        policy_accounting = policy_window_accounting(diagnostics, temporal_windows)
        scope = pd.DataFrame([
            {
                "robustness_component": "NMF candidate and bootstrap stability",
                "status": "completed",
                "evidence_source": "K=2, K=3, K=4 model summaries, hard-assignment sizes, and eight 80% bootstrap replicates",
                "what_is_supported": "The primary K=3 choice and its component-specific bootstrap pattern can be transparently reported.",
                "what_is_not_supported": "Bootstrap values are not confidence intervals; K=3 components should not be called equally invariant.",
            },
            {
                "robustness_component": "Wilkinson manual-addition leave-one-out",
                "status": "completed_with_K2_only_scope",
                "evidence_source": "K=2 NMF refit after excluding DOI 10.1038/sdata.2016.18, using the full-corpus TF--IDF vocabulary",
                "what_is_supported": "The broad K=2 structure can be compared after exclusion of the documented manual addition.",
                "what_is_not_supported": "No K=3 leave-one-out result is produced; do not claim the heritage/preservation component is unchanged.",
            },
            {
                "robustness_component": "Low NMF-assignment-margin grant sensitivity",
                "status": "completed",
                "evidence_source": "Predeclared grant model excluding records flagged below the 0.10 top-two-share margin",
                "what_is_supported": "Direction and estimate comparison with the primary grant model.",
                "what_is_not_supported": "The sensitivity cannot be used to select another topic solution or delete inconvenient records.",
            },
            {
                "robustness_component": "Citation-adjusted grant sensitivity",
                "status": "completed_when_fit",
                "evidence_source": "Predeclared grant model adding observed log1p citation count",
                "what_is_supported": "A descriptive specification sensitivity.",
                "what_is_not_supported": "Citation adjustment is not a primary causal control and cannot identify a funding effect.",
            },
            {
                "robustness_component": "Policy-observation-window accounting",
                "status": "completed",
                "evidence_source": "Predeclared 2022 primary, 2021 longer-window, and all-publication sensitivity cohorts",
                "what_is_supported": "The observed policy-link event counts and the decision to withhold inadequate regressions.",
                "what_is_not_supported": "Sparse policy-link outcomes cannot support multivariable policy association estimates or claims about policy impact.",
            },
            {
                "robustness_component": "FAIR keyword or concept-family indicator",
                "status": "not_used_by_predeclared_design",
                "evidence_source": "Frozen analysis specification",
                "what_is_supported": "Primary analysis uses outcome-blind continuous K=3 NMF shares without a redundant post hoc dictionary.",
                "what_is_not_supported": "No indicator robustness result exists because no FAIR dictionary indicator was introduced.",
            },
        ])
        policy_status_matches_rule = bool((policy_accounting["association_model_status"].eq("not_fit") == ~policy_accounting["event_adequacy_passes"]).all())
        validation = pd.DataFrame([
            {"check": "NMF_expected_144_record_corpus", "passed": True, "detail": ""},
            {"check": "NMF_candidates_K2_K3_K4_and_eight_bootstraps_certified", "passed": True, "detail": ""},
            {"check": "NMF_validation_checks_passed", "passed": True, "detail": ""},
            {"check": "Wilkinson_DOI_present_once_and_K2_leave_one_out_completed", "passed": True, "detail": "The K=2-only scope is explicitly retained."},
            {"check": "full_K2_reconstruction_matches_saved_dominant_assignments_at_or_above_0_95", "passed": True, "detail": str(float(leave_one_out_reproduction.iloc[0]["full_K2_to_saved_K2_dominant_assignment_agreement"]))},
            {"check": "primary_grant_model_fit", "passed": True, "detail": ""},
            {"check": "policy_window_counts_reconcile_between_association_and_temporal_stages", "passed": True, "detail": ""},
            {"check": "policy_event_adequacy_rule_reported_without_sparse_model_substitution", "passed": policy_status_matches_rule, "detail": ""},
            {"check": "no_unplanned_FAIR_keyword_indicator_used", "passed": True, "detail": ""},
            {"check": "final_result", "passed": policy_status_matches_rule, "detail": "Robustness evidence consolidated without selecting a result because it is favorable."},
        ])
        if not policy_status_matches_rule:
            raise RobustnessFailure("A policy association status is inconsistent with the frozen event-adequacy rule.")
        outputs = {
            "nmf_candidate_stability_summary.csv": candidate_summary,
            "nmf_component_stability_summary.csv": component_stability,
            "wilkinson_leave_one_out_K2_component_similarity.csv": leave_one_out_detail,
            "wilkinson_leave_one_out_K2_reproduction_summary.csv": leave_one_out_reproduction,
            "grant_association_sensitivity_comparison.csv": grant_comparison,
            "policy_window_event_adequacy_accounting.csv": policy_accounting,
            "robustness_scope_and_limitations.csv": scope,
            "robustness_validation_checks.csv": validation,
        }
        for filename, frame in outputs.items():
            atomic_write_csv(args.output_dir / filename, frame)
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "input_files": {name: {"path": str(path), "sha256": input_hashes[name]} for name, path in input_paths.items()},
            "frozen_primary_thematic_representation": "Continuous K=3 NMF shares: Topic 1 and Topic 3 relative to Topic 2 in association models.",
            "wilkinson_sensitivity_scope": "K=2 only. The script refits full and leave-one-out K=2 NMF models with the primary-corpus vocabulary; it does not establish stability of the K=3 heritage/preservation component.",
            "FAIR_keyword_indicator": "Not used by the predeclared primary design; no post hoc dictionary robustness analysis is performed.",
            "policy_window_design": "2026 data endpoint; through-2022 primary, through-2021 longer-window robustness, all-final-P sensitivity.",
            "interpretive_boundary": "Robustness comparisons are descriptive model and record-linkage checks. Association results are not causal estimates; sparse policy links do not support a multivariable policy-link analysis.",
            "data_boundary": "All robustness output tables and the manifest are protected local data and must not be committed to GitHub.",
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(frame)} for name, frame in outputs.items()},
        }
        atomic_write_json(args.output_dir / "robustness_manifest.json", manifest)

        primary_policy = policy_accounting.loc[policy_accounting["policy_window"].eq("primary_policy_window")].iloc[0]
        K3_specialist = component_stability.loc[(component_stability["n_topics"].eq(3)) & (component_stability["full_topic"].eq(3))].iloc[0]
        loo_row = leave_one_out_reproduction.iloc[0]
        print("FAIRIFICATION ROBUSTNESS EVIDENCE CONSOLIDATION: PASS")
        print(f"NMF CANDIDATE SOLUTIONS CERTIFIED: {', '.join(str(value) for value in sorted(EXPECTED_TOPICS))}")
        print(f"K=3 HERITAGE/PRESERVATION MINIMUM BOOTSTRAP COSINE: {float(K3_specialist['minimum_component_cosine_similarity']):.6f}")
        print(f"WILKINSON LEAVE-ONE-OUT: K=2 only; minimum matched cosine {float(loo_row['minimum_matched_component_cosine_similarity']):.6f}")
        print(f"FULL K=2 RECONSTRUCTION AGREEMENT WITH SAVED K=2: {float(loo_row['full_K2_to_saved_K2_dominant_assignment_agreement']):.6f}")
        print(f"GRANT SENSITIVITY MODELS ACCOUNTED FOR: {len(GRANT_MODEL_ROLES)}")
        print(f"PRIMARY POLICY WINDOW: {int(primary_policy['n_policy_linked_publications'])} events / {int(primary_policy['n_publications'])} publications; model {primary_policy['association_model_status']}")
        print("FAIR KEYWORD INDICATOR: NOT USED BY PREDECLARED DESIGN")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'robustness_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

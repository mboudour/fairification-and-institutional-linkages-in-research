#!/usr/bin/env python3
# Data-free FAIRification adaptation. Inputs and outputs belong in ignored local directories.
"""Publication-only topic-modeling diagnostic for the FAIRification corpus.

Run from the repository root:
    python code/thematic/publication_topic_model_diagnostic.py

Install the only additional dependency if needed:
    python -m pip install scikit-learn

Purpose
-------
This is a corpus-diagnostic analysis. It asks whether the publication corpus
supports broad, stable, interpretable topic structure, including a possible
bipolar (two-topic) decomposition. It does NOT use grants, policy documents,
institutions, countries, citations, linkages, or any outcome variable.

Method
------
The script fits non-negative matrix factorization (NMF) topic models to TF-IDF
features from publication titles plus available abstracts. This is a
single-mode text analysis; it does not use embeddings, UMAP, network-node
clustering, or policy text. By default, K=2, K=3, and K=4 are evaluated.
Stability is tested through publication bootstrap samples, then each bootstrap
topic set is matched to the full-corpus solution by cosine similarity.

Interpretation
--------------
The outputs are diagnostic. A two-topic solution is a potentially useful
substantive dipole only if both topics are large, interpretable, and stable.
Higher-topic solutions are supplied to reveal whether a broader framework is
more appropriate. No automatic macro-grouping is imposed: any grouping of
topics must be substantively declared after inspecting the topic terms and
record samples, before grants/policy/institution/country outcomes are read.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from scipy.optimize import linear_sum_assignment
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Install it with: python -m pip install scikit-learn"
    ) from exc

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_PUBLICATION_FILE = PROJECT_ROOT / "data" / "publication_anchor_final.pkl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "derived_outputs" / "publication_topic_model_diagnostic"

RANDOM_SEED = 20261024
DEFAULT_TOPICS = (2, 3, 4)
DEFAULT_BOOTSTRAPS = 8
DEFAULT_SAMPLE_FRACTION = 0.80
DEFAULT_MAX_FEATURES = 15000
DEFAULT_MIN_DF = 2
DEFAULT_MAX_ITER = 300
TOP_TERMS = 20
REVIEW_DOCUMENTS_PER_TOPIC = 25

# Only generic FAIR retrieval anchors are removed so topics are not mere
# repetitions of the search scope. Substantive terms such as metadata,
# repository, ontology, preservation, governance, workflow, and stewardship
# remain available to distinguish the corpus' orientations.
ANCHOR_PHRASES = (
    r"\bfairification\b",
    r"\bfair\s+data\b",
    r"\bfair\s+principles?\b",
    r"\bfair\b",
    r"\bfindable\b",
    r"\baccessible\b",
    r"\binteroperable\b",
    r"\breusable\b",
)

# Generic scholarly terms are removed as stopwords. They are not substantive
# candidates for a bipolar framework.
CUSTOM_STOPWORDS = {
    "abstract", "aim", "analysis", "analyses", "approach", "article", "articles",
    "author", "authors", "background", "case", "cases", "conclusion", "conclusions",
    "data", "dataset", "datasets", "design", "discussion", "effect", "effects",
    "fair", "fairification", "findable", "accessible", "interoperable", "reusable",
    "finding", "findings", "method", "methods", "model", "models", "objective",
    "objectives", "paper", "papers", "principle", "principles", "research", "result",
    "results", "review", "study", "studies", "system", "systems", "use", "using", "used",
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-file", type=Path, default=DEFAULT_PUBLICATION_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--topics",
        default=",".join(str(value) for value in DEFAULT_TOPICS),
        help="Comma-separated topic counts, for example 2,3,4,5,6.",
    )
    parser.add_argument("--bootstraps", type=int, default=DEFAULT_BOOTSTRAPS)
    parser.add_argument("--sample-fraction", type=float, default=DEFAULT_SAMPLE_FRACTION)
    parser.add_argument("--max-features", type=int, default=DEFAULT_MAX_FEATURES)
    parser.add_argument("--min-df", type=int, default=DEFAULT_MIN_DF)
    parser.add_argument("--max-iter", type=int, default=DEFAULT_MAX_ITER)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def remove_anchor_phrases(text: str) -> str:
    result = text
    for phrase in ANCHOR_PHRASES:
        result = re.sub(phrase, " ", result, flags=re.IGNORECASE)
    return result


def make_document_text(title: Any, abstract: Any) -> tuple[str, bool]:
    title_text = clean_text(title)
    abstract_text = clean_text(abstract)
    # Repeating the title once gives it modest additional weight while retaining
    # the abstract as the main evidence when it is available.
    raw = " ".join(part for part in [title_text, title_text, abstract_text] if part)
    return remove_anchor_phrases(raw), bool(abstract_text)


def parse_topic_counts(text: str) -> list[int]:
    try:
        values = [int(value.strip()) for value in text.split(",") if value.strip()]
    except ValueError as exc:
        raise SystemExit("--topics must be comma-separated positive integers, e.g. 2,3,4,5,6") from exc
    if not values or any(value < 2 for value in values) or len(set(values)) != len(values):
        raise SystemExit("--topics must contain distinct integers, each at least 2.")
    return values


def normalized_entropy(weights: np.ndarray) -> np.ndarray:
    row_sums = weights.sum(axis=1, keepdims=True)
    proportions = np.divide(weights, row_sums, out=np.zeros_like(weights), where=row_sums > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        logp = np.where(proportions > 0, np.log(proportions), 0.0)
    entropy = -(proportions * logp).sum(axis=1)
    return entropy / math.log(weights.shape[1])


def fit_nmf(matrix: Any, n_topics: int, random_state: int, max_iter: int) -> NMF:
    model = NMF(
        n_components=n_topics,
        init="nndsvda",
        solver="cd",
        beta_loss="frobenius",
        max_iter=max_iter,
        random_state=random_state,
        l1_ratio=0.0,
        alpha_W=0.0,
        alpha_H=0.0,
    )
    model.fit(matrix)
    return model


def topic_terms(model: NMF, terms: np.ndarray, n_topics: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for topic_index, weights in enumerate(model.components_, start=1):
        top_indices = np.argsort(weights)[::-1][:TOP_TERMS]
        for rank, term_index in enumerate(top_indices, start=1):
            rows.append({
                "n_topics": n_topics,
                "topic": topic_index,
                "rank": rank,
                "term": str(terms[term_index]),
                "term_weight": float(weights[term_index]),
            })
    return pd.DataFrame(rows)


def full_model_outputs(
    publications: pd.DataFrame,
    matrix: Any,
    model: NMF,
    terms: np.ndarray,
    n_topics: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    weights = model.transform(matrix)
    weight_sums = weights.sum(axis=1, keepdims=True)
    shares = np.divide(weights, weight_sums, out=np.zeros_like(weights), where=weight_sums > 0)
    dominant = np.argmax(shares, axis=1) + 1
    dominant_share = np.max(shares, axis=1)
    entropy = normalized_entropy(weights)

    assignments = publications[["id", "title", "year", "has_abstract"]].copy()
    assignments.insert(0, "n_topics", n_topics)
    assignments["dominant_topic"] = dominant
    assignments["dominant_topic_share"] = dominant_share
    assignments["normalized_topic_entropy"] = entropy
    for index in range(n_topics):
        assignments[f"topic_{index + 1}_share"] = shares[:, index]

    sizes = (
        assignments.groupby("dominant_topic", as_index=False)
        .agg(
            n_publications=("id", "size"),
            pct_of_P=("id", lambda values: 100 * len(values) / len(assignments)),
            mean_dominant_topic_share=("dominant_topic_share", "mean"),
            median_dominant_topic_share=("dominant_topic_share", "median"),
            mean_normalized_topic_entropy=("normalized_topic_entropy", "mean"),
        )
        .sort_values("dominant_topic")
        .reset_index(drop=True)
    )
    sizes.insert(0, "n_topics", n_topics)

    terms_table = topic_terms(model, terms, n_topics)
    top_topic_terms = (
        terms_table.sort_values(["topic", "rank"])
        .groupby("topic")["term"]
        .apply(lambda values: "; ".join(values.head(10)))
        .rename("top_10_terms")
        .reset_index()
    )
    sizes = sizes.merge(top_topic_terms, left_on="dominant_topic", right_on="topic", how="left", validate="one_to_one").drop(columns="topic")

    summary = {
        "n_topics": n_topics,
        "reconstruction_error": float(model.reconstruction_err_),
        "mean_dominant_topic_share": float(dominant_share.mean()),
        "median_dominant_topic_share": float(np.median(dominant_share)),
        "share_dominant_topic_at_least_0_50": float((dominant_share >= 0.50).mean()),
        "share_dominant_topic_at_least_0_60": float((dominant_share >= 0.60).mean()),
        "mean_normalized_topic_entropy": float(entropy.mean()),
        "smallest_topic_share": float(sizes["pct_of_P"].min() / 100),
        "largest_topic_share": float(sizes["pct_of_P"].max() / 100),
    }
    return assignments, sizes, terms_table, summary


def bootstrap_stability(
    matrix: Any,
    full_model: NMF,
    full_assignments: np.ndarray,
    n_topics: int,
    n_bootstraps: int,
    sample_fraction: float,
    max_iter: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rng = np.random.default_rng(RANDOM_SEED + n_topics)
    n_documents = matrix.shape[0]
    sample_size = int(math.floor(n_documents * sample_fraction))
    if sample_size < n_topics * 10:
        raise SystemExit("Bootstrap sample is too small for the requested number of topics.")

    rows: list[dict[str, Any]] = []
    full_components = full_model.components_
    for replicate in range(1, n_bootstraps + 1):
        sampled = np.sort(rng.choice(n_documents, size=sample_size, replace=False))
        bootstrap_model = fit_nmf(matrix[sampled], n_topics, RANDOM_SEED + 1000 * n_topics + replicate, max_iter)
        similarity = cosine_similarity(full_components, bootstrap_model.components_)
        full_indices, bootstrap_indices = linear_sum_assignment(-similarity)
        mapping = {int(bootstrap): int(full) for full, bootstrap in zip(full_indices, bootstrap_indices)}
        matched_similarities = {int(full): float(similarity[full, bootstrap]) for full, bootstrap in zip(full_indices, bootstrap_indices)}

        bootstrap_weights_all = bootstrap_model.transform(matrix)
        raw_assignments = np.argmax(bootstrap_weights_all, axis=1)
        mapped_assignments = np.array([mapping[int(value)] for value in raw_assignments])
        assignment_agreement = float((mapped_assignments == full_assignments).mean())
        for topic_index in range(n_topics):
            rows.append({
                "n_topics": n_topics,
                "replicate": replicate,
                "full_topic": topic_index + 1,
                "matched_bootstrap_topic": int(next(bootstrap for bootstrap, full in mapping.items() if full == topic_index)) + 1,
                "component_cosine_similarity": matched_similarities[topic_index],
                "dominant_assignment_agreement_all_P": assignment_agreement,
                "sample_fraction": sample_fraction,
                "sample_size": sample_size,
            })
    detail = pd.DataFrame(rows)
    summary = {
        "n_topics": n_topics,
        "bootstraps": n_bootstraps,
        "mean_component_cosine_similarity": float(detail["component_cosine_similarity"].mean()),
        "minimum_component_cosine_similarity": float(detail["component_cosine_similarity"].min()),
        "mean_dominant_assignment_agreement": float(detail["dominant_assignment_agreement_all_P"].mean()),
        "minimum_dominant_assignment_agreement": float(detail["dominant_assignment_agreement_all_P"].min()),
    }
    return detail, summary


def review_samples(assignments: pd.DataFrame, n_topics: int) -> pd.DataFrame:
    rows = []
    for topic in range(1, n_topics + 1):
        score_col = f"topic_{topic}_share"
        sample = assignments.sort_values([score_col, "id"], ascending=[False, True]).head(REVIEW_DOCUMENTS_PER_TOPIC).copy()
        sample.insert(1, "topic", topic)
        sample.insert(2, "topic_share", sample[score_col])
        rows.append(sample[["n_topics", "topic", "topic_share", "id", "year", "title", "has_abstract", "dominant_topic", "dominant_topic_share", "normalized_topic_entropy"]])
    return pd.concat(rows, ignore_index=True)


def validate_inputs(publications: pd.DataFrame, topics: list[int]) -> pd.DataFrame:
    checks = []
    checks.append({"check": "Publication IDs are unique", "failures": int(publications["id"].astype(str).duplicated().sum())})
    checks.append({"check": "Every publication has a nonempty title", "failures": int(publications["title"].map(clean_text).eq("").sum())})
    checks.append({"check": "Topic counts are smaller than document count", "failures": int(sum(value >= len(publications) for value in topics))})
    return pd.DataFrame(checks)


def main() -> None:
    args = parse_args()
    topics = parse_topic_counts(args.topics)
    publication_file = args.publication_file.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not publication_file.is_file():
        raise SystemExit(f"Publication file not found: {publication_file}")
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise SystemExit(f"Output directory already contains files: {output_dir}\nUse --overwrite only if you intend to replace it.")
    if not 0.50 <= args.sample_fraction < 1.0:
        raise SystemExit("--sample-fraction must be at least 0.50 and below 1.0.")
    if args.bootstraps < 5:
        raise SystemExit("--bootstraps must be at least 5.")

    publications = pd.read_pickle(publication_file).copy()
    required = ["id", "title", "abstract", "year"]
    missing = [column for column in required if column not in publications.columns]
    if missing:
        raise SystemExit("Publication file is missing required field(s): " + ", ".join(missing))
    if "retain_in_final_P" in publications.columns and not publications["retain_in_final_P"].astype(bool).all():
        raise SystemExit("Input contains a record outside the retained publication anchor.")
    publications["id"] = publications["id"].map(clean_text)
    publications["title"] = publications["title"].map(clean_text)
    publications["abstract"] = publications["abstract"].map(clean_text)
    validation = validate_inputs(publications, topics)
    if validation["failures"].sum() != 0:
        raise SystemExit("Input validation failed. No topic-model output was created.\n" + validation.to_string(index=False))

    documents: list[str] = []
    abstract_flags: list[bool] = []
    for title, abstract in zip(publications["title"], publications["abstract"]):
        document, has_abstract = make_document_text(title, abstract)
        documents.append(document)
        abstract_flags.append(has_abstract)
    publications["has_abstract"] = abstract_flags
    if any(not document.strip() for document in documents):
        raise SystemExit("At least one document is empty after anchor-phrase removal. Stopping.")

    stopwords = sorted(set(ENGLISH_STOP_WORDS).union(CUSTOM_STOPWORDS))
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words=stopwords,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b",
        ngram_range=(1, 2),
        min_df=args.min_df,
        max_df=0.80,
        max_features=args.max_features,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform(documents)
    if matrix.shape[1] < max(topics) * 25:
        raise SystemExit(
            f"Vocabulary too small ({matrix.shape[1]} features) for the requested topic counts. "
            "Lower --min-df or reduce --topics."
        )
    terms = vectorizer.get_feature_names_out()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_summaries: list[dict[str, Any]] = []
    all_sizes: list[pd.DataFrame] = []
    all_terms: list[pd.DataFrame] = []
    all_stability_detail: list[pd.DataFrame] = []
    all_stability_summary: list[dict[str, Any]] = []
    all_samples: list[pd.DataFrame] = []
    selected_assignments: dict[int, pd.DataFrame] = {}

    for n_topics in topics:
        print(f"Fitting {n_topics}-topic NMF model and {args.bootstraps} bootstrap stability replicates ...")
        full_model = fit_nmf(matrix, n_topics, RANDOM_SEED + n_topics, args.max_iter)
        assignments, sizes, terms_table, summary = full_model_outputs(publications, matrix, full_model, terms, n_topics)
        full_assignments = assignments["dominant_topic"].to_numpy(dtype=int) - 1
        stability_detail, stability_summary = bootstrap_stability(
            matrix,
            full_model,
            full_assignments,
            n_topics,
            args.bootstraps,
            args.sample_fraction,
            args.max_iter,
        )
        all_summaries.append(summary)
        all_sizes.append(sizes)
        all_terms.append(terms_table)
        all_stability_detail.append(stability_detail)
        all_stability_summary.append(stability_summary)
        all_samples.append(review_samples(assignments, n_topics))
        selected_assignments[n_topics] = assignments

    model_summary = pd.DataFrame(all_summaries).sort_values("n_topics")
    stability_summary = pd.DataFrame(all_stability_summary).sort_values("n_topics")
    model_summary = model_summary.merge(stability_summary, on="n_topics", how="left", validate="one_to_one")
    topic_sizes = pd.concat(all_sizes, ignore_index=True)
    topic_terms_df = pd.concat(all_terms, ignore_index=True)
    stability_detail_df = pd.concat(all_stability_detail, ignore_index=True)
    review_samples_df = pd.concat(all_samples, ignore_index=True)

    # This is an empirical screen, not a declaration that k=2 is substantively valid.
    bipole = model_summary[model_summary["n_topics"] == 2].copy()
    if bipole.empty:
        bipole_assessment = pd.DataFrame()
    else:
        bipole["both_topics_at_least_30pct"] = bipole["smallest_topic_share"] >= 0.30
        bipole["at_least_70pct_dominant_share_at_least_0_60"] = bipole["share_dominant_topic_at_least_0_60"] >= 0.70
        bipole["mean_component_similarity_at_least_0_75"] = bipole["mean_component_cosine_similarity"] >= 0.75
        bipole["mean_assignment_agreement_at_least_0_75"] = bipole["mean_dominant_assignment_agreement"] >= 0.75
        bipole["automatic_screen_status"] = np.where(
            bipole[["both_topics_at_least_30pct", "at_least_70pct_dominant_share_at_least_0_60", "mean_component_similarity_at_least_0_75", "mean_assignment_agreement_at_least_0_75"]].all(axis=1),
            "passes_minimum_coverage_and_stability_screen__requires_substantive_human_interpretation",
            "does_not_pass_minimum_coverage_and_stability_screen",
        )
        bipole_assessment = bipole

    text_audit = pd.DataFrame([
        {"metric": "publications", "value": int(len(publications))},
        {"metric": "publications_with_available_abstract", "value": int(publications["has_abstract"].sum())},
        {"metric": "publications_title_only", "value": int((~publications["has_abstract"]).sum())},
        {"metric": "title_plus_available_abstract_documents", "value": int(len(documents))},
        {"metric": "tfidf_features", "value": int(matrix.shape[1])},
        {"metric": "tfidf_nonzero_entries", "value": int(matrix.nnz)},
        {"metric": "anchor_phrases_removed", "value": "; ".join(ANCHOR_PHRASES)},
        {"metric": "custom_stopwords_removed", "value": "; ".join(sorted(CUSTOM_STOPWORDS))},
    ])
    validation = pd.concat([
        validation,
        pd.DataFrame([
            {"check": "TF-IDF matrix has one row per publication", "failures": int(matrix.shape[0] != len(publications))},
            {"check": "TF-IDF vocabulary is nonempty", "failures": int(matrix.shape[1] == 0)},
            {"check": "Every topic model has all requested topic assignments", "failures": int(sum(len(frame) != len(publications) for frame in selected_assignments.values()))},
            {"check": "Every stability run completed", "failures": int(len(stability_detail_df) != args.bootstraps * sum(topics))},
        ]),
    ], ignore_index=True)
    if validation["failures"].sum() != 0:
        raise SystemExit("Internal validation failed. No topic-model outputs were certified.\n" + validation.to_string(index=False))

    model_summary.to_csv(output_dir / "topic_model_summary.csv", index=False)
    stability_summary.to_csv(output_dir / "topic_stability_summary.csv", index=False)
    stability_detail_df.to_csv(output_dir / "topic_stability_detail.csv", index=False)
    topic_sizes.to_csv(output_dir / "topic_sizes.csv", index=False)
    topic_terms_df.to_csv(output_dir / "topic_terms.csv", index=False)
    review_samples_df.to_csv(output_dir / "topic_review_samples.csv", index=False)
    bipole_assessment.to_csv(output_dir / "bipole_screen.csv", index=False)
    text_audit.to_csv(output_dir / "text_corpus_audit.csv", index=False)
    validation.to_csv(output_dir / "validation_checks.csv", index=False)

    # The full record-level assignment tables are retained locally for later
    # interpretation and institutional/country stratification, but are not
    # required for the initial upload.
    for n_topics, assignments in selected_assignments.items():
        assignments.to_pickle(output_dir / f"publication_topic_assignments_k{n_topics}.pkl")
        assignments.to_csv(output_dir / f"publication_topic_assignments_k{n_topics}.csv", index=False)

    with pd.ExcelWriter(output_dir / "topic_model_diagnostic.xlsx", engine="openpyxl") as writer:
        text_audit.to_excel(writer, sheet_name="text_audit", index=False)
        model_summary.to_excel(writer, sheet_name="model_summary", index=False)
        bipole_assessment.to_excel(writer, sheet_name="bipole_screen", index=False)
        stability_summary.to_excel(writer, sheet_name="stability_summary", index=False)
        topic_sizes.to_excel(writer, sheet_name="topic_sizes", index=False)
        topic_terms_df.to_excel(writer, sheet_name="topic_terms", index=False)
        review_samples_df.to_excel(writer, sheet_name="review_samples", index=False)
        validation.to_excel(writer, sheet_name="validation", index=False)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Publication-only, outcome-blind diagnostic of broad, stable, interpretable FAIRification topic structure and possible bipolar decomposition.",
        "input": str(publication_file),
        "unit_of_analysis": "publication title plus available abstract",
        "records": int(len(publications)),
        "topics_tested": topics,
        "text_representation": {
            "model": "TF-IDF",
            "ngram_range": [1, 2],
            "min_df": args.min_df,
            "max_df": 0.80,
            "max_features": args.max_features,
            "title_repetition": 2,
            "anchor_phrases_removed": list(ANCHOR_PHRASES),
            "custom_stopwords_removed": sorted(CUSTOM_STOPWORDS),
        },
        "topic_model": {
            "method": "NMF",
            "init": "nndsvda",
            "max_iter": args.max_iter,
            "random_seed": RANDOM_SEED,
        },
        "stability": {
            "bootstrap_replicates": args.bootstraps,
            "publication_sample_fraction": args.sample_fraction,
            "matching": "Hungarian maximum-cosine matching of bootstrap topics to full-corpus topics",
            "assignment_stability": "dominant-topic agreement over all publications after matched-topic relabeling",
        },
        "outcome_exclusion": "No grants, policy documents, institutions, countries, citations, linkage variables, or outcomes enter topic construction, selection, or stability testing.",
        "interpretive_boundary": "The k=2 screen is necessary but not sufficient for a substantive dipole. Human review of topic terms and record samples is required before any topic grouping is declared or linked to institutional/country analysis.",
        "output_files": [
            "topic_model_diagnostic.xlsx",
            "topic_model_summary.csv",
            "topic_stability_summary.csv",
            "topic_stability_detail.csv",
            "topic_sizes.csv",
            "topic_terms.csv",
            "topic_review_samples.csv",
            "bipole_screen.csv",
            "text_corpus_audit.csv",
            "validation_checks.csv",
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Publication-only topic-model diagnostic completed.")
    print(f"Output directory: {output_dir}")
    print(model_summary.to_string(index=False))
    if not bipole_assessment.empty:
        print("\nTwo-topic diagnostic screen:")
        print(bipole_assessment.to_string(index=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate local-only institution and country landscape figures for FAIRification.

This script accepts one completed output directory from
`19_restore_institution_country_landscapes.py`; it verifies the Stage-19
manifest, hashes, and row counts before reading any table. It then creates two
supplementary figures comparable to the institution/country material in the
prior AI--mental-health study.

Policy-issuer landscapes are not plotted because their publication coverage is
sparse. This display decision is documented in the manuscript's TeX captions;
it does not imply that policy documents or issuer attributes are absent.

Named organizations and countries are protected local data. Both input and
output directories must be outside this repository's Git worktree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCRIPT_VERSION = "20_generate_institution_country_figures_2.2"
REQUIRED_RESTORATION_STAGE = "19_restore_institution_country_landscapes_1.0"
REQUIRED_FILES = {
    "theme_institution_representation.csv",
    "theme_country_representation.csv",
    "theme_role_scope_summary.csv",
    "view_definitions.csv",
}
RELATIONS = (
    ("P_PI_affiliation", "A. Publication affiliations", "Blues"),
    ("P_G_GI_funder", "B. Grant funders via P--G", "Greens"),
    ("P_D_DI_issuer", "C. Policy issuers via P--D", "Purples"),
)


class FigureGenerationFailure(RuntimeError):
    """Raised when a proposed named landscape cannot be traced to Stage 19."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restoration-dir", type=Path, required=True, help="Completed Stage-19 output directory.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=8)
    return parser.parse_args()


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def repository_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preflight(args: argparse.Namespace) -> argparse.Namespace:
    args.restoration_dir = resolved(args.restoration_dir)
    args.output_dir = resolved(args.output_dir)
    if not args.restoration_dir.is_dir() or args.restoration_dir.is_symlink():
        raise FileNotFoundError(f"Completed Stage-19 output directory does not exist or is unsafe: {args.restoration_dir}")
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must not already exist: {args.output_dir}")
    if args.top_n < 1:
        raise ValueError("--top-n must be positive.")
    repo = repository_root()
    if repo is not None and (is_within(args.restoration_dir, repo) or is_within(args.output_dir, repo)):
        raise ValueError(f"Named input/output directories must be outside the Git worktree: {repo}")
    if is_within(args.output_dir, args.restoration_dir) or is_within(args.restoration_dir, args.output_dir):
        raise ValueError("Figure output directory must not contain, or be contained by, the Stage-19 output directory.")
    return args


def require_columns(frame: pd.DataFrame, label: str, columns: set[str]) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise FigureGenerationFailure(f"{label} is missing required columns: {', '.join(missing)}")


def require_finite_percentage(frame: pd.DataFrame, field: str, label: str) -> None:
    values = pd.to_numeric(frame[field], errors="coerce")
    if values.isna().any() or (~np.isfinite(values)).any() or ((values < -1e-9) | (values > 100 + 1e-9)).any():
        raise FigureGenerationFailure(f"{label} has an invalid percentage field: {field}")
    frame[field] = values.astype(float)


def require_unique(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    if frame.duplicated(subset=columns).any():
        raise FigureGenerationFailure(f"{label} contains duplicate rows for {', '.join(columns)}.")


def load_completed_restoration(restoration_dir: Path) -> tuple[dict[str, Any], dict[str, pd.DataFrame], str]:
    manifest_path = restoration_dir / "institution_country_restoration_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FigureGenerationFailure("Stage-19 manifest is missing or unsafe.")
    raw_manifest = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as error:
        raise FigureGenerationFailure("Stage-19 manifest is not valid JSON.") from error
    if manifest.get("stage") != REQUIRED_RESTORATION_STAGE or manifest.get("status") != "complete":
        raise FigureGenerationFailure("Figures require a completed, compatible Stage-19 restoration manifest.")
    output_files = manifest.get("output_files")
    if not isinstance(output_files, dict) or not REQUIRED_FILES.issubset(output_files):
        raise FigureGenerationFailure("Stage-19 manifest does not certify all required figure inputs.")
    frames: dict[str, pd.DataFrame] = {}
    for filename in sorted(REQUIRED_FILES):
        entry = output_files.get(filename)
        path = restoration_dir / filename
        if not isinstance(entry, dict) or path.is_symlink() or not path.is_file():
            raise FigureGenerationFailure(f"Required Stage-19 output is missing or unsafe: {filename}")
        if not isinstance(entry.get("sha256"), str) or sha256(path) != entry["sha256"]:
            raise FigureGenerationFailure(f"Stage-19 output hash mismatch: {filename}")
        frame = pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig")
        if entry.get("rows") != len(frame):
            raise FigureGenerationFailure(f"Stage-19 output row-count mismatch: {filename}")
        frames[filename] = frame
    return manifest, frames, hashlib.sha256(raw_manifest.encode("utf-8")).hexdigest()


def theme_views(views: pd.DataFrame) -> pd.DataFrame:
    require_columns(views, "Stage-19 view definitions", {"view_id", "view_kind", "theme_id", "publication_denominator"})
    require_unique(views, ["view_id"], "Stage-19 view definitions")
    topic_views = views.loc[views["view_kind"].eq("dominant_K3_theme")].copy()
    topic_views["theme_id"] = pd.to_numeric(topic_views["theme_id"], errors="coerce")
    topic_views["publication_denominator"] = pd.to_numeric(topic_views["publication_denominator"], errors="coerce")
    if len(topic_views) != 3 or set(topic_views["theme_id"]) != {1, 2, 3} or topic_views["publication_denominator"].isna().any() or (topic_views["publication_denominator"] < 0).any():
        raise FigureGenerationFailure("Stage-19 view definitions do not contain the required three frozen K=3 views.")
    all_row = views.loc[views["view_id"].eq("all_final_anchor")]
    if len(all_row) != 1:
        raise FigureGenerationFailure("Stage-19 view definitions lack exactly one all-final-anchor view.")
    return topic_views.sort_values("theme_id")


def validate_scope(scope: pd.DataFrame, views: pd.DataFrame) -> None:
    require_columns(scope, "Stage-19 role scope", {"view_id", "relation_code", "publication_denominator", "publications_with_at_least_one_target"})
    require_unique(scope, ["view_id", "relation_code"], "Stage-19 role scope")
    expected = {(view, relation) for view in views["view_id"] for relation, _, _ in RELATIONS}
    observed = set(zip(scope["view_id"].astype(str), scope["relation_code"].astype(str)))
    if observed != expected:
        raise FigureGenerationFailure("Stage-19 role scope does not contain the complete view-by-relation matrix.")
    denominator = pd.to_numeric(scope["publication_denominator"], errors="coerce")
    support = pd.to_numeric(scope["publications_with_at_least_one_target"], errors="coerce")
    if denominator.isna().any() or support.isna().any() or (denominator < 0).any() or (support < 0).any() or (support > denominator).any() or (denominator % 1 != 0).any() or (support % 1 != 0).any():
        raise FigureGenerationFailure("Stage-19 role scope has invalid denominators or relation support counts.")


def validate_representation(frame: pd.DataFrame, *, kind: str, allowed_views: set[str]) -> None:
    if kind == "institution":
        required, keys = {"view_id", "relation_code", "organization_id", "organization_name", "percentage_of_view_publications"}, ["view_id", "relation_code", "organization_id"]
    else:
        required, keys = {"view_id", "relation_code", "country", "percentage_of_view_publications"}, ["view_id", "relation_code", "country"]
    require_columns(frame, f"Stage-19 {kind} representation", required)
    if not set(frame["view_id"].astype(str)).issubset(allowed_views) or not set(frame["relation_code"].astype(str)).issubset({item[0] for item in RELATIONS}):
        raise FigureGenerationFailure(f"Stage-19 {kind} representation contains an invalid view or relation.")
    require_unique(frame, keys, f"Stage-19 {kind} representation")
    require_finite_percentage(frame, "percentage_of_view_publications", f"Stage-19 {kind} representation")


def relation_support(scope: pd.DataFrame, relation: str) -> int:
    row = scope.loc[(scope["view_id"] == "all_final_anchor") & (scope["relation_code"] == relation)]
    if len(row) != 1:
        raise FigureGenerationFailure(f"Expected exactly one all-anchor scope row for {relation}.")
    return int(pd.to_numeric(row.iloc[0]["publications_with_at_least_one_target"], errors="raise"))


def wrap(value: str, width: int = 24) -> str:
    return "\n".join(textwrap.wrap(str(value), width=width, break_long_words=False, break_on_hyphens=False))


def panel_matrix(frame: pd.DataFrame, *, relation: str, id_column: str, label_column: str, topics: pd.DataFrame, top_n: int) -> tuple[list[str], list[str], np.ndarray]:
    value_column = "percentage_of_view_publications"
    overall = frame.loc[(frame["view_id"] == "all_final_anchor") & (frame["relation_code"] == relation)].copy()
    if overall.empty:
        return [], [], np.empty((0, len(topics)))
    overall = overall.sort_values([value_column, label_column, id_column], ascending=[False, True, True]).head(top_n)
    ids = overall[id_column].astype(str).tolist()
    labels = overall[label_column].astype(str).tolist()
    matrix: list[list[float]] = []
    for identifier in ids:
        row: list[float] = []
        for topic in topics.itertuples(index=False):
            cell = frame.loc[(frame["view_id"] == topic.view_id) & (frame["relation_code"] == relation) & (frame[id_column].astype(str) == identifier)]
            row.append(float(cell.iloc[0][value_column]) if len(cell) == 1 else 0.0)
        matrix.append(row)
    return ids, labels, np.array(matrix, dtype=float)


def save_figure(figure: plt.Figure, output: Path, filename: str) -> list[str]:
    png, pdf = output / f"{filename}.png", output / f"{filename}.pdf"
    figure.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.12)
    figure.savefig(pdf, bbox_inches="tight", pad_inches=0.12)
    return [str(png), str(pdf)]


def draw_heatmap_figure(*, kind: str, frame: pd.DataFrame, topics: pd.DataFrame, scope: pd.DataFrame, output: Path, top_n: int) -> list[str]:
    if kind == "institution":
        identifier, label, title, filename, width = "organization_id", "organization_name", "Institutional representation across FAIRification publication themes", "figure_7_institution_landscapes", 26
    else:
        identifier, label, title, filename, width = "country", "country", "Country representation across FAIRification publication themes", "figure_6_country_landscapes", 22
    plotted_relations = RELATIONS[:2]
    figure, axes = plt.subplots(1, 2, figsize=(13.0, 8.4), constrained_layout=False)
    figure.subplots_adjust(left=0.095, right=0.985, top=0.88, bottom=0.12, wspace=1.05)
    figure.text(0.075, 0.965, title, ha="left", va="top", fontsize=15, fontweight="bold", color="#202124")
    topic_codes = [f"T{int(row.theme_id)}\n(n={int(row.publication_denominator)})" for row in topics.itertuples(index=False)]
    for axis, (relation, panel_title, cmap) in zip(axes, plotted_relations):
        _, labels, matrix = panel_matrix(frame, relation=relation, id_column=identifier, label_column=label, topics=topics, top_n=top_n)
        if matrix.size == 0:
            axis.axis("off")
            axis.text(0.5, 0.5, f"{panel_title}\nNo eligible stored attributes", transform=axis.transAxes, ha="center", va="center", fontsize=10)
            continue
        ceiling = max(float(matrix.max()), 1.0)
        axis.imshow(matrix, aspect="auto", cmap=cmap, vmin=0, vmax=ceiling)
        axis.set_title(panel_title, loc="left", fontsize=10.5, fontweight="bold", pad=10, color="#202124")
        axis.set_xticks(range(len(topic_codes)), topic_codes, fontsize=8.5, fontweight="bold")
        axis.set_yticks(range(len(labels)), [wrap(value, width) for value in labels], fontsize=7.1)
        axis.tick_params(axis="both", length=0)
        for row_index in range(matrix.shape[0]):
            for column_index in range(matrix.shape[1]):
                value = matrix[row_index, column_index]
                axis.text(column_index, row_index, f"{value:.1f}", ha="center", va="center", fontsize=7.2, color="white" if value > 0.58 * ceiling else "#344054")
        for spine in axis.spines.values():
            spine.set_color("#B7C0CC")
    files = save_figure(figure, output, filename)
    plt.close(figure)
    return files


def atomic_text(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def main() -> None:
    try:
        args = preflight(parse_args())
        manifest, frames, restoration_manifest_hash = load_completed_restoration(args.restoration_dir)
        institutions = frames["theme_institution_representation.csv"]
        countries = frames["theme_country_representation.csv"]
        scope = frames["theme_role_scope_summary.csv"]
        views = frames["view_definitions.csv"]
        topics = theme_views(views)
        validate_scope(scope, views)
        allowed_views = set(views["view_id"].astype(str))
        validate_representation(institutions, kind="institution", allowed_views=allowed_views)
        validate_representation(countries, kind="country", allowed_views=allowed_views)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        institution_files = draw_heatmap_figure(kind="institution", frame=institutions, topics=topics, scope=scope, output=args.output_dir, top_n=args.top_n)
        country_files = draw_heatmap_figure(kind="country", frame=countries, topics=topics, scope=scope, output=args.output_dir, top_n=args.top_n)
        figure_manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "restoration_manifest": {"path": str(args.restoration_dir / "institution_country_restoration_manifest.json"), "sha256": restoration_manifest_hash, "stage": manifest["stage"]},
            "verified_input_outputs": {name: manifest["output_files"][name] for name in sorted(REQUIRED_FILES)},
            "top_n": args.top_n,
            "policy_issuer_panel_rule": "Not plotted because policy-issuer publication coverage is sparse; the manuscript TeX captions state this display boundary.",
            "institution_figure_files": institution_files,
            "country_figure_files": country_files,
            "data_boundary": "Named institution/country figures are protected local outputs and must not be committed to GitHub without a separate review.",
        }
        atomic_text(args.output_dir / "institution_country_figures_manifest.json", json.dumps(figure_manifest, ensure_ascii=False, indent=2) + "\n")
        print("FAIRIFICATION INSTITUTION/COUNTRY FIGURES: PASS")
        print("FIGURES: figure_6_country_landscapes.{png,pdf}; figure_7_institution_landscapes.{png,pdf}")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'institution_country_figures_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

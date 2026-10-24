#!/usr/bin/env python3
"""Restore local-only institution and country landscapes for FAIRification.

This script restores the descriptive institution/country material that was
calculated in the local network stage but intentionally excluded from the
first aggregate-only reporting bundle.  It is designed to run *only* against
protected local Dimensions-derived files.  Its outputs contain organization
and country attributes and therefore must not be committed to the public
repository without a separate release review.

It produces two complementary descriptions:

1. Full-anchor role networks: P--PI author-affiliation, G--GI funder,
   D--DI policy-issuer, plus the audited P--G, P--D, and issuer--P layers.
2. K=3 hard-theme landscapes for publication affiliations, grant funders
   reached through P--G, and policy issuers reached through P--D.  A grant or
   issuer can appear in more than one theme when it is linked to publications
   in more than one theme.  Within a theme, each publication--target pair is
   counted at most once.

The analysis is descriptive.  It reports stored Dimensions identifiers and
attributes, not institutional influence, funding intent, policy uptake,
endorsement, impact, or causal effects.

Example:
    python code/analysis/19_restore_institution_country_landscapes.py \
      --anchor-file data/04_final_linked/publication_anchor_final_run.pkl \
      --grants-file data/04_final_linked/linked_grants_final_run.pkl \
      --policy-file data/04_final_linked/linked_policy_documents_final_run.pkl \
      --publication-grant-edges-file computations/outputs/10.../edges_publication_grant.csv \
      --publication-policy-edges-file computations/outputs/10.../edges_publication_policy_document.csv \
      --policy-issuer-publication-edges-file computations/outputs/10.../edges_policy_issuer_publication.csv \
      --relational-summary-file computations/outputs/10.../retrieval_summary.json \
      --output-dir computations/outputs/19_institution_country_restoration_run_YYYYMMDD_HHMM
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import tempfile
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "19_restore_institution_country_landscapes_1.0"
EXPECTED_PUBLICATIONS = 144
TOPIC_LABELS = {
    1: "Institutional stewardship, research-data management, and Open Science practice",
    2: "Technical metadata, semantic infrastructure, and reproducible workflows",
    3: "Digital cultural heritage, collections, and preservation",
}
THEME_FIELD_MAP = {
    "nmf_primary_k": "n_topics",
    "nmf_dominant_theme": "dominant_topic",
    "nmf_dominant_theme_share": "dominant_topic_share",
    "nmf_topic_1_share": "topic_1_share",
    "nmf_topic_2_share": "topic_2_share",
    "nmf_topic_3_share": "topic_3_share",
}
ROLE_PATHS = (
    ("P_PI_affiliation", "P--PI author-affiliation organizations", "publication_affiliation_organization"),
    ("P_G_GI_funder", "G--GI funder organizations reached through P--G", "linked_grant_funder_organization"),
    ("P_D_DI_issuer", "D--DI policy-issuer organizations reached through P--D", "policy_issuer_organization"),
)


class RestorationFailure(RuntimeError):
    """Raised when a protected input does not meet the frozen local contract."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-file", type=Path, required=True)
    parser.add_argument("--grants-file", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--publication-grant-edges-file", type=Path, required=True)
    parser.add_argument("--publication-policy-edges-file", type=Path, required=True)
    parser.add_argument("--policy-issuer-publication-edges-file", type=Path, required=True)
    parser.add_argument("--relational-summary-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-publications", type=int, default=EXPECTED_PUBLICATIONS)
    return parser.parse_args()


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return "" if text.casefold() in {"", "nan", "none", "null"} else " ".join(text.split())


def parse_list(value: Any) -> list[Any]:
    """Read Dimensions list/object fields without deriving any new identities."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw.casefold() in {"nan", "none", "null"}:
            return []
        for decoder in (json.loads, ast.literal_eval):
            try:
                return parse_list(decoder(raw))
            except (ValueError, SyntaxError, json.JSONDecodeError):
                pass
        return [raw]
    return [value]


def parse_policy_document_ids(value: Any) -> list[str]:
    """Parse the semicolon-delimited Stage-10 issuer-edge contract exactly."""
    if isinstance(value, str) and ";" in value:
        values = [clean(item) for item in value.split(";")]
    else:
        values = [clean(item) for item in parse_list(value)]
    values = [item for item in values if item]
    if len(values) != len(set(values)):
        raise RestorationFailure("A policy issuer edge repeats a policy-document ID.")
    return sorted(values)


def countries_from(value: Any) -> list[str]:
    countries: list[str] = []
    for item in parse_list(value):
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("country_name") or item.get("country")
        else:
            candidate = item
        text = clean(candidate)
        if text:
            countries.append(text)
    return sorted(set(countries))


def object_text(value: Any, keys: Iterable[str]) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        candidate = value.get(key)
        if "country" in key:
            texts = countries_from(candidate)
            if texts:
                return " | ".join(texts)
        else:
            text = clean(candidate)
            if text:
                return text
    return ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def repository_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    return None


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
                                     prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            frame.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
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


def require_columns(frame: pd.DataFrame, label: str, columns: set[str]) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise RestorationFailure(f"{label} is missing required column(s): {', '.join(missing)}")


def validate_unique_ids(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    result = frame.copy()
    result["id"] = result["id"].map(clean)
    if result["id"].eq("").any() or result["id"].duplicated().any():
        raise RestorationFailure(f"{label} contains blank or duplicate IDs.")
    return result


def preflight(args: argparse.Namespace) -> argparse.Namespace:
    for name in (
        "anchor_file", "grants_file", "policy_file", "publication_grant_edges_file",
        "publication_policy_edges_file", "policy_issuer_publication_edges_file",
        "relational_summary_file", "output_dir",
    ):
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [
        args.anchor_file, args.grants_file, args.policy_file, args.publication_grant_edges_file,
        args.publication_policy_edges_file, args.policy_issuer_publication_edges_file,
        args.relational_summary_file,
    ]
    absent = [str(path) for path in inputs if not path.is_file()]
    if absent:
        raise FileNotFoundError("Required input file(s) missing:\n" + "\n".join(absent))
    if args.expected_publications < 1:
        raise ValueError("--expected-publications must be positive.")
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must not already exist: {args.output_dir}")
    repo = repository_root()
    if repo is not None and is_within(args.output_dir, repo):
        raise ValueError(f"Protected restoration output must be outside the Git worktree: {repo}")
    if any(is_within(path, args.output_dir) for path in inputs):
        raise ValueError("Output directory cannot be an ancestor of an input path.")
    return args


def extract_explicit_organizations(
    frame: pd.DataFrame,
    *,
    role: str,
    record_id_column: str,
    id_column: str,
    name_column: str,
    country_column: str,
    type_column: str | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract explicit organization IDs and conservative stored attributes.

    Parallel arrays are only paired when they all have the same length as the
    explicit-ID array.  This prevents attaching a country/name to a different
    organization when a Dimensions record contains unequal parallel fields.
    Embedded attributes inside an ID object remain usable without positional
    pairing.
    """
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        record_id = clean(record.get(record_id_column))
        ids = parse_list(record.get(id_column))
        names = parse_list(record.get(name_column))
        countries = parse_list(record.get(country_column))
        types = parse_list(record.get(type_column)) if type_column and type_column in frame.columns else []
        lengths = {"ids": len(ids), "names": len(names), "countries": len(countries), "types": len(types)}
        nonempty_parallel_lengths = [length for key, length in lengths.items() if key != "ids" and length > 0]
        aligned = not nonempty_parallel_lengths or all(length == len(ids) for length in nonempty_parallel_lengths)
        audit.append({
            "role": role,
            "record_id": record_id,
            "explicit_id_entries": len(ids),
            "name_entries": len(names),
            "country_entries": len(countries),
            "type_entries": len(types),
            "parallel_fields_aligned_or_absent": aligned,
        })
        for index, raw_id in enumerate(ids):
            identifier = clean(raw_id.get("id")) if isinstance(raw_id, dict) else clean(raw_id)
            if not identifier:
                continue
            embedded_name = object_text(raw_id, ("name",))
            embedded_country = object_text(raw_id, ("country_name", "country", "countries"))
            embedded_type = object_text(raw_id, ("types", "type"))
            positional_name = clean(names[index]) if aligned and index < len(names) else ""
            positional_countries = countries_from(countries[index]) if aligned and index < len(countries) else []
            positional_type = clean(types[index]) if aligned and index < len(types) else ""
            stored_countries = countries_from(embedded_country) or positional_countries
            rows.append({
                "role": role,
                "record_id": record_id,
                "organization_id": identifier,
                "organization_name": embedded_name or positional_name,
                "organization_countries_json": json.dumps(stored_countries, ensure_ascii=False),
                "organization_type": embedded_type or positional_type,
                "attribute_pairing_rule": "embedded_attributes_or_equal_length_parallel_arrays_only",
            })
    columns = [
        "role", "record_id", "organization_id", "organization_name", "organization_countries_json",
        "organization_type", "attribute_pairing_rule",
    ]
    incidence = pd.DataFrame(rows, columns=columns)
    if not incidence.empty:
        incidence = incidence.drop_duplicates(subset=["role", "record_id", "organization_id"]).sort_values(
            ["role", "record_id", "organization_id"]
        ).reset_index(drop=True)
    audit_frame = pd.DataFrame(audit)
    return incidence, audit_frame


def representation(incidence: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    columns = group_columns + [
        "organization_id", "organization_name", "organization_name_variants", "organization_type",
        "organization_type_variants", "organization_countries_json", "distinct_associated_records",
        "rank_by_distinct_associated_records", "identity_boundary",
    ]
    if incidence.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for keys, group in incidence.groupby(group_columns + ["organization_id"], dropna=False, sort=True):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_columns + ["organization_id"], key_values))
        names = sorted({clean(value) for value in group["organization_name"] if clean(value)})
        types = sorted({clean(value) for value in group["organization_type"] if clean(value)})
        countries = sorted({country for raw in group["organization_countries_json"] for country in countries_from(raw)})
        row.update({
            "organization_name": names[0] if names else "",
            "organization_name_variants": " | ".join(names),
            "organization_type": types[0] if types else "",
            "organization_type_variants": " | ".join(types),
            "organization_countries_json": json.dumps(countries, ensure_ascii=False),
            "distinct_associated_records": int(group["record_id"].nunique()),
            "identity_boundary": "Organization identity is an explicit Dimensions ID within this role only; no name-based or cross-role merge is performed.",
        })
        rows.append(row)
    output = pd.DataFrame(rows)
    output = output.sort_values(group_columns + ["distinct_associated_records", "organization_id"], ascending=[True] * len(group_columns) + [False, True])
    output["rank_by_distinct_associated_records"] = output.groupby(group_columns, dropna=False).cumcount() + 1
    return output[columns].reset_index(drop=True)


def country_representation(incidence: pd.DataFrame, group_columns: list[str], denominator_column: str = "record_id") -> pd.DataFrame:
    columns = group_columns + [
        "country", "distinct_associated_records_with_country", "available_distinct_associated_records",
        "records_with_at_least_one_country", "percentage_of_available_records",
        "multi_country_counting_note",
    ]
    if incidence.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for keys, group in incidence.groupby(group_columns, dropna=False, sort=True):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        key_row = dict(zip(group_columns, key_values))
        available = int(group[denominator_column].nunique())
        by_record: dict[str, set[str]] = defaultdict(set)
        for record in group[[denominator_column, "organization_countries_json"]].drop_duplicates().itertuples(index=False):
            record_id = clean(getattr(record, denominator_column))
            by_record[record_id].update(countries_from(getattr(record, "organization_countries_json")))
        represented = sum(bool(countries) for countries in by_record.values())
        counter: dict[str, set[str]] = defaultdict(set)
        for record_id, countries in by_record.items():
            for country in countries:
                counter[country].add(record_id)
        for country, record_ids in sorted(counter.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            row = dict(key_row)
            row.update({
                "country": country,
                "distinct_associated_records_with_country": len(record_ids),
                "available_distinct_associated_records": available,
                "records_with_at_least_one_country": represented,
                "percentage_of_available_records": round(100 * len(record_ids) / available, 3) if available else np.nan,
                "multi_country_counting_note": "A record may contribute once to every stored country; percentages are non-exclusive and need not sum to 100.",
            })
            rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def gini(values: Iterable[float]) -> float | None:
    array = np.array([float(v) for v in values if v is not None and not pd.isna(v)], dtype=float)
    array = array[array >= 0]
    if not len(array) or array.sum() == 0:
        return None
    array = np.sort(array)
    n = len(array)
    return float((2 * np.sum(np.arange(1, n + 1) * array) / (n * array.sum())) - (n + 1) / n)


def component_sizes(edges: pd.DataFrame, left: str, right: str) -> pd.DataFrame:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for row in edges[[left, right]].drop_duplicates().itertuples(index=False):
        a, b = f"L::{getattr(row, left)}", f"R::{getattr(row, right)}"
        adjacency[a].add(b)
        adjacency[b].add(a)
    unseen = set(adjacency)
    rows: list[dict[str, int]] = []
    number = 0
    while unseen:
        number += 1
        start = next(iter(unseen))
        queue = deque([start])
        seen = {start}
        unseen.remove(start)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    unseen.discard(neighbor)
                    queue.append(neighbor)
        rows.append({
            "component_id": number,
            "left_nodes": sum(node.startswith("L::") for node in seen),
            "right_nodes": sum(node.startswith("R::") for node in seen),
            "total_nodes": len(seen),
            "unique_edges": sum(len(adjacency[node]) for node in seen) // 2,
        })
    return pd.DataFrame(rows)


def network_summary(relation: str, edges: pd.DataFrame, left: str, right: str, left_available: int, right_available: int) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dedup = edges[[left, right]].drop_duplicates().copy()
    left_degree = dedup.groupby(left).size().rename("degree").reset_index() if not dedup.empty else pd.DataFrame(columns=[left, "degree"])
    right_degree = dedup.groupby(right).size().rename("degree").reset_index() if not dedup.empty else pd.DataFrame(columns=[right, "degree"])
    components = component_sizes(dedup, left, right) if not dedup.empty else pd.DataFrame(columns=["component_id", "left_nodes", "right_nodes", "total_nodes", "unique_edges"])
    edge_count = len(dedup)
    n_left, n_right = len(left_degree), len(right_degree)
    largest = components.sort_values(["total_nodes", "unique_edges"], ascending=False).head(1)
    summary = {
        "relation": relation,
        "left_endpoint": left,
        "right_endpoint": right,
        "available_left_nodes": int(left_available),
        "available_right_nodes": int(right_available),
        "connected_left_nodes": int(n_left),
        "connected_right_nodes": int(n_right),
        "unique_edges": int(edge_count),
        "density_among_connected_nodes": round(edge_count / (n_left * n_right), 8) if n_left and n_right else np.nan,
        "mean_left_degree": round(float(left_degree["degree"].mean()), 6) if n_left else np.nan,
        "mean_right_degree": round(float(right_degree["degree"].mean()), 6) if n_right else np.nan,
        "maximum_left_degree": int(left_degree["degree"].max()) if n_left else 0,
        "maximum_right_degree": int(right_degree["degree"].max()) if n_right else 0,
        "connected_components": int(len(components)),
        "largest_component_total_nodes": int(largest.iloc[0]["total_nodes"]) if not largest.empty else 0,
        "left_degree_gini": round(gini(left_degree["degree"]), 6) if n_left else np.nan,
        "right_degree_gini": round(gini(right_degree["degree"]), 6) if n_right else np.nan,
    }
    components.insert(0, "relation", relation)
    return summary, left_degree, right_degree, components


def require_theme_fields(P: pd.DataFrame) -> pd.DataFrame:
    require_columns(P, "Publication anchor", {"id", "retain_in_final_P", *THEME_FIELD_MAP})
    result = P.copy()
    if not result["retain_in_final_P"].map(lambda value: clean(value).casefold() in {"true", "1", "yes"}).all():
        raise RestorationFailure("The anchor contains a publication outside final P.")
    k = pd.to_numeric(result["nmf_primary_k"], errors="coerce")
    if k.isna().any() or not (k == 3).all():
        raise RestorationFailure("The institution/country restoration requires frozen K=3 anchor fields.")
    result["theme_id"] = pd.to_numeric(result["nmf_dominant_theme"], errors="coerce")
    if result["theme_id"].isna().any() or not result["theme_id"].isin(TOPIC_LABELS).all():
        raise RestorationFailure("Anchor dominant topics must be integer values in {1, 2, 3}.")
    result["theme_id"] = result["theme_id"].astype(int)
    shares = result[["nmf_topic_1_share", "nmf_topic_2_share", "nmf_topic_3_share"]].apply(pd.to_numeric, errors="coerce")
    if shares.isna().any().any() or ((shares < -1e-9) | (shares > 1 + 1e-9)).any().any():
        raise RestorationFailure("K=3 topic shares must be finite values in [0, 1].")
    if not np.allclose(shares.sum(axis=1).to_numpy(), 1.0, atol=1e-8):
        raise RestorationFailure("K=3 topic shares must sum to one for every anchor publication.")
    dominant_share = pd.to_numeric(result["nmf_dominant_theme_share"], errors="coerce")
    if dominant_share.isna().any() or ((dominant_share < -1e-9) | (dominant_share > 1 + 1e-9)).any():
        raise RestorationFailure("Dominant K=3 theme shares must be finite values in [0, 1].")
    selected_share = np.array([shares.iloc[index, theme - 1] for index, theme in enumerate(result["theme_id"])])
    maximum_share = shares.max(axis=1).to_numpy()
    if not np.allclose(dominant_share.to_numpy(), selected_share, atol=1e-8) or np.any(maximum_share > selected_share + 1e-8):
        raise RestorationFailure("Dominant K=3 assignments do not reconcile to the stored topic-share vector.")
    result["theme_label"] = result["theme_id"].map(TOPIC_LABELS)
    return result


def policy_issuer_paths(
    ip: pd.DataFrame, policy_ids: set[str], publication_ids: set[str], policy_publication_pairs: set[tuple[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = {"issuer_id", "issuer_name", "issuer_type", "issuer_country", "publication_id", "n_policy_documents", "policy_document_ids"}
    require_columns(ip, "Policy issuer--publication edges", required)
    rows: list[dict[str, Any]] = []
    doc_rows: list[dict[str, Any]] = []
    for record in ip.itertuples(index=False):
        publication_id = clean(getattr(record, "publication_id"))
        issuer_id = clean(getattr(record, "issuer_id"))
        if publication_id not in publication_ids or not issuer_id:
            raise RestorationFailure("Policy issuer--publication edge has an invalid endpoint.")
        try:
            raw_weight = float(getattr(record, "n_policy_documents"))
        except (ValueError, TypeError):
            raise RestorationFailure("Policy issuer edge contains a nonnumeric policy-document weight.") from None
        if not np.isfinite(raw_weight) or raw_weight < 1 or not raw_weight.is_integer():
            raise RestorationFailure("Policy issuer edge weight must be a positive integer.")
        weight = int(raw_weight)
        docs = parse_policy_document_ids(getattr(record, "policy_document_ids"))
        if len(docs) != weight:
            raise RestorationFailure("Policy issuer edge policy-document IDs do not reconcile to its stored weight.")
        countries = countries_from(getattr(record, "issuer_country"))
        rows.append({
            "role": "policy_issuer_organization",
            "record_id": publication_id,
            "organization_id": issuer_id,
            "organization_name": clean(getattr(record, "issuer_name")),
            "organization_countries_json": json.dumps(countries, ensure_ascii=False),
            "organization_type": clean(getattr(record, "issuer_type")),
            "attribute_pairing_rule": "audited_policy_issuer_publication_edge",
        })
        for policy_document_id in docs:
            if policy_document_id not in policy_ids:
                raise RestorationFailure("An issuer edge references a policy document outside the retained policy table.")
            if (publication_id, policy_document_id) not in policy_publication_pairs:
                raise RestorationFailure("An issuer path is not an audited publication--policy-document edge.")
            doc_rows.append({
                "policy_document_id": policy_document_id,
                "issuer_id": issuer_id,
                "issuer_name": clean(getattr(record, "issuer_name")),
                "issuer_type": clean(getattr(record, "issuer_type")),
                "issuer_country_json": json.dumps(countries, ensure_ascii=False),
            })
    issuer_columns = ["role", "record_id", "organization_id", "organization_name", "organization_countries_json", "organization_type", "attribute_pairing_rule"]
    document_columns = ["policy_document_id", "issuer_id", "issuer_name", "issuer_type", "issuer_country_json"]
    issuer_p = pd.DataFrame(rows, columns=issuer_columns)
    d_i = pd.DataFrame(doc_rows, columns=document_columns)
    if not issuer_p.empty:
        issuer_p = issuer_p.drop_duplicates(subset=["role", "record_id", "organization_id"]).sort_values(["record_id", "organization_id"]).reset_index(drop=True)
    if not d_i.empty:
        d_i = d_i.drop_duplicates(subset=["policy_document_id", "issuer_id"]).sort_values(["policy_document_id", "issuer_id"]).reset_index(drop=True)
    conflict = d_i.groupby("policy_document_id")["issuer_id"].nunique().rename("n_issuer_ids").reset_index() if not d_i.empty else pd.DataFrame(columns=["policy_document_id", "n_issuer_ids"])
    return issuer_p, d_i, conflict


def make_views(P: pd.DataFrame) -> pd.DataFrame:
    rows = [{
        "view_id": "all_final_anchor",
        "view_kind": "all_final_anchor",
        "theme_id": 0,
        "theme_label": "All final anchor publications",
        "publication_denominator": int(len(P)),
        "selection_rule": "All retained Dimensions publication-anchor records.",
    }]
    for theme_id in sorted(TOPIC_LABELS):
        count = int((P["theme_id"] == theme_id).sum())
        rows.append({
            "view_id": f"K3_topic_{theme_id}",
            "view_kind": "dominant_K3_theme",
            "theme_id": theme_id,
            "theme_label": TOPIC_LABELS[theme_id],
            "publication_denominator": count,
            "selection_rule": f"Frozen dominant K=3 topic assignment = {theme_id}.",
        })
    return pd.DataFrame(rows)


def thematic_paths(P: pd.DataFrame, pg: pd.DataFrame, affiliation: pd.DataFrame, funder: pd.DataFrame, issuer_p: pd.DataFrame) -> pd.DataFrame:
    publication_theme = P[["id", "theme_id", "theme_label"]].rename(columns={"id": "publication_id"})
    direct = affiliation.rename(columns={"record_id": "publication_id"}).copy()
    direct["relation_code"] = "P_PI_affiliation"
    direct["relation"] = "P--PI author-affiliation organizations"

    pg_link = pg.merge(publication_theme, on="publication_id", how="inner", validate="many_to_one")
    fund = funder.rename(columns={"record_id": "grant_id"})
    fund_path = pg_link.merge(fund, on="grant_id", how="inner", validate="many_to_many").drop(columns=["grant_id"])
    fund_path["relation_code"] = "P_G_GI_funder"
    fund_path["relation"] = "G--GI funder organizations reached through P--G"

    issuer = issuer_p.rename(columns={"record_id": "publication_id"}).merge(publication_theme, on="publication_id", how="inner", validate="many_to_one")
    issuer["relation_code"] = "P_D_DI_issuer"
    issuer["relation"] = "D--DI policy-issuer organizations reached through P--D"

    direct = direct.merge(publication_theme, on="publication_id", how="inner", validate="many_to_one")
    columns = [
        "publication_id", "theme_id", "theme_label", "relation_code", "relation", "organization_id",
        "organization_name", "organization_countries_json", "organization_type",
    ]
    paths = pd.concat([direct[columns], fund_path[columns], issuer[columns]], ignore_index=True)
    return paths.drop_duplicates(subset=["publication_id", "relation_code", "organization_id"]).sort_values(
        ["relation_code", "publication_id", "organization_id"]
    ).reset_index(drop=True)


def path_landscapes(paths: pd.DataFrame, views: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    org_frames: list[pd.DataFrame] = []
    country_frames: list[pd.DataFrame] = []
    scope_rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    for view in views.itertuples(index=False):
        selected = paths if view.theme_id == 0 else paths.loc[paths["theme_id"] == view.theme_id].copy()
        for relation_code, relation, _ in ROLE_PATHS:
            path = selected.loc[selected["relation_code"] == relation_code].copy()
            denominator = int(view.publication_denominator)
            linked_publications = int(path["publication_id"].nunique())
            organizations = representation(
                path.rename(columns={"publication_id": "record_id"}),
                ["relation_code", "relation"],
            )
            if not organizations.empty:
                organizations.insert(0, "view_id", view.view_id)
                organizations.insert(1, "view_kind", view.view_kind)
                organizations.insert(2, "theme_id", view.theme_id)
                organizations.insert(3, "theme_label", view.theme_label)
                organizations.insert(4, "publication_denominator", denominator)
                organizations["percentage_of_view_publications"] = (100 * organizations["distinct_associated_records"] / denominator).round(3) if denominator else np.nan
            else:
                organizations = pd.DataFrame(columns=[
                    "view_id", "view_kind", "theme_id", "theme_label", "publication_denominator",
                    "relation_code", "relation", "organization_id", "organization_name",
                    "organization_name_variants", "organization_type", "organization_type_variants",
                    "organization_countries_json", "distinct_associated_records",
                    "rank_by_distinct_associated_records", "identity_boundary",
                    "percentage_of_view_publications",
                ])
            org_frames.append(organizations)

            countries = country_representation(
                path.rename(columns={"publication_id": "record_id"}),
                ["relation_code", "relation"],
            )
            if not countries.empty:
                countries.insert(0, "view_id", view.view_id)
                countries.insert(1, "view_kind", view.view_kind)
                countries.insert(2, "theme_id", view.theme_id)
                countries.insert(3, "theme_label", view.theme_label)
                countries.insert(4, "publication_denominator", denominator)
                countries["percentage_of_view_publications"] = (100 * countries["distinct_associated_records_with_country"] / denominator).round(3) if denominator else np.nan
            else:
                countries = pd.DataFrame(columns=[
                    "view_id", "view_kind", "theme_id", "theme_label", "publication_denominator",
                    "relation_code", "relation", "country", "distinct_associated_records_with_country",
                    "available_distinct_associated_records", "records_with_at_least_one_country",
                    "percentage_of_available_records", "multi_country_counting_note",
                    "percentage_of_view_publications",
                ])
            country_frames.append(countries)

            publications_with_country = int(
                sum(
                    any(bool(countries_from(value)) for value in group["organization_countries_json"])
                    for _, group in path.groupby("publication_id", sort=False)
                )
            )

            scope_rows.append({
                "view_id": view.view_id,
                "view_kind": view.view_kind,
                "theme_id": view.theme_id,
                "theme_label": view.theme_label,
                "relation_code": relation_code,
                "relation": relation,
                "publication_denominator": denominator,
                "publications_with_at_least_one_target": linked_publications,
                "distinct_organizations": int(path["organization_id"].nunique()),
                "organization_incidence_pairs": int(len(path)),
                "publications_with_country_attribute": publications_with_country,
                "distinct_stored_countries": int(len({country for value in path["organization_countries_json"] for country in countries_from(value)})),
                "country_counting_rule": "Non-exclusive stored-country representation; a publication may contribute to multiple countries.",
            })
            aggregate_rows.append({
                "view_id": view.view_id,
                "view_kind": view.view_kind,
                "theme_id": view.theme_id,
                "theme_label": view.theme_label,
                "relation_code": relation_code,
                "publication_denominator": denominator,
                "publications_with_at_least_one_target": linked_publications,
                "distinct_organizations": int(path["organization_id"].nunique()),
                "distinct_stored_countries": int(len({country for value in path["organization_countries_json"] for country in countries_from(value)})),
                "organization_incidence_pairs": int(len(path)),
                "interpretive_boundary": "Aggregate descriptive counts of Dimensions-recorded identifiers/attributes; not institutional influence, funding intent, policy uptake, or impact.",
            })
    return (
        pd.concat(org_frames, ignore_index=True) if org_frames else pd.DataFrame(),
        pd.concat(country_frames, ignore_index=True) if country_frames else pd.DataFrame(),
        pd.DataFrame(scope_rows),
        pd.DataFrame(aggregate_rows),
    )


def verify_stage10_lineage(
    summary: dict[str, Any], *, hashes: dict[str, str], n_publications: int, n_grants: int, n_policy_documents: int,
    n_pg: int, n_pd: int, n_issuer_publication: int,
) -> None:
    """Require the supplied protected files to form one completed Stage-10 run."""
    if not str(summary.get("stage", "")).startswith("10_") or summary.get("status") != "complete":
        raise RestorationFailure("Restoration requires a completed Stage-10 relational-audit manifest.")
    record_counts = summary.get("record_counts")
    edge_counts = summary.get("edge_counts")
    input_files = summary.get("input_files")
    output_files = summary.get("output_files")
    if not all(isinstance(value, dict) for value in (record_counts, edge_counts, input_files, output_files)):
        raise RestorationFailure("Stage-10 manifest lacks complete record/edge/hash provenance.")
    expected_records = {
        "final_publications_P": n_publications,
        "linked_grants_G": n_grants,
        "linked_policy_documents_D": n_policy_documents,
    }
    expected_edges = {
        "publication_grant": n_pg,
        "publication_policy_document": n_pd,
        "policy_issuer_publication": n_issuer_publication,
    }
    if any(record_counts.get(key) != value for key, value in expected_records.items()):
        raise RestorationFailure("Stage-10 record counts do not reconcile to the supplied P/G/D tables.")
    if any(edge_counts.get(key) != value for key, value in expected_edges.items()):
        raise RestorationFailure("Stage-10 edge counts do not reconcile to the supplied audited edge tables.")
    for manifest_key, local_key in (
        ("publication_anchor", "anchor"),
        ("linked_grants", "grants"),
        ("linked_policy_documents", "policy_documents"),
    ):
        entry = input_files.get(manifest_key)
        if not isinstance(entry, dict) or entry.get("sha256") != hashes[local_key]:
            raise RestorationFailure(f"Stage-10 input hash mismatch for {manifest_key}.")
    for manifest_key, local_key, rows in (
        ("edges_publication_grant.csv", "publication_grant_edges", n_pg),
        ("edges_publication_policy_document.csv", "publication_policy_edges", n_pd),
        ("edges_policy_issuer_publication.csv", "policy_issuer_publication_edges", n_issuer_publication),
    ):
        entry = output_files.get(manifest_key)
        if not isinstance(entry, dict) or entry.get("sha256") != hashes[local_key] or entry.get("rows") != rows:
            raise RestorationFailure(f"Stage-10 output hash/row mismatch for {manifest_key}.")


def main() -> None:
    try:
        args = preflight(parse_args())
        inputs = {
            "anchor": args.anchor_file,
            "grants": args.grants_file,
            "policy_documents": args.policy_file,
            "publication_grant_edges": args.publication_grant_edges_file,
            "publication_policy_edges": args.publication_policy_edges_file,
            "policy_issuer_publication_edges": args.policy_issuer_publication_edges_file,
            "relational_summary": args.relational_summary_file,
        }
        hashes = {name: sha256(path) for name, path in inputs.items()}
        P = require_theme_fields(validate_unique_ids(pd.read_pickle(args.anchor_file), "Publication anchor"))
        G = validate_unique_ids(pd.read_pickle(args.grants_file), "Linked grants")
        D = validate_unique_ids(pd.read_pickle(args.policy_file), "Linked policy documents")
        if len(P) != args.expected_publications:
            raise RestorationFailure(f"Expected {args.expected_publications} final publications; observed {len(P)}.")
        require_columns(P, "Publication anchor", {"research_orgs", "research_org_names", "research_org_countries", "research_org_types"})
        require_columns(G, "Linked grants", {"funder_orgs", "funder_org_name", "funder_org_countries", "research_orgs", "research_org_names", "research_org_countries", "research_org_types"})
        require_columns(D, "Linked policy documents", {"id", "publication_ids"})
        summary = json.loads(args.relational_summary_file.read_text(encoding="utf-8"))

        pg = pd.read_csv(args.publication_grant_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        pd_edges = pd.read_csv(args.publication_policy_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        ip = pd.read_csv(args.policy_issuer_publication_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        require_columns(pg, "Publication--grant edges", {"publication_id", "grant_id"})
        require_columns(pd_edges, "Publication--policy-document edges", {"publication_id", "policy_document_id"})
        require_columns(ip, "Policy issuer--publication edges", {"issuer_id", "publication_id"})
        for frame, columns in ((pg, ["publication_id", "grant_id"]), (pd_edges, ["publication_id", "policy_document_id"])):
            for column in columns:
                frame[column] = frame[column].map(clean)
            if frame[columns].eq("").any().any() or frame.duplicated(subset=columns).any():
                raise RestorationFailure("An audited relation table has blank or duplicate endpoints.")
        for column in ("issuer_id", "publication_id"):
            ip[column] = ip[column].map(clean)
        if ip[["issuer_id", "publication_id"]].eq("").any().any() or ip.duplicated(subset=["issuer_id", "publication_id"]).any():
            raise RestorationFailure("The issuer--publication edge table has blank or duplicate endpoints.")
        P_ids, G_ids, D_ids = set(P["id"]), set(G["id"]), set(D["id"])
        if not set(pg["publication_id"]).issubset(P_ids) or not set(pg["grant_id"]).issubset(G_ids):
            raise RestorationFailure("P--G endpoints do not reconcile to final P/G tables.")
        if not set(pd_edges["publication_id"]).issubset(P_ids) or not set(pd_edges["policy_document_id"]).issubset(D_ids):
            raise RestorationFailure("P--D endpoints do not reconcile to final P/D tables.")
        if not set(ip["publication_id"]).issubset(P_ids):
            raise RestorationFailure("Issuer--publication endpoints do not reconcile to final P.")
        verify_stage10_lineage(
            summary, hashes=hashes, n_publications=len(P), n_grants=len(G), n_policy_documents=len(D),
            n_pg=len(pg), n_pd=len(pd_edges), n_issuer_publication=len(ip),
        )

        affiliation, affiliation_audit = extract_explicit_organizations(
            P, role="publication_affiliation_organization", record_id_column="id", id_column="research_orgs",
            name_column="research_org_names", country_column="research_org_countries", type_column="research_org_types",
        )
        funder, funder_audit = extract_explicit_organizations(
            G, role="linked_grant_funder_organization", record_id_column="id", id_column="funder_orgs",
            name_column="funder_org_name", country_column="funder_org_countries", type_column=None,
        )
        recipient, recipient_audit = extract_explicit_organizations(
            G, role="linked_grant_recipient_organization", record_id_column="id", id_column="research_orgs",
            name_column="research_org_names", country_column="research_org_countries", type_column="research_org_types",
        )
        policy_pairs = set(zip(pd_edges["publication_id"], pd_edges["policy_document_id"]))
        issuer_p, d_i, issuer_conflicts = policy_issuer_paths(ip, D_ids, P_ids, policy_pairs)
        all_incidence = pd.concat([affiliation, funder, recipient, issuer_p], ignore_index=True)
        organization_representation = representation(all_incidence, ["role"])
        direct_country_representation = country_representation(all_incidence, ["role"])
        role_audits = pd.concat([affiliation_audit, funder_audit, recipient_audit], ignore_index=True)
        role_schema = []
        for role, frame, audit in (
            ("publication_affiliation_organization", P, affiliation_audit),
            ("linked_grant_funder_organization", G, funder_audit),
            ("linked_grant_recipient_organization", G, recipient_audit),
        ):
            role_schema.append({
                "role": role,
                "available_source_records": int(len(frame)),
                "records_with_explicit_org_id": int((audit["explicit_id_entries"] > 0).sum()),
                "parallel_length_mismatch_records": int((~audit["parallel_fields_aligned_or_absent"]).sum()),
                "identity_rule": "Explicit Dimensions organization ID only; unaligned parallel attributes are not attached.",
            })
        role_schema.append({
            "role": "policy_issuer_organization",
            "available_source_records": int(len(P)),
            "records_with_explicit_org_id": int(issuer_p["record_id"].nunique()),
            "parallel_length_mismatch_records": 0,
            "identity_rule": "Explicit issuer ID in the audited policy-issuer--publication edge only.",
        })

        # Restore the role networks that the Niko paper reported descriptively.
        ppi_edges = affiliation.rename(columns={"record_id": "publication_id"})[["publication_id", "organization_id"]]
        ggi_edges = funder.rename(columns={"record_id": "grant_id"})[["grant_id", "organization_id"]]
        ddi_edges = d_i[["policy_document_id", "issuer_id"]].rename(columns={"issuer_id": "organization_id"})
        issuer_p_edges = issuer_p.rename(columns={"record_id": "publication_id"})[["publication_id", "organization_id"]]
        network_specs = (
            ("P_PI_affiliation", ppi_edges, "publication_id", "organization_id", len(P), int(affiliation["organization_id"].nunique())),
            ("P_G", pg, "publication_id", "grant_id", len(P), len(G)),
            ("G_GI_funder", ggi_edges, "grant_id", "organization_id", len(G), int(funder["organization_id"].nunique())),
            ("P_D", pd_edges, "publication_id", "policy_document_id", len(P), len(D)),
            ("D_DI_issuer", ddi_edges, "policy_document_id", "organization_id", len(D), int(d_i["issuer_id"].nunique())),
            ("DI_P_issuer_publication", issuer_p_edges, "organization_id", "publication_id", int(issuer_p["organization_id"].nunique()), len(P)),
        )
        network_rows: list[dict[str, Any]] = []
        component_frames: list[pd.DataFrame] = []
        degree_frames: list[pd.DataFrame] = []
        for relation, edges, left, right, left_available, right_available in network_specs:
            row, left_degree, right_degree, components = network_summary(relation, edges, left, right, left_available, right_available)
            network_rows.append(row)
            component_frames.append(components)
            left_degree = left_degree.rename(columns={left: "node_id", "degree": "degree"})
            left_degree.insert(0, "relation", relation)
            left_degree.insert(1, "partition", "left")
            right_degree = right_degree.rename(columns={right: "node_id", "degree": "degree"})
            right_degree.insert(0, "relation", relation)
            right_degree.insert(1, "partition", "right")
            degree_frames.extend([left_degree, right_degree])

        views = make_views(P)
        paths = thematic_paths(P, pg, affiliation, funder, issuer_p)
        theme_organizations, theme_countries, theme_scope, aggregate_scope = path_landscapes(paths, views)

        # Named issuer representation is restored locally, with no claim about policy influence.
        issuer_representation = representation(issuer_p, ["role"])
        if not issuer_representation.empty:
            issuer_representation = issuer_representation.rename(columns={"rank_by_distinct_associated_records": "issuer_rank_by_linked_publications"})

        validations = [
            {"check": "expected_final_publication_count", "passed": len(P) == args.expected_publications, "detail": f"{len(P)} publications"},
            {"check": "K3_shares_valid", "passed": True, "detail": "All K=3 shares are finite, bounded, and sum to one."},
            {"check": "P_G_endpoints_reconcile", "passed": True, "detail": f"{len(pg)} unique P--G edges"},
            {"check": "P_D_endpoints_reconcile", "passed": True, "detail": f"{len(pd_edges)} unique P--D edges"},
            {"check": "issuer_policy_document_weights_reconcile", "passed": True, "detail": f"{len(d_i)} D--DI edges from audited issuer paths"},
            {"check": "no_name_based_identity_resolution", "passed": True, "detail": "All organization identities use explicit Dimensions IDs within separated roles."},
            {"check": "unaligned_parallel_attributes_not_paired", "passed": True, "detail": "Unequal parallel metadata arrays were not positionally attached."},
            {"check": "result_scope", "passed": True, "detail": "All outputs are descriptive Dimensions-recorded identifiers and stored attributes only."},
        ]
        outputs: dict[str, pd.DataFrame] = {
            "view_definitions.csv": views,
            "role_attribute_schema_audit.csv": pd.DataFrame(role_schema),
            "organization_role_incidence.csv": all_incidence,
            "organization_role_representation.csv": organization_representation,
            "country_role_representation.csv": direct_country_representation,
            "policy_issuer_representation.csv": issuer_representation,
            "policy_document_issuer_edges.csv": d_i,
            "policy_document_issuer_conflicts.csv": issuer_conflicts,
            "role_network_basic_statistics.csv": pd.DataFrame(network_rows),
            "role_network_components.csv": pd.concat(component_frames, ignore_index=True),
            "role_network_node_degrees.csv": pd.concat(degree_frames, ignore_index=True),
            "theme_publication_target_paths.csv": paths,
            "theme_institution_representation.csv": theme_organizations,
            "theme_country_representation.csv": theme_countries,
            "theme_role_scope_summary.csv": theme_scope,
            "aggregate_institution_country_scope_by_theme.csv": aggregate_scope,
            "institution_country_validation_checks.csv": pd.DataFrame(validations),
        }
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, frame in outputs.items():
            atomic_csv(args.output_dir / name, frame)
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "expected_final_publications": args.expected_publications,
            "input_files": {key: {"path": str(value), "sha256": hashes[key]} for key, value in inputs.items()},
            "record_counts": {
                "final_publications": int(len(P)), "linked_grants": int(len(G)), "linked_policy_documents": int(len(D)),
                "publication_affiliation_incidence": int(len(affiliation)), "grant_funder_incidence": int(len(funder)),
                "grant_recipient_incidence": int(len(recipient)), "policy_issuer_publication_incidence": int(len(issuer_p)),
            },
            "views": views.to_dict(orient="records"),
            "identity_rule": "An organization is defined only by an explicit Dimensions ID within a role. No name-based or cross-role identity merge occurs.",
            "country_rule": "Stored-country counts are non-exclusive; a publication may contribute to more than one country.",
            "interpretive_boundary": "Outputs describe Dimensions-recorded identifiers, attributes, and relation paths. They do not establish institutional influence, funding intent, policy endorsement, uptake, impact, knowledge translation, or causal effects.",
            "data_boundary": "All outputs contain protected record-level identifiers and/or named organization/country attributes and must remain local unless separately reviewed for release.",
            "output_files": {name: {"sha256": sha256(args.output_dir / name), "rows": int(len(frame))} for name, frame in outputs.items()},
        }
        atomic_json(args.output_dir / "institution_country_restoration_manifest.json", manifest)
        print("FAIRIFICATION INSTITUTION/COUNTRY RESTORATION: PASS")
        print(f"FINAL PUBLICATIONS: {len(P)}")
        print(f"P--PI AFFILIATION INCIDENCES: {len(affiliation)}")
        print(f"G--GI FUNDER INCIDENCES: {len(funder)}")
        print(f"D--DI POLICY-ISSUER EDGES: {len(d_i)}")
        print(f"K=3 VIEWS: {len(views) - 1} themes plus all-final-anchor")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'institution_country_restoration_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Describe FAIRification linkage networks, organization roles, and countries.

This local, no-API script adapts the descriptive network stage from the prior
AI--mental-health study. It constructs three distinct identifier networks from
the already audited Dimensions edge lists:

* publication--grant;
* publication--policy document; and
* policy issuer--publication, weighted by the number of recorded policy documents.

It also describes organization and country representation separately by role:
publication affiliation, grant funder, grant recipient organization, and policy
issuer. Organization IDs are never inferred from organization names; roles are
never merged. In particular, an affiliated organization is not treated as a
funder, and a funder is not treated as a policy issuer.

The results are descriptive properties of Dimensions-recorded identifiers and
attributes. They do not establish influence, preference, intentional selection,
causal funding, policy uptake, policy impact, endorsement, or knowledge
translation.

Example:
    python code/analysis/14_networks_organizations_countries.py \
      --anchor-file /path/to/publication_anchor_final_run.pkl \
      --grants-file /path/to/linked_grants_final_run.pkl \
      --policy-file /path/to/linked_policy_documents_final_run.pkl \
      --publication-grant-edges-file /path/to/edges_publication_grant.csv \
      --publication-policy-edges-file /path/to/edges_publication_policy_document.csv \
      --policy-issuer-publication-edges-file /path/to/edges_policy_issuer_publication.csv \
      --relational-summary-file /path/to/retrieval_summary.json \
      --output-dir /path/to/computations/outputs/14_networks_organizations_countries_run
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "14_networks_organizations_countries_1.0"
EXPECTED_PUBLICATION_RECORDS = 144
TOP_N = 25
CONCENTRATION_SHARES = (0.01, 0.05, 0.10)
ANCHOR_REQUIRED_COLUMNS = {"id", "title", "year", "retain_in_final_P"}
GRANT_REQUIRED_COLUMNS = {"id", "title", "start_year"}
POLICY_REQUIRED_COLUMNS = {"id", "title", "year"}
PG_REQUIRED_COLUMNS = {"publication_id", "grant_id"}
PD_REQUIRED_COLUMNS = {"publication_id", "policy_document_id"}
IP_REQUIRED_COLUMNS = {"issuer_id", "issuer_name", "issuer_type", "issuer_country", "publication_id", "n_policy_documents"}


class NetworkAuditFailure(RuntimeError):
    """Input-contract or network-reconciliation error."""


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
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
    parser.add_argument("--top-n", type=int, default=TOP_N)
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
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return "" if text.casefold() == "nan" else " ".join(text.split())


def bool_from(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean_text(value).casefold() in {"true", "1", "yes"}


def parse_list(value: Any) -> list[Any]:
    """Parse stored Dimensions list-like values without deriving new values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() == "nan":
            return []
        for parser in (json.loads, ast.literal_eval):
            try:
                return parse_list(parser(text))
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
        return [text]
    return [value]


def display_value(value: Any) -> str:
    """Return a stored display value but never construct an identifier from it."""
    if isinstance(value, dict):
        for key in ("name", "country_name", "country", "type", "id"):
            text = clean_text(value.get(key))
            if text:
                return text
        return ""
    values = parse_list(value)
    for item in values:
        text = display_value(item) if isinstance(item, dict) else clean_text(item)
        if text:
            return text
    return ""


def normalise_countries(value: Any) -> list[str]:
    countries: list[str] = []
    for item in parse_list(value):
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("country_name") or item.get("country")
        else:
            candidate = item
        text = clean_text(candidate)
        if text:
            countries.append(text)
    return sorted(set(countries))


def scalar_or_join(value: Any, *, max_length: int = 500) -> str:
    """Render a compact stored value for local descriptive output."""
    if isinstance(value, dict):
        text = display_value(value)
    elif isinstance(value, (list, tuple, set)):
        values = [display_value(item) if isinstance(item, dict) else clean_text(item) for item in value]
        text = "; ".join(item for item in values if item)
    else:
        text = clean_text(value)
    return text[:max_length]


def gini(values: Iterable[float]) -> float | None:
    array = np.array([float(value) for value in values if value is not None and not pd.isna(value)], dtype=float)
    array = array[array >= 0]
    if len(array) == 0 or float(array.sum()) == 0:
        return None
    ordered = np.sort(array)
    n = len(ordered)
    return float((2 * np.sum(np.arange(1, n + 1) * ordered) / (n * ordered.sum())) - (n + 1) / n)


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    names = (
        "anchor_file", "grants_file", "policy_file", "publication_grant_edges_file",
        "publication_policy_edges_file", "policy_issuer_publication_edges_file",
        "relational_summary_file", "output_dir",
    )
    for name in names:
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [
        args.anchor_file, args.grants_file, args.policy_file, args.publication_grant_edges_file,
        args.publication_policy_edges_file, args.policy_issuer_publication_edges_file,
        args.relational_summary_file,
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


def require_columns(frame: pd.DataFrame, label: str, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise NetworkAuditFailure(f"{label} is missing required columns: " + ", ".join(missing))


def normalise_unique_ids(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    result = frame.copy()
    result["id"] = result["id"].map(clean_text)
    if result["id"].eq("").any() or result["id"].duplicated().any():
        raise NetworkAuditFailure(f"{label} contains blank or duplicate identifiers.")
    return result


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


def degree_table(edges: pd.DataFrame, node_column: str, weight_column: str | None = None) -> pd.DataFrame:
    if edges.empty:
        return pd.DataFrame(columns=[node_column, "unweighted_degree", "weighted_degree"])
    unweighted = edges.groupby(node_column).size().rename("unweighted_degree")
    if weight_column is None:
        weighted = unweighted.rename("weighted_degree")
    else:
        weights = pd.to_numeric(edges[weight_column], errors="raise")
        weighted = weights.groupby(edges[node_column]).sum().rename("weighted_degree")
    return pd.concat([unweighted, weighted], axis=1).reset_index()


def connected_components(edges: pd.DataFrame, left_column: str, right_column: str) -> pd.DataFrame:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for row in edges[[left_column, right_column]].drop_duplicates().itertuples(index=False):
        left = f"L::{getattr(row, left_column)}"
        right = f"R::{getattr(row, right_column)}"
        adjacency[left].add(right)
        adjacency[right].add(left)
    unseen = set(adjacency)
    rows: list[dict[str, Any]] = []
    component_id = 0
    while unseen:
        component_id += 1
        first = next(iter(unseen))
        queue: deque[str] = deque([first])
        seen = {first}
        unseen.remove(first)
        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    unseen.discard(neighbor)
                    queue.append(neighbor)
        rows.append({
            "component_id": component_id,
            "left_nodes": sum(node.startswith("L::") for node in seen),
            "right_nodes": sum(node.startswith("R::") for node in seen),
            "total_nodes": len(seen),
            "unique_edges": sum(len(adjacency[node]) for node in seen) // 2,
        })
    return pd.DataFrame(rows)


def network_statistics(
    *, network: str, left_label: str, right_label: str, edges: pd.DataFrame,
    left_column: str, right_column: str, left_total: int, right_total: int,
    weight_column: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    unique_edges = edges.drop_duplicates(subset=[left_column, right_column]).copy()
    left_degrees = degree_table(unique_edges, left_column, weight_column)
    right_degrees = degree_table(unique_edges, right_column, weight_column)
    components = connected_components(unique_edges, left_column, right_column)
    left_connected, right_connected = len(left_degrees), len(right_degrees)
    edge_total = len(unique_edges)
    largest = components.sort_values(["total_nodes", "unique_edges"], ascending=False).head(1)
    rows: list[dict[str, Any]] = []
    for partition, label, degrees, available in (
        ("left", left_label, left_degrees, left_total),
        ("right", right_label, right_degrees, right_total),
    ):
        rows.append({
            "network": network,
            "partition": partition,
            "node_type": label,
            "available_nodes": int(available),
            "connected_nodes": int(len(degrees)),
            "isolated_or_unconnected_nodes": int(available - len(degrees)),
            "unique_edges": int(edge_total),
            "weighted_edge_total": float(pd.to_numeric(unique_edges[weight_column], errors="raise").sum()) if weight_column else int(edge_total),
            "bipartite_density_among_connected_nodes": round(edge_total / (left_connected * right_connected), 8) if left_connected and right_connected else None,
            "mean_unweighted_degree": round(float(degrees["unweighted_degree"].mean()), 6) if not degrees.empty else None,
            "median_unweighted_degree": float(degrees["unweighted_degree"].median()) if not degrees.empty else None,
            "maximum_unweighted_degree": int(degrees["unweighted_degree"].max()) if not degrees.empty else None,
            "mean_weighted_degree": round(float(degrees["weighted_degree"].mean()), 6) if not degrees.empty else None,
            "median_weighted_degree": float(degrees["weighted_degree"].median()) if not degrees.empty else None,
            "maximum_weighted_degree": float(degrees["weighted_degree"].max()) if not degrees.empty else None,
            "connected_components": int(len(components)),
            "largest_component_total_nodes": int(largest.iloc[0]["total_nodes"]) if not largest.empty else 0,
            "largest_component_node_share_among_connected": round(float(largest.iloc[0]["total_nodes"]) / (left_connected + right_connected), 6) if not largest.empty and (left_connected + right_connected) else None,
        })
    concentration_rows: list[dict[str, Any]] = []
    for partition, label, degrees in (("left", left_label, left_degrees), ("right", right_label, right_degrees)):
        total_weight = float(degrees["weighted_degree"].sum()) if not degrees.empty else 0.0
        for share in CONCENTRATION_SHARES:
            k = max(1, math.ceil(len(degrees) * share)) if len(degrees) else 0
            leading_weight = float(degrees.nlargest(k, "weighted_degree")["weighted_degree"].sum()) if k else 0.0
            concentration_rows.append({
                "network": network,
                "partition": partition,
                "node_type": label,
                "connected_node_count": len(degrees),
                "top_node_share": share,
                "top_node_count": k,
                "top_nodes_weighted_edge_share": round(leading_weight / total_weight, 6) if total_weight else None,
                "weighted_degree_gini": round(gini(degrees["weighted_degree"].tolist()), 6) if len(degrees) else None,
            })
    components.insert(0, "network", network)
    return pd.DataFrame(rows), left_degrees, right_degrees, components, pd.DataFrame(concentration_rows)


def node_table(frame: pd.DataFrame, *, id_column: str, label_column: str | None, year_column: str | None, country_column: str | None) -> pd.DataFrame:
    result = pd.DataFrame({"node_id": frame[id_column].map(clean_text)})
    result["node_label"] = frame[label_column].map(scalar_or_join) if label_column and label_column in frame.columns else ""
    result["node_year"] = pd.to_numeric(frame[year_column], errors="coerce") if year_column and year_column in frame.columns else np.nan
    result["node_countries"] = frame[country_column].map(lambda value: "; ".join(normalise_countries(value))) if country_column and country_column in frame.columns else ""
    return result.drop_duplicates(subset=["node_id"])


def top_nodes(
    *, network: str, partition: str, degrees: pd.DataFrame, degree_id_column: str,
    attributes: pd.DataFrame, top_n: int,
) -> pd.DataFrame:
    output = degrees.rename(columns={degree_id_column: "node_id"}).merge(attributes, on="node_id", how="left", validate="one_to_one")
    output.insert(0, "network", network)
    output.insert(1, "partition", partition)
    return output.sort_values(["weighted_degree", "unweighted_degree", "node_id"], ascending=[False, False, True]).head(top_n)


def indexed_value(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def object_value(value: Any, keys: Iterable[str]) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        candidate = value.get(key)
        if key in {"country", "country_name", "countries", "types", "type"}:
            displayed = "; ".join(normalise_countries(candidate)) if "country" in key else scalar_or_join(candidate)
        else:
            displayed = scalar_or_join(candidate)
        if displayed:
            return displayed
    return ""


def organization_incidence(
    frame: pd.DataFrame, *, role: str, record_id_column: str,
    organization_id_column: str, name_column: str, country_column: str, type_column: str,
) -> pd.DataFrame:
    """Extract only explicitly supplied organization IDs, paired with stored attributes."""
    rows: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        record_id = clean_text(row.get(record_id_column))
        ids = parse_list(row.get(organization_id_column))
        names = parse_list(row.get(name_column))
        countries = parse_list(row.get(country_column))
        types = parse_list(row.get(type_column))
        count = max(len(ids), len(names), len(countries), len(types), 0)
        for index in range(count):
            raw_identifier = indexed_value(ids, index)
            identifier = clean_text(raw_identifier.get("id")) if isinstance(raw_identifier, dict) else clean_text(raw_identifier)
            if not identifier:
                continue
            embedded_name = object_value(raw_identifier, ("name",))
            embedded_country = object_value(raw_identifier, ("country_name", "country", "countries"))
            embedded_type = object_value(raw_identifier, ("types", "type"))
            country_values = normalise_countries(indexed_value(countries, index))
            rows.append({
                "role": role,
                "record_id": record_id,
                "organization_id": identifier,
                "organization_name": embedded_name or scalar_or_join(indexed_value(names, index)),
                "organization_countries": embedded_country or "; ".join(country_values),
                "organization_type": embedded_type or scalar_or_join(indexed_value(types, index)),
            })
    columns = ["role", "record_id", "organization_id", "organization_name", "organization_countries", "organization_type"]
    result = pd.DataFrame(rows, columns=columns)
    return result.drop_duplicates(subset=["role", "record_id", "organization_id"]).sort_values(columns[:3]).reset_index(drop=True)


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def organization_representation(incidence: pd.DataFrame) -> pd.DataFrame:
    if incidence.empty:
        return pd.DataFrame(columns=[
            "role", "organization_id", "organization_name", "organization_type", "organization_countries",
            "distinct_associated_records", "role_rank_by_distinct_associated_records", "identity_boundary",
        ])
    rows: list[dict[str, Any]] = []
    for (role, organization_id), group in incidence.groupby(["role", "organization_id"], sort=True):
        names = sorted({clean_text(value) for value in group["organization_name"] if clean_text(value)})
        types = sorted({clean_text(value) for value in group["organization_type"] if clean_text(value)})
        countries = sorted({country for value in group["organization_countries"] for country in normalise_countries(value)})
        rows.append({
            "role": role,
            "organization_id": organization_id,
            "organization_name": names[0] if names else "",
            "organization_name_variants": " | ".join(names),
            "organization_type": types[0] if types else "",
            "organization_type_variants": " | ".join(types),
            "organization_countries": " | ".join(countries),
            "distinct_associated_records": int(group["record_id"].nunique()),
            "identity_boundary": "Organization identity is based only on an explicit Dimensions organization ID within this role; names are descriptive attributes and are not used to merge roles.",
        })
    result = pd.DataFrame(rows).sort_values(["role", "distinct_associated_records", "organization_id"], ascending=[True, False, True])
    result["role_rank_by_distinct_associated_records"] = result.groupby("role").cumcount() + 1
    return result


def role_attribute_coverage(
    frame: pd.DataFrame, *, role: str, record_id_column: str, id_column: str,
    name_column: str, country_column: str, type_column: str,
) -> dict[str, Any]:
    def present_list(value: Any) -> bool:
        return bool(parse_list(value))
    identifiers = frame[id_column].map(present_list) if id_column in frame.columns else pd.Series(False, index=frame.index)
    names = frame[name_column].map(present_list) if name_column in frame.columns else pd.Series(False, index=frame.index)
    countries = frame[country_column].map(present_list) if country_column in frame.columns else pd.Series(False, index=frame.index)
    types = frame[type_column].map(present_list) if type_column in frame.columns else pd.Series(False, index=frame.index)
    return {
        "role": role,
        "available_source_records_or_nodes": len(frame),
        "records_or_nodes_with_organization_id_field": int(identifiers.sum()),
        "records_or_nodes_with_organization_name_field": int(names.sum()),
        "records_or_nodes_with_organization_country_field": int(countries.sum()),
        "records_or_nodes_with_organization_type_field": int(types.sum()),
        "role_identity_rule": "Only an explicit Dimensions organization ID defines an organization node within this role; no name-based resolution is performed.",
    }


def country_representation(frame: pd.DataFrame, *, source: str, country_column: str) -> pd.DataFrame:
    counter: Counter[str] = Counter()
    represented = 0
    for value in frame[country_column] if country_column in frame.columns else []:
        countries = normalise_countries(value)
        if countries:
            represented += 1
            counter.update(countries)
    rows = [{
        "source_role": source,
        "country": country,
        "nodes_or_records_with_country": count,
        "available_nodes_or_records": len(frame),
        "nodes_or_records_with_at_least_one_country": represented,
        "percentage_of_all_nodes_or_records": round(100 * count / len(frame), 3) if len(frame) else None,
        "multi_country_counting_note": "A node or record may contribute once to each stored country; percentages need not sum to 100.",
    } for country, count in counter.most_common()]
    return pd.DataFrame(rows, columns=[
        "source_role", "country", "nodes_or_records_with_country", "available_nodes_or_records",
        "nodes_or_records_with_at_least_one_country", "percentage_of_all_nodes_or_records", "multi_country_counting_note",
    ])


def main() -> None:
    try:
        args = parse_args()
        if args.expected_publication_records < 1 or args.top_n < 1:
            raise ValueError("--expected-publication-records and --top-n must be positive.")
        args = preflight_paths(args)
        input_paths = {
            "publication_anchor": args.anchor_file,
            "linked_grants": args.grants_file,
            "linked_policy_documents": args.policy_file,
            "publication_grant_edges": args.publication_grant_edges_file,
            "publication_policy_edges": args.publication_policy_edges_file,
            "policy_issuer_publication_edges": args.policy_issuer_publication_edges_file,
            "relational_summary": args.relational_summary_file,
        }
        input_hashes = {name: sha256(path) for name, path in input_paths.items()}

        P = normalise_unique_ids(pd.read_pickle(args.anchor_file), "Publication anchor")
        G = normalise_unique_ids(pd.read_pickle(args.grants_file), "Linked grants")
        D = normalise_unique_ids(pd.read_pickle(args.policy_file), "Linked policy documents")
        pg = pd.read_csv(args.publication_grant_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        pd_edges = pd.read_csv(args.publication_policy_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        ip = pd.read_csv(args.policy_issuer_publication_edges_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        summary = json.loads(args.relational_summary_file.read_text(encoding="utf-8"))
        if not isinstance(summary, dict) or summary.get("status") != "complete":
            raise NetworkAuditFailure("Relational summary must be a completed JSON object.")
        require_columns(P, "Publication anchor", ANCHOR_REQUIRED_COLUMNS)
        require_columns(G, "Linked grants", GRANT_REQUIRED_COLUMNS)
        require_columns(D, "Linked policy documents", POLICY_REQUIRED_COLUMNS)
        require_columns(pg, "Publication-grant edges", PG_REQUIRED_COLUMNS)
        require_columns(pd_edges, "Publication-policy-document edges", PD_REQUIRED_COLUMNS)
        require_columns(ip, "Policy-issuer-publication edges", IP_REQUIRED_COLUMNS)
        if len(P) != args.expected_publication_records:
            raise NetworkAuditFailure(f"Expected {args.expected_publication_records} final publications; found {len(P)}.")
        if not P["retain_in_final_P"].map(bool_from).all():
            raise NetworkAuditFailure("Publication anchor includes a record outside final P.")

        for frame, columns in ((pg, ["publication_id", "grant_id"]), (pd_edges, ["publication_id", "policy_document_id"]), (ip, ["issuer_id", "publication_id"])):
            for column in columns:
                frame[column] = frame[column].map(clean_text)
            if frame[columns].eq("").any().any():
                raise NetworkAuditFailure("An edge table contains a blank endpoint ID.")
        for field in ("issuer_name", "issuer_type", "issuer_country"):
            ip[field] = ip[field].map(clean_text)
        ip["n_policy_documents"] = pd.to_numeric(ip["n_policy_documents"], errors="coerce")
        if ip["n_policy_documents"].isna().any() or (ip["n_policy_documents"] < 1).any() or (ip["n_policy_documents"] % 1 != 0).any():
            raise NetworkAuditFailure("Policy issuer--publication edge weights must be positive integer policy-document counts.")
        ip["n_policy_documents"] = ip["n_policy_documents"].astype(int)
        if pg.duplicated(subset=["publication_id", "grant_id"]).any() or pd_edges.duplicated(subset=["publication_id", "policy_document_id"]).any() or ip.duplicated(subset=["issuer_id", "publication_id"]).any():
            raise NetworkAuditFailure("Audited edge list contains a duplicate endpoint pair.")

        P_ids, G_ids, D_ids = set(P["id"]), set(G["id"]), set(D["id"])
        endpoint_checks = {
            "publication_grant": int((~pg["publication_id"].isin(P_ids)).sum()) + int((~pg["grant_id"].isin(G_ids)).sum()),
            "publication_policy_document": int((~pd_edges["publication_id"].isin(P_ids)).sum()) + int((~pd_edges["policy_document_id"].isin(D_ids)).sum()),
            "policy_issuer_publication": int((~ip["publication_id"].isin(P_ids)).sum()),
        }
        if any(endpoint_checks.values()):
            raise NetworkAuditFailure("One or more audited edges have endpoints outside the supplied final node tables.")
        record_counts = summary.get("record_counts", {})
        edge_counts = summary.get("edge_counts", {})
        if record_counts.get("final_publications_P") != len(P) or record_counts.get("linked_grants_G") != len(G) or record_counts.get("linked_policy_documents_D") != len(D):
            raise NetworkAuditFailure("Relational summary record counts do not reconcile to supplied P, G, and D tables.")
        for name, observed in (("publication_grant", len(pg)), ("publication_policy_document", len(pd_edges)), ("policy_issuer_publication", len(ip))):
            if edge_counts.get(name) != observed:
                raise NetworkAuditFailure(f"Relational summary edge count for {name} does not reconcile to supplied edge list.")
        if int(ip["n_policy_documents"].sum()) > len(pd_edges):
            raise NetworkAuditFailure("Issuer--publication policy-document weights exceed the number of retained publication--policy edges.")

        network_rows: list[pd.DataFrame] = []
        concentration_rows: list[pd.DataFrame] = []
        component_rows: list[pd.DataFrame] = []
        top_node_rows: list[pd.DataFrame] = []
        P_nodes = node_table(P, id_column="id", label_column="title", year_column="year", country_column="research_org_countries")
        G_nodes = node_table(G, id_column="id", label_column="title", year_column="start_year", country_column="funder_org_countries")
        D_nodes = node_table(D, id_column="id", label_column="title", year_column="year", country_column="publisher_org_country")
        issuer_nodes = ip[["issuer_id", "issuer_name", "issuer_type", "issuer_country"]].drop_duplicates(subset=["issuer_id"]).rename(columns={"issuer_id": "node_id", "issuer_name": "node_label", "issuer_type": "node_type_attribute", "issuer_country": "node_countries"})
        issuer_nodes["node_year"] = np.nan
        issuer_nodes["node_countries"] = issuer_nodes["node_countries"].map(lambda value: "; ".join(normalise_countries(value)))
        issuer_nodes = issuer_nodes[["node_id", "node_label", "node_year", "node_countries", "node_type_attribute"]]

        for specification in (
            ("publication_grant", "publication", "grant", pg, "publication_id", "grant_id", len(P), len(G), None, P_nodes, G_nodes),
            ("publication_policy_document", "publication", "policy_document", pd_edges, "publication_id", "policy_document_id", len(P), len(D), None, P_nodes, D_nodes),
            ("policy_issuer_publication", "policy_issuer", "publication", ip, "issuer_id", "publication_id", len(issuer_nodes), len(P), "n_policy_documents", issuer_nodes, P_nodes),
        ):
            network, left_label, right_label, edges, left_column, right_column, left_total, right_total, weight_column, left_attributes, right_attributes = specification
            stats, left_degrees, right_degrees, components, concentration = network_statistics(
                network=network, left_label=left_label, right_label=right_label, edges=edges,
                left_column=left_column, right_column=right_column, left_total=left_total,
                right_total=right_total, weight_column=weight_column,
            )
            network_rows.append(stats)
            concentration_rows.append(concentration)
            component_rows.append(components)
            top_node_rows.append(top_nodes(network=network, partition="left", degrees=left_degrees, degree_id_column=left_column, attributes=left_attributes, top_n=args.top_n))
            top_node_rows.append(top_nodes(network=network, partition="right", degrees=right_degrees, degree_id_column=right_column, attributes=right_attributes, top_n=args.top_n))

        # Keep affiliations, funders, grant-recipient organizations, and policy issuers role-separated.
        affiliation_incidence = organization_incidence(
            P, role="publication_affiliation_organization", record_id_column="id", organization_id_column="research_orgs",
            name_column="research_org_names", country_column="research_org_countries", type_column="research_org_types",
        )
        funder_incidence = organization_incidence(
            G, role="linked_grant_funder_organization", record_id_column="id", organization_id_column="funder_orgs",
            name_column="funder_org_name", country_column="funder_org_countries", type_column="funder_org_types",
        )
        recipient_incidence = organization_incidence(
            G, role="linked_grant_recipient_organization", record_id_column="id", organization_id_column="research_orgs",
            name_column="research_org_names", country_column="research_org_countries", type_column="research_org_types",
        )
        issuer_incidence = ip.rename(columns={"issuer_id": "organization_id", "publication_id": "record_id", "issuer_name": "organization_name", "issuer_country": "organization_countries", "issuer_type": "organization_type"})[
            ["record_id", "organization_id", "organization_name", "organization_countries", "organization_type"]
        ].copy()
        issuer_incidence.insert(0, "role", "policy_issuer_organization")
        all_organization_incidence = pd.concat([affiliation_incidence, funder_incidence, recipient_incidence, issuer_incidence], ignore_index=True)
        organization_summary = organization_representation(all_organization_incidence)
        coverage_rows = [
            role_attribute_coverage(P, role="publication_affiliation_organization", record_id_column="id", id_column="research_orgs", name_column="research_org_names", country_column="research_org_countries", type_column="research_org_types"),
            role_attribute_coverage(G, role="linked_grant_funder_organization", record_id_column="id", id_column="funder_orgs", name_column="funder_org_name", country_column="funder_org_countries", type_column="funder_org_types"),
            role_attribute_coverage(G, role="linked_grant_recipient_organization", record_id_column="id", id_column="research_orgs", name_column="research_org_names", country_column="research_org_countries", type_column="research_org_types"),
            role_attribute_coverage(issuer_nodes.rename(columns={"node_id": "issuer_id", "node_label": "issuer_name", "node_countries": "issuer_country", "node_type_attribute": "issuer_type"}), role="policy_issuer_organization", record_id_column="issuer_id", id_column="issuer_id", name_column="issuer_name", country_column="issuer_country", type_column="issuer_type"),
        ]
        organization_coverage = pd.DataFrame(coverage_rows)
        issuer_representation = (
            ip.groupby(["issuer_id", "issuer_name", "issuer_type", "issuer_country"], dropna=False)
            .agg(
                distinct_linked_publications=("publication_id", "nunique"),
                issuer_publication_pairs=("publication_id", "size"),
                recorded_linked_policy_documents=("n_policy_documents", "sum"),
            )
            .reset_index()
            .sort_values(["distinct_linked_publications", "recorded_linked_policy_documents", "issuer_id"], ascending=[False, False, True])
        )
        issuer_representation["issuer_rank_by_linked_publications"] = range(1, len(issuer_representation) + 1)
        issuer_representation["interpretive_boundary"] = "Describes Dimensions-recorded publisher-organization links only; not policy influence, endorsement, policy impact, or institutional intent."

        country_frames = [
            country_representation(P, source="publication_affiliation_countries", country_column="research_org_countries"),
            country_representation(G, source="linked_grant_funder_countries", country_column="funder_org_countries"),
            country_representation(G, source="linked_grant_recipient_organization_countries", country_column="research_org_countries"),
            country_representation(issuer_nodes, source="policy_issuer_countries", country_column="node_countries"),
        ]
        country_summary = pd.concat(country_frames, ignore_index=True)
        network_basic = pd.concat(network_rows, ignore_index=True)
        network_concentration = pd.concat(concentration_rows, ignore_index=True)
        network_components = pd.concat(component_rows, ignore_index=True)
        network_top = pd.concat(top_node_rows, ignore_index=True)
        coverage_gap = len(pd_edges) - int(ip["n_policy_documents"].sum())
        validation = pd.DataFrame([
            {"check": "final_publication_record_count", "passed": len(P) == args.expected_publication_records, "detail": ""},
            {"check": "relational_summary_counts_reconcile", "passed": True, "detail": ""},
            {"check": "publication_grant_endpoints_valid", "passed": endpoint_checks["publication_grant"] == 0, "detail": ""},
            {"check": "publication_policy_document_endpoints_valid", "passed": endpoint_checks["publication_policy_document"] == 0, "detail": ""},
            {"check": "policy_issuer_publication_endpoints_valid", "passed": endpoint_checks["policy_issuer_publication"] == 0, "detail": ""},
            {"check": "policy_issuer_edge_weights_positive_integers", "passed": bool((ip["n_policy_documents"] >= 1).all()), "detail": ""},
            {"check": "issuer_policy_weight_not_greater_than_policy_edges", "passed": coverage_gap >= 0, "detail": f"{coverage_gap} retained P--D edges are not represented by a valid issuer--P weighted tie, if positive."},
            {"check": "organization_roles_not_name_merged", "passed": True, "detail": "Organization identity uses explicit IDs within role only; no cross-role or name-based resolution is performed."},
            {"check": "final_result", "passed": True, "detail": "All outputs are descriptive record-link representations only."},
        ])

        outputs = {
            "network_basic_statistics.csv": network_basic,
            "network_degree_concentration.csv": network_concentration,
            "network_components.csv": network_components,
            "network_top_nodes.csv": network_top,
            "organization_role_incidence.csv": all_organization_incidence,
            "organization_role_representation.csv": organization_summary,
            "organization_role_attribute_coverage.csv": organization_coverage,
            "policy_issuer_representation.csv": issuer_representation,
            "country_representation.csv": country_summary,
            "network_validation_checks.csv": validation,
        }
        for filename, frame in outputs.items():
            atomic_write_csv(args.output_dir / filename, frame)
        manifest = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "input_files": {name: {"path": str(path), "sha256": input_hashes[name]} for name, path in input_paths.items()},
            "record_counts": {"final_publications_P": len(P), "linked_grants_G": len(G), "linked_policy_documents_D": len(D), "policy_issuer_nodes": len(issuer_nodes)},
            "edge_counts": {"publication_grant": len(pg), "publication_policy_document": len(pd_edges), "policy_issuer_publication": len(ip), "policy_issuer_publication_weight_sum": int(ip["n_policy_documents"].sum())},
            "networks": {
                "publication_grant": "Unique audited publication--grant identifier pairs.",
                "publication_policy_document": "Unique audited publication--policy-document identifier pairs.",
                "policy_issuer_publication": "Unique audited issuer--publication pairs, weighted by the recorded count of linked policy documents.",
            },
            "role_separation": "Publication affiliation organizations, grant funder organizations, grant recipient organizations, and policy issuer organizations are separate roles. No organization ID or name is used to merge roles.",
            "country_counting": "Countries are non-exclusive counts from stored Dimensions attributes. A node or record can contribute to multiple countries, so percentages do not sum to 100.",
            "interpretive_boundary": "Network topology, organization representation, and country representation describe Dimensions-recorded identifiers and attributes only. They do not establish influence, institutional preference, intentional selection, causal funding, policy uptake, policy impact, endorsement, knowledge translation, or semantic affinity.",
            "data_boundary": "All network, organization, and country outputs are protected local data and must not be committed to GitHub.",
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(frame)} for name, frame in outputs.items()},
        }
        atomic_write_json(args.output_dir / "network_analysis_manifest.json", manifest)

        pg_stats = network_basic.loc[(network_basic["network"] == "publication_grant") & (network_basic["partition"] == "left")].iloc[0]
        pd_stats = network_basic.loc[(network_basic["network"] == "publication_policy_document") & (network_basic["partition"] == "left")].iloc[0]
        ip_stats = network_basic.loc[(network_basic["network"] == "policy_issuer_publication") & (network_basic["partition"] == "left")].iloc[0]
        print("FAIRIFICATION NETWORKS, ORGANIZATIONS, AND COUNTRIES: PASS")
        print(f"FINAL PUBLICATIONS: {len(P)}")
        print(f"PUBLICATION-GRANT NETWORK: {int(pg_stats['unique_edges'])} edges; {int(pg_stats['connected_nodes'])} linked publications")
        print(f"PUBLICATION-POLICY-DOCUMENT NETWORK: {int(pd_stats['unique_edges'])} edges; {int(pd_stats['connected_nodes'])} linked publications")
        print(f"POLICY-ISSUER-PUBLICATION NETWORK: {int(ip_stats['unique_edges'])} unique edges; {int(ip_stats['weighted_edge_total'])} policy-document weight")
        print(f"PUBLICATION-AFFILIATION ORGANIZATION IDS: {int((organization_summary['role'] == 'publication_affiliation_organization').sum())}")
        print(f"GRANT-FUNDER ORGANIZATION IDS: {int((organization_summary['role'] == 'linked_grant_funder_organization').sum())}")
        print(f"POLICY-ISSUER ORGANIZATION IDS: {int((organization_summary['role'] == 'policy_issuer_organization').sum())}")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"MANIFEST: {args.output_dir / 'network_analysis_manifest.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

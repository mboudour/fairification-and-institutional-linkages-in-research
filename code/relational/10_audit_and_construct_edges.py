#!/usr/bin/env python3
"""Audit the frozen FAIRification relational data and construct identifier-based edges.

This no-API script is the FAIRification adaptation of the prior project's
`step1_v6_audit_and_edges_v2.py`. It validates the final publication anchor (P),
linked grants (G), linked policy documents (D), and their retrieval manifests.
It also reconciles the 144-record Dimensions analytic subset to the frozen
163-record source-coverage audit.

Only recorded Dimensions identifiers are used to construct:
  * P-G: publication `supporting_grant_ids` intersected with final grant IDs;
  * P-D: policy-document `publication_ids` intersected with final P IDs; and
  * issuer-P: publisher organization IDs joined through retained P-D edges.

It makes no Dimensions requests, does not inspect policy full text, and does not
estimate associations or causal effects. All output files are protected local
data and must not be committed to GitHub.

Example:
    python code/relational/10_audit_and_construct_edges.py \
      --anchor-file /path/to/publication_anchor_final_run.pkl \
      --anchor-manifest-file /path/to/publication_anchor_retrieval_manifest_run.json \
      --grants-file /path/to/linked_grants_final_run.pkl \
      --grants-manifest-file /path/to/linked_grants_retrieval_manifest_run.json \
      --policy-file /path/to/linked_policy_documents_final_run.pkl \
      --policy-manifest-file /path/to/linked_policy_documents_retrieval_manifest_run.json \
      --coverage-overall-file /path/to/source_dimensions_coverage_overall.csv \
      --coverage-record-level-file /path/to/source_dimensions_coverage_record_level.csv \
      --output-dir /path/to/computations/outputs/10_relational_audit_and_edges_run
"""

from __future__ import annotations

import argparse
import ast
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

import pandas as pd


SCRIPT_VERSION = "10_audit_and_construct_edges_1.0"
EXPECTED_SOURCE_RECORDS = 163
EXPECTED_PUBLICATION_RECORDS = 144
ANCHOR_REQUIRED_COLUMNS = {"id", "source_record_id", "year", "title", "supporting_grant_ids", "retain_in_final_P"}
GRANTS_REQUIRED_COLUMNS = {"id", "start_year", "title", "retrieved_from_publication_ids", "grant_retrieval_status"}
POLICY_REQUIRED_COLUMNS = {"id", "year", "title", "publication_ids", "publisher_org", "retrieved_by_publication_ids", "policy_retrieval_status"}
COVERAGE_OVERALL_REQUIRED_COLUMNS = {
    "source_cohort_records", "dimensions_recovered_analytic_records", "not_recovered_by_doi_first_procedure",
    "dimensions_recovery_rate_pct", "manual_addition_recovered",
}
COVERAGE_RECORD_REQUIRED_COLUMNS = {"source_record_id", "source_record_origin", "in_dimensions_analytic_subset", "coverage_status"}


class AuditFailure(RuntimeError):
    """An input-contract or relational-integrity error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-file", type=Path, required=True)
    parser.add_argument("--anchor-manifest-file", type=Path, required=True)
    parser.add_argument("--grants-file", type=Path, required=True)
    parser.add_argument("--grants-manifest-file", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--policy-manifest-file", type=Path, required=True)
    parser.add_argument("--coverage-overall-file", type=Path, required=True)
    parser.add_argument("--coverage-record-level-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source-records", type=int, default=EXPECTED_SOURCE_RECORDS)
    parser.add_argument("--expected-publication-records", type=int, default=EXPECTED_PUBLICATION_RECORDS)
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


def parse_list(value: Any) -> list[Any]:
    """Parse stored list-like values without splitting or inventing IDs."""
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
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
                parsed = parser(text)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
            return parse_list(parsed)
        return [text]
    return [value]


def id_list(value: Any) -> list[str]:
    """Extract explicit IDs from list-like values; never derive one from free text."""
    output: list[str] = []
    for item in parse_list(value):
        identifier = clean_text(item.get("id")) if isinstance(item, dict) else clean_text(item)
        if identifier and identifier not in output:
            output.append(identifier)
    return output


def value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    if isinstance(value, str):
        return bool(clean_text(value))
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return True


def display_value(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("country_name") or value.get("country") or value.get("id"))
    values = parse_list(value)
    for item in values:
        text = display_value(item) if isinstance(item, dict) else clean_text(item)
        if text:
            return text
    return ""


def normalise_id_column(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    result = frame.copy()
    result["id"] = result["id"].map(clean_text)
    if result["id"].eq("").any():
        raise AuditFailure(f"{label} contains a blank identifier.")
    if result["id"].duplicated().any():
        raise AuditFailure(f"{label} contains duplicate identifiers.")
    return result


def require_columns(frame: pd.DataFrame, label: str, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise AuditFailure(f"{label} is missing required columns: " + ", ".join(missing))


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, possible_parent: Path) -> bool:
    return path == possible_parent or possible_parent in path.parents


def preflight_paths(args: argparse.Namespace) -> argparse.Namespace:
    names = (
        "anchor_file", "anchor_manifest_file", "grants_file", "grants_manifest_file", "policy_file",
        "policy_manifest_file", "coverage_overall_file", "coverage_record_level_file", "output_dir",
    )
    for name in names:
        setattr(args, name, resolved(getattr(args, name)))
    inputs = [
        args.anchor_file, args.anchor_manifest_file, args.grants_file, args.grants_manifest_file,
        args.policy_file, args.policy_manifest_file, args.coverage_overall_file, args.coverage_record_level_file,
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
            f"Output directory is not empty: {args.output_dir}. Choose a new empty directory; this script never deletes audit outputs."
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


def read_csv(path: Path, required: set[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    require_columns(frame, label, required)
    return frame


def read_json(path: Path, label: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AuditFailure(f"{label} must be a JSON object.")
    return data


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


def field_coverage(frame: pd.DataFrame, dataset: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in frame.columns:
        present = int(frame[field].map(value_present).sum())
        rows.append({
            "dataset": dataset,
            "field": field,
            "records": len(frame),
            "present_n": present,
            "present_share": round(present / len(frame), 6) if len(frame) else None,
        })
    return rows


def extract_issuer(policy_row: pd.Series) -> dict[str, str] | None:
    """Use publisher organization identifiers only when Dimensions supplies them."""
    flattened_id = clean_text(policy_row.get("publisher_org.id"))
    if flattened_id:
        return {
            "issuer_id": flattened_id,
            "issuer_name": clean_text(policy_row.get("publisher_org.name")),
            "issuer_type": display_value(policy_row.get("publisher_org.types")),
            "issuer_country": display_value(policy_row.get("publisher_org.country_name")) or display_value(policy_row.get("publisher_org_country.name")),
        }
    for candidate in parse_list(policy_row.get("publisher_org")):
        if not isinstance(candidate, dict):
            continue
        identifier = clean_text(candidate.get("id"))
        if not identifier:
            continue
        return {
            "issuer_id": identifier,
            "issuer_name": clean_text(candidate.get("name")),
            "issuer_type": display_value(candidate.get("types") or candidate.get("type")),
            "issuer_country": display_value(policy_row.get("publisher_org_country")) or clean_text(candidate.get("country_name") or candidate.get("country")),
        }
    return None


def year_audit(frame: pd.DataFrame, dataset: str, field: str) -> dict[str, Any]:
    years = pd.to_numeric(frame[field], errors="coerce")
    return {
        "dataset": dataset,
        "year_field": field,
        "records": len(frame),
        "missing_or_non_numeric_year_n": int(years.isna().sum()),
        "minimum_observed_year": int(years.min()) if years.notna().any() else None,
        "maximum_observed_year": int(years.max()) if years.notna().any() else None,
        "year_window_rule": "Descriptive only; no fixed 2025 endpoint is imposed. The policy endpoint is the actual retrieval endpoint.",
    }


def status_bool(value: Any) -> bool:
    return clean_text(value).casefold() == "returned"


def main() -> None:
    try:
        args = parse_args()
        if args.expected_source_records < 1 or args.expected_publication_records < 1:
            raise ValueError("Expected record counts must be positive.")
        args = preflight_paths(args)
        input_paths = {
            "publication_anchor": args.anchor_file,
            "publication_anchor_manifest": args.anchor_manifest_file,
            "linked_grants": args.grants_file,
            "linked_grants_manifest": args.grants_manifest_file,
            "linked_policy_documents": args.policy_file,
            "linked_policy_documents_manifest": args.policy_manifest_file,
            "source_dimensions_coverage_overall": args.coverage_overall_file,
            "source_dimensions_coverage_record_level": args.coverage_record_level_file,
        }
        input_hashes = {name: sha256(path) for name, path in input_paths.items()}

        P = normalise_id_column(pd.read_pickle(args.anchor_file), "Publication anchor P")
        G = normalise_id_column(pd.read_pickle(args.grants_file), "Linked grants G")
        D = normalise_id_column(pd.read_pickle(args.policy_file), "Linked policy documents D")
        anchor_manifest = read_json(args.anchor_manifest_file, "Publication-anchor manifest")
        grants_manifest = read_json(args.grants_manifest_file, "Linked-grants manifest")
        policy_manifest = read_json(args.policy_manifest_file, "Policy-document manifest")
        coverage_overall = read_csv(args.coverage_overall_file, COVERAGE_OVERALL_REQUIRED_COLUMNS, "Source-coverage overall table")
        coverage_record = read_csv(args.coverage_record_level_file, COVERAGE_RECORD_REQUIRED_COLUMNS, "Source-coverage record-level table")

        require_columns(P, "Publication anchor P", ANCHOR_REQUIRED_COLUMNS)
        require_columns(G, "Linked grants G", GRANTS_REQUIRED_COLUMNS)
        require_columns(D, "Linked policy documents D", POLICY_REQUIRED_COLUMNS)
        if len(P) != args.expected_publication_records:
            raise AuditFailure(f"Expected {args.expected_publication_records} final publication records; found {len(P)}.")
        if not P["retain_in_final_P"].map(bool_from).all():
            raise AuditFailure("Publication anchor includes a record outside the approved final P set.")
        if not G["grant_retrieval_status"].map(status_bool).all():
            raise AuditFailure("Linked grants table includes a non-returned grant record.")
        if not D["policy_retrieval_status"].map(status_bool).all():
            raise AuditFailure("Linked policy-document table includes a non-returned policy record.")

        if anchor_manifest.get("outputs", {}).get("returned_records") != len(P) or anchor_manifest.get("outputs", {}).get("unreturned_records") != 0:
            raise AuditFailure("Publication-anchor manifest does not certify the supplied complete P table.")
        if grants_manifest.get("outputs", {}).get("returned_grant_records") != len(G) or grants_manifest.get("outputs", {}).get("unreturned_grant_ids") != 0:
            raise AuditFailure("Linked-grants manifest does not certify the supplied complete G table.")
        if policy_manifest.get("outputs", {}).get("unique_policy_documents_returned") != len(D):
            raise AuditFailure("Policy-document manifest does not certify the supplied D table.")
        if any(manifest.get("status") != "complete" for manifest in (anchor_manifest, grants_manifest, policy_manifest)):
            raise AuditFailure("One or more relational retrieval manifests are not marked complete.")

        if len(coverage_overall) != 1:
            raise AuditFailure("Source-coverage overall table must have exactly one row.")
        coverage_row = coverage_overall.iloc[0]
        source_n = int(pd.to_numeric(coverage_row["source_cohort_records"], errors="raise"))
        recovered_n = int(pd.to_numeric(coverage_row["dimensions_recovered_analytic_records"], errors="raise"))
        unresolved_n = int(pd.to_numeric(coverage_row["not_recovered_by_doi_first_procedure"], errors="raise"))
        if source_n != args.expected_source_records or recovered_n != len(P) or unresolved_n != source_n - recovered_n:
            raise AuditFailure("Source-coverage overall summary does not reconcile to the frozen 163-to-144 design.")
        if not bool_from(coverage_row["manual_addition_recovered"]):
            raise AuditFailure("Source-coverage audit does not confirm recovery of the documented manual addition.")
        coverage_record["source_record_id"] = coverage_record["source_record_id"].map(clean_text)
        if len(coverage_record) != source_n or coverage_record["source_record_id"].eq("").any() or coverage_record["source_record_id"].duplicated().any():
            raise AuditFailure("Source-coverage record-level audit has an invalid source-record denominator or identifiers.")
        record_recovered_n = int(coverage_record["in_dimensions_analytic_subset"].map(bool_from).sum())
        if record_recovered_n != recovered_n:
            raise AuditFailure("Source-coverage record-level and overall recovered counts disagree.")
        manual_addition = coverage_record.loc[
            coverage_record["source_record_origin"].map(clean_text).eq("documented_manual_addition")
        ]
        if len(manual_addition) != 1 or not bool_from(manual_addition.iloc[0]["in_dimensions_analytic_subset"]):
            raise AuditFailure("Source-coverage audit must contain exactly one recovered documented manual addition.")
        P["source_record_id"] = P["source_record_id"].map(clean_text)
        if P["source_record_id"].eq("").any() or P["source_record_id"].duplicated().any():
            raise AuditFailure("Publication anchor has blank or duplicate source_record_id values.")
        recovered_source_ids = set(
            coverage_record.loc[coverage_record["in_dimensions_analytic_subset"].map(bool_from), "source_record_id"]
        )
        if set(P["source_record_id"]) != recovered_source_ids:
            raise AuditFailure("Publication-anchor source_record_id values do not exactly equal the recovered source-record set in the coverage audit.")

        P_ids, G_ids, D_ids = set(P["id"]), set(G["id"]), set(D["id"])
        duplicate_checks = pd.DataFrame([
            {"dataset": "final_publications_P", "rows": len(P), "unique_ids": P["id"].nunique(), "duplicate_id_rows": int(P["id"].duplicated().sum())},
            {"dataset": "linked_grants_G", "rows": len(G), "unique_ids": G["id"].nunique(), "duplicate_id_rows": int(G["id"].duplicated().sum())},
            {"dataset": "linked_policy_documents_D", "rows": len(D), "unique_ids": D["id"].nunique(), "duplicate_id_rows": int(D["id"].duplicated().sum())},
        ])
        years = pd.DataFrame([
            year_audit(P, "final_publications_P", "year"),
            year_audit(G, "linked_grants_G", "start_year"),
            year_audit(D, "linked_policy_documents_D", "year"),
        ])

        # P-G edges are strictly the anchor's recorded supporting-grant IDs intersected with final G.
        raw_pg_rows: list[dict[str, str]] = []
        for _, record in P[["id", "supporting_grant_ids"]].iterrows():
            for grant_id in id_list(record["supporting_grant_ids"]):
                raw_pg_rows.append({"publication_id": record["id"], "grant_id": grant_id})
        raw_pg = pd.DataFrame(raw_pg_rows, columns=["publication_id", "grant_id"])
        pg_unique = raw_pg.drop_duplicates().reset_index(drop=True)
        pg_edges = pg_unique.loc[pg_unique["grant_id"].isin(G_ids)].reset_index(drop=True)
        pg_not_retrieved = pg_unique.loc[~pg_unique["grant_id"].isin(G_ids)].reset_index(drop=True)

        grant_provenance_by_id = {row["id"]: set(id_list(row["retrieved_from_publication_ids"])) for _, row in G.iterrows()}
        pg_provenance_mismatches = pd.DataFrame([
            {"publication_id": row.publication_id, "grant_id": row.grant_id, "reason": "Grant retrieval provenance does not list this retained publication."}
            for row in pg_edges.itertuples(index=False)
            if row.publication_id not in grant_provenance_by_id.get(row.grant_id, set())
        ], columns=["publication_id", "grant_id", "reason"])

        # P-D edges are strictly the policy records' publication_ids intersected with final P.
        raw_pd_rows: list[dict[str, str]] = []
        for _, record in D[["id", "publication_ids"]].iterrows():
            for publication_id in id_list(record["publication_ids"]):
                raw_pd_rows.append({"policy_document_id": record["id"], "publication_id": publication_id})
        raw_pd = pd.DataFrame(raw_pd_rows, columns=["policy_document_id", "publication_id"])
        pd_unique = raw_pd.drop_duplicates().reset_index(drop=True)
        pd_edges = pd_unique.loc[pd_unique["publication_id"].isin(P_ids)].reset_index(drop=True)
        pd_non_p = pd_unique.loc[~pd_unique["publication_id"].isin(P_ids)].reset_index(drop=True)

        policy_provenance_by_id = {row["id"]: set(id_list(row["retrieved_by_publication_ids"])) for _, row in D.iterrows()}
        pd_provenance_mismatches = pd.DataFrame([
            {"policy_document_id": row.policy_document_id, "publication_id": row.publication_id, "reason": "Policy retrieval provenance does not list this retained publication."}
            for row in pd_edges.itertuples(index=False)
            if row.publication_id not in policy_provenance_by_id.get(row.policy_document_id, set())
        ], columns=["policy_document_id", "publication_id", "reason"])

        # Publisher-to-publication incidences are derived only through retained P-D edges.
        policy_by_id = D.set_index("id", drop=False)
        issuer_rows: list[dict[str, str]] = []
        missing_issuer_ids: list[str] = []
        for policy_id, group in pd_edges.groupby("policy_document_id", sort=False):
            issuer = extract_issuer(policy_by_id.loc[policy_id])
            if issuer is None:
                missing_issuer_ids.append(policy_id)
                continue
            for publication_id in group["publication_id"]:
                issuer_rows.append({**issuer, "policy_document_id": policy_id, "publication_id": publication_id})
        issuer_incidence = pd.DataFrame(
            issuer_rows,
            columns=["issuer_id", "issuer_name", "issuer_type", "issuer_country", "policy_document_id", "publication_id"],
        )
        if issuer_incidence.empty:
            issuer_edges = pd.DataFrame(columns=[
                "issuer_id", "issuer_name", "issuer_type", "issuer_country", "publication_id", "n_policy_documents", "policy_document_ids"
            ])
        else:
            issuer_edges = (
                issuer_incidence.groupby(["issuer_id", "issuer_name", "issuer_type", "issuer_country", "publication_id"], dropna=False)
                .agg(
                    n_policy_documents=("policy_document_id", "nunique"),
                    policy_document_ids=("policy_document_id", lambda values: "; ".join(sorted(set(values)))),
                )
                .reset_index()
            )
        missing_issuer = pd.DataFrame({"policy_document_id_without_valid_publisher_org_id": sorted(set(missing_issuer_ids))})

        relation_checks = pd.DataFrame([
            {
                "relation": "publication_grant",
                "definition": "P.supporting_grant_ids intersected with final linked-grant IDs",
                "raw_pairs_before_target_intersection": len(raw_pg),
                "retained_unique_edges": len(pg_edges),
                "source_endpoints_not_in_final_P": int((~pg_edges["publication_id"].isin(P_ids)).sum()),
                "target_endpoints_not_in_final_target": int((~pg_edges["grant_id"].isin(G_ids)).sum()),
                "unmatched_raw_pairs": len(pg_not_retrieved),
                "duplicate_pairs_removed": int(len(raw_pg) - len(pg_unique)),
                "retrieval_provenance_mismatches": len(pg_provenance_mismatches),
            },
            {
                "relation": "publication_policy_document",
                "definition": "D.publication_ids intersected with final P IDs",
                "raw_pairs_before_target_intersection": len(raw_pd),
                "retained_unique_edges": len(pd_edges),
                "source_endpoints_not_in_final_P": int((~pd_edges["publication_id"].isin(P_ids)).sum()),
                "target_endpoints_not_in_final_target": int((~pd_edges["policy_document_id"].isin(D_ids)).sum()),
                "unmatched_raw_pairs": len(pd_non_p),
                "duplicate_pairs_removed": int(len(raw_pd) - len(pd_unique)),
                "retrieval_provenance_mismatches": len(pd_provenance_mismatches),
            },
            {
                "relation": "policy_issuer_publication",
                "definition": "Publisher organization IDs joined to retained policy-document-P edges; repeated issuer-P pairs weighted by distinct policy documents",
                "raw_pairs_before_target_intersection": len(issuer_incidence),
                "retained_unique_edges": len(issuer_edges),
                "source_endpoints_not_in_final_P": int((~issuer_edges["publication_id"].isin(P_ids)).sum()) if not issuer_edges.empty else 0,
                "target_endpoints_not_in_final_target": 0,
                "unmatched_raw_pairs": len(missing_issuer),
                "duplicate_pairs_removed": int(len(issuer_incidence) - len(issuer_incidence.drop_duplicates())) if not issuer_incidence.empty else 0,
                "retrieval_provenance_mismatches": 0,
            },
        ])
        edge_summary = pd.DataFrame([
            {"network": "publication_grant", "left_node_type": "publication", "left_nodes_connected": pg_edges["publication_id"].nunique(), "right_node_type": "grant", "right_nodes_connected": pg_edges["grant_id"].nunique(), "edges": len(pg_edges)},
            {"network": "publication_policy_document", "left_node_type": "publication", "left_nodes_connected": pd_edges["publication_id"].nunique(), "right_node_type": "policy_document", "right_nodes_connected": pd_edges["policy_document_id"].nunique(), "edges": len(pd_edges)},
            {"network": "policy_issuer_publication", "left_node_type": "policy_issuer", "left_nodes_connected": issuer_edges["issuer_id"].nunique() if not issuer_edges.empty else 0, "right_node_type": "publication", "right_nodes_connected": issuer_edges["publication_id"].nunique() if not issuer_edges.empty else 0, "edges": len(issuer_edges)},
        ])
        coverage_summary = pd.DataFrame([{
            "frozen_source_cohort_records": source_n,
            "dimensions_recovered_analytic_subset_records": recovered_n,
            "not_recovered_by_doi_first_procedure": unresolved_n,
            "dimensions_recovery_rate_pct": pd.to_numeric(coverage_row["dimensions_recovery_rate_pct"], errors="coerce"),
            "documented_manual_addition_recovered": bool_from(coverage_row["manual_addition_recovered"]),
            "record_level_recovered_records": record_recovered_n,
            "interpretation": "The analytic relational anchor contains only the DOI-first Dimensions-recovered subset. The unresolved source records remain in the coverage audit and are not classified as absent from Dimensions.",
        }])
        field_coverage_table = pd.DataFrame(
            field_coverage(P, "final_publications_P") + field_coverage(G, "linked_grants_G") + field_coverage(D, "linked_policy_documents_D")
        )

        failures: list[str] = []
        if duplicate_checks["duplicate_id_rows"].sum() != 0:
            failures.append("duplicate record identifiers")
        if not pg_not_retrieved.empty:
            failures.append("publication-grant IDs absent from complete grant table")
        if not pg_provenance_mismatches.empty:
            failures.append("publication-grant retrieval-provenance mismatches")
        if not pd_provenance_mismatches.empty:
            failures.append("publication-policy retrieval-provenance mismatches")
        if int((~pg_edges["publication_id"].isin(P_ids)).sum()) or int((~pg_edges["grant_id"].isin(G_ids)).sum()):
            failures.append("invalid publication-grant endpoints")
        if int((~pd_edges["publication_id"].isin(P_ids)).sum()) or int((~pd_edges["policy_document_id"].isin(D_ids)).sum()):
            failures.append("invalid publication-policy endpoints")
        if not issuer_edges.empty and int((~issuer_edges["publication_id"].isin(P_ids)).sum()):
            failures.append("invalid policy-issuer-publication endpoints")
        validation = pd.DataFrame([
            {"check": "frozen_163_to_144_source_coverage_reconciles", "passed": True, "failure_notes": ""},
            {"check": "documented_manual_addition_recovered", "passed": True, "failure_notes": ""},
            {"check": "unique_P_G_D_identifiers", "passed": duplicate_checks["duplicate_id_rows"].sum() == 0, "failure_notes": "duplicate record identifiers" if "duplicate record identifiers" in failures else ""},
            {"check": "complete_anchor_and_grant_retrievals", "passed": True, "failure_notes": ""},
            {"check": "publication_grant_endpoints_valid", "passed": "invalid publication-grant endpoints" not in failures and "publication-grant IDs absent from complete grant table" not in failures, "failure_notes": "; ".join(item for item in failures if "grant" in item)},
            {"check": "publication_policy_endpoints_valid", "passed": "invalid publication-policy endpoints" not in failures, "failure_notes": "; ".join(item for item in failures if "policy" in item and "provenance" not in item)},
            {"check": "publication_grant_retrieval_provenance_valid", "passed": pg_provenance_mismatches.empty, "failure_notes": "publication-grant retrieval-provenance mismatches" if not pg_provenance_mismatches.empty else ""},
            {"check": "publication_policy_retrieval_provenance_valid", "passed": pd_provenance_mismatches.empty, "failure_notes": "publication-policy retrieval-provenance mismatches" if not pd_provenance_mismatches.empty else ""},
            {"check": "final_result", "passed": not failures, "failure_notes": "; ".join(failures)},
        ])
        if failures:
            raise AuditFailure("Audit validation failed before output certification: " + "; ".join(failures))

        output_frames = {
            "duplicate_id_checks.csv": duplicate_checks,
            "year_coverage_audit.csv": years,
            "field_coverage.csv": field_coverage_table,
            "source_dimensions_match_quality_summary.csv": coverage_summary,
            "edges_publication_grant.csv": pg_edges,
            "publication_grant_ids_not_in_final_grant_set.csv": pg_not_retrieved,
            "publication_grant_retrieval_provenance_mismatches.csv": pg_provenance_mismatches,
            "edges_publication_policy_document.csv": pd_edges,
            "policy_cited_publication_ids_not_in_final_P.csv": pd_non_p,
            "publication_policy_retrieval_provenance_mismatches.csv": pd_provenance_mismatches,
            "edges_policy_issuer_publication.csv": issuer_edges,
            "policy_documents_without_valid_publisher_org_id.csv": missing_issuer,
            "relationship_checks.csv": relation_checks,
            "edge_summary.csv": edge_summary,
            "validation_checks.csv": validation,
        }
        for name, frame in output_frames.items():
            atomic_write_csv(args.output_dir / name, frame)
        retrieval_summary = {
            "stage": SCRIPT_VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dimensions_requests_made": 0,
            "source_to_dimensions": {
                "frozen_source_cohort_records": source_n,
                "dimensions_recovered_analytic_subset_records": recovered_n,
                "not_recovered_by_doi_first_procedure": unresolved_n,
                "dimensions_recovery_rate_pct": float(pd.to_numeric(coverage_row["dimensions_recovery_rate_pct"], errors="raise")),
                "documented_manual_addition_recovered": True,
            },
            "record_counts": {"final_publications_P": len(P), "linked_grants_G": len(G), "linked_policy_documents_D": len(D)},
            "edge_counts": {
                "publication_grant": len(pg_edges),
                "publication_policy_document": len(pd_edges),
                "policy_issuer_publication": len(issuer_edges),
            },
            "relationship_fields": {
                "publication_grant": "P.supporting_grant_ids intersected with final G.id",
                "publication_policy_document": "D.publication_ids intersected with final P.id",
                "policy_issuer_publication": "D.publisher_org ID joined through retained P-D edges",
            },
            "input_files": {name: {"path": str(path), "sha256": input_hashes[name]} for name, path in input_paths.items()},
            "output_files": {name: {"path": str(args.output_dir / name), "sha256": sha256(args.output_dir / name), "rows": len(frame)} for name, frame in output_frames.items()},
            "interpretive_boundary": "All retained ties are Dimensions-recorded identifier relationships. They are not evidence of causal funding effects, policy endorsement, policy uptake, policy impact, topical similarity, or institutional intention.",
            "data_boundary": "All audit and edge outputs are protected local data and must not be committed to GitHub.",
        }
        atomic_write_json(args.output_dir / "retrieval_summary.json", retrieval_summary)

        print("FAIRIFICATION RELATIONAL AUDIT AND EDGE CONSTRUCTION: PASS")
        print(f"SOURCE COHORT RECORDS: {source_n}")
        print(f"DIMENSIONS-RECOVERED PUBLICATION ANCHOR: {len(P)}")
        print(f"UNRESOLVED SOURCE RECORDS RETAINED IN COVERAGE AUDIT: {unresolved_n}")
        print(f"LINKED GRANTS: {len(G)}")
        print(f"LINKED POLICY DOCUMENTS: {len(D)}")
        print(f"PUBLICATION-GRANT EDGES: {len(pg_edges)}")
        print(f"PUBLICATION-POLICY-DOCUMENT EDGES: {len(pd_edges)}")
        print(f"POLICY-ISSUER-PUBLICATION EDGES: {len(issuer_edges)}")
        print(f"POLICY DOCUMENTS WITHOUT VALID PUBLISHER ORGANIZATION ID: {len(missing_issuer)}")
        print("DIMENSIONS REQUESTS: 0")
        print(f"OUTPUT DIRECTORY: {args.output_dir}")
        print(f"SUMMARY: {args.output_dir / 'retrieval_summary.json'}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

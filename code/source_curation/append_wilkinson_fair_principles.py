#!/usr/bin/env python3
"""Append the Wilkinson et al. 2016 FAIR Principles record to a Scopus-style CSV.

The source CSV is read without modification. The script appends exactly one
record, using Crossref and PMC metadata for DOI 10.1038/sdata.2016.18, and
writes a JSON provenance manifest. Scopus-specific values that cannot be
verified from those sources (Scopus author IDs, EID, and the export-date
Scopus citation count) are intentionally left blank rather than invented.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DOI = "10.1038/sdata.2016.18"
TITLE = "The FAIR Guiding Principles for scientific data management and stewardship"
CROSSREF_URL = f"https://api.crossref.org/works/{DOI}"
PMC_XML_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC4792175"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/26978244/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FAIRification-dataset-curation/1.0 (metadata validation)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def initials(given: str) -> str:
    pieces = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", given)
    return "".join(f"{piece[0]}." for piece in pieces if piece)


def author_display(family: str, given: str) -> str:
    return f"{family} {initials(given)}".strip()


def parse_pmc_authors_and_affiliations(xml_bytes: bytes) -> tuple[list[dict[str, Any]], list[str], str]:
    root = ET.fromstring(xml_bytes)
    article_meta = root.find(".//article-meta")
    if article_meta is None:
        raise ValueError("PMC XML does not contain article metadata.")

    aff_map: dict[str, str] = {}
    affiliation_order: list[str] = []
    for aff in article_meta.findall(".//aff"):
        aff_id = aff.attrib.get("id", "").strip()
        value = normalize_text(" ".join(aff.itertext()))
        if value:
            if aff_id:
                aff_map[aff_id] = value
            if value not in affiliation_order:
                affiliation_order.append(value)

    author_nodes = article_meta.findall(".//contrib-group/contrib[@contrib-type='author']")
    authors: list[dict[str, Any]] = []
    for node in author_nodes:
        name = node.find("name")
        if name is None:
            continue
        family = normalize_text(name.findtext("surname"))
        given = normalize_text(name.findtext("given-names"))
        if not family:
            continue
        refs: list[str] = []
        for xref in node.findall("xref[@ref-type='aff']"):
            for ref_id in xref.attrib.get("rid", "").split():
                if ref_id in aff_map and aff_map[ref_id] not in refs:
                    refs.append(aff_map[ref_id])
        authors.append({"family": family, "given": given, "affiliations": refs})

    correspondence = ""
    corresp = article_meta.find(".//author-notes/corresp")
    if corresp is not None:
        correspondence = normalize_text(" ".join(corresp.itertext()))
    return authors, affiliation_order, correspondence


def get_crossref_record() -> dict[str, Any]:
    payload = json.loads(fetch_bytes(CROSSREF_URL).decode("utf-8"))
    message = payload.get("message", {})
    if str(message.get("DOI", "")).casefold() != DOI.casefold():
        raise ValueError("Crossref response DOI does not match the requested DOI.")
    return message


def issue_year(message: dict[str, Any]) -> str:
    for field in ("published-online", "published-print", "issued", "created"):
        values = message.get(field, {}).get("date-parts", [[]])
        if values and values[0]:
            return str(values[0][0])
    raise ValueError("No publication year found in Crossref metadata.")


def build_row(columns: list[str], message: dict[str, Any], authors: list[dict[str, Any]], affiliations: list[str], correspondence: str) -> dict[str, str]:
    row = {column: "" for column in columns}
    by_name = {column.lstrip("\ufeff").strip('"'): column for column in columns}

    def put(field: str, value: Any) -> None:
        if field in by_name:
            row[by_name[field]] = "" if value is None else str(value)

    # PMC XML provides the affiliation mappings; Crossref supplies the deposited
    # bibliographic and license metadata. Scopus-specific values are left blank.
    author_short = "; ".join(author_display(a["family"], a["given"]) for a in authors)
    author_full = "; ".join(f'{a["family"]}, {a["given"]}'.strip().rstrip(",") for a in authors)
    author_affiliations = "; ".join(
        f'{author_display(a["family"], a["given"])}, {"; ".join(a["affiliations"])}'.rstrip(", ")
        for a in authors
    )

    title = normalize_text((message.get("title") or [TITLE])[0])
    if title.casefold() != TITLE.casefold():
        raise ValueError("Crossref title does not match the requested article.")
    abstract = normalize_text(message.get("abstract", ""))
    issn = "; ".join(message.get("ISSN", []))
    license_urls = [str(item.get("URL", "")) for item in message.get("license", []) if item.get("URL")]

    put("Authors", author_short)
    put("Author full names", author_full)
    put("Author(s) ID", "")
    put("Title", title)
    put("Year", issue_year(message))
    put("Source title", (message.get("container-title") or ["Scientific Data"])[0])
    put("Volume", message.get("volume", ""))
    put("Issue", message.get("issue", ""))
    put("Art. No.", "160018")
    put("Page start", "")
    put("Page end", "")
    put("Cited by", "")
    put("DOI", DOI)
    put("Link", f"https://doi.org/{DOI}")
    put("Affiliations", "; ".join(affiliations))
    put("Authors with affiliations", author_affiliations)
    put("Abstract", abstract)
    put("Author Keywords", "")
    put("Index Keywords", "")
    put("Correspondence Address", correspondence)
    put("Editors", "")
    put("Publisher", message.get("publisher", ""))
    put("ISSN", issn)
    put("ISBN", "")
    put("CODEN", "")
    put("PubMed ID", "26978244")
    put("Language of Original Document", message.get("language", "English").capitalize())
    put("Abbreviated Source Title", (message.get("short-container-title") or ["Sci. Data"])[0])
    put("Document Type", "Article")
    put("Publication Stage", "Final")
    put("Open Access", "All Open Access; Gold Open Access")
    put("Source", "Scopus")
    put("EID", "")

    row["__metadata_sources__"] = {
        "crossref_url": CROSSREF_URL,
        "pmc_xml_url": PMC_XML_URL,
        "pubmed_url": PUBMED_URL,
        "license_urls": license_urls,
    }
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Original Scopus-style CSV; never modified.")
    parser.add_argument("--output", type=Path, required=True, help="Updated CSV with the appended record.")
    parser.add_argument("--manifest", type=Path, required=True, help="JSON provenance manifest for the manual addition.")
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"Input CSV not found: {args.input}")
    original_hash_before = sha256(args.input)
    data = pd.read_csv(args.input, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    data.columns = [str(column).lstrip("\ufeff") for column in data.columns]
    required = {"Title", "DOI", "Year", "Source title", "Abstract", "Source", "EID"}
    missing = sorted(required.difference(data.columns))
    if missing:
        raise SystemExit("Input is not the expected Scopus-style schema. Missing: " + ", ".join(missing))

    doi_present = data["DOI"].astype(str).str.strip().str.casefold().eq(DOI.casefold())
    title_present = data["Title"].astype(str).str.strip().str.casefold().eq(TITLE.casefold())
    if doi_present.any() or title_present.any():
        raise SystemExit("Target article already exists as a DOI or title record; no row appended.")

    crossref = get_crossref_record()
    pmc_xml = fetch_bytes(PMC_XML_URL)
    authors, affiliations, correspondence = parse_pmc_authors_and_affiliations(pmc_xml)
    if len(authors) < 2 or not affiliations:
        raise SystemExit("PMC metadata parsing did not yield the expected author and affiliation information.")
    row = build_row(data.columns.tolist(), crossref, authors, affiliations, correspondence)
    source_metadata = row.pop("__metadata_sources__")
    updated = pd.concat([data, pd.DataFrame([{col: row.get(col, "") for col in data.columns}])], ignore_index=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    updated.to_csv(args.output, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL, lineterminator="\n")
    if len(updated) != len(data) + 1:
        raise RuntimeError("Output row count is not exactly one greater than input.")
    if updated["DOI"].astype(str).str.strip().str.casefold().eq(DOI.casefold()).sum() != 1:
        raise RuntimeError("Output does not contain exactly one target DOI.")
    if sha256(args.input) != original_hash_before:
        raise RuntimeError("The source file was modified, which is prohibited.")

    intentionally_blank = {
        "Author(s) ID": "Scopus author identifiers were not reconstructed from public Crossref/PMC metadata.",
        "Cited by": "A Scopus export-date citation count was not available and is not substituted with Crossref or PubMed counts.",
        "EID": "Scopus EID was not verified from the supplied export or a licensed Scopus record.",
        "Author Keywords": "No author-keyword field was verified from the retrieved Crossref/PMC metadata.",
        "Index Keywords": "Scopus indexing keywords were not reconstructed from non-Scopus metadata.",
        "Editors": "No editor metadata was required or verified.",
        "ISBN": "Not applicable to this journal article.",
        "CODEN": "Not verified from the retrieved metadata.",
        "Page start": "The article uses the article number 160018 rather than a page range.",
        "Page end": "The article uses the article number 160018 rather than a page range.",
    }
    manifest = {
        "operation": "manual_append_of_omitted_foundational_FAIR_article",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_csv": {"path": str(args.input), "sha256": original_hash_before, "rows": int(len(data)), "columns": int(len(data.columns))},
        "output_csv": {"path": str(args.output), "sha256": sha256(args.output), "rows": int(len(updated)), "columns": int(len(updated.columns))},
        "added_record": {
            "doi": DOI,
            "title": TITLE,
            "publication_year": "2016",
            "pmid": "26978244",
            "pmcid": "PMC4792175",
            "author_count_from_pmc_xml": len(authors),
            "affiliation_count_from_pmc_xml": len(affiliations),
            "append_position_1_indexed": int(len(updated)),
        },
        "metadata_sources": source_metadata,
        "intentionally_blank_or_non_scopus_reconstructed_fields": intentionally_blank,
        "validation": {
            "target_doi_absent_in_input": True,
            "target_title_absent_in_input_title_field": True,
            "one_row_appended": True,
            "source_file_hash_unchanged_after_run": True,
        },
        "interpretive_note": "This is a transparent manual addition to a Scopus-derived cohort. It is not a replacement for a licensed Scopus export. Dimensions matching should use the DOI as the primary identifier, and Dimensions-derived citation and affiliation fields should be used in the later linked-data analysis.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "manifest": str(args.manifest), "rows": len(updated)}, indent=2))


if __name__ == "__main__":
    main()

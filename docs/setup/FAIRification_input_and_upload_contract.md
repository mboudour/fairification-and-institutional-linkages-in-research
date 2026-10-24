# FAIRification input and upload contract

## What is already available here

The preserved archive supplies the analytical lineage: downstream Python scripts, output formats, certified aggregate outputs, and the final-v6 computational logic. It does **not** contain the original raw input directory `data/linked_final_outputs_v6`, the original Dimensions retrieval/matching code, or Dimensions credentials.

The local starter now includes the received 162-record Scopus-style export and the frozen 163-record curated cohort. The one-record difference is documented: Wilkinson et al. (2016), DOI `10.1038/sdata.2016.18`, was absent as a title or DOI record in the export and was appended from verified Crossref and PMC/PubMed metadata. The project therefore needs a new, documented source-to-Dimensions acquisition and matching stage before any inherited downstream computation can run.

## Source-cohort contract

The project has two source layers, which must never be conflated.

`data/00_immutable_source/libraries_dataset_nq.csv` is the original 162-record Scopus export. It remains unchanged and is evidence of what was received. `data/01_source_curation/libraries_dataset_nq_with_wilkinson_2016.csv` is the frozen 163-record source cohort, denoted \(S\), and is the denominator for Dimensions matching, NMF, and all subsequent analyses.

The `01_source_curation` folder also contains the append script, notes, and JSON manifest. The manifest identifies both file hashes, the DOI and row position of the manual addition, the public metadata sources, and values deliberately left blank because they could not be verified as Scopus-export fields. In particular, blank Scopus author IDs, `Cited by`, EID, and Scopus indexing fields in the manually added record are not zeros, are not to be imputed, and must not cause the record to be excluded. The Dimensions match should use its DOI as the primary key and later Dimensions-derived metadata should be stored separately from the source row.

The working matching table needs, wherever available: a stable source-record identifier, a `source_record_origin` field (`original_export` or `documented_manual_addition`), DOI, title, authors, publication year, source/journal title, document type, volume, issue, pages, abstract, author keywords, source database, and export/curation date. Missing values are valid values and must not be silently filled.

## Dimensions access and raw retrieval record

The person running the retrieval needs institutional Dimensions Analytics API, BigQuery, or an approved export route that can lawfully return publication records and the cross-source fields required by the protocol. The access method, endpoint/export route, retrieval timestamp, query/request body, pagination log, and response count must be saved.

For every high-confidence matched publication, the enrichment needs enough data to build the FAIRification data contract:

- publication identifier, title, abstract, year/date, DOI, document type/type, author/affiliation data, organization/country fields, citation count, and `supporting_grant_ids`;
- grant identifier, title, start year/date, funder information, and recipient organization information where returned;
- policy-document identifier, title, year/date, `publication_ids`, and publisher/issuer organization and country where returned.

The match-decision file must retain every one of the 163 source records whether it matched or not. Required fields include source record ID, source-record origin, candidate Dimensions publication ID(s), normalized DOI/title/year/author comparison fields, match tier, deterministic score or rule, final decision, ambiguity status, and decision reason. It must confirm that the Wilkinson DOI occurs exactly once in the source cohort and report its match decision.

## Frozen core input contract

The FAIR-adapted core scripts will consume three frozen tables plus provenance records. Names follow the original archive for continuity, but they are FAIRification-specific data products:

```text
04_final_linked/
├── publication_anchor_final.pkl
├── linked_grants_final.pkl
├── linked_policy_documents_final.pkl
├── screening_manifest.json
├── final_retrieval_summary.json
└── publication_screening_decisions.csv
```

At minimum, the first edge-construction script requires `id`, `year`, `title`, `supporting_grant_ids`, and a FAIRification final-retention flag in `publication_anchor_final.pkl`; `id`, `start_year`, and `title` in `linked_grants_final.pkl`; and `id`, `year`, `title`, and `publication_ids` in `linked_policy_documents_final.pkl`.

The FAIRification version will validate and document additional fields before downstream use, including abstracts for NMF, citation counts if a predeclared adjustment uses them, affiliation and organization fields for descriptive representation, and issuer/funder fields for role-specific summaries.

## Outputs to upload for review

Upload outputs by completed stage, retaining the directory structure and manifests. The raw Dimensions extract need not be uploaded if licence restrictions prevent it; in that case upload the permitted derived tables, hashes, schema/data dictionary, retrieval log, and aggregate audits.

For the source-cohort, matching, and freeze review, upload:

```text
provenance/source_manifest.json
data/01_source_curation/libraries_dataset_nq_with_wilkinson_2016_manifest.json
data/03_matching/match_decisions.csv
data/03_matching/match_coverage_summary.csv
data/04_final_linked/screening_manifest.json
data/04_final_linked/final_retrieval_summary.json
provenance/dimensions_request_log.*
```

For the first analytic review, upload the complete output folders from the FAIR-adapted audit/edge script and NMF script, including their manifests, validation checks, edge summaries, topic terms, topic stability results, assignments, and document-review packets. The NMF review must include the primary 163-record result and the labelled leave-one-out sensitivity that excludes the documented manual addition. Do not upload only selected favourable tables.

For subsequent review, upload each script’s complete output directory and its manifest. This permits a result to be traced to its exact data inputs and parameters.

## Boundaries for the first local run

Do not run the archived AI–mental-health scripts directly against FAIRification data. They contain AI–mental-health vocabulary, labels, hard-coded expected input paths, and model-variable assumptions. The first FAIRification run must use the field-specific scripts and configuration produced from the frozen 163-record input contract.

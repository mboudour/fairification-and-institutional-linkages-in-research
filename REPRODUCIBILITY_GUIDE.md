# Reproducibility guide

## Purpose

This repository is a reproducibility release that deliberately excludes research inputs, Dimensions exports, record-level matching material, and record-level analytical results. It may include explicitly reviewed, component-level aggregate outputs that contain no source records, identifiers, bibliographic text, entities, or edges.

## What a permitted local workspace contains

A private local workspace may contain, outside Git-tracked files:

1. the immutable source cohort;
2. the curated source cohort after the documented Wilkinson et al. (2016) addition;
3. `dimensions_api_key.txt`, held outside version control;
4. Dimensions raw retrieval responses and matching audit files;
5. private project outputs, including corpus text, publication-level assignments, and later linked-data outputs.

None of those materials may be committed without an explicit, separate release decision. The reviewed aggregate NMF release in `derived_outputs/thematic/` is the current exception; its allowed files and data boundary are documented in that directory's README and enforced by the release-boundary checker.

## Environment

The intended core environment is Python 3.11, defined in:

- `code/setup/environment-core-macos.yml`
- `requirements.txt`

Create and validate it locally:

```bash
conda env create -f code/setup/environment-core-macos.yml
conda activate fairification-py311
python code/setup/verify_fairification_environment.py
```

## Ordered workflow

1. Read `docs/protocol/FAIRification_in_Dimensions_transparent_analysis_protocol.md`.
2. Curate the source cohort with the documented source-curation code.
3. Build the source registry and execute DOI-first Dimensions matching locally.
4. Record the retained Dimensions publication anchor and coverage audit.
5. Retrieve publication title/abstract metadata only and run the outcome-blind NMF diagnostics.
6. Review and freeze a thematic decision **before** retrieving grants, policy documents, citations, organizations, or other relational outcome layers.
7. Only then retrieve and analyze the linked relational layers.

## Data-protection check before every commit

Run:

```bash
git status --ignored
```

Then inspect staged content:

```bash
git diff --cached --name-only
git diff --cached --check
```

A safe commit may contain source code, documentation, query templates, environment definitions, and explicitly reviewed non-record-level aggregate outputs. It must not contain a credential, source/data export, API response, row-level record, title/abstract corpus, identifier-level matching result, publication assignment, relation edge, or unreviewed figure.

## NMF methodological boundary

The NMF stage is publication-text only. It must not read or use grant, policy-document, citation, funder, organization, country, affiliation, or linkage fields in model construction, component selection, bootstrap stability assessment, or theme interpretation.

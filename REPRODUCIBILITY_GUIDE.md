# Reproducibility guide

## Purpose

This repository is a **data-free computational and documentation release**. It preserves the project design, environment definition, source-curation procedure, and implementation contracts while deliberately excluding research inputs, Dimensions exports, record-level matching material, and derived analytical results.

## What a permitted local workspace contains

A private local workspace may contain, outside Git-tracked files:

1. the immutable source cohort;
2. the curated source cohort after the documented Wilkinson et al. (2016) addition;
3. `dimensions_api_key.txt`, held outside version control;
4. Dimensions raw retrieval responses and matching audit files;
5. private project outputs, including NMF diagnostics and later linked-data outputs.

None of those materials may be committed without an explicit, separate release decision.

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

A safe commit should contain only source code, documentation, query templates, environment definitions, and empty-directory README files. It must not contain a credential, data export, API response, row-level record, title/abstract corpus, matching result, derived output, or figure.

## NMF methodological boundary

The NMF stage is publication-text only. It must not read or use grant, policy-document, citation, funder, organization, country, affiliation, or linkage fields in model construction, component selection, bootstrap stability assessment, or theme interpretation.

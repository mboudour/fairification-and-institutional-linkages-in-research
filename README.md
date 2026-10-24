# FAIRification and Institutional Linkages in Research

Private, data-free reproducibility repository for a publication-centred study of FAIRification, research-data stewardship, and Dimensions-recorded institutional linkages.

## Scope

The project starts from a curated external source cohort and constructs a high-confidence Dimensions-recovered publication anchor through deterministic DOI-first matching. Publication titles and abstracts are then used—before any relational outcomes are examined—to diagnose FAIRification thematic structure with nonnegative matrix factorization (NMF). Later project stages will examine Dimensions-recorded publication–grant and publication–policy-document relations, alongside descriptive institutional annotations.

This repository intentionally contains **no research data**. It does not contain source CSV files, Dimensions API responses, publication-level exports, record-level match tables, abstracts, topic assignments, derived outputs, figures based on data, credentials, or a manuscript-result package.

## Repository layout

```text
code/
  setup/              Local environment definitions and preflight checks
  source_curation/    Reproducible source-cohort curation code
  matching/           DOI-first matching design and API-safety notes
  thematic/           Publication-text NMF preparation and diagnostic code
  validation/         Reserved for validation and release checks
docs/
  protocol/           Transparent analysis protocol
  setup/              Mac setup and local input/upload documentation
  source_curation/    Documentation of the foundational FAIR Principles record
queries/              Reusable Dimensions DSL templates; no retrieved results
data/                 Local-only data location; ignored except this README
derived_outputs/      Local-only computed outputs; ignored except this README
figures/              Local-only data-derived figures; ignored except this README
manuscript/           Reserved for manuscript source, not results or data
tools/                Utility scripts
```

## Data and credential protection

Never commit any of the following:

- source cohorts or manually curated source exports;
- Dimensions raw responses, matching tables, record-level metadata, abstracts, or API-output manifests;
- output tables, serialized objects, topic assignments, record-level review packets, figures, or manuscript result files derived from non-public data;
- `dimensions_api_key.txt`, authentication tokens, environment files containing secrets, or notebook checkpoints.

The `.gitignore` is intentionally restrictive. Keep research inputs and outputs in the local `data/`, `derived_outputs/`, `figures/`, and `manuscript/` directories only.

## Current project boundary

The repository currently records the methodological and computational foundation through the publication-only NMF stage. It does not claim that later grant, policy-document, citation, funder, organization, country, or linkage analyses have been completed or released.

## Local environment

Create the core environment from `code/setup/environment-core-macos.yml`, then run:

```bash
python code/setup/verify_fairification_environment.py
```

See [the Mac setup guide](docs/setup/Mac_local_environment_guide.md) and [the transparent protocol](docs/protocol/FAIRification_in_Dimensions_transparent_analysis_protocol.md) for the full workflow and data-handling boundaries.

## Attribution

Project owner: Moses Boudourides.

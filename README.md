# FAIRification and Institutional Linkages in Research

**Moses Boudourides**

Private, data-free reproducibility repository for a publication-centred study of FAIRification, research-data stewardship, and Dimensions-recorded institutional linkages.

## Scope

The project starts from a curated external source cohort and constructs a high-confidence Dimensions-recovered publication anchor through deterministic DOI-first matching. Publication titles and abstracts are then used—before any relational outcomes are examined—to diagnose FAIRification thematic structure with nonnegative matrix factorization (NMF). Later project stages will examine Dimensions-recorded publication–grant and publication–policy-document relations, alongside descriptive institutional annotations.

This repository intentionally contains **no research data**. It does not contain source CSV files, Dimensions API responses, publication-level exports, record-level match tables, abstracts, topic assignments, derived outputs, figures based on data, credentials, or a manuscript-result package.

## Data provenance and current study population

### Scopus source study

The source bibliographic design is drawn from Papachristopoulos, Sfakakis, and Papatheodorou's Scopus-based study of FAIR data and libraries:

> Papachristopoulos, L., Sfakakis, M., & Papatheodorou, C. (2026). *Who Cares About FAIR Data? Libraries in the Ecosystem of FAIRification*. **Metrics, 3**, 22. https://doi.org/10.3390/metrics3040022

That study's broad corpus contains **2,790** English-language journal articles and conference papers published from **2000–2025**, retrieved in Scopus using explicit FAIR-focused expressions (`FAIR data`, `FAIR principle`, `fairification`, or `Findable Accessible Interoperable Reusable`). Its library-focused subset adds `library` or `libraries` to the title/abstract/keyword search and contains **162** records. The source paper analyzes this literature bibliometrically with Bibliometrix; it does not use Dimensions links.

### This project's curated source cohort

This project begins from the shared 162-record library-focused Scopus export, rather than from the paper's full 2,790-record corpus. The source export did not contain the foundational article by Wilkinson et al., *The FAIR Guiding Principles for scientific data management and stewardship* (2016), DOI `10.1038/sdata.2016.18`. A documented, reproducible manual addition produces a frozen **163-record** source cohort. The original export, the curated cohort, and the associated curation manifest remain private and are not distributed here.

### Dimensions-recovered analytic subset

Dimensions is used for a new, separate relational enrichment of the frozen source cohort. It is not treated as a replacement for Scopus and the project does not assert that unrecovered records are absent from Dimensions.

- A deterministic DOI-first procedure queried the 148 source records with a DOI.
- **144 of the 163** curated source records were accepted as unambiguous, one-to-one exact DOI matches in Dimensions (**88.34%** source-cohort recovery).
- The remaining **19** source records are retained in the matching audit but excluded from the primary Dimensions publication anchor: 15 have no source DOI and 4 did not return a Dimensions candidate in the DOI-first procedure.
- The initial Dimensions publication-text subset contains title metadata for all 144 matched records and abstracts for 140 of them. It is used for outcome-blind thematic diagnostics before retrieval of grant, policy-document, citation, funder, organization, country, or other relational layers.

All source and Dimensions record-level materials, raw API responses, matching tables, and derived outputs remain local and excluded from version control.

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
streamlit_app.py       Private-local companion dashboard
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

## Companion Streamlit dashboard

Run the local dashboard with:

```bash
streamlit run streamlit_app.py
```

The dashboard is safe to commit because it contains no research data and does not authenticate to Dimensions. It documents the study design and can render optional **local-only aggregate NMF outputs** if they are placed in `derived_outputs/private_nmf/`, which is ignored by Git. It does not require, expose, or transmit raw source or Dimensions records.

## Attribution

Project owner: Moses Boudourides.

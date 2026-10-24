# Implementation status

The repository contains the data-free local environment, source-curation and DOI-matching scripts, NMF diagnostics, Dimensions relational retrieval scripts, association/timing/network/configuration analyses, reporting scripts, reviewed aggregate-only results, and reviewed core figures.

## Protected local institution-country restoration

The initial certified aggregate bundle deliberately retained only network scope, concentration, and organization-attribute coverage. It did not publish named organization, country, top-node, component, or theme-landscape outputs. The corresponding local restoration is now implemented as:

- `code/analysis/19_restore_institution_country_landscapes.py`;
- `code/reporting/20_generate_institution_country_figures.py`.

These scripts reconstruct P--PI affiliation, G--GI funder, D--DI issuer, P--G, P--D, and issuer--P descriptive views from the completed protected local P/G/D tables and audited edges. They also construct full-anchor and frozen-K=3 institution/country landscapes. They make no API requests.

All named organization/country, record-level, node-level, and edge-level outputs from this restoration remain local and are deliberately excluded from GitHub. See [`docs/analysis/FAIRification_institution_country_restoration_contract.md`](../docs/analysis/FAIRification_institution_country_restoration_contract.md) for the exact input/output and interpretation contracts.

The absence of source and record-level data files is intentional and not a missing repository artifact.

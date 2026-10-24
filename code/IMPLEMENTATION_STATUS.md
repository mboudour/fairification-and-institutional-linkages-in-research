# Implementation status

This initial repository release contains the data-free environment, protocol, source-curation script, matching/thematic contracts, and a safe Dimensions query template.

The stepwise matching and NMF scripts executed in the private local workspace are deliberately not reconstructed from private execution artifacts in this release. Before any future public-facing release, their source should be copied from the controlled local project into the corresponding `code/` directories and reviewed with `git diff --cached --check` to ensure that no source data, API key, response, record-level output, or result is embedded.

The absence of data files is intentional and not a missing repository artifact.

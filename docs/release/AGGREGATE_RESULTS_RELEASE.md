# Reviewed aggregate-results release

## What is released

This repository release contains 26 non-record-level CSV tables in `derived_outputs/released_results/` and five manuscript figures in `figures/manuscript/`. They are the reviewed aggregate-only outputs created by the completed FAIRification analysis pipeline. The release is designed to support transparent reading of the reported results, the Streamlit companion app, and compilation of the manuscript source.

The tables report only study-level, thematic, model-level, network-summary, timing-summary, robustness, and permutation-summary quantities. They contain no source cohort, Dimensions response, title, abstract, author, organization name, country name, record identifier, DOI, match-decision record, publication-level assignment, node list, or edge list.

## Verification before release

The original local certified-results bundle contained 27 manifest-declared outputs and passed nine validation checks. The uploaded bundle was independently checked before this release: every declared bundle file matched its SHA-256 manifest entry. The local figures package contained 11 manifest-declared outputs—five PNG figures, five PDF figures, and one captions file—and every output matched its SHA-256 manifest entry.

The local manifests are not copied here because they contain device-local paths. The `results_bundle_index.csv` is retained because it gives table-level provenance without exposing record-level or device-local information.

## Release exclusions

This release does not distribute the 163-record curated source cohort, the 144-record Dimensions anchor, the 19 unresolved records, raw API responses, credentials, record-level matching outputs, publication-level text or NMF assignments, grant or policy records, organization or issuer names, or identifier-level relation edges. It does not permit causal interpretations of the reported grant-link associations, policy-document links, stored record-year differences, or configuration tests.

## Citable scope

The study population is a 163-record curated source cohort derived from the library-focused Scopus subset in Papachristopoulos, Sfakakis, and Papatheodorou (2026), augmented by a documented addition of the foundational FAIR Principles paper. The analytic Dimensions anchor contains 144 exact DOI-first matches (88.344% of the curated cohort). See the project README and transparent protocol for the full matching and analytical design.

# FAIRification and Institutional Linkages in Research

**Moses Boudourides**

Reproducibility repository for a publication-centred study of FAIRification, research-data stewardship, and Dimensions-recorded grant and policy-document links.

## Study in brief

The project starts from a curated external source cohort and constructs a high-confidence Dimensions publication anchor through deterministic DOI-first matching. Publication titles and abstracts are then used—before relational outcomes are examined—to diagnose FAIRification thematic structure with nonnegative matrix factorization (NMF). The completed relational stage examines Dimensions-recorded publication–grant and publication–policy-document links, descriptive role-separated network summaries, local institution/country landscapes, and local grant–policy configuration patterns.

The study does not interpret recorded grant or policy links as causal effects, funding intent, policy uptake, endorsement, impact, or institutional influence.

## Data provenance and analytic scope

### Scopus source study

The source bibliographic design is drawn from Papachristopoulos, Sfakakis, and Papatheodorou's Scopus-based study of FAIR data and libraries:

> Papachristopoulos, L., Sfakakis, M., & Papatheodorou, C. (2026). *Who Cares About FAIR Data? Libraries in the Ecosystem of FAIRification*. **Metrics, 3**, 22. https://doi.org/10.3390/metrics3040022

That study's broad corpus contains 2,790 English-language journal articles and conference papers published from 2000–2025. Its library-focused subset adds `library` or `libraries` to the FAIR-focused search design and contains 162 records. The source paper analyses the literature bibliometrically with Bibliometrix; it does not use Dimensions relation data.

### Curated source cohort and Dimensions anchor

This project begins from the shared 162-record library-focused Scopus export. A documented addition of Wilkinson et al.'s foundational FAIR Principles paper (2016) produces a frozen **163-record** source cohort. A deterministic DOI-first procedure accepted **144 exact one-to-one Dimensions matches** (**88.344%** of the curated cohort). The 19 unresolved records remain in the matching audit; they are not treated as absent from Dimensions.

The primary analytic anchor contains 144 matched publications. All have titles and 140 have abstracts. Publication-text thematic diagnostics were completed before grant, policy-document, citation, funder, organization, country, or relation variables were retrieved or analysed.

## Main aggregate findings

The frozen primary NMF representation is **K=3**: institutional stewardship, research-data management, and open-science practice (51 publications; 35.4%); technical metadata, semantic infrastructure, and reproducible workflows (80; 55.6%); and digital cultural heritage, collections, and preservation (13; 9.0%). K=2 is retained as a coarsened sensitivity. The small heritage/preservation component has a component-specific bootstrap caveat and is interpreted cautiously.

Among the 144 anchor publications, 52 (36.111%) have a Dimensions-recorded grant link and 4 (2.778%) have a Dimensions-recorded policy-document link. The year-adjusted primary grant-link model finds lower conditional odds of a recorded grant link for a ten-percentage-point compositional shift from the technical-metadata reference toward institutional stewardship/open science (OR 0.772, 95% CI 0.684–0.871) or heritage/preservation (OR 0.785, 95% CI 0.647–0.952). These are recorded-link associations, not causal funding effects.

Policy links are too sparse for the predeclared multivariable policy model: the primary through-2022 window contains 3 events among 72 publications, below the 30-event adequacy threshold. The primary publication-year-stratified configuration test shows no evidence that the observed publication overlap of recorded grant and policy links exceeds its year-conditioned null.

The reviewed institution/country restoration finds stored affiliation organizations for 128 publications (313 organizations across 46 stored countries) and recorded grant-funder representation for 52 publications (47 organizations across 17 stored countries). The policy-issuer path reaches 44 organizations and 19 stored countries through only four publications, so it is retained as sparse descriptive context rather than plotted. The country and organization landscapes preserve these roles and do not measure institutional influence, funding allocation, country effects, policy uptake, or impact.

## Reviewed aggregate-only release

The repository contains a deliberately limited, reviewed release of 27 aggregate result tables in [`derived_outputs/released_results/`](derived_outputs/released_results/) and seven reviewed figures in [`figures/manuscript/`](figures/manuscript/). The release includes no source records, Dimensions API responses, publication text, identifiers, matching records, publication-level assignments, node lists, or edge lists. Figures 6--7 are a narrowly reviewed exception: they contain selected, role-specific organization and country labels for descriptive manuscript figures, not a full named representation table.

See the [aggregate-results release note](docs/release/AGGREGATE_RESULTS_RELEASE.md) and the [institution-country results release note](docs/release/INSTITUTION_COUNTRY_RESULTS_RELEASE.md) for the review, scope, and exclusions. The `results_bundle_index.csv` retained in the aggregate folder documents table-level source-stage provenance without device-local paths or identifiers.

## Institution and country restoration and release boundary

The local restoration stage reproduces role-separated publication affiliations, grant funders, grant recipients, and policy issuers; P--PI, G--GI, and D--DI relation networks; and full-anchor/K=3 descriptive landscapes. It is implemented in [`19_restore_institution_country_landscapes.py`](code/analysis/19_restore_institution_country_landscapes.py) and [`20_generate_institution_country_figures.py`](code/reporting/20_generate_institution_country_figures.py). The scripts make no API requests but require the protected local P/G/D tables and audited edge lists created by the preceding pipeline. The public release is limited to aggregate scope table `H01` and Figures 6--7 after review; all local identifier-level outputs and full named representation tables remain excluded. See the [method contract](docs/analysis/FAIRification_institution_country_restoration_contract.md).

## Repository layout

```text
code/
  matching/            DOI-first matching design and API-safety notes
  thematic/            Publication-text NMF preparation and diagnostics
  relational/          Local relational retrieval and audit scripts
  analysis/            Local association, timing, network, configuration, and institution/country scripts
  reporting/           Certified bundle, core-figure, and local institution/country-figure scripts
  validation/          Repository release-boundary check
docs/
  protocol/            Transparent analysis protocol
  analysis/            Frozen analytical specifications and contracts
  release/             Aggregate-only release note
derived_outputs/
  thematic/            Reviewed component-level NMF diagnostics
  released_results/    Reviewed non-record-level certified result tables
figures/
  manuscript/          Reviewed PNG/PDF manuscript figures and captions
```

## Data and credential protection

Never commit source cohorts, Dimensions raw responses, record-level matching tables, publication metadata, abstracts, publication-level assignments, identifiers, full organization or issuer representation tables, node lists, edge lists, manuscript source, or `dimensions_api_key.txt`. Selected organization/country labels are permitted only in the reviewed Figures 6--7. The `.gitignore` and [`check_release_boundary.py`](code/validation/check_release_boundary.py) permit only named reviewed aggregate tables and figures after release review.

## Attribution

Project owner and sole manuscript author: Moses Boudourides, School of Professional Studies, Northwestern University.

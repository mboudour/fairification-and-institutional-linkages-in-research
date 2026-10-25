# Reviewed institution-country results release

## What this release adds

This reviewed update releases the non-record-level role-separated institution/country scope table and the two corresponding manuscript figures generated from the completed local restoration run dated 2026-10-25.

The release adds:

- `derived_outputs/released_results/H01_role_separated_institution_country_scope.csv`, a 12-row aggregate table for the full 144-publication anchor and the three frozen dominant-$K=3$ theme views;
- `figures/manuscript/figure_6_country_landscapes.{pdf,png}`; and
- `figures/manuscript/figure_7_institution_landscapes.{pdf,png}`.

The two figures contain selected, role-specific named country and organization representations. They are reviewed descriptive visual summaries rather than raw-data exports. Their narrative interpretation is supplied in manuscript TeX, not embedded in the figure files.

## Verified aggregate scope

Across the 144-publication Dimensions anchor, the reviewed aggregate counts are:

| Role-separated view | Publications with a stored target | Distinct organizations | Organization-incidence pairs | Distinct stored countries |
|---|---:|---:|---:|---:|
| Publication affiliations (P--PI) | 128 | 313 | 392 | 46 |
| Grant funders reached through recorded P--G links (P--G--GI) | 52 | 47 | 101 | 17 |
| Policy issuers reached through recorded P--D links (P--D--DI) | 4 | 44 | 47 | 19 |

Country memberships are non-exclusive stored attributes. Organization identities remain role-specific: no names are used to merge affiliations, funders, or issuers.

## Figure design and interpretation boundary

Figures 6 and 7 show publication-affiliation and grant-funder panels only. For each relation layer, the eight most represented countries or organizations are selected from the full anchor and displayed as the share of publications in each frozen hard-assignment theme. The policy-issuer panel is deliberately omitted because only four anchor publications have a recorded issuer path. This presentation choice does not imply that other policy documents or issuers do not exist.

The figures and `H01` are descriptive results from Dimensions-recorded identifiers and stored attributes. They do **not** measure institutional influence, research capacity, funding allocation or intent, policy uptake, policy impact, or country-level effects.

## Deliberate exclusions

The following remain excluded from GitHub: the local Stage 19 and Stage 20 output directories; publication-, grant-, policy-document-, and organization-level identifiers; node and edge lists; full named representation tables; raw Dimensions responses; publication text; source-cohort data; matching records; and credentials.

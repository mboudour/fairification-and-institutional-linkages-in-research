# FAIRification institution-country restoration contract

## Purpose

This local-only stage restores the descriptive institution and country material that is comparable to the corresponding section of the prior AI–mental-health study. It does **not** change the frozen 144-publication Dimensions anchor, the K=3 NMF decision, the grant association model, the sparse-policy safeguard, or the publication-year-stratified configuration test.

The first FAIRification aggregate release retained only network scope, concentration, and role-attribute coverage. It excluded named organization, country, top-node, component, and theme-landscape material from the certified bundle. That was a release-boundary decision, not a failure to retrieve the relevant Dimensions fields.

## Inputs

`code/analysis/19_restore_institution_country_landscapes.py` runs locally, makes no Dimensions requests, and requires the protected completed outputs from the existing pipeline:

- final linkage-ready publication anchor (`publication_anchor_final*.pkl`), including frozen K=3 fields and publication-affiliation organization/country fields;
- final linked grants (`linked_grants_final*.pkl`), including funder and recipient organization/country fields;
- final linked policy documents (`linked_policy_documents_final*.pkl`);
- audited `edges_publication_grant.csv`, `edges_publication_policy_document.csv`, and `edges_policy_issuer_publication.csv` from Stage 10;
- Stage 10 `retrieval_summary.json`.

The script validates the K=3 shares, identifier uniqueness, endpoint reconciliation, and Stage-10 record/edge/hash chain. It refuses an output directory that already exists or sits inside the Git worktree.

## Restored relation views

The stage preserves role separation and uses only explicit stored Dimensions identifiers:

| Relation view | Construction | Meaning of institution/country count |
|---|---|---|
| `P_PI_affiliation` | retained publication → explicit affiliation organization | publication-affiliation representation |
| `P_G_GI_funder` | retained publication → audited grant → explicit funder organization | funder representation reached through a recorded P–G link |
| `P_D_DI_issuer` | retained publication → audited policy-document path → explicit policy issuer | issuer representation reached through a recorded P–D link |
| `linked_grant_recipient_organization` | linked grant → explicit recipient organization | supplementary role-separated context, never merged with the funder role |

A role-specific organization is an explicit Dimensions organization ID only. Organization names are descriptive attributes, not matching keys. The pipeline never merges affiliations, funders, recipients, or policy issuers across roles. It does not infer institutions from author names.

Stored countries are non-exclusive: one publication can contribute to more than one stored country. No country normalization, regional grouping, income classification, or country-level inference is performed.

## K=3 thematic landscapes

The primary landscape views are the full anchor and the three frozen dominant-topic groups:

1. institutional stewardship, research-data management, and Open Science practice;
2. technical metadata, semantic infrastructure, and reproducible workflows;
3. digital cultural heritage, collections, and preservation.

For each view, the script reports named local organization/country representations and a safe aggregate scope summary. A publication–organization pair is counted once within a view. Grants and issuers may appear in more than one view when their recorded links reach publications in multiple themes. Hard-theme landscapes are descriptive supplements, not replacements for the continuous-share grant model. The small third component must retain its documented component-stability caution.

## Outputs

Stage 19 writes these protected local tables:

- role network statistics, components, and node degrees for P–PI, P–G, G–GI, P–D, D–DI, and issuer–P layers;
- organization incidence and representation by separated role;
- country representation by separated role;
- named policy issuer representation and D–DI paths;
- institution and country representations by full-anchor/K=3 view;
- theme-level scope summaries and a non-identifier aggregate scope summary;
- validation checks and a SHA-256 input/output manifest.

`code/reporting/20_generate_institution_country_figures.py` then creates local-only Figure 6 (country landscapes) and Figure 7 (institutional landscapes). The top targets are selected in each relation from the all-anchor view before their K=3 cells are plotted. Policy-issuer heatmap panels are withheld by default when fewer than 10 publications have a recorded issuer path; this is a display safeguard and is not evidence of missing policy documents or issuers.

## Local execution

From the FAIRification project root on the Mac, with `fairification-py311` activated, the completed October 24 local files can be used without a further Dimensions API request:

```bash
BASE="fairification_local_starter/fairification_pipeline_template"
AUDIT="$BASE/computations/outputs/10_relational_audit_and_edges_run_20261024_2031"
RUN19="$BASE/computations/outputs/19_institution_country_restoration_run_20261025"
RUN20="$BASE/computations/outputs/20_institution_country_figures_run_20261025"

python fairification-github/code/analysis/19_restore_institution_country_landscapes.py \
  --anchor-file "$BASE/data/04_final_linked/publication_anchor_final_run_20261024_2003.pkl" \
  --grants-file "$BASE/data/04_final_linked/linked_grants_final_run_20261024_2016.pkl" \
  --policy-file "$BASE/data/04_final_linked/linked_policy_documents_final_run_20261024_2027.pkl" \
  --publication-grant-edges-file "$AUDIT/edges_publication_grant.csv" \
  --publication-policy-edges-file "$AUDIT/edges_publication_policy_document.csv" \
  --policy-issuer-publication-edges-file "$AUDIT/edges_policy_issuer_publication.csv" \
  --relational-summary-file "$AUDIT/retrieval_summary.json" \
  --output-dir "$RUN19"

python fairification-github/code/reporting/20_generate_institution_country_figures.py \
  --restoration-dir "$RUN19" \
  --output-dir "$RUN20"
```

The two output directory names must be new, must not be inside the `fairification-github` worktree, and will be rejected if they already exist. Stage 19 makes zero Dimensions requests. Stage 20 verifies the Stage-19 manifest and every consumed CSV hash before writing its two figures.

## Required interpretation boundary

These outputs describe Dimensions-recorded identifiers, stored organization/country attributes, and relation paths. They do not demonstrate institutional influence, research capacity, funding intent, allocation, policy endorsement, policy uptake, policy impact, knowledge translation, or causal country/institution effects.

## Public-release boundary

The Stage 19 and 20 **code and this contract** are public. Their actual local outputs contain protected record-level identifiers and named organization/country attributes and are not committed to GitHub. Any future aggregate-only public release requires a separate review and an explicit update to `check_release_boundary.py`; names, IDs, publication-level paths, node lists, and edge lists remain excluded.

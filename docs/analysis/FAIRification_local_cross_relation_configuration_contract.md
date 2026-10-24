# FAIRification local cross-relation configuration test contract

`code/analysis/16_test_local_cross_relation_configurations.py` is the predeclared, local, no-API structural test of alignment between two audited Dimensions relation layers:

- **P–G:** publication–grant identifier edges; and
- **P–D:** publication–policy-document identifier edges.

The unit of analysis is the retained publication. The test starts from the completed 144-publication linkage base and the audited 163 P–G and 223 P–D edges. It does not use publication text, NMF shares, citation counts, organization names, funder identities, policy text, or any outcome model.

Before calculation, the script verifies the SHA-256 chain in the completed upstream manifests: the publication-level analysis base is matched to its own certified output entry; the P–G and P–D tables are matched both to the analysis-base inputs and to the relational-audit outputs; the issuer–P table is matched to the relational-audit output; and the relational summary is matched to the analysis-base input. Matching counts alone are not accepted as provenance.

## Primary null and statistics

The primary null permutes the publication endpoint mapping of all P–D ties **within publication-year strata**, holding the P–G layer fixed. All P–D edges incident on the same original publication move together as a degree bundle. This preserves the P–D degree multiset within each year stratum and each policy-document endpoint, while disrupting whether the P–D bundle aligns with a particular P–G degree.

The two predeclared primary statistics are:

1. `N_both`: the number of publications with at least one P–G and at least one P–D relation—the extensive margin; and
2. `intensive_degree_product_sum`: \(\sum_P d_{P,G}d_{P,D}\)—the intensive co-location of relation degrees.

The unstratified publication-endpoint permutation is a labelled sensitivity null, not a replacement for the primary year-conditioned comparison.

## Sparse-policy safeguard

The FAIRification data have only four policy-linked publications. Within a year stratum that has homogeneous grant-link status, the extensive-margin statistic `N_both` can be fixed by design even when the intensive degree-product statistic remains variable. The script determines the exact support bounds of `N_both` from within-stratum counts of P–G-positive and P–D-positive publications. Only when those bounds coincide is `N_both` labelled `analytically_degenerate__no_permutation_contrast` and assigned no p-value.

For the degree-product statistic, and for an analytically variable `N_both`, the script reports a p-value only when variation is observed among the Monte Carlo draws. If no variation is observed in \(B\) draws, it reports `no_variation_observed_in_B_draws__not_analytically_classified` rather than incorrectly calling the full null degenerate. Monte Carlo standard errors are included with reported p-values. The configuration-count rows (`P_G_only`, `P_D_only`, and `neither`) are algebraically related to the fixed margins and `N_both`; they are descriptive context and receive no p-values.

## Policy issuers

Policy-issuer–publication edges are used only to describe observed issuer reach among publications that already have both P–G and P–D relations. Issuers are not independently rewired, are not treated as a third relation layer, and are not used to infer issuer intent or influence. Incomplete issuer metadata does not block the P–G/P–D configuration test: issuer-attributed P–D incidence coverage is separately reported, and only issuer endpoints that are not P–D endpoints cause a validation failure.

## Interpretation boundary

This is a descriptive database-linkage configuration test. It cannot establish a causal pathway from grants to policy, funding intent, policy endorsement, policy uptake, policy impact, institutional influence, topical affinity, communities, or latent profiles. All output files, including the permutation replicates, remain protected local data and must not be committed to GitHub.

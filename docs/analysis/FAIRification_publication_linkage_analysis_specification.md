# FAIRification publication-linkage analysis specification

**Status:** Frozen before association-model fitting

**Decision date:** 2026-10-24

## Thematic representation

The primary thematic representation is the frozen, outcome-blind K=3 publication NMF. The three continuous component shares are compositional and sum to one for every retained publication:

1. Institutional stewardship, research-data management, and open-science practice.
2. Technical metadata, semantic infrastructure, and reproducible workflows.
3. Digital cultural heritage, collections, and preservation.

Association models will use the continuous Topic 1 and Topic 3 shares, with Topic 2 omitted as the compositional reference. Thus, a coefficient describes association with a shift in membership toward Topic 1 or Topic 3 relative to the technical metadata/workflows component, conditional on the other included terms. Dominant-theme labels are retained for supplementary descriptive tables only. Key analyses will later be repeated after excluding publications whose top-two component-share margin is below 0.10.

No separate FAIR keyword/dictionary indicator or manually constructed concept-family layer is used in the primary model. The original AI–mental-health terms do not transfer substantively, and an overlapping FAIR governance-versus-technical dictionary would duplicate the NMF orientations after the outcome links have been retrieved. A distinct supplementary codebook can be added only through a dated, outcome-blind deviation that demonstrates a nonredundant construct, its included and excluded terms, coverage, prevalence, overlap, and sensitivity rules.

## Recorded linkage outcomes

The two publication-level outcomes are `has_grant_link` and `has_policy_document_link`. They equal one only where the audited Dimensions identifier edge lists contain at least one publication–grant or publication–policy-document edge. Link counts are retained descriptively.

These outcomes are database-recorded relationships. They do not identify causal funding effects, funder intent, policy endorsement, policy uptake, policy impact, topical similarity, or institutional influence.

## Association adjustments

The planned primary association models adjust for centered publication year, which acts as a record-coverage and cohort descriptor. Citation count is not included in the primary adjustment set because it accrues after publication and may be associated with both visibility and observed linkage opportunities. A clearly labelled sensitivity can add `log1p(times_cited)` for records with an observed Dimensions citation count. Neither model is causal.

## Policy-observation design

The policy retrieval endpoint is 2026, as fixed by the completed retrieval manifest. The primary policy-link association sample is publications through **2022**. A longer-observation robustness sample is publications through **2021**. The all-publication policy analysis is a sensitivity only because newer publications have fewer observed policy-document years.

This is a record-coverage convention, not a causal time-to-policy or impact window. Differences between publication and policy-document years will be reported as record-year differences only.

## Local implementation

`code/analysis/11_prepare_publication_linkage_analysis_base.py` constructs the protected publication-level analysis base and descriptive outcome tables without fitting an association model or requesting any external data. The base is excluded from GitHub because it contains protected publication-level Dimensions-derived data.

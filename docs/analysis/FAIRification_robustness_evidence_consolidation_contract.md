# FAIRification robustness evidence-consolidation contract

`code/analysis/15_consolidate_robustness_evidence.py` is a local, no-API robustness stage. It summarizes already completed diagnostics and association sensitivities and performs one fixed NMF sensitivity calculation: K=2 with the documented Wilkinson record excluded. It does not refit any grant or policy association model, add terms, change the corpus, or select a favorable result.

## NMF evidence

The script verifies the outcome-blind NMF diagnostic for the fixed 144-publication Dimensions corpus: candidate K=2, K=3, and K=4 solutions; eight 80% publication-subsample bootstraps per solution; hard-assignment sizes; component-level cosine similarities; and assignment agreement. It reports the primary K=3 component pattern alongside the candidate solutions without treating reconstruction error as a selection rule or bootstrap quantities as confidence intervals.

The documented manual addition is Wilkinson et al., DOI `10.1038/sdata.2016.18`. The script refits the **K=2-only** full and leave-one-out models using the frozen 144-publication anchor and the primary-corpus TF--IDF vocabulary. It first requires at least .95 dominant-assignment agreement between its full K=2 reconstruction and the saved K=2 output; then it reports cosine similarities for the two matched K=2 components after exclusion. This supports only the narrow claim about the broad K=2 structure. It does **not** test or establish invariance of the primary K=3 heritage/preservation specialist component.

## Grant and policy association robustness

The script compares, term by term, the already fitted year-adjusted continuous-K=3 grant model with its prespecified low-assignment-margin and citation-adjusted sensitivities. It does not promote any sensitivity over the primary model or interpret an association as causal.

For policy links, it reconciles event counts between the association and temporal stages for the predeclared 2022 primary window, 2021 longer-window check, and all-publication sensitivity. When a sample fails the frozen event-adequacy rule, `not_fit` is the required result. The project does not substitute a sparse, univariate, penalized, or post hoc policy model simply to produce a coefficient.

## No FAIR keyword indicator

No FAIR keyword dictionary or manual concept-family score is part of the predeclared primary association design. The outcome-blind NMF already provides the thematic representation. Accordingly, the robustness output reports that an indicator sensitivity is **not used by design**; this is not a failed analysis or a missing result.

All output tables and manifests are protected local data and must not be committed to GitHub.

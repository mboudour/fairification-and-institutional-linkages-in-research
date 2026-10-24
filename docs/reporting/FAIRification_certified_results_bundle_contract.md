# FAIRification certified-results bundle contract

`code/reporting/17_build_certified_results_bundle.py` is the first reporting-stage script. It creates a **local-only, aggregate-only** bridge from the completed core FAIRification stages to later figures and paper materials. It does not retrieve Dimensions data, fit any new model, choose a preferred result, or generate a figure.

## Inputs and certification

The script takes the completed local output directories for the relational audit, publication linkage analysis base, linkage associations, temporal audit, role-separated network analysis, robustness consolidation, and local cross-relation configuration test.

Every selected input CSV must appear in the producing stage’s `output_files` manifest with an exact matching SHA-256 digest and an exact integral row count. All seven stage manifests must be marked `complete`.

The bundle also closes the upstream hash chain: the analysis base must reference the supplied relational audit and its P–G/P–D edges; the association and temporal stages must reference that exact analysis base; the network stage must reference the supplied relation layers; the robustness stage must reference the supplied association and temporal manifests; and the configuration test must reference the same base, relation summary, and P–G/P–D/issuer–P edges. A matching filename, row count, or isolated manifest is insufficient.

The frozen project values are fixed rather than caller-configurable: 163 source records, 144 recovered Dimensions publications, 52 grant-linked publications, 4 policy-linked publications, and a 72-publication/3-event primary policy window. The primary grant model must be fit; the primary policy model must be certified as `not_fit` because it is below the predeclared 30-event threshold. The bundle also checks the 163 P–G, 223 P–D, and 47 issuer–P edge counts and the observed configuration counts and primary structural statistics. It preserves Stage 16’s documented sparse-policy information states: Monte Carlo variation, analytical degeneracy, and Monte Carlo-limited no-variation are each valid certified statuses rather than generic bundle failures.

A stage output with a matching filename or matching number of rows is not accepted if its certified hash differs.

## Eligible material

The bundle contains only result-level aggregate tables, including:

- source-to-Dimensions coverage and audited relation counts;
- overall and supplementary K=3 linkage outcomes;
- association diagnostics, coefficients, and event-adequacy tables;
- record-year and policy-window summaries;
- role-separated network size, degree-concentration, and attribute-coverage summaries;
- NMF stability and predeclared robustness summaries; and
- observed P–G/P–D configuration and permutation-summary tables.

The bundle adds an index, a headline overview, validation checks, a README, and a manifest that preserve table provenance.

## Excluded material

The script blocks tables containing publication, grant, policy-document, source-record, DOI, title, abstract, author, issuer, organization, edge-list, or textual-record identifier columns, including normalized alternatives such as `publicationId`. Each permitted aggregate table also has a table-specific row ceiling. The sole narrow transformation is documented in the bundle index: the one-row Stage 15 Wilkinson K=2 leave-one-out summary is retained while its `excluded_doi` field is dropped and replaced with the non-identifier description `documented_manual_addition`. The source table’s manifest-certified hash remains recorded. It does not copy raw Dimensions retrievals, publication-level NMF assignments, individual records, node lists, organization names, country rankings, or permutation replicate draws.

Consequently, the bundle remains protected local output. The script refuses to write its output anywhere inside the Git worktree or inside any input-stage directory. It is not a GitHub data release.

## Interpretation boundary

The bundle reproduces completed aggregate evidence and does not change its meaning. Grant and policy outcomes remain Dimensions-recorded identifier links, not causal effects or measures of funding intent, policy endorsement, uptake, or impact. Record-year differences are descriptive database dates, role-separated network summaries do not establish influence, and the configuration test concerns structural alignment of recorded link layers rather than a causal grant-to-policy mechanism.

Later figure and manuscript-material scripts must read the certified bundle rather than independently select prior-stage outputs.

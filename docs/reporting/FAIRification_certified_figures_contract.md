# FAIRification certified-figures contract

`code/reporting/18_generate_certified_figures.py` creates the first local manuscript figure set. It accepts only the completed Script 17 certified aggregate results bundle. It does not retrieve Dimensions data, read an earlier stage directly, fit a model, calculate a new statistical result, or select a result after viewing the figures.

## Certification and input boundary

Before plotting, the script requires the exact completed Script 17 version and its full fixed output contract—not merely a self-labelled `complete` manifest. It verifies the Script 17 stage-manifest and cross-stage-lineage hash declarations, selected-input provenance set, results-bundle validation checks, index, and the exact SHA-256 digest and row count for every bundle output. It reads the selected figure tables from verified byte snapshots rather than hashing a file and reopening it later.

It also rechecks the frozen project values: 163 curated source records, 144 exact-DOI-matched Dimensions publications, 52 grant-linked publications, 4 policy-linked publications, and the 72-publication/3-event primary policy window. Before plotting, it reconciles theme denominators, events, linkage rates, and Wilson intervals; configuration counts and shares; null intervals, enrichment, and p-values; and all three policy-window statuses. Record-year ordering categories are reconciled to Stage 13’s `n_edges_with_both_record_years`, while the reported missing-year count completes the raw audited-edge denominator; no missing year is treated as a timing value. Every policy-window model must be certified as `not_fit`, below its 30-event requirement, before the withheld-model figure can be drawn.

The selected inputs are limited to aggregate scope, edge-count, linkage-outcome, K=3 supplementary theme, grant-association, record-year, policy-event-adequacy, and cross-relation configuration/null-summary tables. A second normalized-column firewall and table-specific row ceiling reject publication, grant, policy-document, DOI, title, abstract, author, organization, issuer, node, edge-list, textual-record, and disguised identifier fields such as `publicationId`. No publication, grant, policy-document, DOI, title, abstract, author, organization, issuer, node, edge-list, or permutation-replicate file is read.

The script refuses to write figures inside either the Git worktree or the certified-bundle input directory. It uses a unique temporary staging directory and does not delete any pre-existing same-prefix directory. It writes atomically to a new local directory with a `figure_manifest.json` and a `figure_captions.md` file.

## Generated figures

1. **Study scope and Dimensions-recorded relation layers.** The 163-to-144 source-to-anchor scope and the recorded P–G, P–D, and issuer–P relation layers.
2. **Supplementary K=3 theme linkage rates.** Hard-assignment NMF component-group sizes and descriptive grant/policy recorded-linkage rates with Wilson intervals. This does not replace the primary continuous-share analysis; the small heritage/preservation component retains its component-specific stability and K=3 leave-one-out caveat.
3. **Primary grant-link associations.** The two non-reference K=3 share terms from the predeclared publication-year-adjusted grant model.
4. **Record-year context and policy event adequacy.** Descriptive stored record-year ordering among edges with both stored years—explicitly labelled with its dated-pair denominator—and the predeclared reason that policy models are withheld: 3 primary-window events versus 30 required.
5. **Year-stratified cross-relation configurations.** Observed P–G/P–D configurations with primary-null interval summaries for extensive and intensive alignment statistics.

Each figure is saved as PNG and PDF. The generated figures and captions are local derived outputs, not an automatic GitHub release.

## Interpretation boundary

The figures reproduce certified aggregate evidence only. Grant and policy outcomes remain Dimensions-recorded identifier links rather than causal effects, funding intent, policy endorsement, policy uptake, or policy impact. Record-year differences are descriptive stored-date quantities. The cross-relation null is a structural test of recorded-link alignment, not a grant-to-policy causal pathway.

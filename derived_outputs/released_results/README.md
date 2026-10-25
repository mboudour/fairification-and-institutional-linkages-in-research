# Reviewed aggregate-only results

These CSV files are the reviewed non-record-level results released from the completed FAIRification pipeline. They are safe for display and manuscript reproduction only because they contain aggregate quantities rather than source, Dimensions, or identifier-level records.

The files follow the certified bundle’s domains:

- `00_`, `A01`, and `A02`: source-to-Dimensions scope and audited relation-layer counts;
- `B01`–`B03`: recorded-linkage outcomes and frozen policy-observation denominators;
- `C01`–`C04`: grant-link model diagnostics and sparse-policy descriptive evidence;
- `D01`–`D02`: descriptive stored record-year and policy-window context;
- `E01`–`E03`: role-separated network and metadata-coverage summaries;
- `F01`–`F06`: NMF, association, and policy-window robustness evidence;
- `G01`–`G03`: observed P–G/P–D configurations and permutation summaries; and
- `H01`: reviewed non-identifier institution/country scope by the full anchor and frozen $K=3$ theme views.

`results_bundle_index.csv` records source-stage provenance and the aggregate-only release check. `results_bundle_validation_checks.csv` records the certified bundle’s validation checks.

`H01_role_separated_institution_country_scope.csv` contains no organization, country, publication, grant, policy-document, or edge identifiers. Its organization and country columns are aggregate counts only. The complementary Figures 6–7 are separately reviewed, selected descriptive displays of role-specific names; see [`docs/release/INSTITUTION_COUNTRY_RESULTS_RELEASE.md`](../../docs/release/INSTITUTION_COUNTRY_RESULTS_RELEASE.md).

These are not raw data. In particular, `A02_recorded_relation_edge_summary.csv` is an aggregate count table, not an edge list. The repository deliberately excludes record-level inputs and outputs, full named representation tables, and all publication, grant, policy-document, organization, issuer, and DOI identifiers.

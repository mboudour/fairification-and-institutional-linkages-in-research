# Reviewed aggregate-only results

These CSV files are the reviewed non-record-level results released from the completed FAIRification pipeline. They are safe for dashboard display and manuscript reproduction only because they contain aggregate quantities rather than source, Dimensions, or identifier-level records.

The files follow the certified bundle’s domains:

- `00_`, `A01`, and `A02`: source-to-Dimensions scope and audited relation-layer counts;
- `B01`–`B03`: recorded-linkage outcomes and frozen policy-observation denominators;
- `C01`–`C04`: grant-link model diagnostics and sparse-policy descriptive evidence;
- `D01`–`D02`: descriptive stored record-year and policy-window context;
- `E01`–`E03`: role-separated network and metadata-coverage summaries;
- `F01`–`F06`: NMF, association, and policy-window robustness evidence; and
- `G01`–`G03`: observed P–G/P–D configurations and permutation summaries.

`results_bundle_index.csv` records source-stage provenance and the aggregate-only release check. `results_bundle_validation_checks.csv` records the certified bundle’s validation checks.

These are not raw data. In particular, `A02_recorded_relation_edge_summary.csv` is an aggregate count table, not an edge list. The repository deliberately excludes publication, grant, policy-document, organization, issuer, and DOI identifiers; all record-level inputs and outputs remain private.

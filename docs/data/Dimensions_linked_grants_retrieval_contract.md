# Dimensions linked-grant retrieval contract

This note documents the local grant retrieval implemented in `code/relational/08_retrieve_linked_grant_records.py`. The input is the frozen 144-record `publication_anchor_final`. It retrieves only the grant IDs already recorded in the anchor’s `supporting_grant_ids` field.

Dimensions documents `supporting_grant_ids` as a publication field containing the list of Dimensions grant IDs supporting a publication. Its cross-source data model describes the two-stage procedure used here: retrieve those IDs from the retained publications, then query the Grants source by those IDs for the actual grant records. [Dimensions publications schema](https://docs.dimensions.ai/dsl/datasource-publications.html) [Dimensions cross-source data model](https://docs.dimensions.ai/dsl/data-model.html)

The grant request is restricted to `id`, title and abstract, start/end timing, active years, funder organization fields, recipient research-organization fields, country and organization-type descriptors, and investigator metadata. Dimensions describes `funder_orgs` as the organization funding a grant; `research_orgs` as organizations receiving a grant; and notes that organization identifiers extracted from source text can be missing. [Dimensions grants schema](https://docs.dimensions.ai/dsl/datasource-grants.html)

The returned grant table retains a `retrieved_from_publication_ids` list and count for every grant. This preserves the identifier-based provenance of the publication–grant relation without inferring a connection from grant titles, topic similarity, funder names, organizations, or free text.

The script does not retrieve policy documents or policy-document text. It does not estimate associations or causal effects. Dimensions-recorded publication–grant relations will be analysed only as database-recorded links; they do not establish causal funding effects, funding intent, or influence.

Raw DSL queries, JSON responses, returned grant records, unreturned grant-ID lists, and manifests are protected local licensed materials. They remain excluded from GitHub.

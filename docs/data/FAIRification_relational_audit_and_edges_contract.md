# FAIRification relational audit and identifier-edge construction contract

`code/relational/10_audit_and_construct_edges.py` is the local, no-API adaptation of the prior project's data-audit and edge-construction stage. It verifies the three completed Dimensions layers before any relational analysis: the 144-record publication anchor (P), the linked grant records (G), and the linked policy documents (D).

The audit also carries forward the source-to-Dimensions coverage design. It checks that the final P table’s source-record identifiers are exactly the 144 records marked as recovered in the record-level coverage audit; that the frozen source cohort remains 163 records; that the remaining 19 records remain visible in the coverage audit; and that exactly one documented manual addition is present and recovered. The relational analyses therefore apply to the Dimensions-recovered analytic subset, not automatically to the entire original Scopus/WoS source corpus.

Three relations are constructed solely from recorded Dimensions identifiers:

- Publication–grant edges are the unique pairs in `P.supporting_grant_ids` whose grant ID exists in final G.
- Publication–policy-document edges are the unique pairs in `D.publication_ids` whose publication ID exists in final P.
- Policy-issuer–publication edges are derived only from retained publication–policy-document edges and a policy document’s supplied publisher-organization identifier. Repeated issuer-publication pairs retain a count of distinct intervening policy documents.

The script verifies the endpoint sets, deduplicates identical pairs, audits field coverage and observed year ranges, and compares each edge with the provenance recorded by the grant and policy retrieval scripts. It makes **zero** Dimensions API requests. It does not inspect policy-document full text, apply semantic filters, label policy content, estimate associations, or make causal claims.

All edge lists, coverage audits, validation tables, and retrieval summaries are protected local data. They remain excluded from GitHub. Recorded Dimensions links are database relationships; they are not evidence of causal funding effects, policy endorsement, policy uptake, policy impact, topical similarity, or institutional intention.

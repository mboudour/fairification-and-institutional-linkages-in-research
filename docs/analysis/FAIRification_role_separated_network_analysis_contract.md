# FAIRification role-separated network analysis contract

`code/analysis/14_networks_organizations_countries.py` is the descriptive network, organization, and country stage. It makes no Dimensions API requests and uses only the completed final publication anchor, linked-grant and linked-policy-document tables, audited edge lists, and relational-summary manifest.

## Distinct networks

The script describes three audited, bipartite identifier networks:

1. **Publication–grant (P–G):** unique publication–grant pairs constructed from recorded Dimensions supporting-grant identifiers.
2. **Publication–policy document (P–D):** unique publication–policy-document pairs constructed from policy-document publication identifiers.
3. **Policy issuer–publication (issuer–P):** unique publisher-organization–publication pairs derived through retained P–D ties. The edge weight is the recorded number of linked policy documents.

For each it reports connected-node coverage, degree summaries, connected components, density among connected nodes, top-node listings, and degree concentration. The P–D network must be read in light of its sparse publication side: only the publications with a recorded policy link enter its connected component.

## Role separation

Publication-affiliation organizations, grant-funder organizations, grant-recipient organizations, and policy-issuer organizations are reported as four separate roles. An organization node is created only where Dimensions provides an explicit organization ID in that role. The script does not infer IDs from names, resolve names, merge organizations across roles, or construct an affiliation–funder or funder–issuer linkage.

This means that a publication affiliation is not interpreted as a funder, a grant recipient is not interpreted as a funder, and no funder is interpreted as a policy issuer—even if a name appears similar across records.

## Country representation

Country tables are non-exclusive counts from the stored Dimensions country attributes, separately for publication affiliations, grant funders, grant recipients, and policy issuers. A record with multiple stored countries contributes once to each of them; percentages therefore need not sum to 100. Missing attributes are reported through role-specific coverage tables and are not imputed.

## Interpretation boundary

Network topology, organization representation, and country representation describe recorded Dimensions identifiers and metadata only. They do not establish organizational influence, institutional preference, intentional selection, causal funding, policy uptake, policy impact, endorsement, knowledge translation, or semantic affinity.

All node-level and edge-level outputs are protected local data. They remain excluded from GitHub.

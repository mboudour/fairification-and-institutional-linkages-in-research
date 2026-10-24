# FAIRification NMF theme decision

**Status:** Frozen for the primary linked-data analysis

**Decision date:** 2026-10-24

**Project owner:** Moses Boudourides

**NMF evidence date:** 2026-10-24

**Scope:** 144 exact-DOI-matched Dimensions publications; 140 with abstracts and 4 represented by title text only.

## Decision

The primary outcome-blind publication-text specification is a **three-component NMF partition (K=3)**:

1. **Institutional stewardship, research-data management, and open-science practice** — 51 publications (35.4%).
2. **Technical metadata, semantic infrastructure, and reproducible workflows** — 80 publications (55.6%).
3. **Digital cultural heritage, collections, and preservation** — 13 publications (9.0%).

The result is not a forced FAIRification analogue of the AI–mental-health partition. Its defensible interpretation is a two-level structure: two broad orientations—stewardship/open-science practice and technical implementation—plus a smaller cultural-heritage/preservation specialization. It is a pragmatic thematic description, not evidence for three equally stable, naturally bounded populations.

The two-component model is retained only as a **predeclared coarsened sensitivity framing** of the two broad orientations. The four-component model is not retained as a primary specification.

## Pre-outcome boundary

No grant, policy-document, citation, funder, organization, country, affiliation, or linkage field was read, retrieved, or used to construct the NMF, select the component count, or interpret these themes. This decision is frozen before the project’s relational retrieval and analysis stages.

## Model and preprocessing

- Unit of analysis: Dimensions publication title repeated twice, plus available abstract.
- Representation: TF–IDF unigrams and bigrams; 2,275 retained features.
- Candidate solutions: K=2, K=3, and K=4.
- Model: NMF with NNDSVDA initialization and coordinate-descent solver; maximum 300 iterations; random seed 20261024.
- Stability: eight 80% publication-subsample bootstraps per candidate solution; Hungarian maximum-cosine matching of bootstrap components to the full solution.
- Retrieval-anchor and generic scholarly language was excluded before vectorisation. Terms capable of distinguishing FAIRification orientations, including metadata, semantic, repository, workflow, preservation, and governance-related language, were retained.

## Evidence for the primary K=3 solution

| Diagnostic | K=2 | K=3 | K=4 |
| --- | ---: | ---: | ---: |
| Reconstruction error | 11.576 | 11.473 | 11.391 |
| Mean dominant-topic share | 0.857 | 0.818 | 0.791 |
| Share with dominant-topic share ≥ .60 | 91.0% | 82.6% | 79.9% |
| Mean component cosine similarity | 0.822 | **0.931** | 0.762 |
| Minimum component cosine similarity | 0.349 | 0.039 | 0.050 |
| Mean dominant-assignment agreement | 0.826 | **0.935** | 0.835 |
| Minimum dominant-assignment agreement | 0.597 | **0.861** | 0.778 |
| Smallest hard-assigned theme | 44.4% | 9.0% | 2.1% |

Reconstruction error is shown descriptively only. It declines mechanically as components are added and does not select K=3 over K=4.

### Interpretation of the comparison

**K=2** is balanced and clear (64 and 80 hard assignments), and it passes the predeclared minimum bipole screen. Its broad contrast is interpretable: institutional stewardship/open-science practice versus technical FAIRification infrastructure and workflows. It is not selected as primary because the stewardship-oriented component is unstable in three of eight bootstrap replications (component cosine similarities 0.349–0.357), indicating substantive substructure.

**K=3** preserves the two broad orientations and separates a coherent cultural-heritage/preservation specialization. Among the evaluated K values, it has the highest mean component similarity (0.931) and mean dominant-assignment agreement (0.935). This aggregate advantage reflects the two highly reproducible broad components: their mean bootstrap component cosine similarities are 0.970 and 0.970, with minima of 0.960 and 0.964. The third component is substantively coherent but smaller and less invariant: seven of eight resamples yielded closely matched components (cosines 0.950–0.980), while one had a cosine similarity of 0.039. It must therefore be described as a small specialist theme, not as an exhaustive or equally stable category. K=3 also has less concentrated assignments than K=2 (mean/median dominant share 0.818/0.862 versus 0.857/0.900), a trade-off accepted in order to distinguish this specialization.

**K=4** introduces a component with three hard assignments (2.1%) whose leading terms are principally an event-series signature (`NISO`, `NISO Plus`, `conference`, `annual`). That component is unstable (mean bootstrap cosine similarity 0.308; six of eight values below .50). K=4 is therefore rejected as the primary partition.

## Component characterizations

| Primary theme | Leading vocabulary | Interpretation rule |
| --- | --- | --- |
| Institutional stewardship, research-data management, and open-science practice | science; management; open; university; open science; researchers; practices; RDM; services; library | Covers institutional, library, repository, support, sharing, and research-data-management practices. |
| Technical metadata, semantic infrastructure, and reproducible workflows | metadata; library; workflow(s); software; open-source; information; community; processing; graph; semantic | Covers metadata standards, semantic annotation, knowledge graphs, software, computational processing, and reproducible workflows. |
| Digital cultural heritage, collections, and preservation | heritage; cultural heritage; cultural; digital; archives; preservation; digital libraries; sustainable; digitization | Covers digital-heritage, archival, humanities, GLAM, and collection-preservation applications. |

The topic labels are operational descriptions of the fitted model and the documented review process. They are not claims that naturally bounded research communities exist.

## Relation between K=2 and K=3

The K=3 specification refines rather than replaces the K=2 broad orientation. The reviewed, non-record-level cross-tab in [`derived_outputs/thematic/topic_2_to_3_crosswalk.csv`](../../derived_outputs/thematic/topic_2_to_3_crosswalk.csv) shows that the K=3 stewardship theme contains 51 records previously in K=2 Topic 1; the technical theme contains 78 records previously in K=2 Topic 2; and the heritage/preservation theme extracts 11 records from K=2 Topic 1 and 2 from K=2 Topic 2. Accordingly, later analysis may report the K=2 framing only as a coarsened sensitivity result.

## Wilkinson et al. sensitivity

The documented manual addition of the foundational FAIR Principles article does not drive the K=2 broad structure. Excluding that one record produces component cosine similarities of 0.99977 and 0.99992 relative to the full K=2 solution. This is a K=2-only sensitivity: it does not establish that the small K=3 heritage/preservation specialization is unchanged by the same exclusion, and it does not remove that component's bootstrap caveat.

## Locked analytical use

All later grant, policy-document, institution, funder, issuer, country, and local-alignment analyses will treat this K=3 theme specification as primary. They must retain continuous component shares and assignment-margin diagnostics; hard-assignment comparisons are supplementary descriptive summaries. Key results must be repeated with low-margin assignments excluded. The eight 80% bootstraps are supportive but limited resampling evidence rather than uncertainty intervals. Any change to the labels, component count, preprocessing, or primary/sensitivity role requires a dated deviation record stating whether relational outcomes had already been inspected.

## Safe release materials

This decision is supported by the reviewed aggregate tables in [`derived_outputs/thematic/`](../../derived_outputs/thematic/). The repository does not contain the source corpus, Dimensions responses, publication-level assignments, publication titles or abstracts, DOI/identifier tables, or review packets.

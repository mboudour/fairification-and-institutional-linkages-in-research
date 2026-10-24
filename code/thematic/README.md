# Outcome-blind publication-text thematic analysis

The FAIRification thematic stage uses the Dimensions-recovered publication anchor only. The input representation is title twice plus available abstract. It compares NMF solutions at K=2, K=3, and K=4 under fixed TF-IDF preprocessing and bootstrap stability diagnostics.

The model may not read or use grant, policy-document, citation, funder, organization, country, affiliation, or linkage variables. Following documented review of terms, representative publications, assignment uncertainty, bootstrap stability, and sensitivity checks, the frozen primary interpretation is K=3: two broad FAIRification orientations plus a small cultural-heritage/preservation specialization. See [`docs/thematic/FAIRification_NMF_theme_decision.md`](../../docs/thematic/FAIRification_NMF_theme_decision.md).

Corpus text, record-level assignments, review packets, and private diagnostics remain excluded. The reviewed component-level summary, size, term, bootstrap-stability, K=2 screen, validation, and K=2-to-K=3 cross-tab tables are versioned in [`derived_outputs/thematic/`](../../derived_outputs/thematic/) because they contain no source records, identifiers, bibliographic text, entities, or edges.

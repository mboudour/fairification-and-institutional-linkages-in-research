# Reviewed aggregate NMF outputs

This directory contains only component-level, non-record-level outputs supporting the frozen FAIRification NMF theme decision:

- `topic_model_summary.csv` — candidate-K model diagnostics;
- `topic_sizes.csv` — component sizes, assignment-concentration summaries, and top terms;
- `topic_terms.csv` — ranked component vocabulary and weights;
- `topic_stability_detail.csv` — bootstrap component-level stability metrics;
- `bipole_screen.csv` — predeclared K=2 diagnostic screen;
- `validation_checks.csv` — input and output validation-check counts.

These tables contain no publication IDs, titles, abstracts, authors, DOIs, organizations, funders, policy documents, or edges. They are reviewed aggregate analytical outputs, not a redistribution of the source Scopus corpus or Dimensions records.

The following NMF materials remain private and excluded from Git: input corpus text, record-level topic assignments, review packets, source-to-Dimensions matching materials, raw API responses, serialized data, spreadsheets, and the full local manifest containing private file paths and hashes.

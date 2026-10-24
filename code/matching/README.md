# DOI-first publication matching

The project uses deterministic DOI-first matching from the curated source cohort to Dimensions publication identifiers.

The local workflow must:

1. build a stable source registry;
2. retrieve publication identity candidates for normalized source DOIs;
3. accept only unambiguous one-to-one exact normalized DOI matches;
4. retain unmatched records in a coverage audit rather than silently dropping them; and
5. preserve raw request/response files locally, outside Git.

Title/author/year fallback matching is not part of the primary FAIRification publication anchor unless a new decision record explicitly authorizes it.

No data, API responses, registry rows, candidate tables, decisions, or match outputs are tracked in this repository.

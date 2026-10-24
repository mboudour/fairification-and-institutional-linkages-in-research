# Manual addition of the foundational FAIR Principles article

`libraries_dataset_nq_with_wilkinson_2016.csv` is an updated version of the supplied 162-record Scopus-style dataset. It contains one additional, appended record for:

> Wilkinson, M. D. *et al.* The FAIR Guiding Principles for scientific data management and stewardship. *Scientific Data* 3, 160018 (2016). https://doi.org/10.1038/sdata.2016.18

The source dataset did not contain this article as a `Title` or `DOI` record. One occurrence of the title was found only within the abstract of another record, which is not an inclusion. The updated dataset preserves the original 33-column schema and every one of the 162 pre-existing records, then appends the new record as row 163.

Bibliographic metadata, abstract, journal details, publication date, article number, publisher, ISSN, licensing, and author information were verified from Crossref and the article’s PMC/PubMed records. The appended row includes 53 authors and 47 affiliations recovered from the PMC XML record. [1] [2] [3]

Some Scopus-specific fields are deliberately empty: Scopus author IDs, EID, and the export-date `Cited by` count. They were not available from the verified public metadata and have not been imputed from a different citation index. Scopus index keywords are also blank. This is intentional and documented in the accompanying JSON manifest. The later Dimensions enrichment should match the article by DOI and use Dimensions-derived citation and affiliation fields for the linked-data analysis.

The source CSV remains unmodified. Its SHA-256 is `0a3c02c0dd83fa5c16ce54e25829a8d7e1955501137b1583db1b1bb8b021ee5b`. The updated CSV SHA-256 is `b83d0044404320dff2d0b3d77361820a08e1052348746899ee6e3b1d116286c6`.

**References**

[1]: https://api.crossref.org/works/10.1038/sdata.2016.18 "Crossref metadata for the FAIR Guiding Principles article"

[2]: https://pmc.ncbi.nlm.nih.gov/articles/PMC4792175/ "PMC full text for the FAIR Guiding Principles article"

[3]: https://pubmed.ncbi.nlm.nih.gov/26978244/ "PubMed record for the FAIR Guiding Principles article"

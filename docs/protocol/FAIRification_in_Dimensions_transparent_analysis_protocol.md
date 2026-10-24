# FAIRification in Dimensions: transparent analysis protocol

## Decision and objective

This is the first project. **HTA is out of scope until the FAIRification project has completed its core analyses.**

The project has four ordered objectives:

1. Use the frozen, curated Scopus or Web of Science FAIRification corpus as the externally defined publication universe, then retrieve and match its records in Dimensions.
2. Use an outcome-blind, publication-only NMF to determine whether the matched FAIRification corpus supports two broad, stable, interpretable themes.
3. Run the transferable, publication-centred relational computations from the Niko project on the FAIRification data, adapting every domain-specific component transparently rather than copying it silently.
4. Draft a paper with the same broad structure and inferential discipline as the Niko paper.

The received Scopus/WoS export, the frozen curated source cohort, and the Dimensions-enriched corpus are not interchangeable. The raw export is preserved as received. The curated source cohort defines the research field. The Dimensions corpus is the high-confidence matched subset for which Dimensions identifiers and recorded grant, policy-document, affiliation, funder, and policy-issuer attributes are available.

## The data model

Let \(S_0\) be the received 162-record Scopus export, \(C(S_0)\) be the documented manual source-curation operation, \(S\) be its frozen 163-record FAIRification cohort, and \(D\) be the Dimensions publication universe. The study population is built in four explicitly retained layers:

\[
S_0 \longrightarrow C(S_0)=S \longrightarrow M(S,D) \longrightarrow P,
\]

The sole current curation operation appends Wilkinson et al. (2016), DOI `10.1038/sdata.2016.18`, after verification that it was absent as a source-record title or DOI. The associated script, metadata-source record, notes, hashes, and field-level limitations are retained. \(M(S,D)\) is the full source-to-Dimensions matching table and \(P\) is the one-to-one, high-confidence Dimensions-matched FAIRification publication anchor.

Dimensions enrichment then produces the same publication-centred relations as in the Niko project:

\[
P\text{–}PI, \quad P\text{–}G, \quad G\text{–}GI, \quad P\text{–}D, \quad D\text{–}DI.
\]

Here, \(PI\) denotes author-affiliation institutions, \(G\) grants recorded as supporting publications, \(GI\) funders, \(D\) policy documents with a recorded publication relation, and \(DI\) policy-document issuers. These are database-recorded relations. They are not evidence that a funder chose a topic, that policy adopted a finding, or that a publication caused policy impact.

## Non-negotiable transparency rules

The project will not use the prior archive as a black box. The archive is a reference implementation and analytical lineage, not an instruction to reuse AI–mental-health terms, topic labels, data paths, or results.

The following rules apply throughout.

- The received Scopus/WoS files will be preserved unchanged, with a manifest containing file hashes, receipt date, supplied field names, source-database provenance, and the documented search definition.
- The frozen source cohort is the 163-record curated file, not the unmodified 162-record export. Its curation manifest records the one appended foundational article, its DOI, its source metadata, the raw- and curated-file hashes, and Scopus-specific fields intentionally left blank. The manual addition occurred before Dimensions matching and before any grant, policy, citation, institution, or funder outcome was retrieved.
- Every Dimensions request will have a saved query or request body, retrieval timestamp, access endpoint, paging log, returned record count, raw response or licensed export location, and checksum. The same metadata will be stored for grants and policy documents.
- The matching table will retain one row for every source publication, including all candidate Dimensions matches, match features, resolution rule, decision, ambiguity flag, and reason for non-match. No unmatched or ambiguous record will disappear.
- Match decisions will be made without examining grant, policy, citation, institution, or funder outcomes. DOI matching is the first tier. A non-DOI match requires a reproducible title–author–year rule and an explicit audit status.
- No topic label, dictionary, threshold, model covariate, or analytic exclusion will be selected after reading grant or policy-linkage results. Changes require a dated entry in a deviation register that states what changed, why, and whether any outcomes had already been viewed.
- Every analytical output will contain an input manifest with filenames, hashes, record counts, parameter settings, random seeds, software versions, and a script version identifier.
- Results will distinguish `confirmatory core`, `robustness/sensitivity`, and `exploratory` analyses. Exploratory output will never be presented as though it had been part of the primary plan.

## FAIRification acquisition and matching

### Raw source export and frozen curated cohort

The received 162-record Scopus/WoS export is stored as \(S_0\) and is never edited. The manually appended, 163-record CSV is the frozen analytic source cohort \(S\), and is stored separately with its curation script, notes, and manifest. The source-to-Dimensions denominator is therefore 163, with the origin of every source record recorded as either `original_export` or `documented_manual_addition`.

The manually added Wilkinson et al. record is a primary DOI match candidate. Its blank Scopus author IDs, EID, source-export citation count, and Scopus indexing fields must remain blank in source-cohort materials; they must not be treated as zeros, imputed, or used to exclude the record. Dimensions-derived fields, after an accepted match, are separate enrichment values. The source identifiers—DOI where available, title, authors, year, source title, volume, issue, and pages—will be normalized in a derived working table, while the raw and frozen source files remain unchanged.

### Dimensions publication matching

The Dimensions retrieval is a targeted enrichment exercise, not a fresh FAIR search that could redefine the cohort.

The matching hierarchy is fixed before linkage outcomes are retrieved:

1. **Exact normalized DOI match** is accepted when the DOI is unique in the source cohort and uniquely resolves in Dimensions.
2. **Non-DOI candidate retrieval** uses normalized title, publication year, and author evidence. A fallback match is accepted only when its deterministic score meets the predeclared threshold and there is no competing candidate of comparable quality.
3. **Ambiguous, conflicting, and no-match cases** stay in the matching audit. They are excluded from \(P\), but remain in the source-to-Dimensions coverage report.

The record-level audit must report the match rate overall and by source year, document type, abstract availability, source database, broad field if present, DOI availability, and source-record origin. It must explicitly verify that the Wilkinson et al. DOI has one source row and report its Dimensions match decision. This establishes what the Dimensions-matched FAIRification population represents and what it does not.

### Dimensions relational retrieval

Only after \(P\) is frozen will the project retrieve the relations required for the prior computation pipeline. The output data contract will include, at minimum:

- `publication_anchor_final`: Dimensions publication identifiers, title, abstract, year, document type, DOI, author affiliations, organizations, countries, citation count, supporting-grant identifiers, and retrieval/match provenance.
- `linked_grants_final`: all grants referenced by a retained \(P\) record, including grant identifier, year/date where available, funder, recipient organization, and raw-record provenance.
- `linked_policy_documents_final`: all policy documents whose recorded publication identifiers include a retained \(P\) identifier, including document identifier, year/date, publisher/issuer organization, country where available, and raw-record provenance.
- `publication_screening_decisions`: all source records and their Dimensions candidate/match/screening status. This replaces the AI–mental-health-specific phrase columns with FAIRification-specific fields.
- `retrieval_summary`: the full data-flow count from source corpus to matched publication anchor to linked grants and policy documents.

The Dimensions retrieval and stored project outputs must comply with the applicable institutional licence and Dimensions reasonable-use terms. The project will retain what is necessary for this defined analysis and will not represent the local extract as an alternative copy of Dimensions.

## Outcome-blind NMF of FAIRification themes

**Decision implementation update (2026-10-24).** The planned K=2 question and K=3/K=4 diagnostics were run before any relational-outcome retrieval or analysis. The frozen primary specification is K=3: institutional stewardship/research-data management/open-science practice; technical metadata/semantic infrastructure/reproducible workflows; and a small digital-cultural-heritage/collections/preservation specialization. K=2 is retained only as a coarsened sensitivity framing and K=4 is rejected. The complete rationale, caveats, and locked analytical role are in [`docs/thematic/FAIRification_NMF_theme_decision.md`](../thematic/FAIRification_NMF_theme_decision.md). The original planned decision logic is retained below for auditability.

The NMF is the first substantive analysis of \(P\). Grants, policy documents, funders, policy issuers, institutions, countries, citations, and link outcomes are not read by the NMF script.

The primary model uses concatenated title and abstract text, with the title given modest extra weight as in `publication_topic_model_diagnostic.py`. Retrieval-anchor language will be removed before vectorisation so the model does not rediscover the query. This includes the FAIR expressions that defined the source cohort—such as `FAIR`, `FAIR data`, `FAIR principle`, `FAIRification`, and the expanded FAIR words where present. Standard scholarly stopwords will also be removed. Terms that might differentiate FAIR research, such as *metadata*, *interoperability*, *repository*, *curation*, *licensing*, *privacy*, *ontology*, *assessment*, or *workflow*, will not be removed merely because they are expected to be important.

The primary planned question is a **two-component NMF**. The working hypothesis, not a pre-assigned conclusion, is that the two components may distinguish a more technical/machine-actionable FAIR orientation from a stewardship, governance, and implementation orientation. This label will not be adopted unless it is supported by topic terms and blinded document packets. The completed diagnostic determined that K=3 was the more informative primary specification; see the dated decision implementation update above.

The protocol also fits \(K=3\) and \(K=4\) as diagnostic alternatives. A two-theme account is retained only if both components are sufficiently populated, stable under document resampling, interpretable from their top terms and document packets, and not revealed by the higher-\(K\) models to be an unhelpful merger of distinct themes. The NMF outputs preserve continuous theme shares, dominant-theme assignment, assignment margin, entropy, top terms, and high-membership/typical-paper review packets.

Theme names and the primary theme specification are frozen before any linkage outcome table or model is viewed. A later model may use hard assignment for clear descriptive comparisons, but it must retain continuous shares and repeat key results after excluding low-margin publications.

## Rebuilding the Niko computation pipeline for FAIRification

The original archive contains historical variants, final `v6` scripts, and explicitly exploratory methods. It is not a file-by-file chronological recipe. The FAIRification project will follow the validated **logical** sequence below.

### Core sequence

**A. New upstream stage: source registry, Dimensions retrieval, and matching.** This stage does not exist in the preserved `v6` archive because its prior publication anchor had already been constructed. It is new and is essential for the FAIRification project.

**B. Data audit and identifier-based edge construction.** Adapt the logic in `step1_v6_audit_and_edges_v2.py`. It will verify the final publication, grant, and policy-document tables; enforce identifier uniqueness; audit field coverage; build \(P\text{–}G\), \(P\text{–}D\), and \(D\text{–}DI\) edges; check whether every edge endpoint belongs to the approved final data tables; and write a manifest. The FAIR version will add the source-to-Dimensions match-quality audit to this step.

**C. Publication-only NMF.** Adapt `publication_topic_model_diagnostic.py` before all relational analyses. Its output becomes a core FAIRification input rather than a detached diagnostic. The FAIR anchor phrases, stopword list, candidate \(K\) values, bootstrap count, review packets, topic decisions, and freeze date will be preserved in a theme-decision record.

**D. FAIR-specific cross-cutting indicators and concept audit.** The AI–mental-health terms in `step2_v6_operationalize_indicators.py` (`ethics/responsibility` and `computational performance`) cannot be transferred. A FAIR codebook will be defined before linkage analysis only if it adds a concept that the NMF does not already represent—for example, a transparent technical-infrastructure or stewardship/governance score. The codebook must include included terms, excluded near-matches, field coverage, prevalence, overlap, and sensitivity definitions. Dimensions concept fields, if retrieved, remain a separate descriptive audit and do not replace text-based themes.

**Decision implementation update (2026-10-24).** No separate FAIR keyword indicator or manual concept-family layer is used in the primary association model. The outcome-blind K=3 NMF already represents the field’s stewardship/open-science, technical-infrastructure, and heritage/preservation orientations; a post hoc overlapping dictionary would not add an independently justified construct. The primary association representation is therefore continuous K=3 shares, with hard dominant-theme labels reserved for supplementary descriptions. The full frozen specification is in [`docs/analysis/FAIRification_publication_linkage_analysis_specification.md`](../analysis/FAIRification_publication_linkage_analysis_specification.md).

**E. FAIR-specific thematic enrichment.** The manual mental-health concept families in `step3_v6_construct_topic_families_v2.py` cannot be reused. The primary FAIR themes are the frozen NMF themes. If a separate Dimensions-concept family layer is valuable, it will be supplementary, codebook-based, non-exclusive, and outcome-blind. It cannot silently become a substitute for the NMF result.

**F. Publication-level linkage associations.** Adapt `step4_v6_linkage_associations.py`. The outcomes remain `has_grant_link` and `has_policy_document_link`, based only on recorded Dimensions links. The primary explanatory structure becomes the frozen FAIR NMF theme representation; all control variables, including the rationale for publication year and citation variables, will be declared in advance. Coefficients describe adjusted associations, not causes.

**Decision implementation update (2026-10-24).** The primary model uses continuous K=3 shares for Themes 1 and 3, with Theme 2 as the compositional reference, and centered publication year. Citation adjustment is a separately labelled sensitivity, not primary adjustment. A multivariable model is fitted only if its sample has at least 10 observed outcome events per non-intercept parameter. When this rule fails, the analysis reports a certified `not_fit` diagnostic and descriptive counts rather than forcing a sparse policy-link model. See [`docs/analysis/FAIRification_linkage_association_event_adequacy_rule.md`](../analysis/FAIRification_linkage_association_event_adequacy_rule.md).

**G. Policy-window and temporal sensitivity.** Adapt `step5_v6_policy_window_and_timing_v2.py`. The policy data-end year is the actual frozen retrieval endpoint, not automatically 2025. The primary publication-year cutoff is selected from a predeclared minimum observation window; a longer-window cohort is a robustness analysis. Differences between grant, publication, and policy years are descriptive record-timing quantities only.

**Decision implementation update (2026-10-24).** The frozen policy retrieval endpoint is 2026. Publications through 2022 form the primary policy-link association sample; publications through 2021 form the longer-window robustness sample; and all retained publications form a clearly labelled sensitivity sample. These choices were recorded before association-model fitting.

The temporal implementation reports only year differences stored on linked Dimensions records and retains negative differences; it does not fit an additional policy regression when the separate event-adequacy rule precludes one. See [`docs/analysis/FAIRification_policy_window_and_record_timing_contract.md`](../analysis/FAIRification_policy_window_and_record_timing_contract.md).

**H. Institutions, funders, issuers, and countries.** Adapt `step6_v6_networks_organizations_countries.py`. Roles stay distinct: publication affiliations are not funders, and funders are not policy issuers. Results are descriptive representations and degree/concentration summaries, not claims of institutional influence.

**Decision implementation update (2026-10-24).** The local network stage constructs only the three audited identifier networks (P–G, P–D, and issuer–P) and reports affiliation, funder, recipient, and issuer organizations as separate roles. It will neither infer identifiers from names nor merge apparent organizations across roles. Country counts are non-exclusive stored-attribute representations. The implementation and its interpretive boundary are documented in [`docs/analysis/FAIRification_role_separated_network_analysis_contract.md`](../analysis/FAIRification_role_separated_network_analysis_contract.md).

**I. Robustness.** Adapt `step7_v6_indicator_robustness.py` to the FAIR codebook and the NMF design. Robustness will cover at least NMF stability, low-margin assignment exclusions, FAIR indicator definitions if used, the policy observation window, and a clearly labelled leave-one-out NMF sensitivity excluding the single documented manual addition. The 163-record cohort remains primary; the leave-one-out result checks whether a foundational article alone determines the topic solution. It will not introduce new terms or choose a model because its result is more favorable.

**Decision implementation update (2026-10-24).** The local robustness stage consolidates the fixed K=2/K=3/K=4 NMF diagnostics, low-margin and citation grant sensitivities, and the predeclared policy windows. It also refits the full and leave-one-out K=2 NMF models on the frozen publication anchor, retaining the full-corpus TF--IDF vocabulary, because the standard local NMF diagnostic does not itself write a leave-one-out table. No FAIR keyword indicator is used because it would duplicate the outcome-blind NMF representation. The leave-one-out result is reported strictly as a K=2-only sensitivity and does not support an invariance claim for the primary K=3 heritage/preservation component. See [`docs/analysis/FAIRification_robustness_evidence_consolidation_contract.md`](../analysis/FAIRification_robustness_evidence_consolidation_contract.md).

**J. Local cross-relation configurations.** Transfer `step12_v6_local_configurations.py` with minimal logical change. The primary test permutes each \(P\text{–}D\) publication endpoint within publication-year strata while holding \(P\text{–}G\) ties fixed. This asks whether recorded grant and policy relations align on the same FAIR publications beyond a year-conditioned null. It is a structural database-linkage test, not a causal pathway from funding to policy.

**Decision implementation update (2026-10-24).** The local configuration stage uses only the audited P–G and P–D identifier edges, after verifying their upstream manifest hashes rather than counts alone. Its primary statistics are the number of publications with both links and the sum of publication-level P–G-by-P–D degree products; the unrestricted endpoint permutation is sensitivity-only. Because only four publications have recorded policy links, the N-both statistic is analytically checked for exact stratum-constrained degeneracy, while other no-variation cases are labelled as Monte Carlo-limited rather than declared degenerate. Context configuration counts receive no p-values. Policy issuers are optional descriptive observed context, never independently rewired, and incomplete issuer metadata does not gate the P–G/P–D test. See [`docs/analysis/FAIRification_local_cross_relation_configuration_contract.md`](../analysis/FAIRification_local_cross_relation_configuration_contract.md).

**K. Figures and paper materials.** Adapt the final figure and supplementary-material scripts only after the tables and sensitivity decisions are frozen. Figures will read only certified aggregate outputs and will state denominators, matched-corpus restrictions, and outcome definitions.

### Exploratory analyses

The archive also contains mixed-mode communities (`step8_v6_mixed_mode_communities.py`), coupled NMF profiles (`step9_v6_coupled_nmf_profiles.py`), regularized coupled Poisson factorization (`step10_v6_regularized_coupled_poisson.py`), and correspondence analysis (`step11_v6_correspondence_analysis.py`). These are valuable possibilities, but they are not required to answer the four core project objectives.

They will be kept separate from the primary paper logic. If run, they will use frozen core inputs, retain their own manifests and stability/holdout diagnostics, and be described as exploratory. They will not drive the primary NMF labels, the inclusion rule, or causal interpretation.

## Paper architecture

The paper will retain the structural logic of the Niko manuscript while making the source-matching design explicit.

1. **Introduction.** Define FAIRification as the fixed source corpus and state the question about its Dimensions-recorded funding and policy-document relations.
2. **Literature and conceptual framing.** Explain the possible technical-infrastructure versus stewardship/governance organization without claiming that the opposition exists before NMF.
3. **Data and methods.** Report the Scopus/WoS source corpus, Dimensions matching hierarchy, unmatched-record audit, relational data model, outcome-blind NMF, association models, policy-window logic, institutional representations, robustness analyses, and alignment null.
4. **Results.** Give the source-to-Dimensions flow; matched-corpus coverage; the NMF topic structure and uncertainty; recorded grant and policy-linkage patterns; institution/funder/issuer representations; and robustness/alignment results.
5. **Discussion.** Interpret the field structure and recorded relational patterns, while maintaining the distinction between database coverage and real-world funding or policy influence.
6. **Transparency materials.** Supply the query/request log, matching rule, match-status summary, screening audit, NMF codebook and review packets, parameter manifests, data dictionaries, and a code/deviation register consistent with the governing licence.

## Completion conditions

The FAIRification analysis is complete only when the following have been produced and checked: the immutable raw-source manifest; the curated-163-record source-cohort manifest; the full Dimensions request log; the record-level matching audit; the final linked data contract; a frozen outcome-blind NMF decision record; certified core computation outputs and sensitivity outputs; a deviation register; reproducible figures; and a manuscript draft with every claim aligned to the data actually observed.

No FAIRification conclusion will be presented as a claim about the whole Scopus/WoS field if it relies on the Dimensions-matched subset without reporting the matching coverage. No conclusion based on a recorded grant or policy edge will be presented as proof of causal selection, policy endorsement, policy uptake, or policy impact.

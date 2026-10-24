# FAIRification linkage-association event-adequacy rule

**Status:** Frozen before association-model fitting

The primary association representation uses continuous K=3 NMF shares. Topic 1 and Topic 3 shares are entered per ten-percentage-point shift, with Topic 2 as the compositional reference, together with centered publication year. This produces three non-intercept parameters in each primary association model.

A multivariable logistic model is fitted only when the analysis sample has at least **10 observed outcome events per non-intercept parameter**. Thus, the three-predictor primary model requires at least 30 events. The rule is assessed separately for every outcome and every sensitivity sample after any complete-case restriction.

If the rule is not met, the output is a certified `not_fit` diagnostic together with descriptive counts and rates. The project will not introduce a penalized, sparse, univariate, or otherwise less stable policy model merely to generate a coefficient. The absence of a fitted policy-link coefficient is a substantive limitation of the observed record-link data, not a missing computational step.

The primary grant-link model is assessed under this rule for all final publications. The primary policy-link model is assessed in the predeclared policy-window cohort, with longer-window and all-publication analyses retained only as separately labelled checks. Citation-adjusted grant results and low-NMF-margin exclusions are sensitivities, not mechanisms for selecting a preferred result.

Every fitted coefficient is a conditional association among Dimensions-recorded identifier links. It does not establish a causal funding effect, funder intent, policy endorsement, policy uptake, policy impact, topical similarity, or institutional influence.

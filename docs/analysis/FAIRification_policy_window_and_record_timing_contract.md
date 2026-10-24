# FAIRification policy-window and record-timing contract

`code/analysis/13_audit_policy_windows_and_record_timing.py` is the local, no-API temporal-accounting stage. It reconciles the final publication anchor, linked grants, linked policy documents, audited identifier edge lists, frozen publication-level analysis base, and completed association manifest.

The script preserves the policy-data endpoint and the two policy-observation cohorts fixed before model fitting: the primary cohort stored in the base uses publications through 2022; the longer-window robustness cohort uses publications through 2021. The all-publication cohort remains a clearly labelled sensitivity because recent publications have fewer observed policy-document years. It rechecks that the stored flags and observed-year counts exactly match this frozen design.

For every recorded publication–grant and publication–policy-document edge, the script calculates the difference between the relevant Dimensions record years. It reports the availability, negative/zero/positive counts, median, quartiles, and extrema. A negative difference is retained rather than deleted. It can arise because a linked record is dated earlier than a publication record and does not invalidate the recorded identifier link.

These are record-year comparisons only. They are **not** causal lags, time to policy impact, evidence of policy uptake, policy endorsement, knowledge translation, funding effect, topical similarity, or institutional influence. The temporal script performs no policy regression; the guarded association stage independently determines whether the policy-event count can support one.

All edge-level timing tables, policy-window summaries, validations, and manifests are protected local data and remain excluded from GitHub.

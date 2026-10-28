# Evaluation Methodology v1.3 (reporting extension: severity MAE)

> **Status: approved by the owner (2026-10-28) as a reporting-only extension.**
> - **Proposed after Stage 2a was authorised and launched.** It played no part in prompt design (V1–V7 were registered beforehand), the D9 v2 selection rule, τ = 0.40, or any Stage 2a setting.
> - **Scoring is unchanged:** `methodology.METHODOLOGY_VERSION` stays `evaluation-methodology-v1.2`, and every existing score in every result is identical. v1.3 adds severity metrics that are computed offline from saved results (`severity_metrics.py`, `scripts/eval_severity_report.py`) and stored in separately versioned reports (`severity-report-v1.3`).

## What v1.3 adds

| Metric | Definition | Role |
|---|---|---|
| **Severity MAE** | mean \|predicted − expected\| over **valid** severity predictions, in severity levels (scale 1–5) | **Primary severity-specific reporting metric** |
| Mean signed error | mean (predicted − expected) over valid predictions; > 0 means over-rating | Supporting: direction of bias |
| Exact accuracy | share of valid predictions with predicted = expected | Supporting |
| Within ±1 | share of valid predictions with \|error\| ≤ 1 | Supporting |
| Confusion matrix | ground-truth level × predicted level, plus `missing` (`extraction_stats.severity_analysis`, unchanged) | Supporting |
| Coverage and failures | valid predictions / attempted video-runs; the rest by category (`no_model_output`, `no_predicted_level`) | Reported next to MAE, always |

- **Valid severity prediction:** a video-run with a model output whose severity field was scored and holds a level from 1 to 5. The valid-output, matching and missing-output definitions are unchanged.
- **Failed calls and invalid outputs:** these are **never given a severity value**. They lower coverage; they do not enter MAE.
- **Paired comparison** (candidate − baseline):
  - per video, the mean over its repeats with a valid prediction;
  - a video counts when both sides have one;
  - 95% video-level cluster bootstrap: repeats move with their video, 10,000 resamples, seed 20261027 (`methodology.BOOTSTRAP_*`).
  - A negative MAE difference means a smaller error than the baseline.
  - A difference whose interval includes 0 is **not** evidence of an improvement.
- **The exact accuracy figures differ:** v1.3's exact accuracy is conditional on a valid prediction. The incident-field `severity_level` accuracy in the main report counts an invalid output as a miss. Both are reported and labelled.

## Primary severity metric against the selection objective

- **MAE is the primary metric for analysing severity estimation.** It distinguishes a one-level error from a four-level one, which exact accuracy does not.
- **D9 v2 remains the pre-registered, unchanged prompt-selection objective.** Its severity component is the exact-match severity score, and its weights, components, guardrails and `+0.02` minimum are untouched.
- **MAE never enters selection during Stage 2:** it neither replaces exact accuracy in D9 nor acts as a tie-breaker. Any future use of MAE in selection would need a new methodology version, pre-registered before the data it selects on.

## Why MAE, and its limits

- **Ordinal scale:** severity is a 1–5 ordinal scale. Exact accuracy treats every miss as equal, so a level-3 incident called 4 and one called 1 count the same. MAE uses the distance, and the signed error shows over- or under-rating, which Stage 1 showed is the main failure (ground-truth level 3 predicted as 4 or 5 in 24 of 38 outputs).
- **Unequal distances:** MAE treats adjacent levels as equally far apart. The rubric's levels are not guaranteed to be equal intervals: the step from 4 (severe harm) to 5 (fatal, catastrophic) may be larger than the step from 1 to 2. MAE is therefore read together with the confusion matrix and within-±1. It is never the sole basis for a claim.
- **Conditional on validity:** MAE is computed over valid predictions only, so a configuration with lower coverage can show a lower MAE on an easier subset. Coverage is always reported next to MAE, and paired comparisons use only videos valid on both sides.

## Results

Severity reports are kept separately from the original results (`eval_data/results/reports/severity-v1.3/`, local). The summary is in [`../docs/experiments/severity-v1.3.md`](../docs/experiments/severity-v1.3.md).

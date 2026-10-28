# Severity analysis under the methodology v1.3 reporting extension

> **Reporting only** ([methodology v1.3](../../methodology/evaluation-methodology-v1.3.md)).
> - **Not selection:** MAE is the primary severity-specific metric. D9 v2, with exact-match severity, stays the prompt-selection objective, unchanged.
> - **No calls:** computed offline from saved outputs, with no model or judge call. The original results are unchanged.
> - **Timing:** proposed after Stage 2a was authorised. It did not influence prompt design or the D9 rule.

## Stage 1 baselines (C1 direct VLM, C2 VSS; dev, 25 clips × 2 repeats)

Report: `eval_data/results/reports/severity-v1.3/stage1/severity-report-v1.3.{json,md}` (local). Its sources are the two v1.1 `results.json` files, with SHA-256 recorded. Severity scoring is the same under v1.1 and v1.2.

| Config | Attempted | Valid severity | Coverage | **MAE** | Mean signed error | Exact | Within ±1 | Over / under-rated |
|---|---|---|---|---|---|---|---|---|
| C1 direct | 50 | 34 | 0.68 | **1.118** | +0.176 | 0.147 | 0.735 | 17 / 12 |
| C2 VSS | 50 | 30 | 0.60 | **0.933** | +0.533 | 0.267 | 0.800 | 17 / 5 |

| Paired | Pairs (videos) | MAE (C1 → C2) | MAE difference | 95% CI | Signed-error difference | 95% CI |
|---|---|---|---|---|---|---|
| C2 − C1 | 18 | 1.056 → 0.944 | −0.111 | [−0.417, +0.167] | +0.222 | [−0.250, +0.639] |

- **Failures without a valid severity:** C1 has 16 request failures. C2 has 18 request failures and 2 invalid outputs with no predicted level.
- **Typical error:** about one level (MAE 0.93–1.12). Both arms over-rate more often than they under-rate (17 over against 12 and 5 under).
- **C2 against C1:**
  - C2's lower MAE and higher bias are both within noise: the intervals include 0.
  - The arms send the same request, so the difference is run-to-run variation, as the main Stage 1 report found for other fields.
- **Compared with exact accuracy:** both views agree that neither arm is reliably better.
  - Exact accuracy (0.15 against 0.27) hides that most errors are one level away (within ±1: 0.74–0.80).
  - It also hides that C1's errors are more spread out: under-ratings partly cancel over-ratings in C1's mean signed error (+0.18), while MAE (1.12) still shows the larger error.

## Stage 2a (baseline and V1–V7)

Added when Stage 2a completes. Each version is paired against the interleaved `s2-vss-baseline`. Of particular interest: whether V1 (severity calibration) lowers MAE and the over-rating bias, read with its interval.

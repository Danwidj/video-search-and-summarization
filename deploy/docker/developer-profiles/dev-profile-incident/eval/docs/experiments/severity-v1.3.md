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

Reports (local):
- recovery-adjusted: `eval_data/results/reports/stage2a/recovery-adjusted-v1/severity-v1.3/`;
- original runs: `eval_data/results/reports/stage2a/original/severity-v1.3/`.

Each version is paired against the interleaved `s2-vss-baseline` over all 25 clips. Full table: [Stage 2a results §5](stage2a-results.md#5-severity-methodology-v13-reporting-extension-mae-is-never-used-in-selection).

| | MAE | Signed error | Within ±1 | Over / under | Paired MAE difference [95% CI] | Signed-error difference [95% CI] |
|---|---|---|---|---|---|---|
| Baseline | 1.082 | +0.184 | 0.714 | 23 / 16 | – | – |
| V1 severity | 0.860 | +0.420 | 0.880 | 28 / 9 | **−0.220 [−0.380, −0.080]** | +0.220 [−0.040, +0.520] |
| V7 checklist | 0.857 | +0.204 | 0.775 | 20 / 11 | −0.220 [−0.420, −0.020] | +0.020 [−0.220, +0.280] |

- **V1 lowers severity MAE:** the interval excludes 0. The original-run difference is −0.240 [−0.400, −0.100].
- **V1 does not lower the over-rating bias:** the signed error rises, and its interval includes 0. The gain comes from fewer under-ratings (16 → 9) and fewer large misses, while over-ratings rise (23 → 28).
- **The bias V1 targeted was not stable:** the Stage 2a baseline's bias (+0.18) is smaller than Stage 1 C2's (+0.53), which motivated V1.
- **V7 matches V1's MAE reduction** without adding bias.
- **D9 is unchanged:** it still scores severity by exact match (V1 +0.06, V7 +0.16 [+0.04, +0.30]).

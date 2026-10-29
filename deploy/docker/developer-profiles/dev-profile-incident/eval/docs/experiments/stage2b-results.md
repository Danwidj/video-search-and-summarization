# Stage 2b results (V8) and the final Stage 2 selection

> **Status (2026-10-29):** Stage 2b ran and was recovered.
> - **Selection:** D9 v2 selects **V1 `p1-v4-e01-severity`** for Stage 3, approved by the owner on 2026-10-29. V8 does not change the selection.
> - **Stage 3 has not run**, and waits for the owner's approval.
> - **Ground truth:** `ground-truth-v1.0` is frozen on the owner's dataset-level approval of AI-assisted labels. It is **not individually human-verified**.
> - **Methodology:** v1.2 (τ = 0.40, AI-calibrated, not human-validated); severity MAE is v1.3, reporting only.
> - **Clips:** dev only (25 clips × 2 repeats).
>
> Reports (local, gitignored): `eval_data/results/reports/stage2b/`:
> - `original/` and `recovery-adjusted-v1/`, each with `report.md`, `d9-v2.json`, `severity-v1.3/` and `sources.txt`;
> - `recovery-adjusted-v1/per-category-dI.json`;
> - `sensitivity-cross-stage/` (§6).

## 1. What ran

| Item | Value |
|---|---|
| Configs | `s2-e08-combined` (V8 `p1-v4-e08-combined`, SHA-256 `9c21fc60f39c…`) and `s2-vss-baseline-b` (`p1-v4-base`, `409ed9b3187a…`), interleaved per video by the D10 order |
| Settings | As Stage 2a ([plan §1](stage2-plan.md#1-fixed-design)): Cosmos 3 Super, `contracts/inference.json` (temperature 0, max_tokens 16,384, 64 frames), `incident-contract-v4`, the local experiment agent (`persisted: false`, crops off, RP1 skipped), retry-v2 |
| Harness | `03533816d`; stage `20261029T092502Z-2864cb83`, two sessions (a laptop-close pause after 71 runs, resumed from the checkpoint) |
| Video-runs | 100 of 100 |
| P1 attempts | 105 (5 retry-v2 retries after HTTP 524 gateway timeouts; no 429s), plus 1 recovery attempt: **106 of the 300 authorised** (recovery: 1 of 90) |
| P1 tokens | 955,177 (baseline 453,564; V8 493,357 + 8,256 recovery) of the 10.5 M authorised |
| Judge | 418 calls (cap 3,420), 158,272 tokens |
| Gateway cost | $0 per token reported by the gateway. The GPU and infrastructure cost is not known, and is not free |
| Stage 2 total | 568 P1 attempts (Stage 2a 462 + Stage 2b 106) |

## 2. Failures and recovery (recovery-v1)

| Config | Video-run | Outcome | Cause | Recovery |
|---|---|---|---|---|
| V8 | Assault015 r2, pos 22, `Xv2-b6079957079a` | timeout | Gateway HTTP 524 on all 3 attempts | `timeout`: **scored**, 1 attempt, fresh URL, 29.1 s |
| Baseline-b | Burglary004 r1 | contract_invalid | The model replied, but the reply failed the contract (no severity level) | Not eligible (model output, never retried) |

- **Reliability** (valid outputs out of 50, original → recovery-adjusted): **baseline-b 49 → 49; V8 49 → 50.** The two are reported separately. G1 passes in both views.
- **Merged views:**
  - V8: `s2-e08-combined-recovery/20261029T111748Z/merged-original+recovery-v1.json`.
  - Baseline-b had nothing eligible, so its merged view records `recovered: 0` (`reports/stage2b/recovery-adjusted-v1/s2-vss-baseline-b-merged-original+recovery-v1.json`). Both arms are therefore under the same protocol, as G3 requires.
- **Effect on the comparison: none.**
  - D9 leaves runs with no model output out of the average.
  - The recovered run scored the same as repeat 1 on every D9 score, so each clip mean is unchanged.
  - All 25 clips are paired in both views (entities 23, instruments 10).
  - The original-run figures below are therefore identical.

## 3. D9 v2: V8 against its interleaved baseline (`s2-vss-baseline-b`)

| | Recovery-adjusted (primary) | Original runs |
|---|---|---|
| **ΔI** [95% CI] | **+0.022 [−0.025, +0.071]** | +0.022 [−0.025, +0.071] |
| Incident component | +0.036 [−0.028, +0.104] | same |
| Entity F1 component | −0.010 [−0.102, +0.082] | same |
| Object F1 component | +0.039 [−0.004, +0.079] | same |
| ΔI8 (secondary) | +0.026 [−0.022, +0.079] | same |
| Guardrails | G1 pass (50 vs 49), G2 none, G3 pass | G1 pass (49 vs 49) |

**Per-score paired differences** (adjusted):

| Score | Difference [95% CI] |
|---|---|
| type | +0.080 [0.000, +0.180] |
| severity (exact) | +0.020 [−0.120, +0.180] |
| start | +0.000 [−0.060, +0.060] |
| end | +0.000 [−0.060, +0.060] |
| description | +0.080 [−0.080, +0.240] |
| entity F1 | −0.010 [−0.102, +0.082] |
| instrument F1 | −0.030 [−0.185, +0.137] |
| asset F1 | **+0.059 [+0.011, +0.115]** |

- **V8 clears the +0.02 bar by 0.002, but its interval includes 0.**
- **The only interval that excludes 0 is asset F1.** Type's lower bound is 0.000, so the type gain is not credible either.
- The components point in different directions: entity F1 slightly down, the incident fields and the object component up, all within noise.

## 4. Field metrics, reliability, latency and tokens (recovery-adjusted)

| | Type | Severity exact | Start ±5 s | End ±5 s | Description | Entities P/R/F1 | Instruments P/R/F1 | Assets P/R/F1 |
|---|---|---|---|---|---|---|---|---|
| Baseline-b | 0.880 | 0.260 | 0.660 | 0.560 | 0.260 | .39/.56/.46 | .62/.22/.33 | .27/.70/.39 |
| V8 | 0.960 | 0.280 | 0.660 | 0.560 | 0.340 | .38/.59/.46 | .54/.19/.29 | .31/.75/.44 |

- **Items:**
  - **Assets:** precision improves (FP 111 → 100, TP 42 → 45), but asset precision is still the main weakness.
  - **Entities:** more are listed (FP 87 → 98).
  - **Instruments:** 1 fewer TP (36 in the ground truth; too few for a conclusion).
- **Invalid outputs:** V8 0, baseline-b 1.
- **Inference latency (P1 only), p50 / p95:**
  - V8 23.4 / 38.1 s;
  - baseline-b 25.8 / 47.1 s.

  The shared gateway's load varies, so this is not evidence that V8 is faster.
- **Prompt-length overhead:**
  - Size: V8 is 23,030 bytes, 3,441 words, against the base prompt's 18,234 bytes and 2,673 words (+768 words, +26%).
  - Measured prompt tokens (median): 7,531 against 6,468 (**+1,063**, +16%).
  - Total tokens per call: 10,032 against 9,071 (+11%), because V8's completions are slightly shorter (median 670 against 728).
  - The worst case stays under the 35,000-token per-attempt ceiling.

## 5. Severity (methodology v1.3, reporting only) and per category

| | MAE | Signed error | Exact | Within ±1 | Over / under |
|---|---|---|---|---|---|
| Baseline-b | 0.898 | +0.163 | 0.265 | 0.837 | 21 / 15 |
| V8 | 0.960 | +0.200 | 0.280 | 0.760 | 23 / 13 |

- **Paired MAE difference:** +0.060 [−0.140, +0.260]. **Signed-error difference:** +0.020 [−0.240, +0.280].
- **Original runs:** MAE 0.959, signed error +0.184.
- **V8 does not reproduce V1's Stage 2a MAE reduction** (−0.220 [−0.380, −0.080]). Compared with Stage 2a's baseline (1.082), this baseline is already better: 0.898.

**ΔI per category** (5 clips each; descriptive only):

| Animal attack | Assault | Burglary | Explosion | Road accident |
|---|---|---|---|---|
| −0.001 | **−0.078** | **+0.112** | +0.022 | +0.054 |

- **Gains:** Burglary and Road accidents.
- **Regression:** Assault.
- With 5 clips per category none of these is reliable.

## 6. V8 against V1 (sensitivity only, not part of the selection)

V1 ran in Stage 2a and V8 in Stage 2b, so **they were never interleaved with each other or with one shared baseline**. Each stage's baseline shares its gateway conditions only with its own arms. The checks below re-pair saved results across stages. They are descriptive and are not D9 selections.

| Comparison | ΔI [95% CI] |
|---|---|
| **Drift:** baseline-b − Stage 2a baseline (same prompt) | +0.012 [−0.021, +0.048] |
| V1 − Stage 2a baseline (its own baseline; the selection figure) | **+0.051 [+0.013, +0.089]** |
| V8 − Stage 2a baseline | +0.034 [−0.006, +0.074] |
| V1 − baseline-b | +0.038 [+0.001, +0.077] |
| V8 − baseline-b (its own baseline; the selection figure) | +0.022 [−0.025, +0.071] |
| **V8 − V1 directly** | **−0.016 [−0.054, +0.021]** |

- **The drift is small and within noise:** the same prompt moved by +0.012 between stages.
- **V1 is ahead of V8 against either baseline.** The direct difference favours V1, but its interval includes 0.
- **What the data support:** V8 is **not shown to be better than V1**, and adding the six other blocks bought no measurable gain.
- **What they do not support:** that V1 is *significantly* better than V8.

## 7. Final Stage 2 selection (D9 v2, pre-registered 2026-10-27)

`select_d9` is applied over every version that ran, each against its own interleaved baseline (`s2-vss-baseline` for V1–V7, `s2-vss-baseline-b` for V8), using the merged `original+recovery-v1` records:

| Version | Stage | ΔI [95% CI] | ≥ +0.02 | Guardrails | Result |
|---|---|---|---|---|---|
| **V1 severity** | 2a | **+0.051 [+0.013, +0.089]** | yes | pass | **Selected** |
| V4 assets | 2a | +0.029 [−0.008, +0.065] | yes | pass | Not selected |
| V3 instruments | 2a | +0.025 [−0.019, +0.069] | yes | pass | Not selected |
| **V8 combined** | 2b | +0.022 [−0.025, +0.071] | yes | pass | Not selected |
| V2 entities | 2a | +0.015 [−0.022, +0.051] | no | pass | Not selected |
| V7 checklist | 2a | +0.009 [−0.031, +0.050] | no | pass | Not selected |
| V6 boundaries | 2a | +0.009 [−0.029, +0.048] | no | pass | Not selected |
| V5 descriptions | 2a | +0.003 [−0.044, +0.047] | no | pass | Not selected |

- **Selected prompt for Stage 3:** **`p1-v4-e01-severity`** (V1, SHA-256 `004746ea7d19…`).
  - It has the highest ΔI.
  - The next best (V4) is 0.022 behind, more than the 0.01 tie window, so no tie-breaker applies.
  - The original-run view gives the same result (V1 +0.054, V8 +0.022).
- **V8 passed** the +0.02 bar and every guardrail, so it is a qualifying candidate. It was not selected, because V1's ΔI is higher.
- **Successful in the rule's sense** (ΔI ≥ +0.02, guardrails pass): V1, V4, V3 and V8. **Below the bar:** V2, V7, V6 and V5. None regressed under G2.
- **Only V1's interval excludes 0.** Every other version's gain, V8's included, is within noise on 25 clips.
- **V1 is chosen on dev.** Stage 3 is the held-out check. The dev clips were also few-shot examples in the retired P1-v1 prompt.

## 8. Limitations

1. **Ground truth:** AI-assisted labels, frozen on dataset-level approval; not individually human-verified.
2. **Matching:** τ = 0.40 is AI-calibrated, not human-validated.
3. **Separate baselines:** V8 and V1 ran in different stages with separate baselines (§6), so no claim that one beats the other rests on an interleaved comparison.
4. **Small samples:** 25 dev clips, 10 paired instrument clips, 5 clips per category.
5. **Shared gateway:** non-determinism at temperature 0. The V8 timeout was recovered under recovery-v1, and original-run reliability is kept separate.
6. **Dev only:** selection on dev clips, which also calibrated τ.

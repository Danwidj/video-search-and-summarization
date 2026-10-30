# Stage 3: final held-out comparison (C1-C4): results

> **Status (2026-10-30): done; integrity audit passed.**
> - **Runs:** the 220 scheduled video-runs (C1-C4 × 55 test clips × 1 repeat) between 2026-10-29 12:45 and 2026-10-30 06:46 UTC, in three sessions (two laptop-close stops at a checkpoint) and 3.55 active hours. Then recovery-v1, both report views and the audit (06:46-07:18 UTC).
> - **Design and settings:** exactly as frozen in the [plan](stage3-plan.md) and pinned by `experiments/stage3/manifest.json` (sha `6bf0650f101d`). Nothing was changed in response to results.
> - **Ground truth:** `ground-truth-v1.0` is frozen on the owner's dataset-level approval of AI-assisted labels; it is **not individually human-verified**. τ = 0.40 is AI-calibrated, **not human-validated**.
> - **Exposure:** the 55 test clips were held out from Stage 2 prompt selection but are **not unseen** (D15; plan §6).
> - **Artifacts** (gitignored) under `eval/eval_data/results/`:
>   - stage directory `experiments/stages/20261029T124321Z-0953f2d3/` (`schedule.json`, `checkpoint.json`, `cost-log.jsonl`, `progress.json[l]`);
>   - results `experiments/s3-*/20261029T124321Z/results.json`; recovery `experiments/s3-*-recovery/20261030T064627Z/` (`results.json`, `merged-original+recovery-v1.json`);
>   - reports `reports/stage3/{original,recovery-adjusted-v1}/` (`stage3-report.{md,json}`, `severity-v1.3/`, `sources.txt`), `reports/stage3/finalize-state.json` and the audit `reports/stage3/audit-20261030T071810Z.json`;
>   - supervisor logs `stage3-supervisor/`.

Following Stage 2, the **recovery-adjusted view is primary**; the original-run view is kept and reported next to it. All figures below are recovery-adjusted unless marked.

## 1. Research summary

1. **Does V1 generalise to the test set? Not demonstrably.** Inside VSS, V1 minus the base prompt (C3−C2) is ΔI **+0.019 [−0.015, +0.055]**: the same direction as on dev (Stage 2a +0.051 [+0.013, +0.089]) but about a third of the size, and the interval includes zero. In the direct arm (C4−C1) it is **−0.011 [−0.045, +0.024]**. The intended severity effect does not show up clearly: severity exact accuracy is unchanged within noise in both arms, and the MAE drops (C3−C2 −0.038, C4−C1 −0.075) are inside wide intervals. The one interval that excludes zero for V1 is a **description regression in the direct arm** (C4−C1 −0.130 [−0.245, −0.018], guardrail G2), which is not seen inside VSS (C3−C2 0.000 [−0.130, +0.130]). End-timestamp accuracy improves inside VSS (+0.074 [+0.018, +0.148]); that is one of many per-score intervals and is not a pre-registered primary result.
2. **Do VSS and direct VLM differ under identical requests? No difference was detected.** C2−C1 (base prompt) ΔI −0.007 [−0.036, +0.024]; C3−C4 (V1) +0.023 [−0.003, +0.050]. Both arms send the same P1 body to the same model, so any difference is a pipeline, transport or run-to-run effect, **never an architectural extraction advantage**; with one repeat, run-to-run variation cannot be separated from it. C3−C4 leans positive mainly through description (+0.093) and entity F1, the scores where V1 moved in opposite directions in the two arms. With identical requests this is consistent with run-to-run noise.
3. **Reliability: no difference between the arms.** There were six gateway timeouts (HTTP 524) across 220 runs, three in each arm. There were also two invalid model outputs, both on the same clip (Burglary020) but under different prompts and arms (C2 and C4). Recovery restored 4 of the 6 timeouts. No 429 stop, outage pause or cap was hit.
4. **Processing time:** no meaningful difference. Model processing p50 is 20-23 s in every configuration (p95 59-66 s); VSS adds **about 0.01 s** median overhead over its own P1 call (p95 ≤ 0.05 s) with crops off and persistence off.
5. **For the FYP presentation:** Stage 3 supports "VSS reproduces direct-VLM extraction quality and reliability at negligible overhead when sending the same request", and "the dev-selected severity prompt did not produce a statistically clear gain on the held-out clips". It does not support "VSS extracts better than a direct VLM", "prompt engineering improved held-out accuracy", or any claim about unseen footage.

## 2. Configurations

| | Arm | Prompt (sha256) | Model |
|---|---|---|---|
| **C1** `s3-c1-direct-base` | direct VLM | `p1-v4-base` (`409ed9b3187a`) | `nvidia/cosmos-3-super-reasoner` |
| **C2** `s3-c2-vss-base` | VSS (local experiment agent, crops off) | `p1-v4-base` | same |
| **C3** `s3-c3-vss-v1` | VSS | V1 `p1-v4-e01-severity` (`004746ea7d19`) | same |
| **C4** `s3-c4-direct-v1` | direct VLM | V1 | same |

Harness commit `820591008`; methodology v1.2 (τ 0.40), severity MAE under v1.3 (reporting only); bootstrap seed 20261027, 10,000 resamples; request parity C1 = C2 and C3 = C4 apart from the agent's `stream: false`.

## 3. D9 v2 paired differences (ΔI, per video, 95% video-cluster bootstrap)

| Comparison | Measures | ΔI adjusted [95% CI] | ΔI original | Incident | Entity F1 | Object F1 | ΔI8 |
|---|---|---|---|---|---|---|---|
| C2−C1 | VSS − direct, base prompt | −0.007 [−0.036, +0.024] | −0.006 [−0.036, +0.024] | −0.004 | +0.004 | −0.021 | −0.005 |
| **C3−C2** | **V1 effect inside VSS (RQ1)** | **+0.019 [−0.015, +0.055]** | +0.016 [−0.019, +0.053] | +0.026 | −0.007 | +0.040 | +0.023 |
| C4−C1 | V1 effect, direct arm | −0.011 [−0.045, +0.024] | −0.014 [−0.048, +0.022] | +0.004 | −0.037 | −0.001 | −0.006 |
| **C3−C4** | **VSS − direct, V1 (RQ2 attributed)** | **+0.023 [−0.003, +0.050]** | +0.019 [−0.007, +0.045] | +0.022 | +0.027 | +0.020 | +0.026 |
| C3−C1 | = (C3−C4) + (C4−C1); never an architecture claim | +0.012 [−0.019, +0.044] | +0.008 [−0.024, +0.042] | +0.022 | −0.005 | +0.019 | +0.018 |

**Excluding the 3 pilot clips** (Animal003, Assault018, Burglary005; 52 clips, still not unseen): C2−C1 −0.007 [−0.037, +0.025]; C3−C2 +0.016 [−0.019, +0.053]; C4−C1 −0.015 [−0.051, +0.022]; C3−C4 +0.023 [−0.005, +0.052]; C3−C1 +0.009 [−0.023, +0.042]. The conclusions are unchanged.

**Per-score differences** (adjusted; intervals excluding zero in bold):

| Comparison | type | severity | start | end | description | entities | instruments | assets |
|---|---|---|---|---|---|---|---|---|
| C2−C1 | −0.018 | +0.018 | +0.018 | 0.000 | −0.037 | +0.004 | +0.051 | −0.021 |
| C3−C2 | +0.018 | 0.000 | +0.037 | **+0.074 [+0.018, +0.148]** | 0.000 | −0.007 | +0.051 | +0.040 |
| C4−C1 | +0.018 | +0.074 | +0.018 | +0.037 | **−0.130 [−0.245, −0.018]** | −0.037 | +0.136 | +0.003 |
| C3−C4 | −0.018 | −0.037 | +0.037 | +0.037 | +0.093 | +0.027 | −0.021 | +0.017 |
| C3−C1 | 0.000 | +0.018 | +0.054 | **+0.073 [+0.018, +0.145]** | −0.036 | −0.005 | +0.103 | +0.019 |

Instrument differences rest on 13-15 paired clips and are descriptive. **Guardrails** (informational; nothing is selected on test): C3−C2 none; C4−C1 G1 (53 valid runs vs C1's 55 after recovery) and G2 (description regression above).

## 4. Incident fields (recovery-adjusted; conditional = videos with a scored output)

| Field | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| Type | 0.836 | 0.815 | 0.836 | 0.852 |
| Severity exact | 0.255 | 0.278 | 0.273 | 0.315 |
| Start ±5 s | 0.691 | 0.722 | 0.746 | 0.704 |
| End ±5 s | 0.582 | 0.593 | 0.654 | 0.630 |
| Duration | 0.436 | 0.444 | 0.509 | 0.481 |
| Description | 0.364 | 0.333 | 0.327 | 0.222 |
| n (conditional / end-to-end) | 55 / 55 | 54 / 55 | 55 / 55 | 54 / 55 |

End-to-end accuracy (a failure counts as a miss) and every 95% interval are in `stage3-report.md`. Absolute levels may be optimistic for the base prompt (D15) and are not comparable with the 2026-10-02 benchmark.

## 5. Severity (methodology v1.3, reporting only)

| Config | Valid | MAE | Signed error | Exact | Within ±1 | Over / under |
|---|---|---|---|---|---|---|
| C1 | 55 | 0.927 | −0.055 | 0.255 | 0.836 | 21 / 20 |
| C2 | 53 | 0.868 | +0.075 | 0.283 | 0.868 | 21 / 17 |
| C3 | 55 | 0.873 | 0.000 | 0.273 | 0.873 | 21 / 19 |
| C4 | 53 | 0.849 | −0.019 | 0.321 | 0.849 | 20 / 16 |

Paired MAE differences: C3−C2 −0.038 [−0.189, +0.113]; C4−C1 −0.075 [−0.264, +0.113]; C2−C1 −0.019 [−0.113, +0.075]; C3−C4 0.000 [−0.189, +0.170]. Unlike dev (where the base prompt over-rated and V1 cut MAE by 0.22), the test-set baselines are not biased upward (signed error near 0), so there was less for V1 to correct.

## 6. Items (pooled, recovery-adjusted)

| Config | Entities P / R / F1 | Instruments P / R / F1 (TP) | Assets P / R / F1 |
|---|---|---|---|
| C1 | 0.376 / 0.672 / 0.482 | 0.059 / 0.071 / 0.065 (1) | 0.184 / 0.627 / 0.285 |
| C2 | 0.395 / 0.647 / 0.490 | 0.154 / 0.182 / 0.167 (2) | 0.132 / 0.642 / 0.219 |
| C3 | 0.372 / 0.588 / 0.456 | 0.214 / 0.214 / 0.214 (3) | 0.190 / 0.657 / 0.294 |
| C4 | 0.339 / 0.539 / 0.416 | 0.235 / 0.308 / 0.267 (4) | 0.182 / 0.636 / 0.283 |

Precision stays low for entities and assets (many unmatched predictions); V1 trades some entity recall for fewer asset false positives. Instruments are too few (11-14 in the ground truth of scored clips) for conclusions.

## 7. Reliability and failures

| Config | Original outcomes | Recovered | Adjusted outcomes |
|---|---|---|---|
| C1 | 53 scored, 2 timeout (RoadAccidents069, Assault019) | 2 of 2 | 55 scored |
| C2 | 53 scored, 1 timeout (Assault019), 1 contract-invalid (Burglary020) | 0 of 1 | unchanged |
| C3 | 53 scored, 2 timeout (Burglary009, Explosion017) | 2 of 2 | 55 scored |
| C4 | 53 scored, 1 timeout (Burglary009), 1 contract-invalid (Burglary020) | 0 of 1 | unchanged |

- **Totals:** original 6 infrastructure failures (all HTTP 524) and 2 invalid model outputs; adjusted 2 and 2.
- **Recovery-v1:** applied to the 6 eligible timeouts only; the two invalid outputs were never retried. C2 Assault019 and C4 Burglary009 timed out again on all 3 recovery attempts and remain failures.
- **Retries inside the run (retry-v2):** 27 extra attempts on 247 (11%), within Stage 2's 5-13%.
- **Repeated clips:** Assault019 (C1, C2; 85 s) and Burglary009 (C3, C4; 85 s) timed out in both arms, and both are about twice the median clip length (42 s). This is consistent with the gateway's about 100 s effective timeout, though RoadAccidents069 (11 s) also timed out once.

## 8. Latency and usage

| Config | Model processing p50 / p95 / mean (s) | VSS overhead p50 / p95 (s) | VSS end-to-end p50 / p95 (s) |
|---|---|---|---|
| C1 | 22.67 / 59.47 / 28.84 | – | – |
| C2 | 21.62 / 65.51 / 29.89 | 0.01 / 0.05 | 21.63 / 65.53 |
| C3 | 20.26 / 62.09 / 25.94 | 0.01 / 0.03 | 20.27 / 62.10 |
| C4 | 21.67 / 64.09 / 28.54 | – | – |

Direct model processing is the harness-to-gateway round trip; VSS model processing is the agent's own P1 round trip. Overhead is measured with crops, RP1 and persistence off, so it is not the production pipeline's end-to-end time.

| | P1 attempts | P1 tokens | Judge calls | Judge tokens | Cap (attempts / tokens / judge) |
|---|---|---|---|---|---|
| Original runs | 247 (220 + 27 retries) | 1,979,469 (3,134,469 reserved under the cap rule) | 845 | 335,143 | 660 / 23.1 M / 6,720 |
| Recovery-v1 | 12 (6 runs) | 31,015 (311,015 reserved) | 20 | 6,999 | 180 / 6.3 M / 2,740 |
| Not in the cost log | 1 | unknown (one call's worth, about 9 k) | a few (fewer than 10) | unknown | – |

- **Not recorded:** on 2026-10-29 at 13:04 UTC a judge `ReadTimeout` (C4 Assault012) raised `EvaluatorDependencyError` and ended the session before that run was checkpointed. Its P1 call and the judge calls already made for it were discarded unrecorded; the supervisor resumed and the run was redone. Even counted generously it leaves usage far inside every cap.
- **Gateway cost:** $0 per token. That does not make the shared infrastructure free.

## 9. Per category and representative clips (descriptive; 10-13 clips each)

| Comparison | Animal attack | Assault | Burglary | Explosion | Road accident |
|---|---|---|---|---|---|
| C2−C1 | −0.009 | −0.058 | +0.011 | +0.007 | +0.003 |
| C3−C2 | −0.003 | −0.008 | +0.059 | +0.007 | +0.015 |
| C4−C1 | +0.004 | −0.071 | +0.008 | −0.021 | +0.005 |
| C3−C4 | −0.017 | +0.010 | +0.066 | +0.035 | +0.013 |

V1's gains concentrate in Burglary; Assault is the weakest category for V1 in the direct arm.

- **C3−C2 (V1 in VSS):** gains Animal004 +0.367, RoadAccidents060 +0.308, Burglary020 +0.300; regressions RoadAccidents030 −0.289, Animal008 −0.222, Explosion041 −0.222.
- **C4−C1 (V1 direct):** gains Burglary041 +0.400, RoadAccidents069 +0.214, Burglary005 +0.200; regressions Assault026 −0.406, Burglary020 −0.295, Explosion019 −0.233.
- **C2−C1 (base, VSS − direct):** gains Burglary041 +0.333, RoadAccidents030 +0.289; regressions Burglary020 −0.295, Animal004 −0.256. Per-clip swings this large with identical requests show the run-to-run variation at temperature 0.

## 10. Integrity audit (`audit-20261030T071810Z.json`: passed)

| Check | Result |
|---|---|
| All 220 runs accounted for, none duplicated | pass (checkpoint, schedule and 220 cost-log lines agree) |
| Outputs linked to the manifest | pass (manifest sha `6bf0650f101d`, config and prompt hashes) |
| Ground truth and methodology unchanged | pass (GT `records_sha256` `391fcd272bf2`, methodology v1.2, τ 0.40) |
| Originals and recovered runs distinguishable | pass (originals untouched; recovery in separate `-recovery` directories and `original+recovery-v1` merged views) |
| Scoring reproducible from saved results | pass (both report views regenerated; items re-matched offline for C1-C4) |
| No calls beyond the approved budgets | pass for recorded usage; the one unrecorded discarded attempt (§8) is disclosed here |

## 11. Limitations

- **Power:** 55 clips and one repeat. The ΔI intervals are about ±0.035 wide, so effects below about 0.03-0.04 cannot be detected, and run-to-run variation is not separated from pipeline effects.
- **Not unseen:** the test clips were in the 2026-10-02 benchmark and three shaped earlier pilots (D15). Any bias favours the base prompt.
- **Ground truth and matching:** AI-assisted, dataset-level approved, not individually human-verified; τ is AI-calibrated. Item scores depend on both.
- **Many per-score comparisons:** an interval excluding zero among about 40 per-score intervals is expected by chance; only ΔI was pre-registered as primary.
- **Scope:** one model (Cosmos 3 Super), crops off, a local agent, not the production VM; the cropping-on end-to-end profile and the transfer models were not run.

## 12. Not done in response to these results

No prompt was revised, Stage 3 was not rerun, no new experiment was launched and the methodology was not changed. Adopting V1 in production, if wanted, is a separate decision with a contract bump.

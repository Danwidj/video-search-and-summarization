# Stage 2a results: VSS baseline and V1–V7 (dev, 25 clips × 2 repeats)

> **Status, 2026-10-29:** Stage 2a is complete. All 400 scheduled video-runs are recorded, and recovery-v1 has run on the infrastructure failures. **V8 is proposed, not registered, and not run.** Stage 2b waits for the owner's approval.
> - **Unchanged throughout:** ground truth, methodology v1.2 (τ = 0.40), D9 v2, prompts, model and configs.
> - **Ground truth:** `ground-truth-v1.0` is frozen on the owner's dataset-level approval of AI-assisted labels. It is not individually human-verified.
> - **Matching calibration:** AI-labelled and AI-audited, not human-validated.
> - **Dev only:** these are dev results. Stage 3 is the held-out check, and the dev clips were few-shot examples in the retired P1-v1 prompt.

## 1. What ran

| | |
|---|---|
| Configurations | `s2-vss-baseline` (`p1-v4-base`) and V1–V7 (`p1-v4-e01`…`e07`), all through the local VSS agent, interleaved (D10), with crops off |
| Fixed settings | Model `nvidia/cosmos-3-super-reasoner`; retry-v2; harness `7cf4a4131` |
| Video-runs | 8 × 25 × 2 = **400**, run 2026-10-28 14:42 UTC to 2026-10-29 08:38 UTC in three resumable sessions |
| P1 attempts | **451** in Stage 2a plus **11** in recovery = **462 of the 1,200 authorised** |
| Rate limits | 16 attempts were rate-limited (429) |
| P1 tokens | 3,633,327 in Stage 2a plus 52,944 in recovery |
| Judge | 1,603 calls (612,276 tokens) in Stage 2a plus 26 calls (10,624 tokens) in recovery |
| Gateway cost | $0 recorded, because the gateway prices tokens at 0. That is the gateway's recorded figure, not the cost of the GPU infrastructure, which is unknown |
| Prompt identity | For every run with a model output, the agent echoed the registered prompt id and SHA-256. The baseline sends no id, and the agent echoed the production SHA `409ed9b3…` = `p1-v4-base` |
| Results files (local) | `eval_data/results/experiments/s2-*/20261028T144216Z/results.json`; all 8 pass `verify`. Reports: `eval_data/results/reports/stage2a/{original,recovery-adjusted-v1}/` |

**Host interruptions, all checkpointed with no run lost to a restart:**
- An overnight sleep (AC unplugged and lid closed, 23:38–08:18 SGT).
- Two clean stops at the owner's request.
- A brief network (DNS) outage at 13:44 SGT on 2026-10-29.

## 2. Failures and recovery (recovery-v1)

| Config | Video-run (repeat, position, run id) | Original outcome | Cause, from the stored error | Recovery |
|---|---|---|---|---|
| V1 | Assault030 r2, pos 3, `Xv2-886e063bb9ea` | http_error | DNS: "Temporary failure in name resolution" | `transport_error`: **scored**, 1 attempt |
| V2 | Assault030 r2, pos 3, `Xv2-940a21d29abf` | http_error | DNS (the same outage) | `transport_error`: **scored**, 1 attempt |
| V2 | RoadAccidents017 r1, pos 22, `Xv1-973b346bbb19` | timeout | Gateway HTTP 524 on all 3 attempts | **scored**, 3 attempts |
| V4 | Assault015 r1, pos 11, `Xv1-73c4ab5a3bc3` | timeout | Gateway HTTP 524 | **scored**, 1 attempt |
| V7 | Burglary010 r1, pos 5, `Xv1-10e8dfa40c31` | http_error | R2 403 on a signed URL that expired during the overnight suspend: attempt 1 `host_suspended` (31,149 s), and the retry reused the URL | `expired_url`: **scored**, 1 attempt, fresh URL |
| Baseline | RoadAccidents017 r2, pos 2, `Xv2-cef59c2f07fe` | timeout | Gateway HTTP 524 | **scored**, 2 attempts |
| Baseline | Assault015 r2, pos 22, `Xv2-cef59c2f07fe` | timeout | Gateway HTTP 524 | **scored**, 2 attempts |
| V4 | Explosion011 r2 | contract_invalid | The model replied, but the reply failed the contract | Not eligible (model output) |
| V7 | Burglary004 r2 | contract_invalid | Model reply failed the contract | Not eligible |
| Baseline | Burglary004 r2 | contract_invalid | Model reply failed the contract | Not eligible |

**Summary:**
- **Failures:** 10 in total, 7 infrastructure and 3 model.
- **Recovered:** 7 of 7, and 0 observations are still missing for infrastructure reasons.
- **Additional cost:** 11 P1 attempts and 52,944 P1 tokens.
- **Recovery latency:** median 34.5 s, maximum 48.8 s (P1-only, agent-reported).
- **V3, V5 and V6** had no failures to recover.

**Fix before recovery (`dbd21fb7b`, owner-approved 2026-10-29):**
- Classification only. The 524 timeouts were already recoverable.
- `experiment_recovery.failure_class` now reads two more causes from the stored error text:
  - a DNS or connection failure becomes `transport_error`;
  - R2's 403 on the video URL becomes `expired_url`.
- The runner records a new agent DNS failure as `transport_error`, which retry-v2 already retries.
- **Unchanged:** timeout limits, the retry-v2 rules, prompts, model settings, ground truth, τ and the methodology.
- **Fresh URLs:** every recovered video-run signs a fresh R2 URL just before its first attempt. A test pins that the 1-hour URL lifetime is longer than the worst-case retry-v2 span.

**Provenance:**
- **Originals untouched:** they are byte-identical to their pre-recovery SHA-256.
- **Links:** each recovered run carries `recovers: {position, run_id, outcome, class}`.
- **Same slot:** each recovery replaces its original `(repeat, clip)` slot in `merged-original+recovery-v1.json`, so no repeat is added.
- **V3, V5 and V6:** their merged views (`recovered: 0`) are in `reports/stage2a/recovery-adjusted-v1/`, so all 8 share one protocol (D9 G3).

**Reliability, original and recovery-adjusted, kept separate (valid outputs out of 50):**

| | Baseline | V1 | V2 | V3 | V4 | V5 | V6 | V7 |
|---|---|---|---|---|---|---|---|---|
| Original | 47 | 49 | 48 | 50 | 48 | 50 | 50 | 48 |
| Recovery-adjusted | 49 | 50 | 50 | 50 | 49 | 50 | 50 | 49 |

**Effect of recovery on paired comparisons:**
- Every clip already had at least one valid repeat in every configuration, so the number of paired clips stays at 25 for every component (instruments 11, entities 22).
- Recovery changes only the repeat averages: ΔI moves by −0.002 to −0.005 for every variant.
- The selection and the V8 qualification are the same in both views (§3).

## 3. D9 v2 (pre-registered, unchanged)

Each value is ΔI = the equal-weight mean of the incident, entity-F1 and object-F1 differences against `s2-vss-baseline`. Pairs are matched per clip, repeats are averaged, and intervals are 95% video-cluster bootstrap. The V8 rule uses the recovery-adjusted view, so that view is primary below.

| Variant | ΔI recovery-adjusted [95% CI] | ΔI original [95% CI] | ΔI8 (adj.) | Incident | Entity F1 | Object F1 | G1–G3 | ≥ +0.02 |
|---|---|---|---|---|---|---|---|---|
| **V1 severity** | **+0.051 [+0.013, +0.089]** | +0.054 [+0.016, +0.091] | +0.034 | +0.028 | +0.077 | +0.047 | pass | **yes** |
| V4 assets | +0.029 [−0.008, +0.065] | +0.034 [+0.000, +0.068] | +0.017 | +0.012 | +0.040 | +0.036 | pass | yes |
| V3 instruments | +0.025 [−0.019, +0.069] | +0.028 [−0.014, +0.071] | +0.013 | +0.008 | +0.056 | +0.010 | pass | yes |
| V2 entities | +0.015 [−0.022, +0.051] | +0.018 [−0.019, +0.053] | −0.006 | −0.016 | +0.042 | +0.018 | pass | no |
| V7 checklist | +0.009 [−0.031, +0.050] | +0.011 [−0.029, +0.052] | +0.019 | +0.028 | −0.025 | +0.025 | pass | no |
| V6 boundaries | +0.009 [−0.029, +0.048] | +0.012 [−0.024, +0.050] | +0.009 | +0.012 | −0.004 | +0.020 | pass | no |
| V5 descriptions | +0.003 [−0.044, +0.047] | +0.006 [−0.039, +0.049] | −0.003 | −0.008 | +0.014 | +0.003 | pass | no |

**Reading the table:**
- **D9 v2 selects V1 (`p1-v4-e01-severity`)** in both views, with no tie-break. Only V1's interval excludes 0.
- **The guardrails pass for all seven:**
  - G1 (valid runs): no variant has fewer valid runs than the baseline minus the slack.
  - G2: no score regresses credibly.
  - G3: same videos, repeats, model, ground truth, split, methodology, τ and protocol.
- **Credible changes (adjusted; interval excludes 0):** only three.
  - V1 ΔI +0.051 [+0.013, +0.089];
  - V1 object F1 +0.047 [+0.014, +0.084];
  - V7 severity exact +0.16 [+0.04, +0.30].

  Several gains sit exactly at a lower bound of 0.00 and do not exclude 0: instruments for V1 (+0.11), V4, V5 and V7 (+0.15), and end time for several variants. The description score drops slightly under most variants (−0.04 to −0.10), but every interval includes 0 and none trips G2.
- **Per category** (adjusted ΔI, 5 clips each):

  | Variant | Animal | Assault | Burglary | Explosion | Road |
  |---|---|---|---|---|---|
  | V1 | −0.011 | +0.085 | +0.079 | +0.036 | +0.069 |
  | V4 | +0.031 | +0.031 | +0.049 | +0.014 | +0.013 |
  | V3 | −0.008 | −0.058 | +0.059 | +0.062 | +0.083 |

  - V1 gains in four of five categories, and Animal Attack is flat.
  - Every variant except V2 and V4 is slightly negative on Animal Attack.
  - Detail: `reports/stage2a/recovery-adjusted-v1/per-category-dI.json`.

## 4. Field metrics (original runs; recovery-adjusted in `reports/stage2a/recovery-adjusted-v1/report.md`)

Accuracy is conditional on a model output; `report.md` also gives end-to-end figures and intervals. Item columns are pooled P/R/F1 at τ = 0.40. Latency is P1-only (agent-reported).

| | Type | Severity | Start ±5 s | End ±5 s | Description | Entity P/R/F1 | Instrument P/R/F1 | Asset P/R/F1 | p50 / p95 s | Tokens / call |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 0.896 | 0.188 | 0.646 | 0.521 | 0.375 | .44/.54/.48 | .30/.09/.14 | .17/.69/.27 | 28.2 / 68.9 | 8,829 |
| V1 | 0.980 | 0.265 | 0.694 | 0.571 | 0.347 | .48/.66/.56 | .29/.17/.21 | .18/.73/.29 | 28.5 / 69.0 | 9,245 |
| V2 | 0.938 | 0.125 | 0.667 | 0.562 | 0.333 | .40/.64/.49 | .33/.11/.17 | .17/.71/.27 | 30.8 / 60.9 | 9,054 |
| V3 | 0.940 | 0.220 | 0.640 | 0.540 | 0.380 | .40/.58/.47 | .12/.06/.08 | .29/.75/.42 | 27.0 / 58.1 | 9,179 |
| V4 | 0.939 | 0.245 | 0.714 | 0.551 | 0.306 | .49/.70/.58 | .26/.15/.19 | .32/.73/.44 | 26.1 / 58.8 | 9,017 |
| V5 | 0.940 | 0.240 | 0.640 | 0.540 | 0.280 | .40/.57/.47 | .38/.14/.20 | .17/.68/.27 | 27.6 / 105.1 | 9,223 |
| V6 | 0.960 | 0.180 | 0.700 | 0.580 | 0.320 | .44/.55/.49 | .25/.08/.13 | .28/.72/.41 | 26.1 / 50.9 | 9,042 |
| V7 | 0.939 | 0.367 | 0.653 | 0.551 | 0.306 | .35/.50/.41 | .58/.22/.32 | .26/.71/.38 | 25.8 / 56.2 | 9,078 |

**Notes:**
- **Assets:** precision is the main item weakness. The baseline makes 196 false positives against 40 true positives. V3, V4, V6 and V7 roughly halve the false positives (95–115), while recall holds.
- **Instruments:** the ground truth has only 11 clips with instruments, so these figures are descriptive.
- **Latency and cost:** prompt length adds about 2–5% input tokens. Latency does not differ meaningfully between prompts. V5's p95 of 105 s comes from one long call.

## 5. Severity (methodology v1.3 reporting extension; MAE is never used in selection)

Recovery-adjusted figures; the original-run figures are in `reports/stage2a/original/severity-v1.3/`. Paired differences are against the baseline over 25 clips, with 95% video-cluster bootstrap intervals.

| | Valid | MAE | Signed error | Exact | Within ±1 | Over / under | Paired MAE Δ [CI] | Signed Δ [CI] |
|---|---|---|---|---|---|---|---|---|
| Baseline | 49 | 1.082 | +0.184 | 0.204 | 0.714 | 23 / 16 | – | – |
| **V1** | 50 | **0.860** | +0.420 | 0.260 | **0.880** | 28 / 9 | **−0.220 [−0.380, −0.080]** | +0.220 [−0.040, +0.520] |
| V7 | 49 | 0.857 | +0.204 | **0.367** | 0.775 | 20 / 11 | −0.220 [−0.420, −0.020] | +0.020 [−0.220, +0.280] |
| V4 | 49 | 0.939 | +0.245 | 0.245 | 0.816 | 23 / 14 | −0.160 [−0.320, +0.000] | +0.040 [−0.180, +0.260] |
| V5 | 50 | 0.980 | +0.100 | 0.240 | 0.780 | 23 / 15 | −0.100 [−0.300, +0.120] | −0.100 [−0.380, +0.180] |
| V3 | 50 | 1.000 | +0.080 | 0.220 | 0.780 | 22 / 17 | −0.080 [−0.260, +0.120] | −0.120 [−0.340, +0.120] |
| V6 | 50 | 1.000 | +0.200 | 0.180 | 0.820 | 25 / 16 | −0.080 [−0.200, +0.020] | +0.000 [−0.240, +0.200] |
| V2 | 50 | 1.140 | +0.060 | 0.120 | 0.740 | 24 / 20 | +0.060 [−0.120, +0.240] | −0.140 [−0.480, +0.180] |

**Does V1 reduce severity MAE?** Yes. MAE falls from 1.08 to 0.86. The paired difference is −0.22 [−0.38, −0.08] (original runs: −0.24 [−0.40, −0.10]), and within-±1 rises from 0.71 to 0.88.

**Does V1 reduce systematic over-estimation? No.**
- The mean signed error rises from +0.18 to +0.42. The paired difference is +0.22 [−0.04, +0.52], so the bias is not reduced and, if anything, increases.
- V1's gain comes from **fewer under-ratings** (16 → 9) and fewer large misses. Over-ratings rise from 23 to 28.
- Context: in Stage 2a the baseline's over-rating bias (+0.18) is smaller than Stage 1 C2's (+0.53), the run that motivated V1. The two runs differ only by run-to-run variation, so the baseline bias V1 targeted was not stable either.

**V7 (checklist)** gives the same MAE reduction as V1, −0.22 [−0.42, −0.02], with the highest exact accuracy and no added bias.

## 6. Qualitative examples (V1 against the baseline, recovery-adjusted, per-clip ΔI)

| Clip | ΔI | What changed |
|---|---|---|
| Burglary004 | +0.251 | The baseline's repeat 2 was `contract_invalid` (scored as a miss); V1 gave valid output in both repeats, with better entity F1 (+0.43). This is partly a validity gain, not only accuracy |
| Assault007 | +0.241 | Severity 3 and 2 → 4 and 3 (ground truth 4); entity F1 +0.36; object F1 +0.17 |
| RoadAccidents012 | +0.167 | Same incident fields; entity F1 +0.50 |
| Animal012 | −0.144 | Entity F1 −0.33; severity still split across the two repeats (2 and 3, ground truth 2) |
| Animal011 | −0.067 | One repeat mis-typed as assault; severity 2 in both repeats (ground truth 1; the baseline got 1 once) |
| Explosion002 | −0.058 | Severity 5 and 4 → 4 and 4 (ground truth 3): closer, still over-rated; entity F1 −0.10 |

## 7. V8 qualification

- **Rule** (fixed before any Stage 2 output, [stage2-prompts.md](stage2-prompts.md#v8-combination-rule-fixed-before-any-stage-2-output)): combine the block of every V1–V7 version whose recovery-adjusted D9 v2 comparison has **ΔI > 0, no G2 problem, and passes G1 and G3**.
- **Result:** **all seven qualify.** Every ΔI is above 0, and no variant has a guardrail problem. The original-only view gives the same set.
- **Proposed V8:** `p1-v4-e08-combined`, parent `p1-v4-base`, is the base prompt with the inserted blocks of V1–V7.
  - All eight blocks (V6 has two) are pure insertions at distinct base-prompt positions. They are applied unchanged, in section order: V6 ×2, V5, V1, V2, V3, V4, V7.
  - A check confirms each variant equals the base plus exactly its own blocks.
  - **Full text:** [`../../experiments/stage2-drafts/p1-v4-e08-combined.txt`](../../experiments/stage2-drafts/p1-v4-e08-combined.txt), 642 lines, 23,030 bytes, SHA-256 `9c21fc60f39ca46c5c226c02f17e4e60360cbbd543092c54ebdc7dfb21de7323`.
  - **Diff from the base:** [`p1-v4-e08-combined.diff`](../../experiments/stage2-drafts/p1-v4-e08-combined.diff).
  - **Not registered and not run.** It would be registered unchanged with `prompt_registry.add` only after the owner approves Stage 2b.
- **Caveats for Stage 2b:**
  - Most of the seven blocks have ΔI intervals that include 0, so V8 combines several effects that may be noise.
  - The blocks were never tested together.
  - V7 and V2 lower entity F1 slightly, and most blocks lower the description score slightly.
  - Under the rule, V8 is a candidate like the others. It must reach ΔI ≥ +0.02 against `p1-v4-base` (with a drift-check baseline) to be selected.
  - V1 stays the selected prompt unless V8 beats it under D9 v2.

## 8. Limitations

- **Sample size:** 25 dev clips × 2 repeats gives wide intervals, and instruments rest on 11 clips.
- **Variation between repeats:** run-to-run variation at temperature 0 is large. Burglary004's baseline repeats differ in validity, and Stage 1 against Stage 2a shows the baseline's severity bias moving.
- **Ground truth and calibration:** AI-assisted ground truth (frozen, not individually human-verified), and AI-only matching calibration (8 pairs await human review).
- **Dev clips were exposed:** they appeared in the retired P1-v1 few-shot prompt. Selection on dev is checked on the 55 held-out test clips in Stage 3.

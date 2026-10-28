# Stage 1 baselines: results (dev split)

> **Run 2026-10-28, authorised by the owner.** C1 = direct VLM, C2 = VSS, both with `p1-v4-base` on the 25 dev clips × 2 repeats, against the **frozen `ground-truth-v1.0`**, evaluation-methodology-v1.1. Crops off, RP1 skipped, no Supabase or R2 writes (local experiment agent, no storage variables in its environment). Dev results only: nothing here is a held-out (test) result.
>
> **Ground-truth limitation:** `ground-truth-v1.0` comes from AI-assisted adjudication approved by the owner **at the dataset level**. No annotation was individually human-verified ([freeze README](../../ground_truth/freeze/README.md#ground-truth-v10-as-frozen-limitation)). Absolute accuracy here is accuracy against that reference, which may itself contain errors.

## Setup

| Item | Value |
|---|---|
| Configs | `direct-vlm-baseline` (C1, `frozen_baseline`), `vss-baseline` (C2), interleaved as one stage (D10 order) |
| Model / judge / embedder | `nvidia/cosmos-3-super-reasoner` / `nvidia/nemotron-3-nano-30b-a3b` (output ≤ 1,500 tokens) / MiniLM-L6-v2 (local, :8811) |
| Prompt | `p1-v4-base`, SHA-256 `409ed9b3187a…`, identical in both arms (the P1 prompt tokens are equal for all 19 clips with output in both arms) |
| Ground truth | `ground-truth-v1.0`, frozen, records `391fcd27…` |
| Harness | `7df6f3159` (plus the uncommitted freeze branch, data only) |
| Caps per config | 50 P1 attempts / 1,050,000 P1 tokens (bound) / 1,710 judge calls. Used: C1 50 / 529,840 / 41; C2 50 / 936,419 / 31. No cap or stop rule fired |
| Wall clock | 03:10–09:10 UTC. The host (WSL) was suspended for about 4 h, from 04:51 to 08:51 |
| Results | `eval_data/results/experiments/{direct-vlm-baseline,vss-baseline}/20261028T031009Z/` (local; `verify`: OK for both), stage `stages/20261028T031009Z-6d6fcfc8/` |
| Cost | Gateway $0 per token (configured). Infrastructure cost is unknown and borne by the sponsor |

## Reliability (failures stay in the denominators)

| | C1 direct | C2 VSS |
|---|---|---|
| Attempted video-runs | 50 | 50 |
| Scored, valid output | 34 | 30 |
| Invalid output (`contract_invalid`: a model miss, kept in accuracy) | 0 | 2 (Explosion011, Burglary004) |
| Rate-limited (429, gateway "Model capacity reached", TPM 500,000 shared) | 10 | 11 † |
| Timeout (Cloudflare 524, about 100 s) | 6 | 7 |
| Model-output rate / valid-output rate | 0.68 / 0.68 | 0.64 / 0.60 |
| Clips with no output in either repeat | Burglary093, RoadAccidents017, Explosion011 | Animal012, RoadAccidents005, Assault011 |

- **† Misclassification:** the stored results label the 11 VSS rate limits `http_error`. The agent wraps the upstream 429 in a 500 (`P1 call returned HTTP 429: …`), and the runner only recognised a wrapped 524. Classified from the stored error text, all 11 are 429s.
  - **Fixed for later runs:** `experiment_runner._upstream_status` now maps any wrapped upstream status, and a test covers it.
  - **Effect on this run:** these 11 were also counted at the 35,000-token ceiling as unmetered, which is why C2's token bound (936,419) is high. The corrected rate-limit share was 21%, under the 25% stop rule. I tracked it by hand during the run.
- **Failures are infrastructure, not clip length:** clips of 7–13 s timed out as well as the 196 s clip.
- **Post-suspend window:** all 12 calls after the host resumed failed (8 timeouts, 4 rate limits). That window accounts for a third of all failures.
- **Overall:** 34 of 100 video-runs produced no model output.

## Incident fields

**Conditional** accuracy = over video-runs with a model output (an invalid output counts as a miss). **End-to-end** accuracy = over all 50 attempted video-runs, where a request failure is a miss (methodology §3). 95% video-cluster bootstrap intervals.

| Field | C1 n | C1 conditional | C1 end-to-end (n=50) | C2 n | C2 conditional | C2 end-to-end (n=50) |
|---|---|---|---|---|---|---|
| type | 34 | 0.971 [0.912, 1.000] | 0.660 [0.520, 0.780] | 32 | 0.906 [0.781, 1.000] | 0.580 [0.440, 0.720] |
| severity (exact) | 34 | 0.147 [0.029, 0.265] | 0.100 [0.020, 0.180] | 32 | 0.250 [0.094, 0.406] | 0.160 [0.060, 0.260] |
| start (±5 s) | 34 | 0.647 [0.500, 0.794] | 0.440 [0.300, 0.580] | 32 | 0.688 [0.531, 0.844] | 0.440 [0.300, 0.580] |
| end (±5 s) | 34 | 0.471 [0.294, 0.647] | 0.320 [0.200, 0.440] | 32 | 0.500 [0.312, 0.688] | 0.320 [0.200, 0.460] |
| duration (±5 s) | 34 | 0.324 [0.176, 0.471] | 0.220 [0.100, 0.340] | 32 | 0.375 [0.219, 0.562] | 0.240 [0.120, 0.360] |
| description (judge ≥ 0.5) | 34 | 0.265 [0.118, 0.412] | 0.180 [0.080, 0.300] | 32 | 0.469 [0.312, 0.656] | 0.300 [0.180, 0.420] |

### Severity

| | n | Exact | Within one | Mean signed error |
|---|---|---|---|---|
| C1 | 34 | 0.147 | 0.735 | +0.18 |
| C2 | 32 | 0.250 | 0.750 | +0.53 |

- **Main error, over-rating:** ground-truth level 3 is predicted as 4 or 5 in **24 of 38** outputs (C1 12/20, C2 12/18).
- **Confusion matrix, C1 (ground truth → prediction: count):**
  - 1 → 1: 1, 1 → 2: 2;
  - 2 → 1: 2, 2 → 2: 2, 2 → 3: 2;
  - 3 → 1: 4, 3 → 2: 2, 3 → 3: 2, 3 → 4: 7, 3 → 5: 5;
  - 4 → 3: 2, 4 → 5: 1;
  - 5 → 4: 2.
- **C2** is similar. It also has two missing severities, from the invalid outputs.

### Per category (conditional, passes / outputs; 10 video-runs per category per arm)

| Category | C1 type / severity / description | C2 type / severity / description |
|---|---|---|
| Animal Attack | 7/8, 4/8, 2/8 | 7/8, 4/8, 4/8 |
| Assault | 7/7, 0/7, 0/7 | 4/4, 3/4, 0/4 |
| Burglary | 5/5, 0/5, 0/5 | 5/6, 1/6, 2/6 |
| Explosion | 8/8, 0/8, 6/8 | 7/8, 0/8, 5/8 |
| Road Accident | 6/6, 1/6, 1/6 | 6/6, 0/6, 4/6 |

## Entities, instruments and assets (pooled P/R/F1)

**Conditional** = over video-runs with output. **End-to-end** additionally counts every ground-truth item of a failed video-run as a false negative. The methodology defines item metrics as pooled P/R/F1 only, so the end-to-end column is supplementary.

| Kind | C1 TP / FP / FN | C1 P / R / F1 | C1 end-to-end F1 | C2 TP / FP / FN | C2 P / R / F1 | C2 end-to-end F1 |
|---|---|---|---|---|---|---|
| entities | 1 / 102 / 71 | 0.010 / 0.014 / 0.011 | 0.010 | 1 / 85 / 54 | 0.012 / 0.018 / 0.014 | 0.011 |
| instruments | 1 / 8 / 24 | 0.111 / 0.040 / 0.059 | 0.044 | 0 / 9 / 18 | 0 / 0 / – | 0.000 |
| assets | 2 / 104 / 39 | 0.019 / 0.049 / 0.027 | 0.024 | 0 / 107 / 41 | 0 / 0 / – | 0.000 |

**Item scores are at the floor, and this is a measurement-validity finding, not a scorer bug.**

- **The scorer works as specified.** Re-embedding the unmatched items reproduces exactly 0 extra matches at the pre-registered 0.75 cosine threshold. The judge is called only on matched pairs, which is why there are so few judge calls (41 and 31).
- **Why nothing matches:** MiniLM cosine between a model's entity description and the ground-truth description of the same person rarely reaches 0.75.
  - Example, Assault007 E1: "A person lying motionless on the floor…, light blue shirt" against "Person lying on a mat on the floor… struck repeatedly". It is clearly the same person.
  - The best match per predicted item has a median of about 0.41–0.51 and a maximum of 0.70 (entities) and 0.75 (assets).
- **Threshold sensitivity** (methodology: reported, never used for selection):

  | Threshold | C1 F1 entities / instruments / assets | C2 F1 entities / instruments / assets |
  |---|---|---|
  | 0.65 | 0.069 / 0.059 / 0.095 | 0.057 / 0.074 / 0.122 |
  | 0.75 | 0.011 / 0.059 / 0.027 | 0.014 / 0.000 / 0.000 |
  | 0.85 | 0.011 / 0.059 / 0.027 | 0.014 / 0.000 / 0.000 |

- **What the models get wrong on items (from the counts):**
  - Both arms over-list assets heavily: about 105 predicted against 41 ground-truth assets.
  - They over-list entities (85–102 against 55–72).
  - They under-report instruments (9 predicted against 18–25).
- **Consequence for Stage 2:** two of D9 v2's three `ΔI` components (entity F1 and object F1) sit at the floor. See the [Stage 2 plan](stage2-plan.md), decision S2-A.

## v1.2 final re-matching (τ = 0.40)

[Methodology v1.2](../../methodology/evaluation-methodology-v1.2.md) is final: τ = 0.40 from calibration v2, AI-assisted and not human-validated. The v1.1 results above are unchanged (`results.json`, `verify` OK).
- **Files:** `rematched-v1.2-t0.40-20261028T141652Z.json` (C1) and `…T141656Z.json` (C2), next to each `results.json`. They make no model or judge call, and incident fields are carried over.
- **Newly matched pairs:**
  - their deterministic attributes are scored: entity type, instrument threat level and holder;
  - their judged attributes (names, descriptions) are marked `judged_attributes_pending`: 98 fields for C1, 95 for C2;
  - D9 and item P/R/F1 need only the match counts.
- **Superseded:** earlier `rematched-v1.2-*` files from the provisional calibration are kept but are not the final scores.

| Kind | C1 TP / FP / FN | C1 P / R / F1 | C2 TP / FP / FN | C2 P / R / F1 |
|---|---|---|---|---|
| entities | 41 / 62 / 31 | 0.398 / 0.569 / 0.469 | 30 / 56 / 25 | 0.349 / 0.545 / 0.426 |
| instruments | 5 / 4 / 20 | 0.556 / 0.200 / 0.294 | 4 / 5 / 14 | 0.444 / 0.222 / 0.296 |
| assets | 27 / 79 / 14 | 0.255 / 0.659 / 0.367 | 29 / 78 / 12 | 0.271 / 0.707 / 0.392 |

- **Matched-pair attributes (deterministic, v1.2):**
  - entity type correct 40/41 (C1) and 29/30 (C2);
  - instrument threat level exact 1/5 (C1) and 0/4 (C2);
  - holder correct 0 (C1: 1 incorrect, 4 unresolved) and 1 (C2: 1 incorrect, 2 unresolved).
- **D9 v2 components, C2 − C1** (parity, descriptive; 19 paired clips, 95% CI):
  - `ΔI` −0.030 [−0.117, 0.036];
  - incident +0.032 [−0.065, 0.113];
  - entity F1 −0.119 [−0.258, −0.007];
  - object F1 −0.004 [−0.073, 0.051].
  - The arms send identical requests, so the entity difference is run-to-run output variation, like the description difference. It is not a pipeline effect.
- **Error pattern:**
  - assets are over-listed (precision 0.26–0.27, recall 0.66–0.71);
  - instruments are under-reported (recall 0.20–0.22);
  - entities have precision 0.35–0.40, recall 0.55–0.57.

## v1.2 provisional re-matching (superseded; calibration v1)

The v1.1 results above are unchanged. This section re-matches the same saved outputs offline under the **proposed** [methodology v1.2](../../methodology/evaluation-methodology-v1.2.md) (`eval_experiment.py rematch`: no model or judge call).
- **The threshold:** the calibration rule picked τ = 0.30 ([calibration](../../methodology/calibration/matching-v1.2-calibration.md)). 0.40 is shown as a sensitivity check.
- **Files:** `rematched-v1.2-t0.30-*.json` and `rematched-v1.2-t0.40-*.json`, next to each `results.json`. Each records its source SHA-256 and `match_threshold_provisional: true`.
- **What is re-scored:** only the match counts. Newly matched pairs are marked `attributes_rescored: false`, because their judged attributes (descriptions, names) need a judge re-score that has not been run.
- **Re-matching at 0.75 reproduces the v1.1 counts exactly in both arms.**

| τ | Kind | C1 TP / FP / FN | C1 P / R / F1 | C2 TP / FP / FN | C2 P / R / F1 |
|---|---|---|---|---|---|
| 0.30 | entities | 60 / 43 / 12 | 0.583 / 0.833 / 0.686 | 38 / 48 / 17 | 0.442 / 0.691 / 0.539 |
| 0.30 | instruments | 5 / 4 / 20 | 0.556 / 0.200 / 0.294 | 6 / 3 / 12 | 0.667 / 0.333 / 0.444 |
| 0.30 | assets | 32 / 74 / 9 | 0.302 / 0.780 / 0.435 | 31 / 76 / 10 | 0.290 / 0.756 / 0.419 |
| 0.40 | entities | 41 / 62 / 31 | 0.398 / 0.569 / 0.469 | 30 / 56 / 25 | 0.349 / 0.545 / 0.426 |
| 0.40 | instruments | 5 / 4 / 20 | 0.556 / 0.200 / 0.294 | 4 / 5 / 14 | 0.444 / 0.222 / 0.296 |
| 0.40 | assets | 27 / 79 / 14 | 0.255 / 0.659 / 0.367 | 29 / 78 / 12 | 0.271 / 0.707 / 0.392 |

- **The item scores now carry signal.** The error pattern from the v1.1 counts holds:
  - assets: high recall, low precision (over-listing);
  - instruments: low recall;
  - entities: moderate precision.
- **D9 components, C2 − C1 at τ = 0.30 (descriptive only; parity, not selection):** `ΔI` −0.024 (incident +0.032, entity F1 −0.110, object F1 +0.005). At 0.40: −0.030.
  - The entity difference reflects the two arms' different outputs at the same request, as with the description field above.

## Latency and tokens

| | Inference (P1 only) n / p50 / p95 (s) | End-to-end `/analyze` n / p50 / p95 (s) | P1 tokens (metered) | Tokens per metered call, mean / max | Judge calls / tokens |
|---|---|---|---|---|---|
| C1 | 34 / 37.8 / 73.1 | – | 319,840 over 34 calls | 9,407 / 16,493 | 41 / 19,906 |
| C2 | 32 / 44.7 / 92.8 | 32 / 44.9 / 92.9 | 306,419 over 32 calls | 9,576 / 16,424 | 31 / 16,348 |

- **Inference and end-to-end latency are separate measurements.**
- **VSS overhead with crops off:** the gap between the agent's P1-only time and the `/analyze` wall clock is about 0.2 s.
- **The arms' inference latencies are not a pipeline effect:** they ran interleaved under a fluctuating shared gateway.

## Pipeline parity (C2 − C1, same prompt, paired per video, repeats averaged)

| Field | Pairs | Mean difference | 95% CI |
|---|---|---|---|
| type | 19 | −0.053 | [−0.158, 0.000] |
| severity | 19 | +0.132 | [−0.026, 0.316] |
| start | 19 | −0.053 | [−0.210, 0.105] |
| end | 19 | −0.053 | [−0.158, 0.000] |
| duration | 19 | −0.053 | [−0.158, 0.000] |
| description | 19 | +0.184 | [0.026, 0.368] |

- **The description interval excludes 0, so I investigated it** (plan §F.1).
  - The two arms sent the same request: equal P1 prompt tokens on all 19 clips, and the same inference settings.
  - The outputs differ in run-to-run behaviour: C2's median description is 218 characters against C1's 174, and its mean judge score is 0.49 against 0.40.
  - Within one arm the same request is unstable: in C2, the description pass agrees between the two repeats on only 5 of 10 clips scored twice. In C1 it agrees on 11 of 12.
- **Reading:** upstream non-determinism at temperature 0 on a small paired sample (19 clips, 6 fields, no multiplicity correction). It is **not an architectural extraction advantage**: today's VSS adds nothing before extraction. The other five fields are in parity.

## Limitations

- **Ground truth:** AI-assisted, approved at the dataset level, not individually human-verified (above).
- **Sample:**
  - 25 dev clips, and 34% of video-runs lost to gateway failures, so 19 clips are paired.
  - The intervals are wide.
  - Instruments are thin (25 ground-truth instruments over the dev video-runs).
- **Item metrics:** at the floor at the v1.1 threshold. Under v1.2 (τ = 0.40, AI-calibrated, not human-validated) they are informative (above).
- **Classification:** the VSS 429 misclassification in the stored records is corrected in this report from the stored error text. The stored records themselves are unchanged.
- **Host suspend:** one in-flight call during the suspend, plus the post-resume gateway failures.
- **Exposure:** the dev clips were few-shot examples in the retired P1-v1 prompt (D15).

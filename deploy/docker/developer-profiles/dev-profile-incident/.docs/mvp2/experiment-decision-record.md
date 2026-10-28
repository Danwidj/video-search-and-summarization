# Experiment decision record: D9, D10, D11, D15 and Stage 0

> **Status (2026-10-27):**
> - **D9 v2: pre-registered** ([decisions.md](../decisions.md#2026-10-27-stage-2-prompt-selection-rule-d9-v2-pre-registered)).
> - **D10 and D15:** approved as implemented.
> - **D11:** caps enforced and retry-proof; the judge output is capped at 1,500 tokens ([methodology v1.1](../../eval/methodology/evaluation-methodology-v1.1.md)). The dollar limits are provisional.
> - **Stage 1:** **ran 2026-10-28** on the frozen `ground-truth-v1.0` (AI-assisted, approved at the dataset level, not individually human-verified). Results: [`stage1-baselines.md`](../../eval/docs/experiments/stage1-baselines.md).
> - **Stage 2:** proposed, not run: [`stage2-plan.md`](../../eval/docs/experiments/stage2-plan.md). It waits for the owner's decisions S2-A (item matching), S2-B (top-up of failed runs) and S2-C (E6).
> - **Stage 0:** **ran 2026-10-27** on the sponsor-provided gateway (configured $0 per token; infrastructure cost unknown). Results: [`stage0-pilot.md`](../../eval/docs/experiments/stage0-pilot.md).
> - **Cropping:** option (a) chosen; the work is a separate follow-up. Plan: [`ground-truth-and-prompt-experiments-plan.md`](ground-truth-and-prompt-experiments-plan.md) §F and §H.

## D9 v2: prompt-selection rule (pre-registered)

Code: [`eval/experiment_selection.py`](../../eval/experiment_selection.py) (`evaluate`, `select_d9`); tests: `eval/tests/test_experiment_controls.py`.

### Data

- **Dev clips only**, and only complete, reportable (frozen ground truth), non-pilot VSS-arm results.
- **Baseline:** the initial VSS baseline (`vss-baseline`, C2 on dev). The direct-VLM baseline never enters selection.
- `select_d9` refuses test-split, pilot, unfrozen-ground-truth and incomplete records, and refuses to run until the rule heading exists in decisions.md.

### Primary metric `ΔI`

`ΔI` is the equal-weight mean of three component differences (candidate minus baseline). Each difference is the mean over the dev videos eligible for that component in both runs.

| Component | Per-video value |
|---|---|
| **Incident fields** | The mean of the eligible ones among **type** (exact), **severity** (exact), **start** and **end** (±5 s) and **description** (judge ≥ 0.5). Duration is derived and not used |
| **Entity F1** | `2TP / (2TP + FP + FN)` from the 1-to-1 matching |
| **Object F1** | The mean of the eligible ones among instrument F1 and asset F1 |

`ΔI = (Δincident + Δentity_F1 + Δobject_F1) / 3`. Each component counts as one third whatever the number of fields inside it.

### Secondary metric `ΔI8`

The original eight-score average: per video, the mean of the eligible ones among the five incident fields and the three item F1s, paired the same way. It is reported for every candidate and is the second tie-breaker.

### Eligibility and aggregation, precisely

| Case | Treatment |
|---|---|
| **Out-of-taxonomy clip** (ground truth `Out_Of_Taxonomy`, methodology Option C) | **Field-specific:** only **type** is ineligible. Severity, start, end and description stay eligible, so that clip's incident component is the mean of those four (denominator 4, or fewer if any is unscored). The entity and object components and the other seven of the eight scores are unaffected. In `ΔI8` the clip's denominator is 7 or fewer |
| **Unscored value** (scoring failure) | Not eligible. It is never a zero |
| **Ground truth and prediction both empty** for an item kind | That item's F1 is **not eligible**: nothing to find and nothing claimed |
| **Ground truth empty, prediction non-empty** | F1 = 0 (every prediction is a false positive) |
| **Ground truth non-empty, prediction empty** | F1 = 0 |
| **Object F1 with neither instruments nor assets eligible** | Object component not eligible for that video |
| **Invalid model output** (contract or parse failure) | A miss: incident fields 0 and the prediction empty. Its items follow the rows above |
| **No model output** (request failure) in a repeat | That repeat gives no value for the video |
| **Repeats** | Each score is averaged over the repeats that have a value, **before** pairing |
| **Pairs** | A video counts for a component only when **both** runs have a value for it |
| **A component with no eligible pair** | Left out of `ΔI` (the mean of the remaining components) and recorded in `components_used` |
| **Denominators, end to end** | Per video: incident = number of its eligible incident fields; object = number of eligible F1s among instrument and asset (1 or 2). Per component: the number of videos eligible on both sides. `ΔI` = the number of components with ≥ 1 eligible pair. `ΔI8` per video = its eligible scores |

**Eligible counts are always reported** (`compare()["eligible"]`, and `eligible_counts` on every candidate row of `evaluate`): per component and per score, the baseline's eligible videos, the candidate's, the pairs actually used, and the number of out-of-taxonomy videos. A component computed on few pairs is visible, never hidden.

### Uncertainty

A 95% percentile interval from a **video-cluster bootstrap**:
- resample the paired dev videos with replacement, so all scores of a video move together;
- recompute every component, `ΔI`, `ΔI8` and each of the eight scores;
- use the methodology's seed (20261027) and resample count.

### Guardrails

A candidate must pass all three to be eligible.

| | Rule |
|---|---|
| **G1** | Valid-output video-runs ≥ the baseline's − 1 |
| **G2** | No credible regression on any of the eight scores: a score fails if its point difference is ≤ −0.05 **and** its 95% CI upper bound is < 0 |
| **G3** | Same dev videos, repeats, model, ground-truth digest and split half as the baseline |

### Decision

- **Minimum improvement:** an eligible candidate needs `ΔI ≥ +0.02`. The selected prompt is the one with the highest `ΔI`.
- **If none qualifies,** `p1-v4-base` is selected. C3 then uses the baseline prompt, and the dev answer to RQ1 is "no gain found".

### Tie-breakers

They apply among candidates whose `ΔI` is within **0.01** of the best, in this order:
1. Higher lower bound of the `ΔI` 95% CI.
2. Higher `ΔI8` (secondary).
3. Higher severity-exact difference.
4. More valid-output video-runs.
5. Shorter prompt, in UTF-8 bytes.
6. Earlier registry entry.

### Version cap

At most 8 Stage 2 versions: E1–E7 and one combined candidate made only from versions with `ΔI > 0`. Every version is kept and reported, regressions included.

**Pre-registered:** the decisions.md entry `2026-10-27: Stage 2 prompt selection rule (D9 v2) pre-registered` is the `rule_record` that `select_d9` requires. It was written before any Stage 2 run.

## D10: repeats, order and interleaving (approved)

- **Repeats:** 2 per configuration in Stages 1, 2 and 3 (dev and test). The pilot uses 1.
- **Model:** `nvidia/cosmos-3-super-reasoner` for every decision. The optional transfer check needs separate approval.
- **Order, deterministic:** `experiment_runner.schedule`.
  - Per repeat, the videos are shuffled with `random.Random(20261027 + repeat)`.
  - At each video every configuration of the stage runs, interleaved, with the first configuration rotating by position, so no arm always runs first or in a block.
  - The order is written to the stage's `schedule.json` and to each result.
- **Same conditions:** a fresh signed URL per call, the same host and rate-limit policy (20 s pacing, 2 retries on 429), and the 300 s timeout.
- **Failures:** a video still failing after retries drops out of every pair it would be in. It is never rerun selectively.

## D11: caps, cost logging and volume (enforcement approved; dollar limits provisional)

### Enforced by the runner (`run_stage`)

Every config must carry three hard caps:

| Cap | Meaning |
|---|---|
| `budget.max_p1_calls` | Requests |
| `budget.max_p1_tokens` | Measured P1 tokens |
| `budget.max_judge_calls` | Judge requests |

- **Before any call:** a plan that cannot fit is refused (planned calls × 9,898 > token cap).
- **Before each call:** the stage stops if the next call could break a cap.
  - **Requests:** every HTTP attempt, 429 retries included, counts against `max_p1_calls`, and retries use only the attempts left over after one per remaining video.
  - **Tokens:** the check leaves room for a worst-case attempt of 35,000 tokens (largest prompt plus `max_tokens`). Attempts that report no usage, other than 429 rejections, are counted at that ceiling.
  - **Judge:** the check leaves room for the video's worst-case judge requests (judged fields × 5 attempts).
- **Rate limiting:** the stage also stops if more than 25% of attempts (after 8) were rate-limited.
- **A stopped stage** writes its partial results with `complete: false` and the reason. Selection refuses incomplete records.

### Cost logging

- **Per call:** every call is appended to `stages/<time>-<id>/cost-log.jsonl` with P1 prompt, completion and total tokens, judge calls, estimated judge tokens, the provisional cost and the configuration's running totals.
- **Per result:** each `results.json` carries a `usage` block.
- **Rates:** come from `eval/experiments/pricing.json`, marked `provisional: true`, at an assumed ceiling of $10 per million tokens. Replace it with the confirmed Switchyard rate or quota.

### Volume (Cosmos 3 Super)

The per-call figure is the 2026-10-02 mean of **9,898 P1 tokens per call** (maximum 20,965). Judge calls are budgeted at 1,500 tokens each, and Stages 2–3 at 11,000 tokens per P1 call for longer experiment prompts.

| Stage | P1 calls | Judge calls | Expected tokens | Token cap | Provisional cost cap |
|---|---|---|---|---|---|
| 0 pilot (now 10 calls, see below) | 10 | ≈ 50 | ≈ 0.17 M | 0.36 M (config caps) | $3.60 |
| 1 baselines | 100 | ≈ 500 | ≈ 1.8 M | 3 M | $30 |
| 2 prompt engineering | ≤ 400 | ≈ 2,000 | ≈ 7.4 M | 9 M | $90 |
| 3 held-out C1–C4 | 440 | ≈ 2,200 | ≈ 8.1 M | 10 M | $100 |
| End-to-end profile | 30 | – | ≈ 1.5 M | 2 M | $20 |

### Why the caps (24.5 M as proposed; 24.4 M with the smaller pilot) exceed the expected use (≈ 19 M)

A cap is a ceiling that stops a run, not a forecast. The 5.5 M margin (about 1.3×) covers five sources of variance:
1. **Per-call spread:** P1 calls ranged up to 20,965 tokens (2.1× the mean). Long clips cost more, and a 25- or 55-clip set can be heavier than the 2026-10-02 average.
2. **Retries:** a rate-limited or timed-out attempt can still consume prompt tokens and is retried up to twice.
3. **Longer experiment prompts:** few-shot (E6) and checklist (E7) variants add prompt tokens. 11,000 per call is an estimate.
4. **Judge reasoning length:** the judge model reasons before it scores. 1,500 tokens per call is an estimate.
5. **Unmeasured box calls** in the end-to-end profile.

Stage 0 has the largest relative margin (2.1×) because 10 calls give the least averaging. After the pilot, every later cap is recomputed from measured tokens per call and re-approved.

## D15: held-out exposure (approved)

- **Split:** the 55-clip test split is preserved (`split-v2`).
- **Disclosure:** every Stage 3 report carries it in full (also rendered by `experiment_report`):

  | Exposure | What was seen |
  |---|---|
  | 2026-10-02 benchmark (contract v2, 3 models × 55 test clips, incident fields) | Per-video predictions and scores against pre-correction ground truth |
  | Contract and timeline pilots (2026-09-27, 2026-10-16) | Animal003, Assault018 and Burglary005 (all test clips) shaped the v3 timeline wording behind `p1-v4-base` |
  | Box-accuracy and RP1 pilots | Clips not recorded; treated as possible test exposure |
  | Ground-truth correction (2026-10-27) | The AI reviewer (Claude) viewed frames and annotations of 38 clips, test clips included. It never saw VSS predictions or scores. The same assistant read aggregate token usage, not scores, of the 2026-10-02 runs for budgeting |

- **Quarantine:** Stage 2 prompts and few-shot examples come from dev clips only. Prompt authors do not open per-video test results. The runner refuses the test split until a selection record exists.
- **52-clip subset:** results are also reported on the 52 test clips not named in a recorded pilot. This subset **is not unseen**: all 52 were in the 2026-10-02 benchmark, any of them may have been in the unrecorded pilots, and 38 clips across both halves were viewed during ground-truth correction. It is described only as "excluding the clips named in recorded prompt-design pilots".

## Stage 0 pilot (authorised; blocked on pricing)

**Authorised (2026-10-27):** a no-crop pilot on the five dev clips, with 10 P1 calls in total. It is for operational validation only, on candidate ground truth:
- its results are never used to select prompts, change annotations or claim accuracy;
- `purpose: pilot` records are never reportable, `select_d9` refuses them, and pilot reports show no accuracy tables.

The authorisation has two conditions:
1. **Confirmed Switchyard billing or quota.** **Not met.** The repository documents no price, and the gateway's model listing (`GET /v1/models`, no inference) returns only model ids, with no pricing, quota or rate-limit headers. **So the pilot has not run.** It needs your confirmation: either the gateway is a free or allocated lab quota, or the price per million tokens for `cosmos-3-super-reasoner` and `nemotron-3-nano-30b-a3b`, with any quota limit.
2. **Caps cannot be bypassed by retries.** **Met** (#225, and the judge output limit in methodology v1.1). Before #225, a 429 retry was an extra request that `max_p1_calls` did not count.

**How the caps now hold:**

| Resource | Bound |
|---|---|
| P1 requests | **Hard: ≤ 5 per arm, 10 in total.** Every HTTP attempt counts against `max_p1_calls`. Before each video, the runner keeps one attempt per remaining video, so retries can use only what is left over. With 5 videos and a cap of 5 there is no retry: a 429 ends that video as `rate_limited` |
| P1 tokens | **Hard: ≤ 105,000 per arm, 210,000 in total.** Before each call the runner requires that the tokens counted so far plus a worst-case attempt (35,000 = the largest observed prompt plus the 16,384 `max_tokens`) fit the cap. An attempt with no usage report that was not a 429 is counted at that ceiling |
| Judge requests | **Hard: ≤ 25 per arm, 50 in total.** The pilot scores incident fields only: 1 judged field per video × at most 5 attempts (1 + 2 parse retries + 2 transient retries). Before each video the runner requires room for that worst case |
| Judge tokens | **Output hard-capped at 1,500 tokens per attempt** (methodology v1.1; a truncated reply is a failure, not a score). Input is the judge prompt plus two descriptions and is measured (about 300–600 tokens). Judge tokens are logged from each response's usage
| Crop calls | 0 (crops off) |
| RP1 | 0 (skipped) |

**Spending at the provisional $10 per M tokens:**

| | Expected | Hard ceiling |
|---|---|---|
| P1 | 10 requests, ≈ 99 k tokens, ≈ $0.99 | 10 requests, ≤ 210 k tokens, ≤ $2.10 |
| Judge | ≈ 12 requests (10 + 2 preflight probes), ≈ 15 k tokens, ≈ $0.15 | ≤ 52 requests × (≤ 1,500 output + ≈ 600 input) ≈ 109 k tokens, ≈ $1.09 |
| **Total** | **≈ $1.14** | **≈ $3.19** (output fully capped; input at the measured size), within the $3.60 planning ceiling |

The real-dollar amount stays unknown until the price is confirmed. The token and request bounds hold whatever the price is.

**After the pilot:**
- `measure` reports requests, failures, retries, tokens by model, latency and the provisional charge;
- `budget --measured` recalculates Stages 1–3;
- the gate into Stage 1 is unchanged: frozen ground truth, and the stage budget approved at the confirmed price.

**Cropping, option (a) (chosen and implemented 2026-10-27):** an experimental crops-on request uses a fresh in-memory evidence store for that request only. It holds no production data, never writes to disk or R2, and is discarded on return. Production requests keep the service's own store. An agent with R2 settings still refuses the request.

A crop pilot is **not** authorised. The agent makes up to 4 box calls per predicted item, and the runner cannot count those calls before the response arrives. Its spend needs its own bound: for example, a per-request box-call cap in the agent for experimental requests, or the predicted-item count × 4 accepted as the bound. It also needs its own approval.

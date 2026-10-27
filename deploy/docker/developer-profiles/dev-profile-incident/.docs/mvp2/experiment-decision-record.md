# Experiment decision record: D9, D10, D11, D15 and Stage 0

> **Status (2026-10-27):** **D10** and **D15** are approved. **D11** caps are enforced, but the dollar limits are **provisional** until Switchyard pricing or quota is confirmed. **D9 v2** below is **proposed and not yet pre-registered**: it becomes binding only when its decisions.md heading is written on your approval. **Stage 0** is prepared, not run. Plan: [`ground-truth-and-prompt-experiments-plan.md`](ground-truth-and-prompt-experiments-plan.md) §F and §H.

## D9 v2: prompt-selection rule (proposed)

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
| **Out-of-taxonomy clip** (ground truth `Out_Of_Taxonomy`, methodology Option C) | **Type** is not eligible. The incident component is the mean of the other four fields. Every other score counts as usual |
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

**On approval:** add a decisions.md entry headed `2026-MM-DD: Stage 2 prompt selection rule (D9 v2) pre-registered`. That heading is the `rule_record` `select_d9` requires, and it must be written **before the first Stage 2 run**.

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
- **Before each call:** the stage stops if the next call could break a cap. The token check leaves room for a worst-case call of 21,000 tokens (the largest seen).
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

## Stage 0 pilot (prepared, not run)

**Purpose:** infrastructure, reliability, latency and cost validation only.

**What enforces that:** configs carry `purpose: "pilot"` and are dev-only. They may use the **candidate** ground truth (`allow_candidate: true`). Pilot records are always `reportable: false`, `select_d9` refuses them, and a pilot report shows reliability, latency, usage and cost but **no accuracy tables**.

**Configs:**

| Config | Arm | Clips (1 per dev category) | Repeats | Caps (calls / P1 tokens / judge calls) |
|---|---|---|---|---|
| `pilot-direct-vlm` | direct | Animal001, Assault007, Burglary004, Explosion002, RoadAccidents005 | 1 | 5 / 105,000 / 50 |
| `pilot-vss` | VSS (local experiment agent, crops off) | same | 1 | 5 / 105,000 / 50 |

The two configs run **interleaved** as one stage.

**Estimated spending (provisional $10 per M tokens):**

| | Requests | Tokens | Cost |
|---|---|---|---|
| Expected | 10 P1 + ≈ 50 judge (+ 2 judge preflight probes) | ≈ 99 k P1 + ≈ 75 k judge ≈ **0.17 M** | **≈ $1.74** |
| Hard ceiling (the caps) | 10 P1, ≤ 100 judge | ≤ 210 k P1 + ≤ 150 k judge = **0.36 M** | **≤ $3.60** |

**Crop pilot removed (needs your decision).** Without an R2 evidence store the agent skips cropping entirely, so no box calls are made and crop cost cannot be measured. With R2 configured, an experimental request is refused (409), because evidence images would be uploaded to shared storage. Options:
- **(a)** an experiment-only discard evidence store in the agent, so detection runs but images are dropped (agent code change, experimental path only);
- **(b)** measure crop cost later, in the end-to-end profile, under a separately approved arrangement;
- **(c)** approve R2 writes to a scratch prefix for the pilot.

**Recommended: (a).**

**Gate into Stage 1:**
- 10/10 attempted, ≥ 8 model outputs;
- `verify` clean and zero harness defects (contract version, VSS echo);
- rate-limited ≤ 25% of attempts;
- measured tokens per P1 call ≤ 19,800 (2 × the estimate), otherwise re-estimate and re-approve;
- projected Stage 1 cost within its cap at the confirmed price;
- **`ground-truth-v1.0` frozen with your approval record**;
- the D9 v2 heading written before Stage 2.

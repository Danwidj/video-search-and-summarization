# End-to-end VSS profile (plan §F.2): results

> **Status (2026-10-30): done.** Approved by the owner and run once under the [plan](e2e-profile-plan.md), unchanged.
> - **Runs:** 30 video-runs (C2 and C3 × 15 test clips × 1 repeat) from 12:55 to 14:23 UTC: 5 runs, an outage pause, a 15-minute wait, then a resume from the checkpoint (one resume).
> - **Scoring:** none. Latency and reliability only; these outputs are **not accuracy results**.
> - **Integrity:**
>   - `verify` OK for both results;
>   - every Stage 3 result file still matches its audit hash;
>   - no cap was reached, and no judge request was made.
> - **Artifacts** (gitignored) under `eval/eval_data/results/`:
>   - stage `experiments/stages/20261030T125533Z-6e4a5742/` (checkpoint, schedule, cost log);
>   - results `experiments/e2e-c2-vss-base/20261030T125533Z/` and `experiments/e2e-c3-vss-v1/20261030T125533Z/`;
>   - report `reports/e2e-profile/`.

## 1. Summary

- **Cropping roughly adds half again on top of inference.** For a typical request with the cropping stage on:
  - end to end: about **28–30 s** at the median;
  - model inference: about **19–21 s**;
  - cropping: about **8–10 s** (about a third of the end-to-end time);
  - everything else: **0.02 s**.
- **Cropping cost scales with the number of predicted items**, about 1.7–1.8 s per grounding call at concurrency 4. A request with many items is much slower: C3 on Explosion014 had 101 items, hit the 40-call cap and took 193 s end to end (104 s cropping).
- **Reliability:**
  - 26 of 30 runs produced output. The 4 without output all fell in one gateway outage (HTTP 429 and 524, 13:00–13:36 UTC), 2 per config, and no recovery was run.
  - Of the cropped items, 94% got an image in C2 and 66% in C3.
  - The C3 shortfall is the cap: 61 truncated items on one clip. The C2 gaps are 4 grounding calls that timed out during the outage.
- **C2 vs C3 (descriptive):** on the 12 clips with output in both, the medians are close (end to end 28.0 vs 30.3 s, cropping 9.2 vs 8.4 s, 4.5 items each). C3's longer tail comes from two clips where V1 listed many more items (Explosion014: 101 vs 5; RoadAccidents024: 26 vs 10). With 12 clips and one repeat this is not a prompt effect claim.
- **Resources:** far inside every cap (§4).

## 2. Latency (seconds; runs with output; harness host)

| | C2 n | p50 | p95 | mean | C3 n | p50 | p95 | mean |
|---|---|---|---|---|---|---|---|---|
| **End to end** (`/analyze` wall clock) | 13 | 28.21 | 40.12 | 44.27 | 13 | 28.89 | 75.21 | 44.60 |
| **Model inference** (agent's P1 round trip) | 13 | 19.13 | 28.09 | 26.44 | 13 | 20.35 | 43.98 | 26.42 |
| **Cropping** (agent's crop stage) | 13 | 9.55 | 12.03 | 17.80 | 13 | 8.51 | 31.22 | 18.16 |
| **Other overhead** (the rest) | 13 | 0.02 | 0.04 | 0.02 | 13 | 0.02 | 0.03 | 0.02 |

- **Means vs medians:** the means are pulled up by one outage-period clip in C2 (Burglary005: 248 s, with P1 123 s and four 120 s grounding timeouts) and one capped clip in C3 (Explosion014: 193 s). Medians are the representative figures.
- **Cropping share:** the median is 34% (C2) and 33% (C3) of end to end. The median crop time per grounding call is 1.8 s (C2) and 1.7 s (C3), with up to 4 calls in parallel.
- **Comparison with Stage 3:** these figures are not comparable with the inference-only latency tables (cropping off). The gateway load also differed, so the inference times here are not a second measurement of Stage 3's.

## 3. Cropping stage and reliability

| | C2 | C3 |
|---|---|---|
| Runs with output / scheduled | 13 / 15 | 13 / 15 |
| No output (timeouts after retries) | Assault050, Burglary013 | Burglary005, Assault050 |
| P1 retries (attempts − runs) | 4 | 6 |
| Evidence items | 67 | 179 |
| Images produced | 63 (94.0%) | 118 (65.9%) |
| Items without an image | 4: grounding call timed out (Burglary005, outage period) | 61: crop-call cap reached (Explosion014) |
| Grounding calls (per request p50 / p95 / max) | 67 (4 / 10 / 10) | 118 (5 / 26 / 40) |
| Requests at the 40-call cap | 0 | 1 (Explosion014) |
| Calls refused by the cap | 0 | 61 |

- **The cap worked as designed:**
  - C3 Explosion014 made exactly 40 grounding calls;
  - its 61 remaining items were refused before any request and recorded with `image_gap: "crop-call cap reached"`;
  - without the cap, that report would have made 101 or more calls.
- **The 4 C2 gaps are timeouts:** each grounding call waited the detector's 120 s read timeout during the gateway outage. They count as cropping failures, not cap truncation.
- **Failure causes (all 4 runs without output):** gateway HTTP 524 (after about 125 s) and 429 rate limits, which the agent returns as 500. No cropping ran on those attempts, because P1 failed first.
  - **Outage pause:** the runner paused after 4 consecutive no-output runs (its existing control).
  - **Resume:** the stage resumed after 15 minutes, as the Stage 3 protocol does. All 25 later runs produced output.

## 4. Resources against the approved caps

| | C2 | C3 | Stage | Approved cap (stage) |
|---|---|---|---|---|
| `/analyze` video-runs | 15 | 15 | 30 | 30 |
| Model (P1) attempts | 19 | 21 | **40** | 90 |
| Model tokens, metered | 120,718 | 129,164 | **249,882** | 3,150,000 |
| Model tokens, cap rule (unmetered attempts at 35,000) | 295,718 | 339,164 | 634,882 | 3,150,000 |
| Grounding calls, actual | 67 | 118 | **185** | 1,440 |
| Grounding tokens, metered | 24,448 | 36,855 | **61,303** | 8,640,000 |
| Judge calls | 0 | 0 | **0** | 0 |
| Max grounding calls in one request | 10 | 40 | 40 | 40 per request |

- **Grounding tokens:** about 310–390 per call, well below the 6,000-token planning ceiling. The full run used under 1% of the grounding-token cap.
- **Accounting notes** (disclosed, no cap affected):
  1. **Over-count in the runner's crop bounds.**
     - **Recorded:** 267 / 358 calls and 1.22 M / 1.48 M tokens.
     - **Cause:** the bounds count every timed-out *attempt* at the full 40-call cap. Here those attempts got an agent response (HTTP 500, P1 failed), so they made no grounding call.
     - **Exact figures:** the actual calls above. The bound is conservative by design; it only brought a possible cap stop closer.
  2. **Under-count in the agent's token telemetry.**
     - **Cause:** a grounding call that ends in an exception (the 4 C2 read timeouts) is counted against the cap but not as a "call without usage".
     - **Upper bound:** counting each at the 6,000 ceiling gives C2 ≤ 48,448 grounding tokens, still under 1% of the cap.
     - **Fix:** a later change to `CropCallBudget` can count raised attempts. The code was left as it ran, to match the pinned manifest.
- **Cost:** the gateway reports $0 per token for both P1 and grounding. That is the project's charge only; the sponsor's infrastructure cost is real.

## 5. C2 vs C3 (descriptive)

The comparison uses the 12 clips with output in both configs.

| Median over the 12 | C2 | C3 | Median C3 − C2 | C3 higher on |
|---|---|---|---|---|
| End to end (s) | 28.0 | 30.3 | +2.7 | 8 of 12 |
| Model inference (s) | 18.6 | 20.7 | +1.9 | 8 of 12 |
| Cropping (s) | 9.2 | 8.4 | +1.9 | 8 of 12 |
| Evidence items | 4.5 | 4.5 | 0 | 4 of 12 |

- **Same model:** the two configs differ only in prompt (base vs V1). Inference times overlap; the gateway's load varied during the run, and there is one repeat.
- **The difference is in the tail:** V1 produced two much longer item lists (Explosion014 101 items, RoadAccidents024 26), which dominate C3's p95 and its cap truncation.
- **No significance test:** none is made (15 clips, 1 repeat, a mid-run outage). These are observations, not a pipeline or prompt effect.

## 6. Limits

- **A lower bound for production:** a local agent on the laptop, with crops held in memory, so there is no R2 upload or database write.
- **Gateway load:** it varied, including an outage. Latency depends on the shared gateway.
- **The cap shortens the slowest report:** production has no cap and would be slower on such a report (C3 Explosion014).
- **Not an accuracy result:** extraction outputs were not scored. The agent's tests show extraction is identical with cropping on and off.
- **No recovery:** the 4 runs without output remain failures.

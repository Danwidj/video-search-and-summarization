# End-to-end VSS profile (plan §F.2): execution plan and budget

> **Status (2026-10-30): prepared, not run. Execution waits for the owner's approval of the budget below.**
> - **Done offline:** configs, the pinned manifest, the agent's per-request crop-call cap, the runner's profile mode and crop budget, and the preflight. The preflight passes.
> - **Calls so far:** none. No model, grounding or judge request has been sent for the profile.
> - **Scope:** latency and reliability only. The profile is never scored and never feeds an accuracy result. Stage 3 is complete and is not touched.

## 1. Design

| Item | Value |
|---|---|
| Configurations | **C2** VSS + `p1-v4-base` (`e2e-c2-vss-base`); **C3** VSS + V1 `p1-v4-e01-severity` (`e2e-c3-vss-v1`). Each equals its Stage 3 counterpart in arm, prompt, model, ground truth, split, repeats, RP1-off, agent URL and retry-v2 |
| What changes | Cropping **on** (`skip_crops: false`), capped at **40 grounding calls per request**; `scoring: none`; a 900 s request timeout |
| Clips | 15 test clips, 3 per category, seeded: per category `random.Random(20261027).sample(sorted(test clips), 3)`: Animal003, Animal006, Animal015; Assault012, Assault018, Assault050; Burglary005, Burglary013, Burglary071; Explosion004, Explosion014, Explosion051; RoadAccidents008, RoadAccidents024, RoadAccidents069 |
| Repeats and order | 1; the D10 interleaved order (seed 20261027), so 30 video-runs |
| Agent | The isolated local experiment agent (no Supabase, database or R2 settings, `INCIDENT_EXPERIMENTS_ENABLED=1` in its own process only). Crops go to a per-request in-memory store and are discarded. Never the shared VM agent |
| Grounding model | `nvidia/cosmos-3-super-reasoner` through the same gateway (the agent's `VLM_NAME`), one frame per item at most 1,280 px, `max_tokens` 512 |

**Measured per video-run** (from the agent's response and the harness):

| Measure | Source |
|---|---|
| Full pipeline latency | Harness wall clock of `/analyze` (`transport.end_to_end_s`) |
| Model inference latency | The agent's P1 round trip (`p1_elapsed_ms`) |
| Cropping overhead | The agent's crop-stage wall time (`experiment.crop.elapsed_ms`) |
| Other overhead | End to end − P1 − cropping (video-length read, validation, transport) |
| Cropping stage | Items, images, image rate, gap reasons, grounding calls and tokens, requests at the cap |
| Reliability | Outcomes per config (scored, contract-invalid, timeout, rate-limited, HTTP error) and retries |

Report: `eval_e2e_profile.py report --title … --out eval_data/results/reports/e2e-profile/ C2=<results.json> C3=<results.json>`, kept apart from the Stage 3 inference-latency tables (plan §F.4: the two are never mixed).

## 2. Enforcement

**Per-request cap (agent, `max_crop_calls`)**
- One counter per request, shared by its concurrent crops, checked **before every grounding HTTP attempt**, including the detector's own retries on 429, 5xx and unparseable replies.
- The request never sends more than the cap. An item beyond it keeps `image_gap: "crop-call cap reached"`, which is counted.
- An experimental crops-on request without a cap is refused (400). Production requests are unchanged and uncapped.

**Overall budget (runner, per config and for the stage)**
- `budget.max_crop_calls` and `budget.max_crop_tokens` sit beside the P1 caps.
- Before each video-run the runner reserves the worst case: the cap × (1 + allowed retries) calls, at 6,000 tokens per call.
- An attempt that may have cropped unseen (a client-side timeout) is counted at the full cap. A call that reports no usage is counted at the 6,000-token ceiling.
- If the reservation does not fit, the stage stops with its partial results.

**Stage 3 isolation**
- The profile has its own `e2e-` experiment ids, results directories and stage directory; the runner refuses to write into an existing one.
- The preflight and the report both re-hash every Stage 3 result file against the hashes its passed audit recorded, and fail on any change.
- The profile only reads the Stage 3 C2/C3 results, offline, for the call estimate.
- Profile records are `purpose: profile` and `reportable: false`.

## 3. Proposed budget (for approval)

| | Per config | Stage (C2 + C3) | Expected use |
|---|---|---|---|
| `/analyze` video-runs | 15 | 30 | 30 |
| P1 attempts (hard cap) | 45 | **90** | 30–34 |
| P1 tokens (hard cap) | 1,575,000 | **3,150,000** | about 0.27–0.30 M |
| Grounding calls (hard cap) | 720 | **1,440** | about 220–250 |
| Grounding tokens (hard cap) | 4,320,000 | **8,640,000** | about 0.3–1.0 M (not yet measured) |
| Judge calls | 0 | **0** | 0 |
| Per-request crop-call cap | 40 | 40 | – |

- **Expected calls:** from Stage 3's predicted items on these clips, one grounding call per item up to the cap: about 95 for C2 and 124 for C3. In C3, Explosion014 had 101 items, so 61 would hit the cap. About 15% is allowed for grounding retries (an assumption; not yet measured).
- **Cap logic:** like Stage 3 (3 × runs, 35,000 tokens per attempt), the caps are ceilings for the worst case, not estimates.
- **Runtime:** about 45–60 min with the laptop on AC power and the lid open (Stage 3 took about 58 s per video-run; cropping adds about 10–30 s typically, up to about 2 min for a capped request).
- **Cost:** the gateway reports $0 per token for both P1 and grounding calls. That is the project's charge only; the sponsor's GPU and infrastructure cost is real and not free.

## 4. Run (only after approval)

1. Offline: `uv run python scripts/eval_e2e_profile.py preflight` must print `"ok": true`, and `eval_experiment.py run experiments/configs/e2e-*.json` without `--confirm-paid` (a dry run).
2. The embedding server is **not** needed (no scoring). Start the local experiment agent: `experiments/agent/start-experiment-agent.sh`.
3. Run:

   ```
   experiments/keep-awake.sh -- .venv/bin/python scripts/eval_experiment.py run \
       experiments/configs/e2e-c2-vss-base.json experiments/configs/e2e-c3-vss-v1.json --confirm-paid
   ```

   Continue with `--resume <stage dir>` after a pause or a stop at a checkpoint.
4. `eval_experiment.py verify` both results, then `eval_e2e_profile.py report …`, and re-run the preflight's Stage 3 check.
5. **No recovery is planned.** Failures are reported as reliability results; a recovery would need its own approval.

## 5. Interpretation limits

- One repeat on 15 clips: descriptive figures (p50, p95, mean), no significance test.
- The cap truncates outlier reports (C3 Explosion014). The truncated items are counted, and production, which has no cap, would be slower on such a report.
- A local agent on the laptop, with crops held in memory instead of uploaded to R2: it excludes R2 upload and persistence time, so it is a lower bound for the production pipeline.
- Same model and request as Stage 3, but its extraction outputs are not used for accuracy. Cropping runs only after P1, and the agent tests show extraction is identical with cropping on and off.

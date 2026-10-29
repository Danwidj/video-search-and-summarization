# Stage 3: final held-out comparison (C1-C4): execution plan

> **Status (2026-10-29): prepared, not run.** **Execution waits for the owner's approval** of this plan, its caps and its runtime.
> - **Done offline:** the configs, the reproducibility manifest and the preflight are committed. The preflight passes.
> - **Calls so far:** none. No inference or judge request has been sent for Stage 3.
> - **Ground truth:** `ground-truth-v1.0` is frozen on the owner's dataset-level approval of AI-assisted labels. It is **not individually human-verified**.
> - **Matching:** τ = 0.40 is AI-calibrated, **not human-validated**.

## 1. Design

| Item | Value |
|---|---|
| Configurations | **C1** direct VLM + `p1-v4-base`; **C2** VSS + `p1-v4-base`; **C3** VSS + V1 `p1-v4-e01-severity`; **C4** direct VLM + V1 |
| Selected prompt | V1, chosen on dev by D9 v2 and approved by the owner on 2026-10-29 ([record](../../../.docs/decisions.md#2026-10-29-stage-2-selection-d9-v2-p1-v4-e01-severity)) |
| Clips | The 55 test clips of `split-v2`: Animal attack 10, Assault 10, Burglary 13, Explosion 10, Road accident 12. No dev clip |
| Repeats | **1 per configuration** (owner, 2026-10-29; D10 had planned 2), so **220 video-runs** |
| Order | D10: video order shuffled with `random.Random(20261027 + 1)`; at each clip all four configurations run interleaved, the first rotating by position |
| Model and request | `nvidia/cosmos-3-super-reasoner`, `contracts/inference.json` P1 settings (temperature 0, max_tokens 16,384, 64 frames; Super samples about 24), strict `incident-contract-v4` `response_format` |
| VSS arm | The isolated local experiment agent (`experiments/agent/start-experiment-agent.sh`: no Supabase, database or R2 variable, `persisted: false`), crops off, RP1 skipped. Never the shared VM agent |
| Scoring | Methodology v1.2 (τ = 0.40, the pinned judge and embedder); D9 v2 differences; severity MAE under v1.3, reporting only |
| Retries and recovery | `retry-v2` in every config. After the 220 runs, `recovery-v1` on infrastructure failures only, the same in all four configs |
| Run once | Each config is `final` and `frozen_baseline`: the runner refuses a second run once one is complete. `--resume` continues an interrupted stage |
| Not included | The cropping-on end-to-end profile, the optional transfer models, the Stage 1 recovery and any further experiment. Each needs separate approval |

**Never changed by test results:** prompts, τ and matching, scoring rules, model settings, the selection decision, the ground truth and the split. A genuine ground-truth error found on test would mean a new ground-truth version and a re-score of all four arms. That would be reported, never applied silently.

## 2. Reproducibility

- **Configs:** `experiments/configs/s3-c1-direct-base.json`, `s3-c2-vss-base.json`, `s3-c3-vss-v1.json`, `s3-c4-direct-v1.json`.
  - They differ only in arm, prompt, `baseline_ref` and description.
  - The preflight checks this, and they are frozen by their SHA-256 in the manifest.
- **Manifest** [`experiments/stage3/manifest.json`](../../experiments/stage3/manifest.json) pins:

  | Item | Pinned value |
  |---|---|
  | Configs | Each config file's SHA-256 |
  | Prompts | `409ed9b3187a…` (base) and `004746ea7d19…` (V1) |
  | Model and request | The model, the P1 settings and the `response_format` digest; `incident-contract-v4` |
  | Ground truth | `records_sha256` `391fcd272bf2…` and the freeze-manifest digest |
  | Methodology | Version, τ, judge model, prompt and settings, embedder, ±5 s tolerance, bootstrap seed 20261027 and 10,000 resamples |
  | Clips | The 55 test IDs and their digest |
  | Seeds | The split seed, the order seed 20261027 and the schedule digest |
  | Policies and caps | retry-v2, recovery-v1 and every cap |

  It contains no timestamps, so a rebuild must equal the committed copy (`eval_stage3.py preflight` and a test check this).
- **Request parity** (checked offline: each arm's real body builder, no request):

  | Pair | Body, apart from `stream` (SHA-256) | Difference |
  |---|---|---|
  | C1 and C2 (base) | `807e1de48734…` | Only `"stream": false`, which the agent sends and the direct client omits. It is the API default, an unavoidable transport difference |
  | C4 and C3 (V1) | `4e1a89932ebd…` | The same |

  - **Same input:** the video is the same R2 object, signed fresh per video-run.
  - **The VSS arm adds** the agent hop and the bounds check, and nothing before extraction.
- **Timing, recorded per video-run:**

  | Measure | Direct arm | VSS arm |
  |---|---|---|
  | **Model processing** | The harness-to-gateway P1 round trip | The agent's own P1 round trip (`p1_elapsed_ms`) |
  | **Pipeline overhead** | None (no pipeline stage) | `/analyze` end-to-end minus model processing |
  | **End-to-end** | – | The harness's `/analyze` round trip |

  - **Kept separate:** all three are reported apart. Retry waits are never counted as processing.
  - **Failures:** every attempt, error and token count is kept in `p1_raw.rate_limit.attempts`.

## 3. Resource budget (exact caps; nothing runs above them)

| Item | Per config | Stage 3 (4 configs) | Basis |
|---|---|---|---|
| Scheduled video-runs | 55 | **220** | 55 clips × 1 repeat |
| Max P1 attempts (retries included) | 165 | **660** | every run × 3 (retry-v2: at most 2 retries) |
| P1 token reservation | 5,775,000 | **23,100,000** | attempts × the 35,000-token per-attempt ceiling |
| Max judge calls | 1,680 | **6,720** | derived from the ground truth (`caps`): 336 judged fields × 5 attempts |
| Recovery-v1 max P1 attempts | 45 | **180** | at most 15 recovered runs × 3 |
| Recovery-v1 P1 token reservation | 1,575,000 | **6,300,000** | |
| Recovery-v1 max judge calls | 685 | **2,740** | the 15 clips with the most judged fields × 5 |
| **Total ceiling** | | **840 P1 attempts; 29.4 M P1 tokens reserved; 9,460 judge calls** | |

**Expected use** (an estimate from measured Stage 2 rates on dev; not a cap):

| Item | Expected |
|---|---|
| P1 attempts | ≈ 231–249 (retries were 5% of runs in Stage 2b and 13% in Stage 2a, mostly 524s, some 429s and host suspends) |
| Metered P1 tokens | ≈ 2.0 M (≈ 9,071 per base call, ≈ 9,245 per V1 call) |
| Judge calls | ≈ 490, about 0.19 M tokens |
| Runtime | **≈ 3.1–4.4 h** at the measured 52–69 video-runs per hour (Stage 2a and 2b; judge time included). Two sessions of at most 4 h; the second is likely short |

- **Clips:** test clips are like dev ones (median 42 s against 49 s, max 333 s, 5 over 120 s).
- **Cost:** the gateway reports $0 per token. That is the project's gateway charge only. The sponsor's GPU and infrastructure cost is real, not visible to the project, and **not free**.

## 4. Execution (only after approval)

1. **Preflight** (offline): `uv run python scripts/eval_stage3.py preflight` must print `"ok": true`.
   - It checks roles, shared settings, the runner's test guards, the manifest, the ground-truth digest, the 55 clips, the caps, run-once and request parity.
   - Also run `eval_experiment.py run experiments/configs/s3-*.json` without `--confirm-paid` (a dry run).
2. **Host:** on AC power with the lid open; the DNS check passes; then start the embedder (port 8811) and the local experiment agent.
3. **Run:**

   ```
   experiments/keep-awake.sh -- .venv/bin/python scripts/eval_experiment.py run \
       experiments/configs/s3-c1-direct-base.json experiments/configs/s3-c2-vss-base.json \
       experiments/configs/s3-c3-vss-v1.json experiments/configs/s3-c4-direct-v1.json \
       --confirm-paid --session-hours 4
   ```

   - Continue with `--resume <stage dir>` after a pause (exit 4) or a laptop close (stopped after a checkpoint).
   - **The runner stops or pauses** on:
     - any cap;
     - 4 consecutive runs with no model output;
     - a session rate-limit share above 25%;
     - the 4-hour session limit.
4. **Verify:** `eval_experiment.py verify` every results directory.
5. **Recovery:**
   - First audit the failures, then run `eval_experiment.py recover <the 4 results.json>` as a dry run, then with `--confirm-paid`.
   - Only infrastructure failures are recovered: `rate_limited`, `timeout`, `host_suspended`, `transport_error` and `expired_url`.
   - An invalid model output is never retried.
   - More than 15 failed runs in one config is an outage: report it instead of recovering.
   - A config with nothing to recover gets a `recovered: 0` merged view, so all four share the `original+recovery-v1` protocol.
6. **Report** (offline), for the merged records and again for the original runs:
   - `eval_stage3.py report --title … --out eval_data/results/reports/stage3/<view>/ C1=… C2=… C3=… C4=…`
   - `eval_severity_report.py` with each baseline.

## 5. Reporting (`eval_stage3.py report`, paired per video)

| Content | Comparisons and detail |
|---|---|
| **D9 v2 differences** (ΔI, ΔI8 and the incident, entity-F1 and object-F1 components), every score's difference, 95% video-cluster bootstrap | **C3−C2** prompt effect in VSS (RQ1); **C4−C1** prompt effect in the direct arm; **C2−C1** and **C3−C4** VSS minus direct at the same prompt; **C3−C1** reported as (C3−C4) + (C4−C1). Guardrails G1–G3 on the prompt comparisons, informational only |
| **Incident fields** (type, severity, start, end, description) | Conditional and end-to-end accuracy with intervals (the shared experiment report) |
| **Items** | Entity, instrument and asset P/R/F1 (pooled TP/FP/FN) |
| **Severity (v1.3, reporting only)** | MAE, signed error, exact, within ±1, over/under counts and confusion; paired MAE and signed-error differences per comparison |
| **Reliability** | Outcomes, failure causes per clip, original-run and recovery-adjusted reliability kept apart |
| **Usage and latency** | Tokens; model processing, pipeline overhead and end-to-end latency (p50, p95, mean) |
| **By category** | ΔI per category (10–13 clips each; descriptive) |
| **D15 subset** | ΔI on the 52 clips not named in recorded pilots, which are **not unseen** |
| **Representative clips** | The largest per-clip gains and regressions per comparison |

**Interpretation rules:**
- **Same model, same request:** both arms use the same model and send the same request at each prompt. So a VSS-minus-direct difference is a pipeline, transport, reliability or run-to-run effect, **never an architectural extraction advantage**. With one repeat, run-to-run variation cannot be separated from a pipeline effect.
- **Repeats:** one repeat measures each clip once, and the intervals reflect clip-to-clip variation only.
- **Nothing is selected on test:** D9 v2 here is a measurement.

## 6. Scientific integrity and exposure

- **Preserved:** all Stage 0–2 results, the recovery records, the prompts, the selection record, the frozen ground truth, the calibration, the methodology and `split-v2`. Stage 3 writes new directories only.
- **Exposure (D15):** the 55 test clips were **held out from Stage 2 prompt selection, but they are not unseen**:
  - they were in the 2026-10-02 benchmark (contract v2, pre-correction ground truth);
  - three of them (Animal003, Assault018, Burglary005) shaped the v3 timeline wording behind `p1-v4-base`;
  - the box-accuracy and RP1 pilot clips are unrecorded;
  - the AI-assisted ground-truth correction viewed frames of test clips (never VSS predictions or scores).

  The full table is in the [decision record](../../../.docs/mvp2/experiment-decision-record.md#d15-held-out-exposure-approved), and every report carries the disclosure.
- **No human validation is claimed:** the ground truth (AI-assisted, approved at dataset level) and τ (AI-labelled, AI-audited calibration) are not human-validated.

## 7. Remaining risks

1. **Shared gateway:**
   - non-determinism at temperature 0;
   - HTTP 524 timeouts and occasional 429s (retries were 5–13% of Stage 2 runs);
   - possible 429s if other users load the gateway.

   retry-v2 and recovery-v1 cover these, but a long outage pauses the stage.
2. **One repeat:** wider effective noise than dev's two repeats. A pipeline effect cannot be told apart from run-to-run variation.
3. **Small item counts:** few instruments on test (14 ground-truth instruments on 9 of the 55 clips). Instrument results are descriptive.
4. **Host availability:**
   - A laptop suspend kills in-flight calls (keep-awake, AC and lid open).
   - A stop between sessions resumes from the checkpoint.
   - A signed URL lives 1 h, longer than the worst-case retry span (about 22 min), and recovery signs fresh URLs.
5. **Leakage:** test exposure (§6) may make absolute baseline accuracy optimistic.
6. **Judge:** the pinned judge is an LLM. A truncated or invalid reply stops scoring as a failure, never a zero.

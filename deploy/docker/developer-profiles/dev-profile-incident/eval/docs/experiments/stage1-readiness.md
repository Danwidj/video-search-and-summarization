# Stage 1 readiness (baselines)

> **Status 2026-10-27: ready, not run.** Stage 1 runs only after `ground-truth-v1.0` is reviewed, approved and frozen. The runner refuses unfrozen ground truth for these configs (`allow_candidate: false`). Budgets come from the measured [Stage 0 pilot](stage0-pilot.md).

## Configuration

| | `direct-vlm-baseline` (C1 on dev) | `vss-baseline` (C2 on dev) |
|---|---|---|
| Arm | direct VLM | VSS, through the local experiment agent (`127.0.0.1:8765`, no Supabase or R2, crops off) |
| Prompt | `p1-v4-base` (SHA-256 `409ed9b3…`) | same |
| Model | `nvidia/cosmos-3-super-reasoner` | same |
| Clips | the 25 dev clips of `split-v2` | same |
| Repeats | 2 (D10) | 2 |
| Order | both run **together as one stage**, interleaved per clip with the first config rotating, and the clip order shuffled per repeat (seed 20261027 + repeat) | |
| Scoring | `full` (items matched and judged), evaluation-methodology-v1.1 (judge output ≤ 1,500 tokens) | same |
| Ground truth | `ground-truth-v1.0` **frozen** (required) | same |
| Frozen baseline | yes: never rerun after its first complete run | no |
| `purpose` | experiment (reportable once ground truth is frozen) | experiment |

## Caps and how they are derived

| Cap (per config) | Value | Derivation |
|---|---|---|
| `max_p1_calls` | **50** | 25 clips × 2 repeats. Every HTTP attempt counts, so there is no spare for 429 retries: a 429 becomes a `rate_limited` failure (counted, never rerun) |
| `max_p1_tokens` | **1,050,000** | Unchanged. Before each call the runner requires that the tokens counted so far plus the 35,000-token worst case fit the cap. Expected use is 50 × 9,275 = 464 k. Even if every call were the pilot's largest (16,232), 49 calls (795 k) plus the 35 k reserve is 830 k, which fits. Each timed-out call counts as 35 k, so about 16 timeouts would still fit at the mean |
| `max_judge_calls` | **1,710** | **2 repeats × 171 judged fields × 5 attempts per field.** Judged fields per clip = 1 (incident description) + entities + 2 × instruments + 2 × assets, from the ground truth (a match never exceeds the ground-truth items): 3–19 per clip, 171 in total on dev. 5 attempts = 1 + 2 parse retries + 2 transient retries |
| Judge output | ≤ 1,500 tokens per attempt | methodology v1.1 |

- **Where the per-clip counts live:** [`../../experiments/judge-caps.json`](../../experiments/judge-caps.json) (clip ids and integers only), produced by `uv run python scripts/eval_experiment.py caps experiments/configs/direct-vlm-baseline.json experiments/configs/vss-baseline.json --write`.
- **Caps are re-derived after the freeze.** The counts come from the current candidate (`7abf73ce…`), and the approved annotations may add or remove items. `run_stage` also re-derives the required cap from the frozen ground truth and **refuses to start** if a config's `max_judge_calls` is below it. So the full plan can never be stopped partway by the judge cap.
- **Tests** (`tests/test_stage1_readiness.py`):
  - a full run at the worst-case judge usage completes exactly at the derived cap;
  - one request less is refused before any call;
  - 50 calls at the pilot maximum fit the token cap;
  - the committed caps equal the snapshot's derivation.

**Expected actual use:** 342 judge requests (one attempt per field), well below the 1,710 reserved. About 180 k judge tokens at the pilot's 525 per call.

## Gateway timeout (HTTP 524)

- **What happened:** in the pilot, one VSS call got **HTTP 524** from the gateway. That is Cloudflare's response when the origin does not answer within **about 100 seconds**.
- **What it means:** the effective request timeout of a P1 call through the sponsor gateway is about **100 s**, not the 300 s the clients and the agent are configured with (`inference.json`). A call that needs longer fails at about 100 s. The longest scored pilot call took 66.9 s.
- **Not changed:** the production and gateway configuration, the 300 s client timeout and the agent.
- **How it is recorded (changed in this PR):** 504, 522 and 524 are now classified as `timeout` in both arms, not `http_error`. In the VSS arm the agent reports them as `P1 call returned HTTP 524`.
- **How it is counted:** a timed-out call is **never silently excluded**:

  | Report | Treatment |
  |---|---|
  | Request reliability | Counted under `timeout` (`no_model_output`) |
  | Conditional accuracy (valid outputs) | Not in the denominator, and shown as `no_model_output` |
  | End-to-end accuracy (all attempts) | **Included as a miss** |
  | Paired comparisons | The clip is left out of the pair and the exclusion is **counted** (`excluded`) |

  These are three separate tables (Reliability; Incident fields: conditional and end-to-end), and tests pin them.
- **Long clips:** they may be more exposed to the 100 s limit. If timeouts recur on the same clips in Stage 1, that is reported as a reliability finding of the gateway path, and both arms share it.

## Budget and runtime (from the pilot)

| | Value |
|---|---|
| P1 calls | 100 (50 per config) |
| P1 tokens | ≈ 0.93 M expected (9,275 per call). Hard cap 2 × 1.05 M |
| Judge requests | ≈ 342 expected. Hard cap 2 × 1,710 |
| Judge tokens | ≈ 0.18 M (525 per call), each attempt's output ≤ 1,500 |
| Gateway cost | **$0** (configured price). Infrastructure cost unknown (sponsor's Brev instance) |
| Rate | about 1 call per minute, one at a time (the key allows 60 per minute and 4 at once) |
| Runtime | per call about 20 s pacing + P1 latency (pilot mean 44 s, p95 ≈ 67 s; judging runs inside the pacing window) ≈ **64–87 s**. 100 calls ≈ **1.8–2.4 h**. Each gateway timeout adds up to about 2 min |

## Before Stage 1 can run

1. **Ground truth:** review the 98 Pending entries ([package v0.2.1](../../ground_truth/review/README.md#human-review-package)), build Candidate v0.3, approve the final annotations and exclusions, and freeze `ground-truth-v1.0` with your approval record.
2. **Caps:** re-derive the judge caps on the frozen ground truth (`eval_experiment.py caps … --write`). A change is committed before the run.
3. **Budget:** approve the Stage 1 budget above (gateway $0; runtime about 2 h).
4. **Services:** start the local embedding server (`:8811`, needed for full scoring), then the local experiment agent.

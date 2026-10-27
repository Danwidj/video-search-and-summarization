# Stage 0 pilot: results (infrastructure only)

> **Pilot, 2026-10-27, authorised by the user.** It validates infrastructure, reliability, latency and cost only. It ran on **candidate** ground truth, so **nothing here is an accuracy result**: it is never used for prompt selection, ground-truth changes or accuracy claims (decision record, D15). No crops, no RP1, no Supabase or R2 writes.

## Setup

| Item | Value |
|---|---|
| Configs | `pilot-direct-vlm` (direct arm), `pilot-vss` (VSS arm), run interleaved as one stage (D10 order, seed 20261027) |
| Clips | Animal001, Assault007, Burglary004, Explosion002, RoadAccidents005 (1 dev clip per category) |
| Prompt | `p1-v4-base` (SHA-256 `409ed9b3187a…`), the same in both arms |
| Model | `nvidia/cosmos-3-super-reasoner`; judge `nvidia/nemotron-3-nano-30b-a3b` |
| Scoring | `incident_only`, evaluation-methodology-v1.1 (judge capped at 1,500 output tokens) |
| VSS arm | Local experiment agent (`start-experiment-agent.sh`). Its process held only the model endpoint, key and experiment flag (no Supabase, database or R2 variable); `persisted: false`; no revision written |
| Gateway | Sponsor-provided Switchyard (LiteLLM on Brev). **Configured cost $0 per token**. The underlying GPU infrastructure cost is **unknown** and is borne by the sponsor |
| Caps per arm | 5 P1 requests / 105,000 P1 tokens / 25 judge requests |
| Results | `eval_data/results/experiments/pilot-{direct-vlm,vss}/20261027T143808Z/` (local). `verify`: OK for both |

## Requests and failures

| | Direct | VSS | Total |
|---|---|---|---|
| P1 HTTP attempts | 5 | 5 | **10** (the authorised maximum) |
| Retries | 0 | 0 | 0 |
| Rate-limited (429) | 0 | 0 | 0 |
| Model outputs (scored) | 5 | 4 | 9 |
| Failures | 0 | 1: HTTP 524 from the gateway (Cloudflare origin timeout) on Assault007, surfaced by the agent as 500 → `http_error` | 1 |
| Judge requests | 5 | 4 | 9 (+1 preflight probe) |
| Judge truncations or invalid replies | 0 | 0 | 0 |

**The one failure:** HTTP 524 is Cloudflare's "origin did not respond within about 100 s". The same clip took 35.5 s in the direct arm a minute earlier, so it was a transient upstream delay, not a harness defect. It was not retried, and it was counted against the caps at the 35,000-token worst case. **Implication:** the gateway path puts a hard ceiling of about 100 s on any P1 call, well below our 300 s client timeout. The longest scored P1 call was 66.9 s.

## Tokens by model

| Model | Arm | Calls | Prompt tokens | Completion tokens | Total |
|---|---|---|---|---|---|
| `cosmos-3-super-reasoner` | direct | 5 | 41,388 | 4,084 | 45,472 |
| `cosmos-3-super-reasoner` | VSS | 4 measured (+1 timed out, unmetered) | 34,919 | 3,088 | 38,007 |
| `nemotron-3-nano-30b-a3b` (judge) | both | 9 | – | – | 4,726 (438–705 per call) |

- **P1 per call:** a mean of **9,275 tokens** (the plan assumed 9,898) and a maximum of 16,232 (Animal001, whose prompt alone was 15,530).
- **Pessimistic cap accounting:** 118,479 P1 tokens, counting the timeout at 35,000.
- **Gateway charge: $0.00.** The infrastructure cost is unknown.
- **Rate limit:** the key allows 60 requests per minute and 4 concurrent. The pilot sent about 1 per minute, one at a time.

## Latency (P1 only, seconds)

| Clip | Direct | VSS (agent-measured P1) | VSS end to end |
|---|---|---|---|
| Assault007 | 35.5 | timeout (524) | – |
| Explosion002 | 64.6 | 52.3 | 52.4 |
| Burglary004 | 66.9 | 65.7 | 65.8 |
| Animal001 | 16.7 | 65.8 | 65.9 |
| RoadAccidents005 | 17.5 | 13.4 | 13.4 |

The same clip's latency varies from call to call by up to about 4× (Animal001: 16.7 s vs 65.8 s), so latency reflects shared-gateway load. The agent adds about 0.1 s on top of P1 (end to end minus P1).

## Did the arms behave as intended?

**Yes, as a parity check:**
- **Same request:** for every clip both arms sent the same prompt, with **identical prompt token counts** (6,479 / 6,468 / 15,530 / 6,442), and the agent confirmed the production prompt SHA-256.
- **Different outputs:** completion lengths and raw outputs differed slightly, which is expected run-to-run non-determinism at temperature 0. This is why D10 uses two repeats.
- **Same structured fields:** on the 4 clips scored in both arms, the predicted window and severity matched on all 4 and the type on 3 of 4. This is an operational observation, not an accuracy result.

## Recalculated budgets for the later stages

**Basis:** the measured 9,275 tokens per P1 call (+1,500 for longer experiment prompts in Stages 2–3) and 525 tokens per judge request. The judge requests assume every ground-truth item is matched (1 + entities + 2 × instruments + 2 × assets per clip: 6.8 on dev, 6.1 on test), so they are an upper estimate. Wall clock is about 70 s per call (20 s pacing + measured latency).

| Stage | P1 calls | Judge requests (≤) | Tokens | Gateway cost | At the old $10/M planning rate | Wall clock |
|---|---|---|---|---|---|---|
| 1 baselines | 100 | 684 | 1.29 M | $0 | $13 | ≈ 1.9 h |
| 2 prompt engineering (≤ 8 versions) | 400 | 2,736 | 5.75 M | $0 | $57 | ≈ 7.8 h |
| 3 held-out C1–C4 | 440 | 2,688 | 6.15 M | $0 | $62 | ≈ 8.6 h |
| End-to-end profile | 30 | 183 | 0.37 M | $0 | $4 | ≈ 0.6 h |
| **Total** | **970** | **≤ 6,291** | **13.6 M** (down from 19 M) | **$0** | $136 | ≈ 19 h |

**Cap changes needed before Stage 1** (they need approval):
- **Judge requests:** the committed Stage 1 configs allow 400 judge requests each. The worst-case check reserves 5 attempts per judged field, so a full-scoring run would stop after about 11 clips. It needs about **1,710 per config** (2 repeats × 171 dev fields × 5).
- **P1 tokens:** the token cap (1.05 M) is ample at the measured rate.
- **Timeout:** the gateway's ~100 s ceiling should be noted as a reliability factor for long clips.

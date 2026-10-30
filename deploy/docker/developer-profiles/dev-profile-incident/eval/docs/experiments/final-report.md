# Prompt engineering and direct VLM vs VSS: consolidated evaluation report

> **Status (2026-10-30): final for Stages 0-3.** This report consolidates results that already exist. It made **no new inference or judge call**, and every figure is taken from the stage reports linked below.
> - **Ground truth:** `ground-truth-v1.0` comes from AI-assisted adjudication. It was frozen on the owner's **dataset-level** approval and is **not individually human-verified** ([freeze README](../../ground_truth/freeze/README.md#ground-truth-v10-as-frozen-limitation)). Every accuracy figure is accuracy against that reference.
> - **Matching:** τ = 0.40 (methodology v1.2) is **AI-calibrated, not human-validated**. Eight calibration pairs still await human review.
> - **Held-out set:** the 55 test clips were held out from Stage 2 prompt selection but are **not unseen** (D15, §11).
> - **Production:** the production prompt and `incident-contract-v4` are unchanged. V1 is **not adopted**; adopting it would be a separate decision with a contract bump.
> - **Not yet run:** the cropping-on end-to-end VSS profile (plan §F.2). It is prepared ([plan and proposed budget](e2e-profile-plan.md)) and waits for the owner's budget approval. The optional other-model transfer check and the Stage 1 recovery were not run.
>
> Stage reports: [Stage 0 pilot](stage0-pilot.md) · [Stage 1 baselines](stage1-baselines.md) · [Stage 2 plan](stage2-plan.md) · [Stage 2 prompts](stage2-prompts.md) · [Stage 2a](stage2a-results.md) · [Stage 2b and selection](stage2b-results.md) · [Severity (v1.3)](severity-v1.3.md) · [Failures and recovery](infrastructure-and-recovery.md) · [Stage 3 plan](stage3-plan.md) · [Stage 3 results](stage3-results.md) · [decision record D9-D15](../../../.docs/mvp2/experiment-decision-record.md)

## 1. Research questions and answers

| Question | Answer | Evidence |
|---|---|---|
| **RQ1:** does iterative prompt engineering improve VSS structured incident extraction? | **On dev, one prompt (V1) helped. On the held-out clips the gain was not confirmed.** V1 minus base inside VSS is ΔI +0.051 [+0.013, +0.089] on dev but +0.019 [−0.015, +0.055] on test: the same direction, about a third of the size, with an interval that includes zero | Stage 2a §3; Stage 3 C3−C2 |
| **RQ2:** how does the best dev-selected VSS configuration compare with a fixed direct-VLM baseline? | **No difference was detected.** C3−C1 is ΔI +0.012 [−0.019, +0.044] = (C3−C4) +0.023 [−0.003, +0.050] plus (C4−C1) −0.011 [−0.045, +0.024]. At equal prompts, VSS minus direct is −0.007 [−0.036, +0.024] (base) and +0.023 [−0.003, +0.050] (V1) | Stage 3 §3 |
| Is VSS slower or less reliable than calling the VLM directly? | **No measurable difference** with crops, RP1 and persistence off: about 0.01 s median overhead in Stage 3 (about 0.1-0.2 s in earlier stages), and gateway failures split evenly between the arms | Stages 0, 1 and 3 |

**Conclusions, stated at the strength the data support:**
1. Under identical requests, today's VSS reproduces direct-VLM extraction quality, reliability and latency. That is a **parity** result, not evidence of an architectural extraction advantage: VSS adds nothing before extraction.
2. Prompt engineering produced one dev-credible improvement (V1, a severity-rubric block). It **did not replicate as a statistically clear gain** on the 55 test clips, and in the direct arm it regressed the description score.
3. The largest sources of uncertainty are run-to-run non-determinism at temperature 0, small samples (25 dev and 55 test clips) and the shared gateway's timeouts and rate limits.

## 2. Timeline

| Date (2026) | Step | Outcome |
|---|---|---|
| 10-27 | Plan approved; D9 v2 selection rule pre-registered before any Stage 2 output; Stage 0 pilot | 10 P1 calls, infrastructure only, arms in parity |
| 10-28 | `ground-truth-v1.0` frozen (AI-assisted, dataset-level approval); Stage 1 baselines on dev; methodology v1.2 (τ 0.40) | 34 of 100 video-runs lost to gateway 429s and 524s; arms in parity |
| 10-28 to 10-29 | Stage 2a: VSS baseline and V1-V7 on dev | V1 selected by D9 v2; all seven qualify for V8 |
| 10-29 | Stage 2b: V8 combined with a fresh baseline; final selection V1 (owner-approved) | V8 qualifies, not selected |
| 10-29 to 10-30 | Stage 3: C1-C4 on the 55 test clips, run once, automated supervisor | No ΔI comparison excludes zero; audit passed |

## 3. Method and configurations

| Item | Value |
|---|---|
| Model | `nvidia/cosmos-3-super-reasoner` throughout, via the sponsor's Switchyard gateway; `contracts/inference.json` P1 settings (temperature 0, max_tokens 16,384, 64 frames requested; Super samples about 24) |
| Output contract | `incident-contract-v4`, strict `response_format`, one validator and one scorer for both arms |
| Direct arm | Harness → gateway `/v1/chat/completions` |
| VSS arm | Harness → a **local** experiment agent `POST /api/v1/incidents/{id}/analyze` (no Supabase, database or R2 variables, `persisted: false`), crops off, RP1 skipped. Never the shared VM agent |
| Request parity | Same P1 body at a given prompt in both arms, apart from the agent's `stream: false` (Stage 3 preflight: C1 = C2 sha `807e1de48734`, C3 = C4 `4e1a89932ebd`) |
| Judge / embedder | `nvidia/nemotron-3-nano-30b-a3b` (≤ 1,500 output tokens) / MiniLM-L6-v2 (local) |
| Methodology | v1.1 (Stage 1 as run) → **v1.2** (τ = 0.40; Stage 1 re-matched offline) → v1.3 adds severity MAE as reporting only |
| Split | `split-v2`: 25 dev clips (5 per category) / 55 test clips (10-13 per category) |
| Repeats | 2 on dev (Stages 1-2), **1 on test** (owner, 2026-10-29) |
| Order | D10: interleaved per clip, seeded (20261027) |
| Failures | `retry-v2` inside a run; `recovery-v1` afterwards on infrastructure failures only (timeouts, 429s, host suspend, DNS, expired URLs). Invalid model outputs are model misses and never retried |
| Selection rule (D9 v2) | ΔI = equal-weight mean of the incident-field, entity-F1 and object-F1 differences against the concurrent VSS baseline, paired per clip, 95% video-cluster bootstrap. Needs ΔI ≥ +0.02 and guardrails G1 (valid runs ≥ baseline − 1), G2 (no score with point ≤ −0.05 and CI upper bound < 0), G3 (same clips, repeats, model, ground truth, split). Dev only |

**Prompts** (all in the append-only registry `contracts/experiments/registry.json`; each is `p1-v4-base` plus one block drawn from `annotation-guidelines-v1.0`):

| Id | Change | SHA-256 |
|---|---|---|
| `p1-v4-base` | The production prompt, byte-identical | `409ed9b3187a…` |
| V1 `p1-v4-e01-severity` | Severity decision rules (observed harm, visible indicators per level) | `004746ea7d19…` |
| V2 `p1-v4-e02-entities` | Significant entities only | registry |
| V3 `p1-v4-e03-instruments` | Instrument classification (hand-held rule, threat) | registry |
| V4 `p1-v4-e04-assets` | Asset relevance (no background objects) | registry |
| V5 `p1-v4-e05-descriptions` | Description completeness and consistency | registry |
| V6 `p1-v4-e06-boundaries` | Incident start and end | registry |
| V7 `p1-v4-e07-checklist` | Structured self-check | registry |
| V8 `p1-v4-e08-combined` | V1-V7 blocks combined unchanged (rule fixed before any Stage 2 output) | `9c21fc60f39c…` |

**Stage 3 configurations:** C1 direct + base; C2 VSS + base; C3 VSS + V1; C4 direct + V1. Harness `820591008`, manifest sha `6bf0650f101d`.

## 4. Stage 1: baselines on dev (direct C1 vs VSS C2, base prompt)

- **Reliability:** 34 of 100 video-runs produced no model output (21 rate-limited, 13 timeouts; a host suspend caused a third of the failures). Model-output rate: C1 0.68, C2 0.64. Two invalid outputs in C2.
- **Incident fields** (conditional; C1 n 34, C2 n 32): type 0.971 / 0.906; severity exact 0.147 / 0.250; start 0.647 / 0.688; end 0.471 / 0.500; description 0.265 / 0.469.
- **Severity:** over-rated in both arms (signed error C1 +0.18, C2 +0.53). Ground-truth level 3 was predicted as 4 or 5 in **24 of 38** outputs. This motivated V1.
- **Items:** at the pre-registered τ = 0.75, item F1 was at the floor (entities 0.011 / 0.014). This was a measurement-validity finding: MiniLM similarity between equivalent descriptions rarely reaches 0.75. Methodology v1.2 set τ = 0.40 from an AI-labelled calibration on dev. Re-matched offline (no new calls): entity F1 0.469 / 0.426, instrument F1 0.294 / 0.296, asset F1 0.367 / 0.392.
- **Parity (C2−C1, 19 paired clips):** five of six incident fields in parity. **Description +0.184 [+0.026, +0.368]** and, under v1.2, **entity F1 −0.119 [−0.258, −0.007]** excluded zero although the requests were identical. Investigation found upstream run-to-run variation (C2's description pass agreed between its own two repeats on only 5 of 10 clips). D9 ΔI C2−C1: −0.030 [−0.117, +0.036].
- **Latency** (P1, p50 / p95): C1 37.8 / 73.1 s; C2 44.7 / 92.8 s; VSS overhead about 0.2 s. The arms ran interleaved under a fluctuating gateway, so the latency gap is not a pipeline effect.

**Lesson carried forward:** with identical requests, single per-score intervals can exclude zero by run-to-run variation alone. Later stages therefore lean on the pre-registered ΔI rather than on individual score intervals.

## 5. Stage 2: VSS prompt engineering on dev

### 5.1 Every version (D9 v2 against its own interleaved VSS baseline, recovery-adjusted)

| Version | Stage | ΔI [95% CI] | ΔI8 | Incident | Entity F1 | Object F1 | ≥ +0.02 | Guardrails | Result |
|---|---|---|---|---|---|---|---|---|---|
| **V1 severity** | 2a | **+0.051 [+0.013, +0.089]** | +0.034 | +0.028 | +0.077 | +0.047 | yes | pass | **Selected** |
| V4 assets | 2a | +0.029 [−0.008, +0.065] | +0.017 | +0.012 | +0.040 | +0.036 | yes | pass | Not selected |
| V3 instruments | 2a | +0.025 [−0.019, +0.069] | +0.013 | +0.008 | +0.056 | +0.010 | yes | pass | Not selected |
| V8 combined | 2b | +0.022 [−0.025, +0.071] | +0.026 | +0.036 | −0.010 | +0.039 | yes | pass | Not selected |
| V2 entities | 2a | +0.015 [−0.022, +0.051] | −0.006 | −0.016 | +0.042 | +0.018 | no | pass | Below bar |
| V7 checklist | 2a | +0.009 [−0.031, +0.050] | +0.019 | +0.028 | −0.025 | +0.025 | no | pass | Below bar |
| V6 boundaries | 2a | +0.009 [−0.029, +0.048] | +0.009 | +0.012 | −0.004 | +0.020 | no | pass | Below bar |
| V5 descriptions | 2a | +0.003 [−0.044, +0.047] | −0.003 | −0.008 | +0.014 | +0.003 | no | pass | Below bar |

- **Only V1's interval excludes zero.** Every other gain, V8's included, is within noise on 25 clips. No version regressed under G2. The original-run view gives the same selection (V1 +0.054).
- **Other credible changes (adjusted):** V1 object F1 +0.047 [+0.014, +0.084]; V7 severity exact +0.16 [+0.04, +0.30]; V8 asset F1 +0.059 [+0.011, +0.115].
- **V8 against V1** (cross-stage, descriptive, never interleaved): V8 − V1 −0.016 [−0.054, +0.021]. Combining the other six blocks bought no measurable gain. Baseline drift between the stages was +0.012 [−0.021, +0.048].
- **Description** dropped slightly under most variants (−0.04 to −0.10 on dev), with every interval including zero. This foreshadows the Stage 3 direct-arm regression.

### 5.2 Severity on dev (v1.3, reporting only)

| | MAE | Signed error | Exact | Within ±1 | Paired MAE Δ vs baseline |
|---|---|---|---|---|---|
| Stage 2a baseline | 1.082 | +0.184 | 0.204 | 0.714 | – |
| **V1** | **0.860** | +0.420 | 0.260 | **0.880** | **−0.220 [−0.380, −0.080]** |
| V7 | 0.857 | +0.204 | 0.367 | 0.775 | −0.220 [−0.420, −0.020] |
| V8 (vs baseline-b 0.898) | 0.960 | +0.200 | 0.280 | 0.760 | +0.060 [−0.140, +0.260] |

V1 reduced MAE by cutting under-ratings (16 → 9) and large misses, **not** by reducing the over-rating it targeted (signed error +0.18 → +0.42; difference +0.22 [−0.04, +0.52]). The baseline's bias itself moved between runs (Stage 1 C2 +0.53, Stage 2a +0.18, Stage 2b +0.16).

### 5.3 Stage 2 items and fields (dev, recovery-adjusted where available)

- **Assets:** precision is the main item weakness (baseline: 196 false positives against 40 true positives). V3, V4, V6 and V7 roughly halved the false positives with recall held.
- **Instruments:** 11 dev clips carry instruments; results are descriptive.
- **Type:** V1 0.980 against the baseline's 0.896 (conditional).
- **Selection:** **V1 `p1-v4-e01-severity`**, by D9 v2 (highest ΔI; next best V4 is 0.022 behind, outside the 0.01 tie window). Approved by the owner on 2026-10-29.

## 6. Stage 3: held-out results (55 test clips, 1 repeat, 220 video-runs)

Recovery-adjusted view is primary; the original-run view is in [stage3-results.md](stage3-results.md) and changes no conclusion.

### 6.1 The four paired comparisons (D9 v2 ΔI; 95% video-cluster bootstrap)

| Comparison | Measures | ΔI [95% CI] | Incident | Entity F1 | Object F1 | Excluding 3 pilot clips (52) |
|---|---|---|---|---|---|---|
| C2−C1 | VSS − direct, base prompt | −0.007 [−0.036, +0.024] | −0.004 | +0.004 | −0.021 | −0.007 [−0.037, +0.025] |
| **C3−C2** | **V1 effect inside VSS (RQ1)** | **+0.019 [−0.015, +0.055]** | +0.026 | −0.007 | +0.040 | +0.016 [−0.019, +0.053] |
| C4−C1 | V1 effect, direct arm | −0.011 [−0.045, +0.024] | +0.004 | −0.037 | −0.001 | −0.015 [−0.051, +0.022] |
| **C3−C4** | **VSS − direct, V1 (RQ2 attributed)** | **+0.023 [−0.003, +0.050]** | +0.022 | +0.027 | +0.020 | +0.023 [−0.005, +0.052] |
| C3−C1 | = (C3−C4) + (C4−C1) | +0.012 [−0.019, +0.044] | +0.022 | −0.005 | +0.019 | +0.009 [−0.023, +0.042] |

**Per-score intervals that exclude zero** (about 40 per-score intervals in total, none pre-registered as primary): C3−C2 end-time +0.074 [+0.018, +0.148]; C3−C1 end-time +0.073 [+0.018, +0.145]; **C4−C1 description −0.130 [−0.245, −0.018]** (guardrail G2, informational on test). Nothing is selected on test.

### 6.2 Incident fields (conditional accuracy)

| Field | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| Type | 0.836 | 0.815 | 0.836 | 0.852 |
| Severity exact | 0.255 | 0.278 | 0.273 | 0.315 |
| Start ±5 s | 0.691 | 0.722 | 0.746 | 0.704 |
| End ±5 s | 0.582 | 0.593 | 0.654 | 0.630 |
| Duration | 0.436 | 0.444 | 0.509 | 0.481 |
| Description | 0.364 | 0.333 | 0.327 | 0.222 |
| n (conditional / attempted) | 55 / 55 | 54 / 55 | 55 / 55 | 54 / 55 |

### 6.3 Severity (v1.3, reporting only)

| Config | Valid | MAE | Signed error | Exact | Within ±1 |
|---|---|---|---|---|---|
| C1 | 55 | 0.927 | −0.055 | 0.255 | 0.836 |
| C2 | 53 | 0.868 | +0.075 | 0.283 | 0.868 |
| C3 | 55 | 0.873 | 0.000 | 0.273 | 0.873 |
| C4 | 53 | 0.849 | −0.019 | 0.321 | 0.849 |

Paired MAE: C3−C2 −0.038 [−0.189, +0.113]; C4−C1 −0.075 [−0.264, +0.113]. On test the base prompt was **not** over-rating (signed error near zero), so the problem V1 was written for was largely absent. (C2 and C4 have 54 conditional outputs but 53 valid severities: the contract-invalid output on Burglary020 counts as a model miss in the field table and as no valid severity here.)

### 6.4 Items (pooled P / R / F1)

| Config | Entities | Instruments (TP) | Assets |
|---|---|---|---|
| C1 | 0.376 / 0.672 / 0.482 | 0.059 / 0.071 / 0.065 (1) | 0.184 / 0.627 / 0.285 |
| C2 | 0.395 / 0.647 / 0.490 | 0.154 / 0.182 / 0.167 (2) | 0.132 / 0.642 / 0.219 |
| C3 | 0.372 / 0.588 / 0.456 | 0.214 / 0.214 / 0.214 (3) | 0.190 / 0.657 / 0.294 |
| C4 | 0.339 / 0.539 / 0.416 | 0.235 / 0.308 / 0.267 (4) | 0.182 / 0.636 / 0.283 |

The dev pattern holds: entities and assets are over-listed (low precision, moderate-to-high recall), instruments are rarely found. V1 trades some entity recall for fewer asset false positives. Instruments (11-14 ground-truth items in scored clips) are too few for conclusions.

### 6.5 Per category (ΔI, 10-13 clips each; descriptive)

| Comparison | Animal attack | Assault | Burglary | Explosion | Road accident |
|---|---|---|---|---|---|
| C2−C1 | −0.009 | −0.058 | +0.011 | +0.007 | +0.003 |
| C3−C2 | −0.003 | −0.008 | +0.059 | +0.007 | +0.015 |
| C4−C1 | +0.004 | −0.071 | +0.008 | −0.021 | +0.005 |
| C3−C4 | −0.017 | +0.010 | +0.066 | +0.035 | +0.013 |

V1's gains concentrate in Burglary on both dev (+0.079) and test (+0.059 in VSS); Assault, a dev gain for V1 (+0.085), is flat or negative on test.

## 7. Latency

**Inference latency (P1 only, seconds, p50 / p95)** — the shared gateway's load varies between runs, so compare within a stage only:

| Stage | Direct | VSS |
|---|---|---|
| Stage 0 (5 clips) | 16.7-66.9 per call | 13.4-65.8 per call |
| Stage 1 | 37.8 / 73.1 | 44.7 / 92.8 |
| Stage 2a baseline / V1 | – | 28.2 / 68.9 · 28.5 / 69.0 |
| Stage 3 C1 / C4 (direct), C2 / C3 (VSS) | 22.67 / 59.47 · 21.67 / 64.09 | 21.62 / 65.51 · 20.26 / 62.09 |

**VSS overhead** (`/analyze` end-to-end minus the agent's own P1 time), crops, RP1 and persistence off: about 0.1 s (Stage 0), 0.2 s (Stage 1), **0.01 s p50 / ≤ 0.05 s p95 (Stage 3)**. Prompt length has no measurable latency effect (V8 is +16% prompt tokens).

**End-to-end pipeline latency with cropping on** has **not been measured**. The plan's separate profile (C2 and C3 with crops on, 15 test clips) is prepared ([plan](e2e-profile-plan.md)) but waits for the owner's budget approval; its figures will be reported in a separate table and never mixed with the inference figures above.

## 8. Reliability

| Stage | Video-runs | No model output (original) | Invalid outputs | Recovered | Main causes |
|---|---|---|---|---|---|
| Stage 0 | 10 | 1 | 0 | – (pilot) | HTTP 524 |
| Stage 1 | 100 | 34 (C1 16, C2 18) | 2 | not run (out of scope) | 429 capacity (21), 524 (13); host suspend |
| Stage 2a | 400 | 7 | 3 | 7 of 7 | 524, DNS outage, expired signed URL after a suspend |
| Stage 2b | 100 | 1 | 1 | 1 of 1 | 524 |
| Stage 3 | 220 | 6 (3 per arm) | 2 (Burglary020, C2 and C4) | 4 of 6 | 524 only |

- **No arm effect:** in Stage 3 the six timeouts split three and three between the arms; the two invalid outputs fell on one clip under different prompts and arms.
- **The gateway's about 100 s ceiling** (Cloudflare 524) is the main failure cause. Stage 3's two unrecovered clips (Assault019, Burglary009, both about 85 s against a 42 s median) timed out in both arms and on all three recovery attempts.
- **Retries:** retry-v2 added 5-13% attempts in Stage 2 and 11% in Stage 3.
- Original and recovery-adjusted reliability are always reported separately; originals are never edited.

## 9. Usage against the approved caps

| Stage | P1 attempts (cap) | P1 tokens | Judge calls (cap) | Judge tokens |
|---|---|---|---|---|
| Stage 0 | 10 (10) | 83,479 metered; 118,479 under the cap rule | 9 + 1 probe (50) | 4,726 |
| Stage 1 | 100 (100) | 626,259 metered | 72 (3,420) | 36,254 |
| Stage 2a | 451 + 11 recovery (1,200) | 3,633,327 + 52,944 | 1,603 + 26 | 612,276 + 10,624 |
| Stage 2b | 105 + 1 recovery (300) | 955,177 | 418 (3,420) | 158,272 |
| Stage 3 | 247 + 12 recovery (660 + 180) | 1,979,469 + 31,015 (23.1 M + 6.3 M) | 845 + 20 (6,720 + 2,740) | 335,143 + 6,999 |

- **No stage reached a cap**, and no stop rule fired except the planned session limits and the owner's laptop-close stops (all at a checkpoint).
- **Unrecorded usage (disclosed):** on 2026-10-29 at 13:04 UTC a judge `ReadTimeout` ended a Stage 3 session before C4 Assault012 was checkpointed. Its P1 call (about 9 k tokens) and the judge calls already made for it (fewer than 10) were discarded without a cost-log line; the run was redone. It does not change any cap outcome.
- **Cost:** the gateway records $0 per token. That is the project's gateway charge only; the sponsor's GPU and infrastructure cost is real and not visible to the project.

## 10. Qualitative examples

| Stage | Clip | Comparison | ΔI | What changed |
|---|---|---|---|---|
| 2a (dev) | Assault007 | V1 − base | +0.241 | Severity 3 and 2 → 4 and 3 (ground truth 4); entity F1 +0.36 |
| 2a (dev) | Burglary004 | V1 − base | +0.251 | Partly validity: the baseline's repeat 2 was contract-invalid; V1 valid in both repeats |
| 2a (dev) | Explosion002 | V1 − base | −0.058 | Severity 5 and 4 → 4 and 4 (ground truth 3): closer but still over-rated |
| 3 (test) | Animal004 | C3−C2 | +0.367 | Largest V1 gain inside VSS |
| 3 (test) | Burglary020 | C3−C2 / C4−C1 | +0.300 / −0.295 | The base prompt's VSS run and V1's direct run were both contract-invalid on this clip: one clip swinging in opposite directions per arm |
| 3 (test) | Assault026 | C4−C1 | −0.406 | Largest V1 regression in the direct arm |
| 3 (test) | Burglary041 | C2−C1 | +0.333 | Identical requests, large per-clip swing: run-to-run variation |

Per-clip swings of ±0.3 under identical requests (C2−C1) are as large as the largest prompt effects, which is why single clips are illustrative only.

## 11. Prompt vs pipeline attribution and held-out exposure

**Attribution (plan §F.1):**
- **Pipeline effect** (C2−C1, C3−C4) is VSS minus direct at the same prompt. Today's VSS adds nothing before extraction and sends the same request, so any non-zero value is a pipeline, transport, reliability or run-to-run effect, **never an architectural extraction advantage**. With one test repeat, run-to-run variation cannot be separated from it.
- **Prompt effect** (C3−C2, C4−C1) is measured within one arm. V1's effect differed in sign between the arms on test (+0.019 VSS, −0.011 direct), both within noise; since the requests are identical across arms, that difference is itself run-to-run variation.
- **C3−C1** is only reported as the sum (C3−C4) + (C4−C1).

**Held-out exposure (D15):**

| Exposure | Effect |
|---|---|
| The 55 test clips were in the 2026-10-02 benchmark (contract v2, pre-correction ground truth) | Per-video results were visible to the team before this workstream |
| Three test clips (Animal003, Assault018, Burglary005) shaped the v3 timeline wording behind `p1-v4-base` | The base prompt may be slightly fitted to the test set |
| Box-accuracy and RP1 pilot clips are unrecorded | Possible further exposure |
| The AI-assisted ground-truth correction viewed frames of test clips | Labels were revised on test clips, independently of any VSS prediction or score |
| Dev clips were few-shot examples in the retired P1-v1 prompt | Stronger exposure; kept as dev |

- **Bias direction:** any bias favours the base prompt, so prompt gains on test are conservative (possibly understated), not inflated. Equal-prompt pipeline comparisons share the same exposure on both sides.
- **Sensitivity:** excluding the three pilot clips (52 clips, still not unseen) changes no conclusion (§6.1).
- **Absolute accuracy** may be optimistic for the base prompt and is not comparable with the 2026-10-02 figures.

## 12. Negative findings

1. **V1's dev gain did not replicate clearly on test** (ΔI +0.051 credible on dev → +0.019 within noise in VSS, −0.011 in the direct arm).
2. **V1 did not fix the over-rating it targeted.** On dev it lowered MAE through fewer under-ratings while the signed error rose; on test the baseline was not over-rating at all.
3. **V1 regressed the description score in the direct arm** on test (−0.130 [−0.245, −0.018]); description fell slightly under most variants on dev too.
4. **Six of eight prompt versions did not show a credible gain**, and four fell below the +0.02 bar. Combining all seven blocks (V8) was not better than V1 alone.
5. **The pre-registered τ = 0.75 made item metrics meaningless** (Stage 1 F1 ≈ 0.01); τ had to be recalibrated (AI-calibrated, not human-validated).
6. **Identical requests produce different outputs:** Stage 1 parity found two per-score intervals excluding zero (description, entity F1) with no pipeline difference, and per-clip swings reach ±0.3.
7. **The shared gateway lost 34% of Stage 1 video-runs** and set a hard ~100 s ceiling that two Stage 3 clips never got under.
8. **No VSS advantage** was found at either prompt, which is the expected result given that VSS currently sends the same request as the direct call.

## 13. Limitations

- **Ground truth:** AI-assisted adjudication frozen on dataset-level approval; not individually human-verified. The plan's human review steps (blind review of unchanged incidents, a second reviewer with κ) were replaced by owner-authorised AI-assisted adjudication.
- **Matching:** τ = 0.40 is AI-calibrated on dev, not human-validated; item scores depend on it, and dev also served for selection.
- **Power:** 25 dev clips × 2 repeats and 55 test clips × 1 repeat. ΔI intervals are about ±0.035 on test, so effects below about 0.03-0.04 are not detectable; instruments rest on 10-15 paired clips.
- **Multiplicity:** about 40 per-score intervals per stage; a few excluding zero are expected by chance. Only ΔI was pre-registered.
- **Non-determinism:** temperature-0 outputs vary between calls, and one test repeat cannot separate this from pipeline effects.
- **Exposure:** the test clips are not unseen (§11).
- **Scope:** one model (Cosmos 3 Super), crops off, a local agent rather than the production VM; the cropping-on end-to-end profile, the other-model transfer check and the Stage 1 recovery were not run. Stage 1's figures include its unrecovered failures.
- **Comparability:** V8 and V1 ran in different stages with different baselines; Stage 1 used methodology v1.1 (re-matched under v1.2 offline).

## 14. Selected prompt and status

- **Selected on dev:** V1 `p1-v4-e01-severity` (SHA-256 `004746ea7d19…`), by the pre-registered D9 v2 rule: the highest ΔI (+0.051 [+0.013, +0.089]) and the only version whose interval excluded zero, with every guardrail passing. Owner-approved on 2026-10-29.
- **Held-out check:** not confirmed as a clear gain (§6).
- **Not adopted:** the production prompt and contract are unchanged. Nothing was revised, rerun or re-selected in response to the test results; Stage 3 ran once.
- **For the FYP presentation:** the defensible claims are (1) a pre-registered, auditable prompt-engineering process with all versions and negative results reported; (2) VSS parity with direct VLM calls in accuracy, reliability and latency under identical requests; (3) a severity-rubric prompt that helped on dev but did not clearly generalise. Not defensible: "VSS extracts better than a direct VLM", "prompt engineering improved held-out accuracy", or any claim about unseen footage.

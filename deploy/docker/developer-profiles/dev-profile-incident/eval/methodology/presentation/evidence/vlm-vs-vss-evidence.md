# Direct VLM vs full VSS: evidence record for the FYP presentation

Generated 2026-11-05. Read-only retrieval: no model, judge or embedding call was made, and no repository or data file was changed. No `c3-*` run directory was read, so **no V2 held-out result appears here**.

**Labels used below**
- **PUBLISHED:** quoted from a project document or report JSON.
- **RAW-VERIFIED:** checked against the raw report JSON or results files.
- **DERIVED:** computed for this record from sealed dev run data. It exists in no project document, it was not a pre-registered test, and it needs the owner's review before it goes on a slide.
- **UNAVAILABLE:** searched for and not found.

Path roots:
- `DOCS` = `/home/hengz/vss-wt-c3e/deploy/docker/developer-profiles/dev-profile-incident/eval/docs/experiments`
- `METH` = `/home/hengz/vss-wt-c3e/deploy/docker/developer-profiles/dev-profile-incident/eval/methodology`
- `RES` = `/home/hengz/video-search-and-summarization/deploy/docker/developer-profiles/dev-profile-incident/eval/eval_data/results`
- `V2` = `/home/hengz/evalv2-data/v2/runs`

## 0. Plain answers

**Which comparison is "the baseline"?**
- The fixed direct-VLM baseline is **C1**: `direct-vlm-baseline` on dev (Stage 1) and `s3-c1-direct-base` on test (Stage 3). Both use `p1-v4-base`.
- It is not the baseline for prompt selection. D9 v2 measures against the concurrent **VSS** baseline, and "The direct-VLM baseline never enters selection" (`.docs/mvp2/experiment-decision-record.md`, line 20).
- The clean direct-vs-VSS contrasts are the equal-prompt ones: **C2−C1** (base prompt) and **C3−C4** (V1 prompt).
- **C3−C1** is "best VSS vs fixed direct baseline". It mixes prompt and pipeline, and the project says it is "never an architecture claim" (`stage3-report.json`, `comparisons["C3-C1"].meaning`).

**Did V1's VSS arm contain captions, grounding or zoom?** No, not in anything that was scored.

| Component | V1 Stage 0, 1, 3 (scored) | V1 end-to-end profile (unscored) | V2 Track B (C1b) |
|---|---|---|---|
| Captions | **Absent.** No `caption` or `zoom` string in `incident_report_gen.py` at commits `7df6f3159` or `820591008` | **Absent** (none at `99f3b1cc8`, including `api/incident_analyze.py`) | **On** for clips over 30 s (20 s windows, 2 s overlap, 32 frames, inline base64). Added to P1 as an extra user message |
| Grounding and crops | **Off** (`skip_crops: true`) | **On**, after P1, capped at 40 calls per request. Cannot change extraction | **On** after P1, always on Super. Caps 40 crop calls |
| Zoom | **Absent** | **Absent** | **On** (`zoom_names: true`), cap 80 calls. Changes item names and descriptions only |
| RP1 | Agent: **off** (`skip_rp1: true`). **But see the note below** | Off, and none generated (0 of 15 per config) | Off (`skip_rp1: true`; `report_text` null) |
| Tracking, set-of-marks, blur | Absent or off | Absent or off | Off (`agent.jsonl` flags) |

So your belief is right, and it understates the case: Stage 3's VSS arm had crops off, and captions and zoom did not exist in that code. VSS in V1 was a transport wrapper around the same P1 request. The project says the same: "today's VSS adds nothing before extraction" (`stage1-baselines.md`, Pipeline parity; `final-report.md` §1, §11).

**RP1 note (new finding, not disclosed in the docs).** "RP1 skipped" is true of the agent only.
- All four Stage 3 `results.json` files hold an `rp1_report` with `ok: true` for all 53 core-valid runs per config (the other 2 are `skipped`). Model: `nvidia/nemotron-3-nano-30b-a3b`. Stage 1 has the same: 34 of 50 (C1) and 30 of 50 (C2).
- Cause: `experiment_runner.vss_call` sends `skip_rp1: True` to the agent, but the shared harness function `scripts/eval_run.py::run_one_video` still calls `generate_rp1_report` when `incident_only` is false. It does this in **both arms**, in the harness rather than the agent.
- Effect on results: none on extraction scores. The call comes after `eval_gt.run_evaluation`, reads only the P1 JSON, and is the same in both arms. It is not in the `usage` token counts or the latency figures.
- Do not say "no RP1 call was made in Stage 3". Say "the VSS agent's RP1 stage was skipped".

**Agent commit caveat.** The V1 result files record `harness_git_sha`, not an agent commit. `start-experiment-agent.sh` runs the agent from the same checkout, so "agent = harness commit" is an inference. V2 records the agent directly (`V2/c1b/agent.jsonl`: `acbf892ba`).

**Summary of what each comparison can support**

| # | Comparison | Paths really differ in | Accuracy scored? | Result |
|---|---|---|---|---|
| 0 | V1 Stage 0 pilot | Transport only | No (infrastructure only) | Parity check |
| 1 | V1 Stage 1, dev, C2−C1 | Transport only | Yes | ΔI −0.030 [−0.117, +0.036] |
| 2 | V1 Stage 3, test, C2−C1 and C3−C4 | Transport only | Yes | −0.007 [−0.036, +0.024]; +0.023 [−0.003, +0.050] |
| 2b | V1 Stage 3, C3−C1 | Transport and prompt | Yes | +0.012 [−0.019, +0.044] |
| 3 | V1 end-to-end profile | **No direct arm exists** | No | Cropping cost only |
| 4 | V2 dev, Track B vs Track A | Captions, grounding, zoom, agent retry | Yes | No published paired estimate; DERIVED in §5 |

Only #4 tests a VSS pipeline that does anything before or after extraction. It is 25 dev clips, one Track B repeat, and it is the only such evidence in this record.

## 1. V1 Stage 0 pilot (for completeness)

- **Status:** infrastructure only, on candidate ground truth. "nothing here is an accuracy result".
- **Setup:** `nvidia/cosmos-3-super-reasoner`; `p1-v4-base` (`409ed9b3187a…`); 5 dev clips × 1 repeat per arm; no crops; no agent RP1.
- **Outputs:** direct 5/5; VSS 4/5 (HTTP 524 on Assault007, surfaced by the agent as 500).
- **Parity:** identical prompt token counts (6,479 / 6,468 / 15,530 / 6,442). On the 4 clips scored in both arms, window and severity matched on 4 of 4, type on 3 of 4.
- **VSS overhead:** about 0.1 s.
- **Source:** `DOCS/stage0-pilot.md`, "Requests and failures", "Latency", "Did the arms behave as intended?". Not raw-verified.

Stage 2 (`s2-*`) has no direct arm. The 2026-10-02 benchmark has no VSS arm. Neither is a direct-vs-VSS comparison.

## 2. V1 Stage 1: direct C1 vs VSS C2 on dev

### Setup

| Item | Value | Source |
|---|---|---|
| Model | `nvidia/cosmos-3-super-reasoner` (both) | `RES/experiments/{direct-vlm-baseline,vss-baseline}/20261028T031009Z/results.json`, key `model` |
| Prompt | `p1-v4-base`, SHA-256 `409ed9b3187a56be082bb2542abb243cc13762fdcae7739206d11455064cc4a8` | key `prompt.sha256` |
| Contract | `incident-contract-v4`; schema `a13062782013…` | keys `contract_version`, `schema_sha256` |
| Dataset | `split-v2` dev, 25 clips × 2 repeats = 50 video-runs per arm; `ground-truth-v1.0`, records `391fcd27…` | `stage1-baselines.md` Setup |
| Inference | temperature 0, `max_tokens` 16,384, `num_frames` 64 | key `inference` |
| Methodology | v1.1 as run (τ 0.75); re-matched offline under v1.2 (τ 0.40) | key `methodology`; `rematched-v1.2-t0.40-20261028T141652Z.json` (C1), `…T141656Z.json` (C2) |
| Harness | `7df6f3159` | key `harness_git_sha` |
| Judge, embedder | `nvidia/nemotron-3-nano-30b-a3b`; MiniLM-L6-v2 | `stage1-baselines.md` Setup |

**What differs:** only the path. Direct is harness → gateway. VSS is harness → local experiment agent `/analyze` → gateway. Captions, zoom and crops are absent on both sides, and the agent's RP1 is off. Equal P1 prompt tokens on all 19 clips with output in both arms. **No retry policy** was pinned in Stage 1 (`pipeline` has no `retry_policy`; retry-v2 came later), and recovery was not run.

### Reliability (RAW-VERIFIED, `reliability` and `videos[].outcome`)

| | C1 direct | C2 VSS |
|---|---|---|
| Attempted | 50 | 50 |
| Scored (valid) | 34 | 30 |
| Contract-invalid | 0 | 2 |
| Rate-limited | 10 | 11, stored as `http_error` (doc reclassifies them from the error text) |
| Timeout | 6 | 7 |
| Model-output rate / valid rate | 0.68 / 0.68 | 0.64 / 0.60 |

34 of 100 video-runs produced no output, and a host suspend accounts for about a third of the failures.

### Incident fields (PUBLISHED, `stage1-baselines.md` "Incident fields")

| Field | C1 n | C1 conditional | C1 end-to-end (n=50) | C2 n | C2 conditional | C2 end-to-end (n=50) |
|---|---|---|---|---|---|---|
| type | 34 | 0.971 [0.912, 1.000] | 0.660 [0.520, 0.780] | 32 | 0.906 [0.781, 1.000] | 0.580 [0.440, 0.720] |
| severity exact | 34 | 0.147 [0.029, 0.265] | 0.100 [0.020, 0.180] | 32 | 0.250 [0.094, 0.406] | 0.160 [0.060, 0.260] |
| start ±5 s | 34 | 0.647 [0.500, 0.794] | 0.440 [0.300, 0.580] | 32 | 0.688 [0.531, 0.844] | 0.440 [0.300, 0.580] |
| end ±5 s | 34 | 0.471 [0.294, 0.647] | 0.320 [0.200, 0.440] | 32 | 0.500 [0.312, 0.688] | 0.320 [0.200, 0.460] |
| duration ±5 s | 34 | 0.324 [0.176, 0.471] | 0.220 [0.100, 0.340] | 32 | 0.375 [0.219, 0.562] | 0.240 [0.120, 0.360] |
| description (judge ≥ 0.5) | 34 | 0.265 [0.118, 0.412] | 0.180 [0.080, 0.300] | 32 | 0.469 [0.312, 0.656] | 0.300 [0.180, 0.420] |

### Severity v1.3 (RAW-VERIFIED, `RES/reports/severity-v1.3/stage1/severity-report-v1.3.json`, `summaries`)

| | Valid / attempted | MAE | Signed | Exact | Within ±1 | Over / under |
|---|---|---|---|---|---|---|
| C1 | 34/50 | 1.118 | +0.176 | 0.147 | 0.735 | 17 / 12 |
| C2 | 30/50 | 0.933 | +0.533 | 0.267 | 0.800 | 17 / 5 |

Paired C2−C1 (18 videos, PUBLISHED, `severity-v1.3.md`): MAE −0.111 [−0.417, +0.167]; signed error +0.222 [−0.250, +0.639]. Neither excludes zero.

### Items, pooled

| Kind | τ | C1 TP/FP/FN | C1 P/R/F1 | C2 TP/FP/FN | C2 P/R/F1 |
|---|---|---|---|---|---|
| entities | 0.75 | 1/102/71 | 0.010/0.014/0.011 | 1/85/54 | 0.012/0.018/0.014 |
| instruments | 0.75 | 1/8/24 | 0.111/0.040/0.059 | 0/9/18 | 0/0/– |
| assets | 0.75 | 2/104/39 | 0.019/0.049/0.027 | 0/107/41 | 0/0/– |
| entities | **0.40** | 41/62/31 | 0.398/0.569/0.469 | 30/56/25 | 0.349/0.545/0.426 |
| instruments | **0.40** | 5/4/20 | 0.556/0.200/0.294 | 4/5/14 | 0.444/0.222/0.296 |
| assets | **0.40** | 27/79/14 | 0.255/0.659/0.367 | 29/78/12 | 0.271/0.707/0.392 |

Source: `stage1-baselines.md`, "Entities, instruments and assets" and "v1.2 final re-matching". Use the τ 0.40 rows; τ 0.75 was at the floor.

### Paired C2−C1 (RAW-VERIFIED by re-running `experiment_selection.compare` on the rematched files)

| Score | Pairs | Doc value | Doc CI | Recomputed CI | Match |
|---|---|---|---|---|---|
| **ΔI** | 19 (entity 18) | −0.030 | [−0.117, +0.036] | −0.0305 [−0.1174, +0.0363] | Yes |
| Incident | 19 | +0.032 | [−0.065, +0.113] | +0.0316 [−0.0650, +0.1133] | Yes |
| Entity F1 | 18 | −0.119 | [−0.258, −0.007] | −0.1190 [−0.2577, −0.0068] | Yes (doc says 19 paired clips; entity is 18) |
| Object F1 | 19 | −0.004 | [−0.073, +0.051] | −0.0041 [−0.0726, +0.0514] | Yes |
| type | 19 | −0.053 | [−0.158, 0.000] | −0.0526 [−0.1765, 0.0000] | **CI differs** |
| severity | 19 | +0.132 | [−0.026, +0.316] | +0.1316 [−0.0278, +0.3235] | **CI differs** |
| start | 19 | −0.053 | [−0.210, +0.105] | −0.0526 [−0.2353, +0.1176] | **CI differs** |
| end | 19 | −0.053 | [−0.158, 0.000] | −0.0526 [−0.1765, 0.0000] | **CI differs** |
| duration | 19 | −0.053 | [−0.158, 0.000] | UNAVAILABLE (`compare` has no duration score) | – |
| description | 19 | +0.184 | [+0.026, +0.368] | +0.1842 [+0.0263, +0.3571] | **CI differs** |
| instruments F1 | 8 | not published | – | −0.0625 [−0.3889, +0.1875] | DERIVED |
| assets F1 | 19 | not published | – | +0.0162 [0.0000, +0.0391] | DERIVED |

- Points all match. The per-field intervals in the doc's "Pipeline parity" table were computed differently from `compare`; I did not establish how. No conclusion changes: description still excludes zero, the others still include it.
- **Significance:** by 95% interval only. V1 reports no p-values (UNAVAILABLE). Description and entity F1 exclude zero, with identical requests. The project attributes them to run-to-run variation, with evidence that C2's description pass agreed between its own repeats on only 5 of 10 clips.
- Under v1.1 (τ 0.75), recomputed from `results.json`: ΔI −0.0053 [−0.0454, +0.0295].
- A standardised effect size is UNAVAILABLE. The effect size used throughout V1 is the paired mean difference.

### Latency and tokens (PUBLISHED, `stage1-baselines.md` "Latency and tokens")

| | P1 n / p50 / p95 s | `/analyze` n / p50 / p95 s | P1 tokens metered | Tokens per metered call |
|---|---|---|---|---|
| C1 | 34 / 37.8 / 73.1 | – | 319,840 | 9,407 |
| C2 | 32 / 44.7 / 92.8 | 32 / 44.9 / 92.9 | 306,419 | 9,576 |

VSS overhead about 0.2 s. The latency gap is not a pipeline effect (interleaved under a fluctuating shared gateway).

## 3. V1 Stage 3: C1, C2, C3, C4 on the 55 test clips

### Setup

| Item | Value | Source |
|---|---|---|
| Model | `nvidia/cosmos-3-super-reasoner` | `eval/experiments/stage3/manifest.json`, `model` |
| Prompts | `p1-v4-base` `409ed9b3187a56be082bb2542abb243cc13762fdcae7739206d11455064cc4a8`; V1 `p1-v4-e01-severity` `004746ea7d193fbba4af4c411c8baa2c7a1c9acfdd9d81fdaee19838024c4138` | manifest `configs` |
| Contract | `incident-contract-v4`; `response_format` `521b89e3e16f…` | manifest `p1_request` |
| Inference | temperature 0, `max_tokens` 16,384, `num_frames` 64 | manifest `p1_request.settings` |
| Dataset | `split-v2` test, 55 clips × **1 repeat** = 220 video-runs; `ground-truth-v1.0`, records `391fcd272bf2…` | manifest `split`, `ground_truth` |
| Methodology | v1.2, τ 0.40; severity under v1.3, reporting only; bootstrap seed 20261027, 10,000 resamples; ±5 s | manifest `methodology` |
| Judge, embedder | `nvidia/nemotron-3-nano-30b-a3b`, `judge-prompt-v1`; MiniLM-L6-v2 | manifest `methodology` |
| Harness, manifest | `820591008`; manifest sha `6bf0650f101d…` | `results.json` `harness_git_sha`; audit JSON |
| Retries | `retry-v2` in every config (backoff 60, 180 s; 2 retries; timeouts and 429s); then `recovery-v1` on infrastructure failures only, invalid outputs never retried | manifest `retry_policy`, `recovery` |

**What differs**
- **C2−C1 and C3−C4 (equal prompt):** the agent hop, `stream: false` (the only body difference; parity hashes C1 = C2 `807e1de48734…`, C3 = C4 `4e1a89932ebd…`, from `DOCS/stage3-plan.md` §2, an offline check not found in the run artifacts), and the agent's bounds check. No captions, grounding, zoom or crops. Agent RP1 off. One repeat, so run-to-run variation cannot be separated from pipeline effects.
- **C3−C2 and C4−C1:** prompt only, within one arm.
- **C3−C1:** prompt and path together.

### Per-config results, recovery-adjusted (primary view; RAW-VERIFIED, `RES/reports/stage3/recovery-adjusted-v1/stage3-report.json`, `configs.*`)

| Config | Outcomes | Valid / attempted | Severity valid | MAE | Signed | Exact | Within ±1 | Entities P/R/F1 (TP/FP/FN) | Instruments P/R/F1 (TP/FP/FN) | Assets P/R/F1 (TP/FP/FN) | Model time p50/p95/mean s | VSS overhead p50/p95 s | P1 tokens/call |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | {scored: 55} | 55/55 | 55 | 0.9273 | -0.0545 | 0.2545 | 0.8364 | 0.376/0.672/0.482 (80/133/39) | 0.059/0.071/0.065 (1/16/13) | 0.184/0.627/0.285 (42/186/25) | 22.67/59.47/28.84 | None/None | 9097 |
| C2 | {contract_invalid: 1, scored: 53, timeout: 1} | 53/55 | 53 | 0.8679 | 0.0755 | 0.283 | 0.8679 | 0.395/0.647/0.490 (75/115/41) | 0.154/0.182/0.167 (2/11/9) | 0.132/0.642/0.219 (43/283/24) | 21.62/65.51/29.89 | 0.01/0.05 | 9043 |
| C3 | {scored: 55} | 55/55 | 55 | 0.8727 | 0.0 | 0.2727 | 0.8727 | 0.372/0.588/0.456 (70/118/49) | 0.214/0.214/0.214 (3/11/11) | 0.190/0.657/0.294 (44/188/23) | 20.26/62.09/25.94 | 0.01/0.03 | 9267 |
| C4 | {contract_invalid: 1, scored: 53, timeout: 1} | 53/55 | 53 | 0.8491 | -0.0189 | 0.3208 | 0.8491 | 0.339/0.539/0.416 (62/121/53) | 0.235/0.308/0.267 (4/13/9) | 0.182/0.636/0.283 (42/189/24) | 21.67/64.09/28.54 | None/None | 9147 |


### Per-config results, original view (`RES/reports/stage3/original/stage3-report.json`, `configs.*`)

| Config | Outcomes | Valid / attempted | Severity valid | MAE | Signed | Exact | Within ±1 | Entities P/R/F1 (TP/FP/FN) | Instruments P/R/F1 (TP/FP/FN) | Assets P/R/F1 (TP/FP/FN) | Model time p50/p95/mean s | VSS overhead p50/p95 s | P1 tokens/call |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | {scored: 53, timeout: 2} | 53/55 | 53 | 0.9057 | -0.0377 | 0.2642 | 0.8491 | 0.409/0.681/0.511 (79/114/37) | 0.059/0.091/0.071 (1/16/10) | 0.181/0.615/0.280 (40/181/25) | 22.67/59.47/28.62 | None/None | 8815 |
| C2 | {contract_invalid: 1, scored: 53, timeout: 1} | 53/55 | 53 | 0.8679 | 0.0755 | 0.283 | 0.8679 | 0.395/0.647/0.490 (75/115/41) | 0.154/0.182/0.167 (2/11/9) | 0.132/0.642/0.219 (43/283/24) | 21.62/65.51/29.89 | 0.01/0.05 | 9043 |
| C3 | {scored: 53, timeout: 2} | 53/55 | 53 | 0.8491 | -0.0566 | 0.283 | 0.8868 | 0.360/0.562/0.439 (63/112/49) | 0.231/0.231/0.231 (3/10/10) | 0.186/0.656/0.290 (42/184/22) | 19.52/62.09/25.66 | 0.01/0.02 | 8985 |
| C4 | {contract_invalid: 1, scored: 53, timeout: 1} | 53/55 | 53 | 0.8491 | -0.0189 | 0.3208 | 0.8491 | 0.339/0.539/0.416 (62/121/53) | 0.235/0.308/0.267 (4/13/9) | 0.182/0.636/0.283 (42/189/24) | 21.67/64.09/28.54 | None/None | 9147 |


### Incident fields (RAW-VERIFIED, `RES/reports/stage3/recovery-adjusted-v1/stage3-report.md` "Incident fields"; counts recomputed from the merged files)

Conditional accuracy [95% CI], then end-to-end (failure = miss).

| Field | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| Type | 0.836 [0.727, 0.927]; e2e 0.836 | 0.815 [0.704, 0.907]; e2e 0.800 | 0.836 [0.727, 0.927]; e2e 0.836 | 0.852 [0.759, 0.944]; e2e 0.836 |
| Severity exact | 0.255 [0.145, 0.382]; e2e 0.255 | 0.278 [0.167, 0.407]; e2e 0.273 | 0.273 [0.164, 0.400]; e2e 0.273 | 0.315 [0.204, 0.444]; e2e 0.309 |
| Start ±5 s | 0.691 [0.564, 0.818]; e2e 0.691 | 0.722 [0.593, 0.833]; e2e 0.709 | 0.746 [0.618, 0.855]; e2e 0.746 | 0.704 [0.574, 0.833]; e2e 0.691 |
| End ±5 s | 0.582 [0.455, 0.709]; e2e 0.582 | 0.593 [0.463, 0.722]; e2e 0.582 | 0.654 [0.527, 0.782]; e2e 0.654 | 0.630 [0.500, 0.759]; e2e 0.618 |
| Duration | 0.436 [0.309, 0.564]; e2e 0.436 | 0.444 [0.315, 0.574]; e2e 0.436 | 0.509 [0.382, 0.636]; e2e 0.509 | 0.481 [0.352, 0.611]; e2e 0.473 |
| Description | 0.364 [0.236, 0.491]; e2e 0.364 | 0.333 [0.204, 0.463]; e2e 0.327 | 0.327 [0.200, 0.455]; e2e 0.327 | 0.222 [0.111, 0.333]; e2e 0.218 |
| n conditional / end-to-end | 55 / 55 | 54 / 55 | 55 / 55 | 54 / 55 |

Timestamp errors in seconds: V1 reports only pass rates at ±5 s, so MAE in seconds is UNAVAILABLE for V1.

### Paired differences, recovery-adjusted (primary; RAW-VERIFIED)

Key: `comparisons["<pair>"].d9.point.<score>`, `.ci95.<score>`, `.pairs.<score>`; severity from `comparisons["<pair>"].severity`. Exact JSON values, 4 decimals.

| Score | C2-C1 | C3-C4 | C3-C1 | C3-C2 | C4-C1 |
|---|---|---|---|---|---|
| ΔI (D9 v2) | -0.0066 [-0.0364, +0.0241] (n=) | +0.0231 [-0.0031, +0.0500] (n=) | +0.0120 [-0.0186, +0.0445] (n=) | +0.0195 [-0.0149, +0.0549] (n=) | -0.0111 [-0.0450, +0.0236] (n=) |
| ΔI8 | -0.0051 [-0.0349, +0.0227] (n=54) | +0.0263 [-0.0071, +0.0613] (n=54) | +0.0178 [-0.0135, +0.0519] (n=55) | +0.0234 [-0.0185, +0.0681] (n=54) | -0.0064 [-0.0412, +0.0278] (n=54) |
| Incident component | -0.0037 [-0.0415, +0.0308] (n=54) | +0.0222 [-0.0255, +0.0692] (n=54) | +0.0218 [-0.0182, +0.0655] (n=55) | +0.0259 [-0.0291, +0.0836] (n=54) | +0.0037 [-0.0385, +0.0473] (n=54) |
| Entity F1 component | +0.0043 [-0.0661, +0.0809] (n=51) | +0.0271 [-0.0261, +0.0820] (n=51) | -0.0047 [-0.0756, +0.0708] (n=52) | -0.0075 [-0.0738, +0.0559] (n=51) | -0.0366 [-0.1114, +0.0403] (n=51) |
| Object F1 component | -0.0205 [-0.0547, +0.0122] (n=51) | +0.0199 [-0.0104, +0.0553] (n=51) | +0.0190 [-0.0266, +0.0681] (n=52) | +0.0399 [-0.0084, +0.0924] (n=51) | -0.0005 [-0.0484, +0.0500] (n=51) |
| Type | -0.0185 [-0.0566, +0.0000] (n=54) | -0.0185 [-0.0909, +0.0377] (n=54) | +0.0000 [-0.0545, +0.0545] (n=55) | +0.0185 [-0.0377, +0.0769] (n=54) | +0.0185 [-0.0377, +0.0909] (n=54) |
| Severity exact | +0.0185 [-0.0566, +0.0962] (n=54) | -0.0370 [-0.1667, +0.0943] (n=54) | +0.0182 [-0.0909, +0.1273] (n=55) | +0.0000 [-0.1296, +0.1273] (n=54) | +0.0741 [-0.0727, +0.2182] (n=54) |
| Start ±5 s | +0.0185 [+0.0000, +0.0566] (n=54) | +0.0370 [-0.0364, +0.1111] (n=54) | +0.0545 [-0.0182, +0.1455] (n=55) | +0.0370 [-0.0545, +0.1296] (n=54) | +0.0185 [-0.0741, +0.1111] (n=54) |
| End ±5 s | +0.0000 [-0.0556, +0.0556] (n=54) | +0.0370 [-0.0364, +0.1111] (n=54) | +0.0727 [+0.0182, +0.1455] (n=55) **excl. 0** | +0.0741 [+0.0182, +0.1481] (n=54) **excl. 0** | +0.0370 [-0.0364, +0.1111] (n=54) |
| Description (judge ≥ 0.5) | -0.0370 [-0.1636, +0.0926] (n=54) | +0.0926 [-0.0182, +0.2037] (n=54) | -0.0364 [-0.1273, +0.0545] (n=55) | +0.0000 [-0.1321, +0.1346] (n=54) | -0.1296 [-0.2453, -0.0185] (n=54) **excl. 0** |
| Entities F1 | +0.0043 [-0.0661, +0.0809] (n=51) | +0.0271 [-0.0261, +0.0820] (n=51) | -0.0047 [-0.0756, +0.0708] (n=52) | -0.0075 [-0.0738, +0.0559] (n=51) | -0.0366 [-0.1114, +0.0403] (n=51) |
| Instruments F1 | +0.0513 [+0.0000, +0.1667] (n=13) | -0.0214 [-0.0692, +0.0000] (n=14) | +0.1026 [+0.0000, +0.2564] (n=13) | +0.0513 [+0.0000, +0.1667] (n=13) | +0.1361 [+0.0000, +0.2970] (n=12) |
| Assets F1 | -0.0205 [-0.0495, +0.0065] (n=51) | +0.0166 [-0.0103, +0.0477] (n=51) | +0.0190 [-0.0220, +0.0656] (n=52) | +0.0399 [-0.0105, +0.0968] (n=51) | +0.0027 [-0.0374, +0.0444] (n=51) |
| Severity MAE difference (v1.3, lower better) | -0.0189 [-0.1132, +0.0755] (n=53) | +0.0000 [-0.1887, +0.1698] (n=53) | -0.0545 [-0.1818, +0.0727] (n=55) | -0.0377 [-0.1887, +0.1132] (n=53) | -0.0755 [-0.2642, +0.1132] (n=53) |
| Severity signed-error difference | +0.0566 [-0.0755, +0.2075] | +0.0377 [-0.1321, +0.2075] | +0.0545 [-0.1636, +0.2909] | +0.0000 [-0.2453, +0.2453] | +0.0000 [-0.2453, +0.2453] |


Meaning: C2−C1 and C3−C4 are VSS minus direct at equal prompt. C3−C1 is best VSS vs fixed direct. C3−C2 and C4−C1 are prompt effects. Intervals touching 0 (for example `[0.0000, …]`) do not exclude it. V1 has no p-values (UNAVAILABLE). Only ΔI was pre-registered as primary, from about 40 per-score intervals per stage. The doc's **C3−C1 identity** (C3−C1 = (C3−C4) + (C4−C1)) is arithmetic on similar pairs, not exact: +0.0231 − 0.0111 = +0.0120 matches here, but the pair sets differ (54 vs 55).

### Paired differences, original view

Key: same, in `RES/reports/stage3/original/stage3-report.json`.

| Score | C2-C1 | C3-C4 | C3-C1 | C3-C2 | C4-C1 |
|---|---|---|---|---|---|
| ΔI (D9 v2) | -0.0065 [-0.0365, +0.0244] (n=) | +0.0186 [-0.0066, +0.0446] (n=) | +0.0077 [-0.0242, +0.0418] (n=) | +0.0160 [-0.0195, +0.0528] (n=) | -0.0137 [-0.0482, +0.0221] (n=) |
| ΔI8 | -0.0076 [-0.0372, +0.0206] (n=53) | +0.0244 [-0.0096, +0.0599] (n=53) | +0.0143 [-0.0173, +0.0485] (n=51) | +0.0183 [-0.0235, +0.0637] (n=52) | -0.0078 [-0.0441, +0.0277] (n=52) |
| Incident component | -0.0075 [-0.0462, +0.0269] (n=53) | +0.0226 [-0.0255, +0.0706] (n=53) | +0.0196 [-0.0200, +0.0640] (n=51) | +0.0192 [-0.0353, +0.0778] (n=52) | +0.0038 [-0.0400, +0.0481] (n=52) |
| Entity F1 component | +0.0043 [-0.0661, +0.0809] (n=51) | +0.0210 [-0.0329, +0.0752] (n=50) | -0.0081 [-0.0839, +0.0713] (n=49) | -0.0126 [-0.0810, +0.0523] (n=49) | -0.0356 [-0.1118, +0.0429] (n=50) |
| Object F1 component | -0.0162 [-0.0500, +0.0163] (n=50) | +0.0123 [-0.0156, +0.0441] (n=50) | +0.0117 [-0.0352, +0.0626] (n=48) | +0.0415 [-0.0087, +0.0962] (n=49) | -0.0093 [-0.0560, +0.0399] (n=49) |
| Type | -0.0189 [-0.0588, +0.0000] (n=53) | -0.0189 [-0.0909, +0.0385] (n=53) | -0.0196 [-0.0612, +0.0000] (n=51) | +0.0000 [-0.0566, +0.0566] (n=52) | +0.0192 [-0.0400, +0.0943] (n=52) |
| Severity exact | +0.0000 [-0.0755, +0.0755] (n=53) | -0.0377 [-0.1731, +0.0980] (n=53) | +0.0392 [-0.0625, +0.1481] (n=51) | +0.0192 [-0.1020, +0.1455] (n=52) | +0.0769 [-0.0755, +0.2292] (n=52) |
| Start ±5 s | +0.0189 [+0.0000, +0.0577] (n=53) | +0.0377 [-0.0370, +0.1132] (n=53) | +0.0392 [-0.0385, +0.1200] (n=51) | +0.0192 [-0.0588, +0.1064] (n=52) | +0.0192 [-0.0784, +0.1154] (n=52) |
| End ±5 s | +0.0000 [-0.0566, +0.0556] (n=53) | +0.0377 [-0.0370, +0.1132] (n=53) | +0.0784 [+0.0189, +0.1600] (n=51) **excl. 0** | +0.0769 [+0.0185, +0.1538] (n=52) **excl. 0** | +0.0385 [-0.0370, +0.1176] (n=52) |
| Description (judge ≥ 0.5) | -0.0377 [-0.1667, +0.0943] (n=53) | +0.0943 [-0.0182, +0.2037] (n=53) | -0.0392 [-0.1346, +0.0577] (n=51) | -0.0192 [-0.1538, +0.1176] (n=52) | -0.1346 [-0.2549, -0.0192] (n=52) **excl. 0** |
| Entities F1 | +0.0043 [-0.0661, +0.0809] (n=51) | +0.0210 [-0.0329, +0.0752] (n=50) | -0.0081 [-0.0839, +0.0713] (n=49) | -0.0126 [-0.0810, +0.0523] (n=49) | -0.0356 [-0.1118, +0.0429] (n=50) |
| Instruments F1 | +0.0513 [+0.0000, +0.1667] (n=13) | -0.0214 [-0.0692, +0.0000] (n=14) | +0.1212 [+0.0000, +0.2963] (n=11) | +0.0556 [+0.0000, +0.1818] (n=12) | +0.1485 [+0.0000, +0.3286] (n=11) |
| Assets F1 | -0.0162 [-0.0441, +0.0094] (n=50) | +0.0170 [-0.0104, +0.0487] (n=50) | +0.0117 [-0.0300, +0.0585] (n=48) | +0.0415 [-0.0110, +0.1009] (n=49) | -0.0059 [-0.0436, +0.0342] (n=49) |
| Severity MAE difference (v1.3, lower better) | +0.0000 [-0.0962, +0.0962] (n=52) | -0.0192 [-0.1923, +0.1538] (n=52) | -0.0784 [-0.2157, +0.0392] (n=51) | -0.0588 [-0.2157, +0.0980] (n=51) | -0.0784 [-0.2745, +0.1176] (n=51) |
| Severity signed-error difference | +0.0769 [-0.0577, +0.2308] | +0.0192 [-0.1538, +0.1923] | -0.0392 [-0.2353, +0.1373] | -0.0980 [-0.3137, +0.0980] | +0.0000 [-0.2549, +0.2745] |


### Sensitivity, recovery-adjusted (`d9_excluding_pilot_clips`)

| Comparison | ΔI excluding Animal003, Assault018, Burglary005 (52 clips) |
|---|---|
| C2-C1 | -0.0069 [-0.0374, +0.0251] |
| C3-C4 | +0.0230 [-0.0048, +0.0521] |
| C3-C1 | +0.0086 [-0.0230, +0.0420] |
| C3-C2 | +0.0163 [-0.0195, +0.0535] |
| C4-C1 | -0.0146 [-0.0508, +0.0221] |


### Verification of the Stage 3 tables against the raw JSON

Method, in three steps:
1. Read every number in `DOCS/stage3-results.md` §2-§9 against `stage3-report.json` (both views).
2. Re-ran `experiment_selection.compare` on the four `merged-original+recovery-v1.json` files named in `sources.txt`: **all 13 points and 13 intervals in all five comparisons match the report JSON exactly.**
3. Recounted incident-field passes from the merged files: all match §4 (for example C1 type 46 passes, C3 end 36, C4 description 12).

Result: **the §3 ΔI table, §3 per-score table, §4-§9 and the excluding-pilot line match.** Three-decimal values are correct roundings, allowing for ties at a final 5 (for example −0.0755 shown as −0.075).

Mismatches found:

| # | Where | Doc says | Raw JSON | Severity |
|---|---|---|---|---|
| 1 | `stage3-results.md` §1 item 1 | Description C3−C2 "0.000 [−0.130, +0.130]" | `C3-C2 .d9.ci95.description` = [−0.1321, +0.1346] | Small; conclusion unchanged. Quote the JSON |
| 2 | `stage3-results.md` §3 | Instruments "rest on 13-15 paired clips" | `.pairs.instruments` = 13, 13, 12, 14, 13: **12-14** | Small. (`final-report.md` §13 says 10-15, across stages) |
| 3 | `final-report.md` §13 Scope; `stage3-results.md` §11 | "the cropping-on end-to-end profile … were not run" | It ran (`final-report.md` header, §7; `RES/reports/e2e-profile/`) | Stale sentence in the final report |
| 4 | §5 vs `stage3-report.md` | Not a mismatch: C2 and C4 severity exact 0.283 / 0.321 (n 53) vs 0.278 / 0.315 (n 54) | Different denominators, explained in `final-report.md` §6.3 | Quote the n |

C3−C1 paired severity MAE is in the JSON but not in the docs: −0.0545 [−0.1818, +0.0727], 55 pairs.

Secondary metrics (micro/macro, per-video F1, τ sweep) are in `final-report.md` §6.6 and `RES/reports/stage3-secondary/recovery-adjusted-v1/secondary-metrics.json`. I checked severity and description micro and macro for C1-C4 against the JSON: they match.

### Stage 3 conclusions as the project states them

`DOCS/stage3-results.md` §1 item 5: Stage 3 supports "VSS reproduces direct-VLM extraction quality and reliability at negligible overhead when sending the same request". It does not support "VSS extracts better than a direct VLM".

Wording caution: "no difference was detected" is correct. "Equivalent" is not established: no equivalence margin was set, and effects below about 0.03-0.04 are undetectable (§11). The test clips are "held out from prompt selection", **not unseen** (D15). Ground truth and τ are AI-assisted, not human-verified.

## 4. V1 end-to-end profile with crops

**This is not a direct-vs-VSS comparison.** It has no direct arm and no accuracy scoring (`scoring: none`, `reportable: false`). It measures what cropping costs inside VSS.

| Item | Value | Source |
|---|---|---|
| Configs | `e2e-c2-vss-base` (C2), `e2e-c3-vss-v1` (C3), both VSS | `eval/experiments/configs/e2e-*.json` |
| Model | `nvidia/cosmos-3-super-reasoner`, for P1 and grounding | `results.json` `model`; `e2e-profile-plan.md` §1 |
| Prompts | `p1-v4-base` `409ed9b3187a…`; V1 `004746ea7d19…` | `results.json` `prompt` |
| Contract | `incident-contract-v4` | `results.json` |
| Dataset | 15 test clips (3 per category, seeded) × 1 repeat = 30 video-runs | `e2e-profile-plan.md` §1 |
| Harness | `99f3b1cc8` | `results.json` |
| Differs from Stage 3 | `skip_crops: false`, cap 40 grounding calls per request, `scoring: none`, 900 s timeout. RP1 off. No captions, no zoom | config `pipeline` |
| Retries | `retry-v2`; no recovery | config |

RAW-VERIFIED against `RES/reports/e2e-profile/e2e-profile-report.{md,json}`:

| Seconds, runs with output | C2 n / p50 / p95 / mean | C3 n / p50 / p95 / mean |
|---|---|---|
| End to end | 13 / 28.21 / 40.12 / 44.27 | 13 / 28.89 / 75.21 / 44.60 |
| Model inference | 13 / 19.13 / 28.09 / 26.44 | 13 / 20.35 / 43.98 / 26.42 |
| Cropping | 13 / 9.55 / 12.03 / 17.80 | 13 / 8.51 / 31.22 / 18.16 |
| Other overhead | 13 / 0.02 / 0.04 / 0.02 | 13 / 0.02 / 0.03 / 0.02 |

| | C2 | C3 |
|---|---|---|
| Output / scheduled | 13/15 (2 timeouts) | 13/15 (2 timeouts) |
| Evidence items / images | 67 / 63 (94.0%) | 179 / 118 (65.9%) |
| Grounding calls; per request p50 / p95 / max | 67; 4 / 10 / 10 | 118; 5 / 26 / 40 |
| Calls refused by cap | 0 | 61 (Explosion014) |
| P1 attempts / tokens | 19 / 120,718 | 21 / 129,164 |
| Grounding tokens | 24,448 | 36,855 |

- Median cropping share of end to end: 34% (C2), 33% (C3), about 1.7-1.8 s per grounding call at concurrency 4 (`DOCS/e2e-profile-results.md` §2).
- ΔI, type, severity, timestamps, description, entity and object F1: **UNAVAILABLE** (never scored). Paired effect, CI, significance: **UNAVAILABLE**; §5 of the results says no significance test was made.
- Not comparable with the Stage 3 latency tables (different gateway load). Lower bound for production: local agent, in-memory crops, no R2 or database write.
- Gap wording: the doc says the 4 C2 gaps were grounding timeouts. The report JSON records them as "no crop produced at 10s / 132s (frame unreadable or detector failed)", which is consistent with that but not specific.

## 5. V2 dev pilot: Track A (direct, C1a) vs Track B (pipeline, C1b)

**Status: development only.** 25 dev clips, also used to calibrate budgets, check scorers and choose the model roster. Not held-out. Track B is labelled "historical C1b profile" and is **not current production**: production runs person tracking, object tracking and captions (`evaluation-v2-preregistration.md` §1, §9).

### Setup

| Item | Track A (`v2-c1a-track-a-pilot`, plus `v2-c1a-track-a-recovery-super`) | Track B (`v2-c1b-track-b-pilot-captions`) |
|---|---|---|
| Models | `nvidia/cosmos-3-nano-reasoner`, `nvidia/cosmos-3-super-reasoner` (also Omni, Qwen, Gemma, which have no Track B) | P1 Nano or Super. **Grounding and zoom are always Super** (`provenance.stages`). Caption pass uses the P1 model |
| Prompt | `p1-v4-base`, `409ed9b3187a56be…` | Same file SHA in `provenance.stages.p1.prompts`, **plus** a caption context message on long clips. Zoom and grounding prompts are extra (for example grounding `1fa6ac8e…`) |
| Contract | `incident-contract-v4` | Same |
| Dataset | `split-v2` dev, 25 clips, **2 repeats** | Same clips, **1 repeat** |
| Runs | 50 per model | 25 per model |
| Config SHA | `ea131914b326…`; recovery `7227824a69a5…` | `f8755f962c13…` |
| Eval commit | `ed054cf0d`; recovery `d1e65f691` | `ed054cf0d`; agent `acbf892ba` |
| Path | Harness → Switchyard, presigned R2 URL | Harness → local experiment agent → Switchyard, presigned URL. Isolated, no writes |
| Retries | Harness `retry-v2` on infrastructure failures; model failures never retried | The adapter never re-sends. The agent retries a runaway P1 once and returns only the retry |
| Caps | Run budget caps only | 30 caption, 40 crop, 80 zoom calls |
| Scoring | `evalv2-score-stage-v3`; MiniLM τ 0.40; judge `openrouter-gpt-oss-20b-v1` (PROVISIONAL) in `live-*` files | Same |

Sources: `METH/v2-dev-pilot-results.md` §2, §4; `V2/c1a/manifest.start.json`; `V2/c1b/manifest.start.json`; `V2/c1b/agent.jsonl`.

**What differs between the paths**
1. **Captions:** on clips over 30 s only. 14 of 25 clips are over 30 s. On clips of 30 s or less, the P1 prompt tokens were identical to Track A on all 21 answered runs (DERIVED from `provenance.stages.p1.prompt_tokens` vs `attempts.jsonl`). On captioned clips P1 gained a median of 939 (Nano) and 986 (Super) prompt tokens.
2. **Grounding:** after P1. Does not change report fields.
3. **Zoom:** after grounding. Changes item names and descriptions.
4. **Agent wrapper and retry:** as above.
5. **Repeats:** Track A has 2, Track B has 1.

Same in both: model for P1, base prompt, contract, inference settings, clip transport, validator, scorer.

### Published Track A and Track B results (RAW-VERIFIED against `METH/results/v2-dev/track_a_models.csv`, `track_b_pipeline.csv`, `V2/c1b/scoring/evalv2-score-stage-v3/primary/offline-summary.json`)

Not paired. Different run sets and repeats. Conditional on contract-valid outputs.

| Metric | Nano A (direct) | Nano B P1 | Nano B final | Super A (direct) | Super B P1 | Super B final |
|---|---|---|---|---|---|---|
| Valid / runs | 48/50 | 23/25 | 23/25 | 49/50 | 24/25 | 24/25 |
| Contract-valid | 0.96 [0.88, 1.00] | 0.92 | 0.92 | 0.98 [0.94, 1.00] | 0.96 | 0.96 |
| Severity MAE ↓ | 1.2292 [0.9167, 1.5417] | 1.087 | 1.087 | 0.9388 [0.7551, 1.1224] | 0.9167 | 0.9167 |
| Severity exact | 0.1875 [0.0455, 0.3478] | 0.1739 | 0.1739 | 0.2245 [0.102, 0.3542] | 0.25 | 0.25 |
| Severity QWK | 0.3009 [0.0253, 0.5378] | 0.3495 | 0.3495 | 0.5033 [0.2449, 0.6631] | 0.5102 | 0.5102 |
| Type accuracy | 0.9375 [0.8333, 1.0] | 0.913 (see M1) | 0.913 | 0.9796 [0.9375, 1.0] | 0.9583 | 0.9583 |
| Type, end to end | 0.90 | 0.84 | UNAVAILABLE | 0.96 | 0.92 | UNAVAILABLE |
| Start error s ↓ | 6.2708 [3.2498, 9.5625] | 6.5652 | 6.5652 | 6.3061 [3.22, 9.8299] | 5.0417 | 5.0417 |
| End error s ↓ | 6.1667 [3.8, 8.7391] | 8.4783 | 8.4783 | 7.2857 [4.3469, 10.74] | 6.0417 | 6.0417 |
| Entities F1 | 0.1609 [0.0645, 0.5395] | 0.1946 | 0.2282 | 0.6053 [0.4462, 0.75] | 0.5138 | 0.5688 |
| Instruments F1 | 0.2353 | 0.2759 | 0.2759 | 0.2581 | 0.1111 | 0.1111 |
| Assets F1 | 0.4082 | 0.3894 | 0.3717 | 0.4093 | 0.4220 | 0.4037 |
| Description pass (PROVISIONAL) | 13/47 = 0.2766 (DERIVED) | 8/23 = 0.3478 | 8/23 = 0.3478 | 18/48 = 0.375 (DERIVED) | 8/24 = 0.3333 | 8/24 = 0.3333 |
| Tokens per answered call / per run | 11,685 | – | 37,715 | 9,095 | – | 67,678 |
| Latency p50 / p95 s | 7.5 / 52.6 per call | – | 64.1 / 228.7 per run | 61.6 / 112.3 per call | – | 101.0 / 205.0 per run |
| Attempts per run | 1.00 | – | – | 1.64 | – | – |

Track B P1 column here uses the `p1_agent` stage (valid outputs only), not `p1`; see M1. Track B tokens per run by stage (`track_b_pipeline.csv`): Nano caption 11,681, grounding 2,863, inference 15,397, zoom 7,773; Super caption 24,016, grounding 12,048, inference 12,106, zoom 19,508.

**Valid-output accounting (RAW-VERIFIED, `checkpoint.jsonl`, `attempts.jsonl`)**
- Nano direct failures: Animal002, both repeats, `parse_failure`.
- Nano pipeline failures: Animal002 and Assault030, `parse_failure` (agent 422, `p1_attempts` 2, retried and rejected). These are the 2 runs the caption pairing excludes.
- Super direct failure: Burglary004 repeat 1, `contract_invalid`.
- Super pipeline failure: Burglary010 (196 s clip), gateway HTTP 524 during P1 (`http_error`). Infrastructure, not a model failure.
- Caption context reached P1 on **12** Nano runs and **13** Super runs (`experiment.caption.context_sent`). Nano Burglary010 ran 14 caption calls, hit HTTP 429 and P1 ran with no context.

### Published effects

**Zoom (PUBLISHED, per-run means).** `METH/v2-dev-pilot-results.md` §4: "Zoom effect on entity F1, paired by run: Super +0.026, Nano about 0".

RAW-VERIFIED, `V2/c1b/scoring/evalv2-score-stage-v3/primary/live-summary.json`, `subjects.<s>.pipeline.zoom_effect.metrics`. Published with no CI (the code says intervals "come with the report"; none exists on dev).

| Metric (per-run mean, before → after, Δ; improved / worsened / unchanged) | Nano (23 runs) | Super (24 runs) |
|---|---|---|
| Entities F1 | 0.4727 → 0.4713, −0.0014 (1/1/21) | 0.4993 → 0.5258, +0.0264 (3/1/20) |
| Assets F1 | 0.3957 → 0.3783, −0.0174 (0/1/22) | 0.3805 → 0.3527, −0.0278 (1/2/21) |
| Instruments F1 | 0.1377 → 0.1377, 0.0 | 0.0417 → 0.0417, 0.0 |
| Incident description pass | 0.3478 → 0.3478, 0.0 | 0.3333 → 0.3333, 0.0 |
| Entity description pass, PROVISIONAL | 0.2444 → 0.2222, −0.0222 (0/1/14; 15 pairs) | 0.3922 → 0.2549, **−0.1373** (1/3/13; 17 pairs) |
| Asset description pass, PROVISIONAL | 0.2647 → 0.1765, −0.0882 (0/2/15; 17 pairs) | 0.3333 → 0.1333, **−0.2** (1/5/9; 15 pairs) |
| Asset name pass, PROVISIONAL | 0.8824 → 0.7647, −0.1176 (0/2/15; 17 pairs) | 0.7667 → 0.8, +0.0333 (2/1/12; 15 pairs) |

Type, severity and timing are unchanged by zoom on every run (verified: all deltas exactly 0). The judged description decrease is not mentioned in any doc. The dev pilot doc predates the judge scoring. The judge is not human-calibrated, and these rest on 15-17 pairs with no interval, so treat it as a flag to look at, not a finding.

**Caption effect:** the code defines it (`evalv2/tasks/pipeline/scoring.py::caption_effect`) and the pre-registration names it (§4.3), but **no published dev value exists: UNAVAILABLE as a published number.** A paired direct-vs-pipeline estimate is likewise unpublished. The closest is the prereg §5 Nano−Super line: "+0.27 on A, +0.18 on B" (confirmed below as +0.2766 and +0.1818).

### DERIVED: paired direct-vs-pipeline estimates

**Not project results. Exploratory, dev only, unadjusted for many comparisons.** Computed for this record.

Method:
- Scripts: `/tmp/claude-1000/-home-hengz-video-search-and-summarization-deploy-docker-developer-profiles-dev-profile-incident/7f967942-9eda-412d-9e23-717799313bad/scratchpad/v2_paired.py`, output `/tmp/claude-1000/-home-hengz-video-search-and-summarization-deploy-docker-developer-profiles-dev-profile-incident/7f967942-9eda-412d-9e23-717799313bad/scratchpad/v2_paired_live.json`.
- Inputs: `V2/{c1a,c1a-recovery,c1b}/scoring/evalv2-score-stage-v3/primary/live-videos.jsonl`.
- Statistics: the repo's `evalv2.cluster_bootstrap.paired_difference` (clip-cluster, 10,000 resamples, seed 20261027, percentile CI), with the same index for the added pooled item metrics. Conditional metrics use (clip, repeat) both-valid runs.
- Pairing: the repo's `caption_effect` rule, by clip and repeat, leaving out Track B runs with `p1_retried`. Track B has only repeat 1, so repeat 1 is the defined pair. Repeat 2 is shown as a sensitivity.
- **Validation:** the same code reproduces every value of the published Nano − Super rows in `track_a_paired_differences.csv` exactly (for example severity MAE +0.2766 [−0.0652, +0.6327], entities −0.4404 [−0.6118, −0.0430]).
- The columns read "A vs B: difference [95% CI]", with the pipeline first. "P1" is Track B's raw P1 stage (caption effect). "Final" is after grounding and zoom (total pipeline effect).

**Nano: contract validity, all 25 clips, no exclusions.** Pipeline − direct rep 1: 0.92 vs 0.96: -0.04 [-0.12, +0.00]; pipeline − direct rep 2: 0.92 vs 0.96: -0.04 [-0.12, +0.00]

| Metric | Pipeline P1 − direct rep 1 | Pipeline final − direct rep 1 | Pipeline P1 − direct rep 2 | Pipeline final − direct rep 2 | Noise floor: direct rep 2 − rep 1 |
|---|---|---|---|---|---|
| Clips / both-valid runs | 23 / 23 | 23 / 23 | 23 / 23 | 23 / 23 | 25 / 24 |
| Type accuracy | 0.913 vs 0.913: +0.0000 [+0.0000, +0.0000] | 0.913 vs 0.913: +0.0000 [+0.0000, +0.0000] | 0.913 vs 0.9565: -0.0435 [-0.1304, +0.0000] | 0.913 vs 0.9565: -0.0435 [-0.1304, +0.0000] | 0.9583 vs 0.9167: +0.0417 [+0.0000, +0.1304] |
| Severity MAE ↓ | 1.087 vs 1.2174: -0.1304 [-0.3478, +0.0870] | 1.087 vs 1.2174: -0.1304 [-0.3478, +0.0870] | 1.087 vs 1.1739: -0.0870 [-0.3043, +0.1304] | 1.087 vs 1.1739: -0.0870 [-0.3043, +0.1304] | 1.2083 vs 1.25: -0.0417 [-0.2000, +0.0870] |
| Severity exact | 0.1739 vs 0.1739: +0.0000 [-0.1739, +0.1739] | 0.1739 vs 0.1739: +0.0000 [-0.1739, +0.1739] | 0.1739 vs 0.2174: -0.0435 [-0.1739, +0.0870] | 0.1739 vs 0.2174: -0.0435 [-0.1739, +0.0870] | 0.2083 vs 0.1667: +0.0417 [+0.0000, +0.1304] |
| Severity QWK | 0.3495 vs 0.326: +0.0235 [-0.0973, +0.1393] | 0.3495 vs 0.326: +0.0235 [-0.0973, +0.1393] | 0.3495 vs 0.3206: +0.0290 [-0.1030, +0.1629] | 0.3495 vs 0.3206: +0.0290 [-0.1030, +0.1629] | 0.2982 vs 0.3036: -0.0054 [-0.0556, +0.0388] |
| Start error s ↓ | 6.5652 vs 5.6522: +0.9130 [-3.3913, +7.3043] | 6.5652 vs 5.6522: +0.9130 [-3.3913, +7.3043] | 6.5652 vs 5.6087: +0.9565 [-3.3043, +7.3478] | 6.5652 vs 5.6087: +0.9565 [-3.3043, +7.3478] | 6.25 vs 6.2917: -0.0417 [-0.1304, +0.0000] |
| End error s ↓ | 8.4783 vs 6.3043: +2.1739 [+0.1304, +5.5652] **excl. 0** | 8.4783 vs 6.3043: +2.1739 [+0.1304, +5.5652] **excl. 0** | 8.4783 vs 6.0435: +2.4348 [+0.2609, +5.8696] **excl. 0** | 8.4783 vs 6.0435: +2.4348 [+0.2609, +5.8696] **excl. 0** | 6.0417 vs 6.2917: -0.2500 [-0.7826, +0.0000] |
| Entities F1 (pooled) | 0.1946 vs 0.1538: +0.0408 [-0.0016, +0.1727] | 0.2282 vs 0.1538: +0.0743 [+0.0042, +0.1552] **excl. 0** | 0.1946 vs 0.1589: +0.0357 [-0.0144, +0.1683] | 0.2282 vs 0.1589: +0.0692 [-0.0081, +0.1570] | 0.1634 vs 0.1584: +0.0050 [-0.0130, +0.0309] |
| Instruments F1 (pooled) | 0.2759 vs 0.2308: +0.0451 [-0.0694, +0.2424] | 0.2759 vs 0.2308: +0.0451 [-0.0694, +0.2424] | 0.2759 vs 0.24: +0.0359 [-0.0714, +0.2353] | 0.2759 vs 0.24: +0.0359 [-0.0714, +0.2353] | 0.24 vs 0.2308: +0.0092 [+0.0000, +0.0238] |
| Assets F1 (pooled) | 0.3894 vs 0.4082: -0.0188 [-0.0760, +0.0375] | 0.3717 vs 0.4082: -0.0365 [-0.1092, +0.0289] | 0.3894 vs 0.4167: -0.0273 [-0.0921, +0.0324] | 0.3717 vs 0.4167: -0.0450 [-0.1231, +0.0235] | 0.4124 vs 0.404: +0.0083 [+0.0000, +0.0305] |
| Object F1 (instr.+assets pooled) | 0.3662 vs 0.371: -0.0048 [-0.0522, +0.0437] | 0.3521 vs 0.371: -0.0189 [-0.0814, +0.0387] | 0.3662 vs 0.3802: -0.0140 [-0.0645, +0.0374] | 0.3521 vs 0.3802: -0.0281 [-0.0933, +0.0318] | 0.377 vs 0.368: +0.0090 [+0.0000, +0.0250] |
| Object score (mean of entity F1 and object F1) | 0.2804 vs 0.2624: +0.0180 [-0.0148, +0.0852] | 0.2902 vs 0.2624: +0.0277 [-0.0204, +0.0775] | 0.2804 vs 0.2696: +0.0109 [-0.0260, +0.0805] | 0.2902 vs 0.2696: +0.0206 [-0.0306, +0.0729] | 0.2702 vs 0.2632: +0.0070 [-0.0042, +0.0215] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.3182 vs 0.2727: +0.0455 [-0.1818, +0.2857] n=22 | 0.3182 vs 0.2727: +0.0455 [-0.1818, +0.2857] n=22 | 0.3478 vs 0.3043: +0.0435 [-0.1739, +0.2609] n=23 | 0.3478 vs 0.3043: +0.0435 [-0.1739, +0.2609] n=23 | 0.2609 vs 0.2609: +0.0000 [+0.0000, +0.0000] n=23 |


**Nano by caption exposure.** "Caption context sent" = the 12 clips where P1 received captions. Excludes retried Assault030, and Burglary010 (no context).

| Metric | Caption context sent: P1 − direct rep 1 | Caption context sent: P1 − direct rep 2 | Same clips: direct rep 2 − rep 1 | ≤ 30 s (no captions): P1 − direct rep 1 | ≤ 30 s: direct rep 2 − rep 1 |
|---|---|---|---|---|---|
| Clips / both-valid runs | 12 / 12 | 12 / 12 | 12 / 12 | 10 / 10 | 11 / 10 |
| Type accuracy | 0.9167 vs 0.9167: +0.0000 [+0.0000, +0.0000] | 0.9167 vs 1.0: -0.0833 [-0.2500, +0.0000] | 1.0 vs 0.9167: +0.0833 [+0.0000, +0.2500] | 0.9 vs 0.9: +0.0000 [+0.0000, +0.0000] | 0.9 vs 0.9: +0.0000 [+0.0000, +0.0000] |
| Severity MAE ↓ | 1.0833 vs 1.25: -0.1667 [-0.5000, +0.2500] | 1.0833 vs 1.25: -0.1667 [-0.5833, +0.3333] | 1.25 vs 1.25: +0.0000 [-0.2500, +0.2500] | 1.2 vs 1.2: +0.0000 [+0.0000, +0.0000] | 1.2 vs 1.2: +0.0000 [+0.0000, +0.0000] |
| Severity exact | 0.0833 vs 0.1667: -0.0833 [-0.3333, +0.1667] | 0.0833 vs 0.1667: -0.0833 [-0.3333, +0.1667] | 0.1667 vs 0.1667: +0.0000 [+0.0000, +0.0000] | 0.2 vs 0.2: +0.0000 [+0.0000, +0.0000] | 0.2 vs 0.2: +0.0000 [+0.0000, +0.0000] |
| Severity QWK | 0.2917 vs 0.2424: +0.0492 [-0.1165, +0.2210] | 0.2917 vs 0.2188: +0.0729 [-0.1270, +0.2567] | 0.2188 vs 0.2424: -0.0237 [-0.1193, +0.0523] | 0.4054 vs 0.4054: +0.0000 [+0.0000, +0.0000] | 0.4054 vs 0.4054: +0.0000 [+0.0000, +0.0000] |
| Start error s ↓ | 10.4167 vs 8.6667: +1.7500 [-6.3333, +13.9167] | 10.4167 vs 8.5833: +1.8333 [-6.2500, +14.0000] | 8.5833 vs 8.6667: -0.0833 [-0.2500, +0.0000] | 2.6 vs 2.6: +0.0000 [+0.0000, +0.0000] | 2.6 vs 2.6: +0.0000 [+0.0000, +0.0000] |
| End error s ↓ | 12.3333 vs 8.1667: +4.1667 [+0.2500, +10.4167] **excl. 0** | 12.3333 vs 7.6667: +4.6667 [+0.5833, +10.9167] **excl. 0** | 7.6667 vs 8.1667: -0.5000 [-1.5000, +0.0000] | 3.0 vs 3.0: +0.0000 [+0.0000, +0.0000] | 3.0 vs 3.0: +0.0000 [+0.0000, +0.0000] |
| Entities F1 (pooled) | 0.4872 vs 0.3291: +0.1581 [-0.0820, +0.2946] | 0.4872 vs 0.3415: +0.1457 [-0.1247, +0.3046] | 0.3415 vs 0.3291: +0.0123 [-0.0501, +0.0941] | 0.1538 vs 0.1538: +0.0000 [+0.0000, +0.0000] | 0.1538 vs 0.1538: +0.0000 [+0.0000, +0.0000] |
| Instruments F1 (pooled) | 0.3636 vs 0.3333: +0.0303 [-0.1143, +0.3077] | 0.3636 vs 0.3333: +0.0303 [-0.1143, +0.3077] | 0.3333 vs 0.3333: +0.0000 [+0.0000, +0.0000] | 0.0 vs 0.0: +0.0000 [+0.0000, +0.0000] | 0.0 vs 0.0: +0.0000 [+0.0000, +0.0000] |
| Assets F1 (pooled) | 0.3667 vs 0.4: -0.0333 [-0.1279, +0.0834] | 0.3667 vs 0.4186: -0.0519 [-0.1574, +0.0753] | 0.4186 vs 0.4: +0.0186 [+0.0000, +0.0626] | 0.4 vs 0.4: +0.0000 [+0.0000, +0.0000] | 0.4 vs 0.4: +0.0000 [+0.0000, +0.0000] |
| Object F1 (instr.+assets pooled) | 0.3659 vs 0.381: -0.0151 [-0.0980, +0.0753] | 0.3659 vs 0.3934: -0.0276 [-0.1145, +0.0694] | 0.3934 vs 0.381: +0.0125 [+0.0000, +0.0420] | 0.3774 vs 0.3774: +0.0000 [+0.0000, +0.0000] | 0.3774 vs 0.3774: +0.0000 [+0.0000, +0.0000] |
| Object score (mean of entity F1 and object F1) | 0.4265 vs 0.355: +0.0715 [-0.0606, +0.1531] | 0.4265 vs 0.3675: +0.0591 [-0.0915, +0.1507] | 0.3675 vs 0.355: +0.0124 [-0.0207, +0.0582] | 0.2656 vs 0.2656: +0.0000 [+0.0000, +0.0000] | 0.2656 vs 0.2656: +0.0000 [+0.0000, +0.0000] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.2727 vs 0.1818: +0.0909 [-0.3000, +0.5000] n=11 | 0.3333 vs 0.25: +0.0833 [-0.2500, +0.4167] n=12 | 0.1818 vs 0.1818: +0.0000 [+0.0000, +0.0000] n=11 | 0.4 vs 0.3: +0.1000 [+0.0000, +0.3000] n=10 | 0.3 vs 0.3: +0.0000 [+0.0000, +0.0000] n=10 |


**Super: contract validity, all 25 clips, no exclusions.** Pipeline − direct rep 1: 0.96 vs 0.96: +0.00 [-0.12, +0.12]; pipeline − direct rep 2: 0.96 vs 1.0: -0.04 [-0.12, +0.00]

| Metric | Pipeline P1 − direct rep 1 | Pipeline final − direct rep 1 | Pipeline P1 − direct rep 2 | Pipeline final − direct rep 2 | Noise floor: direct rep 2 − rep 1 |
|---|---|---|---|---|---|
| Clips / both-valid runs | 25 / 23 | 25 / 23 | 25 / 24 | 25 / 24 | 25 / 24 |
| Type accuracy | 0.9565 vs 0.9565: +0.0000 [-0.1250, +0.1250] | 0.9565 vs 0.9565: +0.0000 [-0.1250, +0.1250] | 0.9583 vs 1.0: -0.0417 [-0.1304, +0.0000] | 0.9583 vs 1.0: -0.0417 [-0.1304, +0.0000] | 1.0 vs 0.9583: +0.0417 [+0.0000, +0.1304] |
| Severity MAE ↓ | 0.913 vs 0.913: +0.0000 [-0.3333, +0.3182] | 0.913 vs 0.913: +0.0000 [-0.3333, +0.3182] | 0.9167 vs 0.9583: -0.0417 [-0.2917, +0.2000] | 0.9167 vs 0.9583: -0.0417 [-0.2917, +0.2000] | 0.9583 vs 0.9167: +0.0417 [-0.2917, +0.3333] |
| Severity exact | 0.2609 vs 0.3043: -0.0435 [-0.2381, +0.1429] | 0.2609 vs 0.3043: -0.0435 [-0.2381, +0.1429] | 0.25 vs 0.1667: +0.0833 [-0.0800, +0.2500] | 0.25 vs 0.1667: +0.0833 [-0.0800, +0.2500] | 0.1667 vs 0.2917: -0.1250 [-0.3333, +0.0833] |
| Severity QWK | 0.5156 vs 0.4867: +0.0289 [-0.1885, +0.2241] | 0.5156 vs 0.4867: +0.0289 [-0.1885, +0.2241] | 0.5102 vs 0.5348: -0.0246 [-0.2236, +0.1607] | 0.5102 vs 0.5348: -0.0246 [-0.2236, +0.1607] | 0.5285 vs 0.4832: +0.0453 [-0.1345, +0.2404] |
| Start error s ↓ | 5.1304 vs 8.0435: -2.9130 [-8.4805, +0.8750] | 5.1304 vs 8.0435: -2.9130 [-8.4805, +0.8750] | 5.0417 vs 5.0: +0.0417 [-1.4800, +1.6250] | 5.0417 vs 5.0: +0.0417 [-1.4800, +1.6250] | 4.9583 vs 7.7917: -2.8333 [-8.0800, +0.5200] |
| End error s ↓ | 6.1739 vs 7.0435: -0.8696 [-2.5417, +0.6087] | 6.1739 vs 7.0435: -0.8696 [-2.5417, +0.6087] | 6.0417 vs 6.875: -0.8333 [-2.2609, +0.4800] | 6.0417 vs 6.875: -0.8333 [-2.2609, +0.4800] | 7.375 vs 7.375: +0.0000 [-0.3750, +0.3600] |
| Entities F1 (pooled) | 0.5098 vs 0.6667: -0.1569 [-0.4699, +0.1408] | 0.549 vs 0.6667: -0.1176 [-0.3819, +0.1442] | 0.5138 vs 0.5714: -0.0577 [-0.3236, +0.2064] | 0.5688 vs 0.5714: -0.0026 [-0.2307, +0.2270] | 0.5841 vs 0.6226: -0.0386 [-0.1898, +0.1269] |
| Instruments F1 (pooled) | 0.1176 vs 0.087: +0.0307 [-0.0152, +0.0936] | 0.1176 vs 0.087: +0.0307 [-0.0152, +0.0936] | 0.1111 vs 0.4828: -0.3716 [-0.5926, +0.0000] | 0.1111 vs 0.4828: -0.3716 [-0.5926, +0.0000] | 0.4118 vs 0.0714: +0.3403 [+0.0000, +0.5600] |
| Assets F1 (pooled) | 0.419 vs 0.4118: +0.0073 [-0.0611, +0.0777] | 0.419 vs 0.4118: +0.0073 [-0.0628, +0.0763] | 0.422 vs 0.3925: +0.0295 [-0.0182, +0.0862] | 0.4037 vs 0.3925: +0.0111 [-0.0512, +0.0755] | 0.4 vs 0.419: -0.0190 [-0.0757, +0.0331] |
| Object F1 (instr.+assets pooled) | 0.377 vs 0.352: +0.0250 [-0.0336, +0.0814] | 0.377 vs 0.352: +0.0250 [-0.0313, +0.0773] | 0.378 vs 0.4118: -0.0338 [-0.1345, +0.0459] | 0.3622 vs 0.4118: -0.0496 [-0.1614, +0.0496] | 0.4029 vs 0.3459: +0.0570 [-0.0401, +0.1659] |
| Object score (mean of entity F1 and object F1) | 0.4434 vs 0.5093: -0.0659 [-0.2226, +0.0805] | 0.463 vs 0.5093: -0.0463 [-0.1766, +0.0828] | 0.4459 vs 0.4916: -0.0457 [-0.2187, +0.1058] | 0.4655 vs 0.4916: -0.0261 [-0.1774, +0.1143] | 0.4935 vs 0.4843: +0.0092 [-0.0820, +0.0900] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.3182 vs 0.3182: +0.0000 [-0.2273, +0.2174] n=22 | 0.3182 vs 0.3182: +0.0000 [-0.2273, +0.2174] n=22 | 0.3333 vs 0.4167: -0.0833 [-0.2800, +0.1200] n=24 | 0.3333 vs 0.4167: -0.0833 [-0.2800, +0.1200] n=24 | 0.3913 vs 0.3478: +0.0435 [-0.0952, +0.1905] n=23 |


**Super by caption exposure.**

| Metric | Caption context sent: P1 − direct rep 1 | Caption context sent: P1 − direct rep 2 | Same clips: direct rep 2 − rep 1 | ≤ 30 s (no captions): P1 − direct rep 1 | ≤ 30 s: direct rep 2 − rep 1 |
|---|---|---|---|---|---|
| Clips / both-valid runs | 13 / 12 | 13 / 13 | 13 / 12 | 11 / 11 | 11 / 11 |
| Type accuracy | 0.9167 vs 0.9167: +0.0000 [-0.2308, +0.2308] | 0.9231 vs 1.0: -0.0769 [-0.2308, +0.0000] | 1.0 vs 0.9167: +0.0833 [+0.0000, +0.2500] | 1.0 vs 1.0: +0.0000 [+0.0000, +0.0000] | 1.0 vs 1.0: +0.0000 [+0.0000, +0.0000] |
| Severity MAE ↓ | 1.0 vs 1.1667: -0.1667 [-0.6364, +0.2506] | 1.0 vs 0.9231: +0.0769 [-0.2308, +0.3846] | 0.9167 vs 1.1667: -0.2500 [-0.8000, +0.2500] | 0.8182 vs 0.6364: +0.1818 [-0.2727, +0.6364] | 1.0 vs 0.6364: +0.3636 [+0.0909, +0.6364] **excl. 0** |
| Severity exact | 0.25 vs 0.1667: +0.0833 [+0.0000, +0.2727] | 0.2308 vs 0.2308: +0.0000 [-0.2308, +0.2308] | 0.25 vs 0.1667: +0.0833 [-0.1818, +0.3636] | 0.2727 vs 0.4545: -0.1818 [-0.5455, +0.1818] | 0.0909 vs 0.4545: -0.3636 [-0.6364, -0.0909] **excl. 0** |
| Severity QWK | 0.3684 vs 0.2281: +0.1404 [-0.1746, +0.4274] | 0.3683 vs 0.4157: -0.0474 [-0.2838, +0.1806] | 0.4231 vs 0.2281: +0.1950 [-0.1359, +0.5216] | 0.6431 vs 0.713: -0.0700 [-0.3294, +0.1973] | 0.6266 vs 0.713: -0.0864 [-0.3147, +0.0000] |
| Start error s ↓ | 7.5833 vs 13.5833: -6.0000 [-16.1538, +1.0000] | 7.2308 vs 7.0769: +0.1538 [-2.5404, +3.0769] | 7.4167 vs 13.5833: -6.1667 [-15.7000, +0.0000] | 2.4545 vs 2.0: +0.4545 [-0.2727, +1.6364] | 2.5455 vs 2.0: +0.5455 [-0.2727, +1.9091] |
| End error s ↓ | 9.5833 vs 10.0: -0.4167 [-2.6923, +1.7000] | 9.0769 vs 9.2308: -0.1538 [-1.8462, +1.6154] | 9.75 vs 10.0: -0.2500 [-0.8182, +0.0000] | 2.4545 vs 3.8182: -1.3636 [-3.9091, +0.5455] | 4.0909 vs 3.8182: +0.2727 [+0.0000, +0.8182] |
| Entities F1 (pooled) | 0.4054 vs 0.6471: -0.2417 [-0.6148, +0.1441] | 0.4198 vs 0.5238: -0.1041 [-0.4217, +0.2349] | 0.5067 vs 0.6471: -0.1404 [-0.2860, -0.0098] **excl. 0** | 0.7857 vs 0.7143: +0.0714 [+0.0000, +0.2105] | 0.7143 vs 0.7143: +0.0000 [-0.0840, +0.0606] |
| Instruments F1 (pooled) | 0.0 vs 0.0: +0.0000 [+0.0000, +0.0000] | 0.0 vs 0.4615: -0.4615 [-0.6364, +0.0000] | 0.4615 vs 0.0: +0.4615 [+0.0000, +0.6364] | 0.6667 vs 0.6667: +0.0000 [+0.0000, +0.0000] | 0.6667 vs 0.6667: +0.0000 [+0.0000, +0.0000] |
| Assets F1 (pooled) | 0.3704 vs 0.36: +0.0104 [-0.1181, +0.1450] | 0.3793 vs 0.3396: +0.0397 [-0.0417, +0.1412] | 0.3333 vs 0.36: -0.0267 [-0.1381, +0.0818] | 0.4706 vs 0.4615: +0.0090 [+0.0000, +0.0364] | 0.4444 vs 0.4615: -0.0171 [-0.0356, +0.0000] |
| Object F1 (instr.+assets pooled) | 0.2941 vs 0.2571: +0.0370 [-0.0662, +0.1307] | 0.3014 vs 0.3797: -0.0784 [-0.2422, +0.0646] | 0.3784 vs 0.2571: +0.1212 [-0.0640, +0.2980] | 0.4815 vs 0.4727: +0.0088 [+0.0000, +0.0346] | 0.4561 vs 0.4727: -0.0166 [-0.0345, +0.0000] |
| Object score (mean of entity F1 and object F1) | 0.3498 vs 0.4521: -0.1023 [-0.2902, +0.0871] | 0.3606 vs 0.4518: -0.0912 [-0.3167, +0.1107] | 0.4425 vs 0.4521: -0.0096 [-0.1261, +0.0827] | 0.6336 vs 0.5935: +0.0401 [+0.0000, +0.1213] | 0.5852 vs 0.5935: -0.0083 [-0.0556, +0.0265] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.3636 vs 0.1818: +0.1818 [+0.0000, +0.4444] n=11 | 0.3846 vs 0.3846: +0.0000 [-0.2308, +0.2308] n=13 | 0.3636 vs 0.1818: +0.1818 [+0.0000, +0.4444] n=11 | 0.2727 vs 0.4545: -0.1818 [-0.5455, +0.1818] n=11 | 0.4545 vs 0.4545: +0.0000 [+0.0000, +0.0000] n=11 |


**Nano − Super on each track**

| Metric | Track A Nano − Super (reproduces published CSV) | Track B P1 Nano − Super | Track B final Nano − Super |
|---|---|---|---|
| Clips / both-valid runs | 25 / 47 | 25 / 22 | 25 / 22 |
| Type accuracy | 0.9362 vs 0.9787: -0.0426 [-0.1556, +0.0435] | 0.9091 vs 0.9545: -0.0455 [-0.2000, +0.0952] | 0.9091 vs 0.9545: -0.0455 [-0.2000, +0.0952] |
| Severity MAE ↓ | 1.234 vs 0.9574: +0.2766 [-0.0652, +0.6327] | 1.1364 vs 0.9545: +0.1818 [-0.1818, +0.5500] | 1.1364 vs 0.9545: +0.1818 [-0.1818, +0.5500] |
| Severity exact | 0.1915 vs 0.2128: -0.0213 [-0.1957, +0.1633] | 0.1364 vs 0.2273: -0.0909 [-0.3158, +0.1304] | 0.1364 vs 0.2273: -0.0909 [-0.3158, +0.1304] |
| Severity QWK | 0.3006 vs 0.5001: -0.1995 [-0.4513, +0.0173] | 0.349 vs 0.5174: -0.1684 [-0.5160, +0.1552] | 0.349 vs 0.5174: -0.1684 [-0.5160, +0.1552] |
| Start error s ↓ | 6.2553 vs 6.5319: -0.2766 [-3.5748, +2.5319] | 6.8636 vs 5.1818: +1.6818 [-2.8182, +8.4588] | 6.8636 vs 5.1818: +1.6818 [-2.8182, +8.4588] |
| End error s ↓ | 6.234 vs 7.2128: -0.9787 [-3.3619, +0.7660] | 8.0909 vs 6.1818: +1.9091 [+0.2083, +4.0000] **excl. 0** | 8.0909 vs 6.1818: +1.9091 [+0.2083, +4.0000] **excl. 0** |
| Entities F1 (pooled) | 0.1559 vs 0.5963: -0.4404 [-0.6118, -0.0430] **excl. 0** | 0.2788 vs 0.5: -0.2212 [-0.5108, +0.1395] | 0.2692 vs 0.54: -0.2708 [-0.5080, +0.0454] |
| Instruments F1 (pooled) | 0.24 vs 0.2581: -0.0181 [-0.3232, +0.3393] | 0.32 vs 0.1111: +0.2089 [-0.1895, +0.5714] | 0.32 vs 0.1111: +0.2089 [-0.1895, +0.5714] |
| Assets F1 (pooled) | 0.3979 vs 0.4211: -0.0231 [-0.1144, +0.0791] | 0.3818 vs 0.4381: -0.0563 [-0.1470, +0.0442] | 0.3636 vs 0.419: -0.0554 [-0.1522, +0.0536] |
| Object F1 (instr.+assets pooled) | 0.3651 vs 0.3838: -0.0186 [-0.1111, +0.0818] | 0.3704 vs 0.3902: -0.0199 [-0.1050, +0.0625] | 0.3556 vs 0.374: -0.0184 [-0.1157, +0.0821] |
| Object score (mean of entity F1 and object F1) | 0.2605 vs 0.49: -0.2295 [-0.3369, -0.0229] **excl. 0** | 0.3246 vs 0.4451: -0.1205 [-0.2761, +0.0716] | 0.3124 vs 0.457: -0.1446 [-0.2736, +0.0307] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.2826 vs 0.3478: -0.0652 [-0.2245, +0.0816] n=46 | 0.3636 vs 0.2727: +0.0909 [-0.1905, +0.3750] n=22 | 0.3636 vs 0.2727: +0.0909 [-0.1905, +0.3750] n=22 |


**Zoom with intervals (pooled F1, so not the same statistic as the published per-run mean)**

Nano:

| Metric | final − p1_agent |
|---|---|
| Clips / both-valid runs | 25 / 23 |
| Type accuracy | 0.913 vs 0.913: +0.0000 [+0.0000, +0.0000] |
| Severity MAE ↓ | 1.087 vs 1.087: +0.0000 [+0.0000, +0.0000] |
| Severity exact | 0.1739 vs 0.1739: +0.0000 [+0.0000, +0.0000] |
| Severity QWK | 0.3495 vs 0.3495: +0.0000 [+0.0000, +0.0000] |
| Start error s ↓ | 6.5652 vs 6.5652: +0.0000 [+0.0000, +0.0000] |
| End error s ↓ | 8.4783 vs 8.4783: +0.0000 [+0.0000, +0.0000] |
| Entities F1 (pooled) | 0.2282 vs 0.1946: +0.0336 [-0.0320, +0.0909] |
| Instruments F1 (pooled) | 0.2759 vs 0.2759: +0.0000 [+0.0000, +0.0000] |
| Assets F1 (pooled) | 0.3717 vs 0.3894: -0.0177 [-0.0606, +0.0000] |
| Object F1 (instr.+assets pooled) | 0.3521 vs 0.3662: -0.0141 [-0.0465, +0.0000] |
| Object score (mean of entity F1 and object F1) | 0.2902 vs 0.2804: +0.0097 [-0.0279, +0.0421] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.3478 vs 0.3478: +0.0000 [+0.0000, +0.0000] n=23 |


Super:

| Metric | final − p1_agent |
|---|---|
| Clips / both-valid runs | 25 / 24 |
| Type accuracy | 0.9583 vs 0.9583: +0.0000 [+0.0000, +0.0000] |
| Severity MAE ↓ | 0.9167 vs 0.9167: +0.0000 [+0.0000, +0.0000] |
| Severity exact | 0.25 vs 0.25: +0.0000 [+0.0000, +0.0000] |
| Severity QWK | 0.5102 vs 0.5102: +0.0000 [+0.0000, +0.0000] |
| Start error s ↓ | 5.0417 vs 5.0417: +0.0000 [+0.0000, +0.0000] |
| End error s ↓ | 6.0417 vs 6.0417: +0.0000 [+0.0000, +0.0000] |
| Entities F1 (pooled) | 0.5688 vs 0.5138: +0.0550 [-0.0364, +0.1260] |
| Instruments F1 (pooled) | 0.1111 vs 0.1111: +0.0000 [+0.0000, +0.0000] |
| Assets F1 (pooled) | 0.4037 vs 0.422: -0.0183 [-0.0860, +0.0385] |
| Object F1 (instr.+assets pooled) | 0.3622 vs 0.378: -0.0157 [-0.0709, +0.0336] |
| Object score (mean of entity F1 and object F1) | 0.4655 vs 0.4459: +0.0196 [-0.0274, +0.0609] |
| Description pass (gpt-oss-20b, PROVISIONAL) | 0.3333 vs 0.3333: +0.0000 [+0.0000, +0.0000] n=24 |


**Reading the derived tables**
1. **No primary metric moves.** Pipeline minus direct on type accuracy and severity MAE includes zero for both models, against either Track A repeat.
2. **The agent path itself is transparent for Nano.** On ≤ 30 s clips, where no caption is added, Nano's parsed report was identical to Track A repeat 1 on 9 of 10 clips, and every code-scored metric difference is exactly 0. (Judge verdicts differ slightly. Same-request Nano repeat 1 vs repeat 2 also agrees on 9 of 10.)
3. **The Super comparison is at the noise floor.** Super's parsed report never matched across runs on those clips (0 of 10, for both B vs A and A rep 2 vs rep 1). Same-request Super repeats differ as much as the tracks do. On ≤ 30 s clips, repeat 2 − repeat 1 severity MAE is +0.3636 [+0.0909, +0.6364], which excludes zero with **identical requests**. Instruments F1 moves +0.3403 [0.0000, +0.5600] between Super repeats. So no Super caption or pipeline claim can be made from one Track B repeat. This matches the V1 lesson.
4. **The one candidate caption signal is a Nano harm.** On captioned clips, Nano's end-time error is higher with captions: +4.1667 s [+0.2500, +10.4167] vs repeat 1, +4.6667 s [+0.5833, +10.9167] vs repeat 2. Nano's same-request noise on those clips is small (−0.5 [−1.5, 0.0]). It is 12 clips, an unadjusted exploratory result, and start error does not confirm it. Do not present it as a finding without a held-out check.
5. **Final-stage entity F1 for Nano:** +0.0743 [+0.0042, +0.1552] vs repeat 1 but +0.0692 [−0.0081, +0.1570] vs repeat 2. This hinges on one clip. Burglary010 has 84 entity false positives in both tracks and TP moves 0 → 6 under zoom. Not robust.
6. **Pooled Nano entity F1 is dominated by Burglary010.** That explains Track A's odd interval [0.0645, 0.5395] and why the caption-context subset, which excludes it, reads 0.49 rather than 0.19.
7. **Cost is the clear difference.** Tokens per run: Nano 37,715 vs 11,685 per call; Super 67,678 vs 9,095. Latency p50: Nano 64.1 s per run vs 7.5 s per call; Super 101.0 s vs 61.6 s. Units differ and these are not paired measurements.

### Mismatches and stale statements in the V2 documents

| # | Where | Problem | Evidence |
|---|---|---|---|
| M1 | `v2-dev-pilot-results.md` §4 table, `track_b_pipeline.csv` | The "P1" row uses all 25 runs and "Final" uses valid runs, so **Nano type 0.84 → 0.91 and entities are not a grounding or zoom gain.** 0.84 = 21/25; 0.913 = 21/23. The same 21 clips are correct. `p1` entity F1 0.1921 vs `p1_agent` 0.1946 has the same cause (FN 21 vs 17) | `offline-summary.json`: `stages.p1` vs `stages.p1_agent`. Compare `p1_agent` to `final`, never `p1` to `final` |
| M2 | Same doc, §1, §7, status banner | Says description fields still need the judge. Judged `live-*` scores exist, so the document predates them | `live-summary.json` `mode.judge` = `openrouter-gpt-oss-20b-v1` |
| M3 | Same doc §4 | "The caption pass ran on every clip over 30 s (Nano 14/25, Super 13/24 runs)". Context reached P1 on 12 (Nano) and 13 (Super) | `experiment.caption.context_sent`; Burglary010 Nano 429 |
| M4 | Same doc §4 heading "Production pipeline" | Prereg says historical, not current production | Prereg §1, §9. Always label "historical C1b profile" |
| M5 | `evaluation-methodology-v2.0.md` §2 "As built (J1)" | Says the experimental path runs no caption pass. C1b did run it | `V2/c1b/manifest.start.json` profile `production-v4-captions` |
| M6 | `v2-dev-pilot-results.md` §5 vs prereg §9 vs `final-report.md` §3 | Three claims about Super frames: honours `num_frames` = 64; "ignores `num_frames`"; "samples about 24" | Not resolved here. Do not quote a frame count for Super on a slide |

## 6. Not found (UNAVAILABLE)

- p-values for any V1 comparison (V1 reports intervals only).
- A standardised effect size for any comparison.
- V1 timestamp error in seconds.
- Any accuracy metric for the V1 end-to-end profile.
- Any direct arm with crops, grounding or zoom. Direct paths cannot produce them, and crops are unscored in dev C1b (`c3e-dev-results-v1.md` scores Track B crops against AI reference boxes only, not against a direct path).
- A published paired Track A vs Track B estimate, or a published caption effect on dev.
- Published CIs for the zoom effect on dev.
- Any model other than Nano or Super on a pipeline; any V1 pipeline comparison on a model other than Super.
- The agent commit recorded in V1 results.
- The run artifact for the Stage 3 request-parity hashes (stated in `stage3-plan.md` only; not in the stage directory or `reports/stage3`).
- Any V2 held-out result here, by instruction.

## 7. Defensible wording

Supported:
- "In V1, VSS added no processing before extraction. With identical requests, it matched direct VLM calls on the held-out clips: ΔI −0.007 [−0.036, +0.024] at the base prompt, +0.023 [−0.003, +0.050] at V1."
- "VSS overhead was about 0.01 s with cropping off. Cropping added about a third of request time."
- "V1 therefore tested the wrapper, not a richer pipeline."

Needs the DERIVED label and owner review:
- "On 25 dev clips, the historical pipeline with captions, grounding and zoom showed no clear accuracy change in type or severity against direct calls, at 3 to 7 times the tokens."

Not supported:
- "VSS extracts better than a direct VLM." "VSS is equivalent to direct VLM." "Captions improve extraction." "Zoom improves descriptions." "Stage 3 ran with no RP1 calls." Anything about unseen footage.

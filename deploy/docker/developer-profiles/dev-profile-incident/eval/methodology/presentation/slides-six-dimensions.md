# Six-dimension slide summaries

Each section: title, findings, chart or table, interpretation, caveat, sources. All paths are under `methodology/presentation/` unless stated. "Test clips" means the 55 clips held out from prompt selection. They were previously exposed, so never call them unseen.

## 1. Incident Extraction

**Title:** Models differ more in producing valid reports than in reading incidents correctly.

**Findings**
- End to end, Nano gives the most usable reports of the complete C3 runs: 95/110 valid (0.864), type 0.673, against 0.482–0.500 for Omni, Gemma and Qwen, whose validity is 0.57–0.59.
- Among valid outputs, type accuracy is close: 0.78–0.86, with overlapping intervals.
- Severity is the clearest model difference among valid outputs: Gemma MAE 0.446 [0.284, 0.615], Omni 0.524 [0.349, 0.700], Qwen 0.569 [0.343, 0.846], Nano 0.821 [0.674, 0.968].
- Super is **incomplete**: 50 of 110 when the deadline closed it. The pre-registered Nano − Super comparison has 44 paired items: type 0.000 [−0.114, +0.114], MAE +0.045 [−0.182, +0.273], object −0.011 [−0.081, +0.060], Holm p 1.0. No difference shown, and it cannot support a verdict.

| Config | Valid / planned | Type, valid [95% CI] | Type, end to end | Severity MAE, valid [95% CI] | Usable severity | Status |
|---|---|---|---|---|---|---|
| Nano direct | 95/110 | 0.779 [0.660, 0.885] | 0.673 | 0.821 [0.674, 0.968] | 0.800 | final |
| Omni direct | 63/110 | 0.857 [0.750, 0.940] | 0.491 | 0.524 [0.349, 0.700] | 0.555 | final |
| Gemma 4 31B direct | 65/110 | 0.815 [0.677, 0.934] | 0.482 | 0.446 [0.284, 0.615] | 0.591 | final |
| Qwen3.5-9B direct | 65/110 | 0.846 [0.725, 0.950] | 0.500 | 0.569 [0.343, 0.846] | 0.555 | final |
| Super direct | 50/110 | 0.800 [0.680, 0.900] | 0.364 | 0.840 [0.660, 1.040] | 0.391 | **incomplete, closed at deadline** |
| V1 Super (historical re-score, 1 repeat) | 55/55 | 0.836 [0.727, 0.927] | 0.836 | 0.927 [0.745, 1.109] | 0.836 | historical, not C3 |
| VSS Nano contingency, final | 50/55 | 0.820 [0.700, 0.920] | 0.745 | 0.760 [0.620, 0.900] | 0.873 | contingency |

**Corrected 2026-11-05 (diagnostic audit):** description and ±5 s pass rates must be read on one denominator. Valid-only: description Gemma 42/65 = 0.646, Omni 32/63 = 0.508, Super 21/50 = 0.420 (incomplete), Qwen 26/64 = 0.406, contingency 17/50 = 0.340, Nano 28/95 = 0.295. Start ±5: Qwen 0.800, Super 36/50 = 0.720, Omni 0.762, contingency 0.740, Nano 0.726, Gemma 0.508. End ±5: Nano 0.705, Qwen 0.662, contingency 0.640, Super 32/50 = 0.640, Omni 0.476, Gemma 0.215. Earlier figures (Nano 0.255, Omni 0.291, Gemma 0.393, Qwen 0.250) counted invalid outputs as failures but excluded runs with no output, so they are not comparable with Super's. "Valid / planned" is end-to-end yield, not contract compliance; no model produced malformed JSON at a natural stop. See `diagnostics-initial.md`.

**Chart:** paired bars of valid-only and end-to-end type accuracy per model, with CIs; second panel severity MAE. Grey hatch for Super. Data: `data/d1_incident_extraction.csv`.

**Interpretation.** A model that answers well but rarely in valid form is less useful in a strict pipeline. End-to-end and valid-only views must be shown together.

**Caveat.** Valid-only rates compare different subsets of clips. Super's end-to-end value reflects a provider outage, not its reasoning. Ground truth is AI-assisted. OpenRouter models ran on a different provider.

**Sources:** `data/d1_incident_extraction.csv`, `data/vlm_vs_vss_paired.csv`, `/home/hengz/evalv2-data/v2/results-final/c3-final-analysis.json`.

## 2. Object Identification

**Title:** Among valid reports Gemma and Qwen lead on objects, but yield reshapes the picture.

**Corrected 2026-11-05.** The first version of this slide used a mixed denominator: invalid outputs counted as misses, no-output runs dropped. It also said scores were over valid outputs, which was wrong. Use the views below; figures are in `data/d2_object_views.csv`, and scoring is unchanged.

| Config | Valid / planned | Object score, valid only | Object score, end to end | Entity F1 (valid) | Instrument F1 (valid) | Asset F1 (valid) | Status |
|---|---|---|---|---|---|---|---|
| Gemma direct | 65/110 | 0.627 | 0.438 | 0.715 | 0.276 | 0.591 | final |
| Qwen direct | 65/110 | 0.588 | 0.415 | 0.637 | 0.261 | 0.573 | final |
| Nano direct | 95/110 | 0.460 | 0.427 | 0.478 | 0.321 | 0.463 | final |
| Omni direct | 63/110 | 0.453 | 0.329 | 0.574 | 0.140 | 0.391 | final |
| Super direct | 50/110 | 0.398 | 0.274 | 0.532 | 0.182 | 0.270 | **incomplete, closed at deadline** |
| VSS Nano contingency, final | 50/55 | 0.419 | 0.403 (invalid runs as empty) | 0.482 | 0.108 | 0.402 | contingency |

**Findings**
- Valid-only order is Gemma, Qwen, Nano, Omni. End to end, Gemma, Nano, Qwen, Omni: validity decides where Nano lands.
- Gemma is precise: entity precision 0.83, recall 0.63 among valid outputs. Nano is 0.38 and 0.65.
- Valid sets differ. On the 23 clip-repeats valid for all four, Gemma 0.667, Qwen 0.545, Nano 0.518.
- Instruments are not interpretable: 14 items on 9 clips.
- Zoom: −0.0065 [−0.0213, +0.0079] on 50 clips.

**Chart:** valid-only and end-to-end object score as paired bars. Data: `data/d2_object_views.csv`.

**Interpretation.** Object quality and contract compliance are different things; report both.

**Caveat.** Pooled F1 has no CI here. τ 0.40 is AI-calibrated; assignment runs before the threshold, so scores rise as τ falls whether or not matches are right (`../object-threshold-sensitivity/`). Do not call this "C2": old-deck figures are the 25-clip dev pilot, on different clips (`../c2-c3-object-audit/`).

**Sources:** `data/d2_object_views.csv`, `scripts/v2_object_views.py`, `../c2-c3-object-audit/README.md`.

## 3. Evidence Crops

**Title:** Evidence lands on the right object about 57% of the time when it can be checked.

**Findings**
- Evaluation half, Nano contingency: correct evidence 44/77 = 0.571 [0.471, 0.671]; over all matched entries 44/116 = 0.379; bounds 0.379–0.716.
- When a box reference exists, median IoU is 0.689 and 44/67 reach IoU 0.5. Temporal alignment is 77/87 = 0.885 [0.798, 0.963].
- Reliability: 351 of 367 entries located. But 251 of 367 belong to predicted items that match no ground-truth object.
- Development is similar in level: Nano 0.56, Super 0.57; paired +0.06 [−0.11, +0.25], p 0.50. No Nano − Super comparison is possible on the evaluation half.

| Metric | Eval half, Nano contingency | Dev, Nano (Super grounding) | Dev, Super |
|---|---|---|---|
| Correct evidence, conditional | 44/77 = 0.571 [0.471, 0.671] | 20/36 = 0.56 [0.37, 0.74] | 20/35 = 0.57 [0.38, 0.76] |
| Correct over all matched | 44/116 = 0.379 | 20/59 = 0.34 | 20/54 = 0.37 |
| Median IoU; IoU ≥ 0.5 | 0.689; 44/67 | 0.74; 20/29 | 0.81; 20/30 |
| Temporal alignment | 77/87 = 0.885 | 34/41 = 0.83 | 35/40 = 0.88 |
| Located entries | 351/367 | 229/346 | 150/150 |

Reference coverage, evaluation half, 486 object-seconds: box reference 198, not visible 101, visibility unresolved 129, box unresolved 41, GT identity flag 17.

**Chart:** stacked bar of the 367 entries by class (correct, spatial miss, temporal miss, unscorable, unmatched). Data: `data/d3_evidence_crops.csv`, `data/d3_anchor_coverage_test.json`.

**Interpretation.** The grounding stage usually finds a plausible region at the right time. The larger loss comes earlier: most evidence entries belong to predicted items that match no ground-truth object. Whether those are invented objects or GT gaps is under audit.

**Caveat.** References are AI-generated by one model family and never human-verified. IoU is agreement with AI boxes. Adjudication does not establish correctness. References favour machine-findable objects. Tracking was off, so this is not production. Do not report IoU as accuracy across all evidence. Dev and evaluation values use different grounding models and clips, so they are not a change.

**Sources:** `../c3e-test-results-v1.md`, `../c3e-dev-results-v1.md`, `/home/hengz/evalv2-data/v2/references/c3e-v1/results/c3e-test-v1.json`.

## 4. Chatbot Querying

**Title:** Chat reasons well over good reports; report quality sets the ceiling.

**Findings**
- On oracle reports, exact-answer accuracy is 0.797 [0.701, 0.882] (n=79), contradiction with ground truth 0.054, and refusal recall 20/20.
- On the Nano contingency pipeline reports, exact-answer accuracy is 0.189 [0.103, 0.286] (n=74), contradiction 0.770 (n=74). 10 of 119 questions had no report.
- Unsupported claims stay low in both corpora, 0.048 and 0.015, so answers follow their reports.
- Same pattern as dev (0.78 vs 0.24; contradiction 0.02 vs 0.67).

| Metric | Oracle | Contingency system |
|---|---|---|
| Answered | 119/119 | 109/119 (10 no report) |
| Exact answer | 0.797 [0.701, 0.882] | 0.189 [0.103, 0.286] |
| Contradiction with GT, AI-judged | 0.054 (n=92) | 0.770 (n=74) |
| Unsupported claims, AI-judged | 0.048 (n=84) | 0.015 (n=66) |
| Citation precision / recall | 0.985 / 0.604 | 0.891 / 0.425 |
| Retrieval recall@5 | 0.452 [0.281, 0.629] (n=20) | 0.267 [0.126, 0.434] (n=20) |
| False-refusal rate | 0.061 (n=99) | 0.217 (n=92) |
| Refusal recall | 1.000 (n=20) | 0.882 (n=17) |

**Chart:** paired bars, oracle against system, for exact answer, contradiction and citation recall. Data: `data/d4_chat.csv`.

**Interpretation.** The contrast suggests that upstream report errors drive most contradictions, because answers stay faithful to their reports. It is a contrast between corpora, not an isolated cause.

**Caveat.** Grounded chat is merged but off and not deployed. Template mode was never scored, so no improvement over it can be claimed. The system corpus is a Nano-only contingency, not the planned Super corpus. Judged rates are provisional: gpt-oss-20b, not human-calibrated (AI-consensus κ 0.63), no sensitivity judge. References are AI-generated. `ai_proposed` items are included in "all"; `data/d4_chat.csv` also holds `ai_validated` alone.

**Sources:** `data/d4_chat.csv`; `/home/hengz/evalv2-data/v2/runs/c3-chat-a5-oracle-judge/score-judged/report.json`; `/home/hengz/evalv2-data/v2/runs/c3-chat-a5-system-contingency-judge/score-judged/report.json`; `methodology/v2-chat-judged-results.md` for dev.

## 5. AI Dashboard

**Title:** Ask for a chart matched the expected spec on 57 of 60 valid requests and accepted no invalid ones.

**Findings**
- Exact spec 57/60 = 0.95 [0.889, 1.000]. Figures 72/75 = 0.96 [0.907, 1.000].
- 0 false acceptances, 0 wrong specs, 0 invalid replies. All 3 errors were false refusals.
- Refusal recall 15/15; refusal precision 15/18 = 0.833 [0.636, 1.000].
- Median latency about 1.19 s.

| Metric | Result | 95% CI |
|---|---|---|
| Exact spec | 57/60 = 0.950 | [0.889, 1.000] |
| Figures match | 72/75 = 0.960 | [0.907, 1.000] |
| False acceptance | 0/75 | n/a |
| False refusal | 3/75 | n/a |
| Refusal precision | 15/18 = 0.833 | [0.636, 1.000] |
| Refusal recall | 15/15 = 1.000 | [1.000, 1.000] |

**Chart:** stacked bar of the 75 outcomes: 57 exact, 15 correct refusals, 3 false refusals. Data: `data/d5_dashboard.csv`.

**Interpretation.** The closed spec behaves safely on this set: the only failures were cautious ones.

**Caveat.** References are `ai_proposed`, with deterministic figures. Requests are template-worded, so this does not show robustness to free phrasing. Dev and test are not comparable. Single model. Activation on the shared agent should be checked before a demo.

**Sources:** `data/d5_dashboard.csv`; `/home/hengz/evalv2-data/v2/runs/c3-dashboard/scoring/evalv2-dashboard-score-v1/primary/dashboard-summary.json`.

## 6. Model Efficiency

**Title:** Nano was the fastest valid-report model; the outage, not reasoning, dominated Super's numbers.

**Findings**
- Answered latency p50: Nano 7.82 s, Gemma 15.17 s, Omni 23.96 s, Super 40.15 s, Qwen 63.05 s.
- Super made 170 attempts for 50 valid outputs: 83 timeouts and 37 rate limits. Most timeouts sit at the ~125 s HTTP 524 limit. This is an availability finding.
- Attempts per valid output: Gemma and Qwen 1.69, Nano 1.95, Super 3.40, Omni 3.40.
- Measured spend: Gemma $0.1197 ($0.0018 per valid output), Qwen $0.2555 ($0.0039). Switchyard calls show no price, so "free" is not a real cost.
- The VSS contingency used a median 23,813 tokens and 41.64 s per clip, about 2.4× and 5× direct Nano.

| Config | Attempts | Valid | Timeouts / rate limits / other infra | Median tokens | p50 / p95 s, answered | p95 s, all | Cost USD |
|---|---|---|---|---|---|---|---|
| Nano direct | 185 | 95 | 41 / 18 / 16 | 9,922 | 7.82 / 103.59 | 125.25 | not recorded |
| Omni direct | 214 | 63 | 0 / 104 / 1 | 18,398 | 23.96 / 67.95 | 67.13 | not recorded |
| Super direct | 170 | 50 | 83 / 37 / 0 | 7,216.5 | 40.15 / 114.50 | 125.32 | not recorded |
| Gemma direct | 110 | 65 | 0 / 0 / 3 | 6,727 | 15.17 / 37.88 | 37.42 | 0.1197 |
| Qwen direct | 110 | 65 | 0 / 0 / 5 | 13,319 | 63.05 / 341.21 | 336.82 | 0.2555 |
| VSS Nano contingency | 55 | 50 | 0 / 0 / 1 | 23,813 | 41.64 / 94.46 | 184.38 | not recorded |
| Ultra chart | 75 | 75 | 0 / 0 / 0 | 942 | 1.19 / 5.89 | 5.89 | not recorded |

Pipeline tokens by stage, contingency totals over 50 answered clips: inference 575,966; caption 386,723 (30 clips); zoom 330,549 (973 calls); grounding 114,805 (367 calls).

**Chart:** horizontal bars of attempts by outcome per model; latency dot plot of p50 and p95. Data: `data/d6_efficiency.csv`, `data/d6_pipeline_stage_tokens.csv`.

**Interpretation.** Reliability and rate limits, not raw speed, set the throughput a deployment would see.

**Caveat.** Runs came at different times on shared endpoints, so latency is descriptive. Nano and Omni answers mostly came during a recovery window. Super's low token count is from 26 outputs. Full-stack production latency, with tracking on, is not measured. Omni's 1 further item (Explosion004 repeat 1) is an A1 crash record scored from its stored reply, so it has no attempt row.

**Sources:** `data/efficiency_raw.json`, `data/d6_efficiency.csv`, `data/d6_pipeline_stage_tokens.csv`.

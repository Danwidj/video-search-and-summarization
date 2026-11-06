# Object F1: old slide against C3 Track A (reproducibility audit)

**Read-only and exploratory.** It changes no score, GT, scoring code, frozen file or existing result. Written 2026-11-05. Evidence tags: **[M]** measured from saved records, **[I]** my inference. Super on the evaluation half is the frozen 26-row snapshot, **INCOMPLETE**; A5-s was not read. No VLM, judge or API call; MiniLM ran locally for 545 texts that no run had embedded (rejected replies and one-sided blocks), used only by the diagnostics (§7, and the near-duplicate and cross-kind counts).

## Reporting defect that changes reported figures

**No scorer bug.** Every stored count replays exactly. The defect is in which denominator the C3 object figures use, and in how they are described. **[M]**

- `evaluation-v2-preregistration.md` §4.2–4.3 fixes two object views: **conditional** (primary; "valid outputs (pooled items)") and **end to end** ("an invalid or missing output contributes every ground-truth item as missed").
- `d2_object_identification.csv`, `master-results.md` and `slides-six-dimensions.md` use neither. `v2_c3_presentation_data.d2_rows` takes `aggregate(rows)["continuity_v1"]`: an invalid output is a miss, and a run with **no output is dropped**. Every C3 figure in the request is this third view.
- `slides-six-dimensions.md` then says "Scores are over valid outputs". **That sentence is false for those numbers.**
- The correct conditional counts already exist in `results-final/c3-final-analysis.json` (`assets_cond_precision`, `assets_cond_recall`), and the pre-registered paired test uses both-valid items, so that test is not affected. `diagnostics/objects-crops.md` and `object-threshold-sensitivity/README.md` inherit the chart's view; the first also calls scoring these as misses "the pre-registered rule", which is true only of view 3.

| Model | Kind | Chart (C3 as reported) | Pre-registered conditional (valid only) | Pre-registered end to end |
|---|---|---|---|---|
| Nano | assets | .448 | .463 | .448 |
| Nano | instruments | .286 | .321 | .286 |
| Omni | assets | .271 | .391 | .271 |
| Omni | instruments | .122 | .140 | .122 |
| Super (incomplete) | assets | .216 | .216 | – |
| Super (incomplete) | instruments | .222 | .222 | – |
| Qwen | assets | .468 | .573 | .456 |
| Qwen | instruments | .146 | .261 | .146 |
| Gemma | assets | .425 | .591 | .417 |
| Gemma | instruments | .195 | .276 | .195 |

Object score, evaluation half (the pre-registered primary metric):

| Model | Chart | Pre-registered conditional [95%] | Pre-registered end to end |
|---|---|---|---|
| Nano | .427 | .460 [.380, .542] | .427 |
| Omni | .329 | .453 [.368, .539] | .329 |
| Super (incomplete) | .348 | .348 [.256, .530] | – |
| Qwen | .425 | .588 [.505, .662] | .415 |
| Gemma | .447 | .627 [.555, .693] | .438 |

Conditional, the order is Gemma > Qwen > Nano > Omni. On the chart it is Gemma > Nano > Qwen > Omni. By asset F1, the chart order Qwen > Nano > Gemma > Omni becomes Gemma > Qwen > Nano > Omni ([`rankings.csv`](rankings.csv)). I did not change the chart: the owner should decide on relabelling or replacing it.

**Minor:** Super's C3 asset F1 is 42/194 = 0.21649, so 0.216 (as in `master-results.md`), not 0.217. The 0.217 in the request and on the slide text comes from rounding the stored 0.2165 a second time.

## Answers

| # | Question | Answer |
|---|---|---|
| 1 | Do the old "C2" numbers match the original evaluation? | **Yes, all 10, exactly, but it is not C2.** They are the dev pilot's valid-only figures: C1a + C1a-recovery, C1e, C1f. All five models come from one source, not a mix. C2 is the freeze step and scored nothing. The deck itself says "Development benchmark · Valid outputs only" and never says C2. **[M]** |
| 2 | Are C2 and C3 directly comparable? | **No.** The clips are disjoint (25 and 55, overlap 0) and the statistics differ (valid-only against invalid-as-miss). Super is also incomplete. Prompt, contract, settings, GT, τ, embedder, matcher, object scorer and repeats are the same. **[M]** |
| 3 | Why did Gemma asset F1 fall 70.4 to 42.5? | **−27.9 points: −16.6 is the invalid rule, −11.4 is left.** 58 of the 86 FNs come from 42 rejected replies. The −11.4 has an unpaired interval of [−32.7, +9.8]. FP and FN per valid row barely moved (.46 to .51, .42 to .43); GT per valid row fell 1.46 to 1.11. When all rejected replies are re-matched, the two halves are .693 and .657 (diagnostic). **[M]** The remaining gap reads as selection of which clips passed the contract plus a 13-clip source, not a weaker model. **[I]** |
| 4 | Why did Qwen instrument F1 fall 35.0 to 14.6? | **−20.4 points: −11.5 is the invalid rule, −8.9 is left** [−47.4, +19.5]. 18 of 28 GT instruments sit in rows that failed (40 empty replies). GT instruments per valid row fell .68 to .15, while FP per row held at about .18 to .15, so precision fell .50 to .23. 6 of the 7 dev TPs are Assault clips; C3's valid Assault rows hold no GT instrument. C3 has 3 TPs. **[M]** Too few items to read as a capability change. **[I]** |
| 5 | Did models perform worse, or did the methodology change? | **Neither is shown.** The scoring method did not change. The reported statistic and the clips did. On one rule, all 15 model-by-kind gaps have unpaired intervals that include zero, in both directions, and four of five object scores rise. Reliability did change: Qwen 76% to 59% valid, Nano 96% to 86%, Gemma 48% to 59%, Omni 52% to 57%. **[M]** Model or provider drift cannot be excluded or isolated. **[I]** |
| 6 | Which results are the primary benchmark? | **C3 Track A, pre-registered conditional object score, always beside validity and end-to-end.** Per-kind F1 is secondary. Super stays incomplete until A5-s is resolved. Dev figures are pilot figures. The chart's view is neither; show it only if relabelled. |
| 7 | Should the presentation include a C2-vs-C3 comparison? | **No, not as a result.** A drop chart would present a change of denominator and clips as a decline. Keep the dev table as an annex (the 5 Nov annex slide already warns against comparing). If asked, use the like-for-like table in §6, marked exploratory. |

## Three presentation findings

1. **70.4% and 35.0% were pilot figures, not benchmark results.** They are valid-only on 25 development clips. Gemma's rests on 24 runs of 13 clips, 35 GT assets. *Caveat:* the 48% validity beside it was on the slide; the figures are right, the label "C2" is not.
2. **Under one rule, no drop is distinguishable from clip and sample differences.** Gemma assets −11.4 [−32.7, +9.8], Omni assets −10.9 [−38.4, +21.2], Qwen instruments −8.9 [−47.4, +19.5]. *Caveat:* the clips are disjoint, so these are unpaired and descriptive; they are not evidence that the models are equal.
3. **Object F1 mixes contract compliance with object quality.** Gemma's C3 asset F1 is .591 on valid runs, .417 end to end, and .657 if rejected replies are re-matched. 41 of its 42 rejections are timestamps beyond the clip. *Caveat:* the re-match is a diagnostic, never a score; the contract rule stands.

## 1. Where the figures come from

**Chain [M]:** raw `offline-videos.jsonl` → `reports/track-a-five-models/track-a-report.json` (2 Nov 17:16, `subjects.*.valid.objects`) → `methodology/results/v2-dev/track_a_models.csv` (commit `08da1840e`) and `Comprehensive Evaluation V2 Results.xlsx`, sheet `09_Object_Results` → `Evaluation_V2_Object_Identification_Three_Slides.pptx`, slides 11–12 (3 Nov 15:21, in the owner's Downloads). The same figures reappear in later decks; the 5 Nov `FYP_Finals_*` decks carry them as an annex marked as not the C3 results.

The deck was saved before C3 started (15:50 SGT on 3 Nov), and it states "Held-out C3 results not yet available". I read only project-named decks there, and only their text.

| Item | Source figures | C3 Track A |
|---|---|---|
| Experiments | `v2-c1a-track-a-pilot`, `-recovery-super`, `v2-c1e-openrouter-gemma4-31b`, `v2-c1f-openrouter-qwen35-9b`; 2 Nov | `v2-c3-track-a-switchyard`, `-recovery`, `-recovery-a5a`, `-openrouter`; 3–4 Nov |
| Endpoint models | `nvidia/cosmos-3-nano-reasoner`, `-super-reasoner`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (Switchyard); `google/gemma-4-31b-it`, `qwen/qwen3.5-9b` (OpenRouter) | Same ids, same provider order. No weight pin is exposed |
| Clips, repeats | `split-v2` dev, 25 × 2 | `split-v2` test, 55 × 2 (Super: 26 clips, repeat 1 only) |
| Prompt, contract | `p1-v4-base` `409ed9b3187a`, `incident-contract-v4`, settings `a3bd2c27b27c` | Same hashes |
| GT | `ground-truth-v1.0`, `b90654c3c160` | Same hash |
| τ, embedder, matcher | 0.40, all-MiniLM-L6-v2, cosine, Hungarian then filter | Same |
| Scorer | `evalv2-score-stage-v3`; `aggregate.py` `4cb963a7`, `incident_objects/scoring.py` `34add9e3` | Same two hashes. `score_stage.py` differs (`c5454a99`, `86b1152f`) in judge plumbing; the replay proves the counts agree |
| F1 | Micro, pooled over **contract-valid** rows | Micro, pooled over rows with **any model output** (invalid as miss, no-output dropped) |

Per-run detail: [`provenance.csv`](provenance.csv).

**The clue resolved.** The D2 dev-25 rows are not a different experiment. They are the same runs under the chart's view, which is why Nano matches (its two failed rows are on a clip with no assets or instruments) and Omni, Gemma and Qwen do not. Super's .4055 and .4093 are also the same counts: **.4093 is after recovery, valid only; .4055 is after recovery, invalid as miss.** Before recovery (36 rows) Super was .4025 and .1463. The OpenRouter pilots are the source for Gemma and Qwen. No scorer version, repeat subset or macro F1 is involved: macro gives Gemma .656 and Omni .297. **[M]**

**τ 0.40 or 0.75: 0.40 on both sides. [M]** 0.75 was the pre-registered V1.1 value (`config.MIN_MATCH_SIMILARITY`). `methodology.MATCH_THRESHOLD` has been 0.40 since `21c4266d5` (28 Oct), before every run here. The lowest stored accepted pair is .4015 on dev and .4001 on C3, and only 11 of 377 and 38 of 625 stored pairs reach 0.75. At 0.75 Gemma's dev asset F1 would be .028. τ provenance and limits: [`object-threshold-sensitivity/README.md`](../object-threshold-sensitivity/README.md), not repeated here.

## 2. Scoring rules audit

| Question | Finding [M] |
|---|---|
| Pooled micro or macro? | Micro on both: tp, fp and fn are summed, then F1 |
| One-to-one? | Yes, `linear_sum_assignment`, per clip, kind, run |
| Assignment before threshold? | Yes; effect known to be small (see the threshold README) |
| Within kind? | Yes. Only 1 of the 6 Qwen cross-kind candidates inspected is a real ambiguity ([`cross_kind.csv`](cross_kind.csv), group QI5) |
| Duplicates | Extra copies count as FP under one-to-one. Near-duplicates (cos ≥ .85): Super assets 20 of 157 on dev, 100 of 159 on C3 |
| Invalid lists | A rejected reply is scored from an **empty** prediction. No invalid row holds a prediction (0 blocks), so rejected rows add FN and never FP |
| Embeddings or labels? | Embeddings of `name description` (`type description` for entities). No label, synonym or alias logic |
| Scorer changes since dev | None to object scoring. `aggregate.py`, `incident_objects/scoring.py` hashes equal; `matching.py` and `methodology.py` unchanged since 28 Oct |

## 3. Populations

**Disjoint [M]:** `split-v2` dev 25, test 55, overlap 0, by design. **A same-clip comparison cannot be done**, so clip difficulty, model or provider drift and run-to-run variation cannot be separated. No GT object appears on both sides.

| | Dev | C3 |
|---|---|---|
| Clips (Animal / Assault / Burglary / Explosion / Road) | 25 (5 / 5 / 5 / 5 / 5) | 55 (10 / 10 / 13 / 10 / 12) |
| Median, mean clip length, s | 49, 64 | 42, 62 |
| GT entities per clip | 2.00 | 2.16 |
| GT assets per clip | 1.20 | 1.22 |
| **GT instruments per clip** | **0.72** (18 on 9 clips) | **0.25** (14 on 9 clips) |
| Assault instruments | 9 on 4 of 5 clips | 4 on 2 of 10 clips |
| Definitions, guideline, GT file | Same `ground-truth-v1.0` | Same |

Asset density matches; **instrument density is about three times lower on C3**, a real difference between the halves, not a scoring change. Mean GT text length is a little longer on C3 for assets (24.5 to 28.3 words). Full table: [`populations.csv`](populations.csv).

| Model | Dev: scored / invalid / parse fail / no output of 50 | C3: same, of 110 | Dev valid rate | C3 valid rate |
|---|---|---|---|---|
| Nano | 48 / 0 / 2 / 0 | 95 / 0 / 15 / 0 | 96% | 86% |
| Omni | 26 / 20 / 4 / 0 | 63 / 23 / 24 / 0 | 52% | 57% |
| Super | 49 / 1 / 0 / 0 | 26 / 0 / 0 / 84 (84 open, outage) | 98% | 24% |
| Qwen | 38 / 2 / 9 / 1 | 65 / 0 / 40 / 5 | 76% | 59% |
| Gemma | 24 / 26 / 0 / 0 | 65 / 42 / 0 / 3 | 48% | 59% |

Validity is by contract, so each model's valid rows are a different selection, and that selection is not random:

| Model | Half | Valid rows by Animal / Assault / Burglary / Explosion / Road | Mean clip s, valid / invalid | GT assets per valid row | GT instruments per valid row |
|---|---|---|---|---|---|
| Nano | Dev | 8 / 10 / 10 / 10 / 10 | 66 / 16 | 1.25 | 0.75 |
| Nano | C3 | 20 / 15 / 20 / 20 / 20 | 54 / 113 | 1.29 | 0.22 |
| Omni | Dev | 8 / 4 / 2 / 6 / 6 | 49 / 80 | 1.08 | 0.69 |
| Omni | C3 | 9 / 12 / 20 / 13 / 9 | 72 / 47 | 1.16 | 0.35 |
| Super | Dev | 10 / 10 / 9 / 10 / 10 | 64 / 60 | 1.18 | 0.73 |
| Super | C3 | 5 / 4 / 5 / 5 / 7 | 51 / – | 1.35 | 0.23 |
| Qwen | Dev | 8 / 9 / 3 / 8 / 10 | 39 / 138 | 1.03 | 0.68 |
| Qwen | C3 | 13 / 11 / 9 / 15 / 17 | 42 / 92 | 1.31 | 0.15 |
| Gemma | Dev | 3 / 4 / 8 / 5 / 4 | 96 / 34 | 1.46 | 1.08 |
| Gemma | C3 | 11 / 13 / 20 / 12 / 9 | 76 / 36 | 1.11 | 0.25 |

Gemma's rejections fall on short clips in both halves (mean 34 and 36 s, against 96 and 76 s for its valid rows). Its rejection code is the same too: `WINDOW_BEYOND_VIDEO` on 26 of 26 dev rejections and 41 of 42 on C3. Qwen is the reverse: it fails on longer clips (138 and 92 s), and on C3 its valid rows include only 9 of 26 Burglary runs, where most instruments are. **[M]**

## 4. Reproduction

| Check | Result [M] |
|---|---|
| Slide cells from raw rows, offline and live | **10 of 10** at 3 decimals; offline and live identical |
| `track-a-report.json`, `track_a_models.csv` | Equal to recomputation |
| Stored counts against replay at 0.40 | 747 + 1,371 blocks, **0 mismatches**. 4 blocks pair differently, all ties, same counts |
| `d2_object_identification.csv`, P1 cells | 30 of 30 match by tp, fp, fn |
| Threshold-study sweep cells | 240 of 240 match |
| Local MiniLM against stored vectors | Lowest cosine 0.99999997 on 25 probes |

| Model | Kind | Slide | Recomputed (offline = live) | TP / FP / FN | GT / predicted | Valid rows / clips | Per-clip macro | Same counts, invalid as miss |
|---|---|---|---|---|---|---|---|---|
| Nano | assets | .408 | 0.4082 | 40 / 96 / 20 | 60 / 136 | 48 / 24 | .381 | .408 |
| Nano | instruments | .235 | 0.2353 | 6 / 9 / 30 | 36 / 15 | 48 / 24 | .212 | .235 |
| Omni | assets | .500 | 0.5000 | 13 / 11 / 15 | 28 / 24 | 26 / 16 | .297 | .310 |
| Omni | instruments | .214 | 0.2143 | 3 / 7 / 15 | 18 / 10 | 26 / 16 | .133 | .130 |
| Super | assets | .409 | 0.4093 | 44 / 113 / 14 | 58 / 157 | 49 / 25 | .358 | .406 |
| Super | instruments | .258 | 0.2581 | 8 / 18 / 28 | 36 / 26 | 49 / 25 | .211 | .258 |
| Qwen | assets | .423 | 0.4231 | 22 / 43 / 17 | 39 / 65 | 38 / 21 | .365 | .358 |
| Qwen | instruments | .350 | 0.3500 | 7 / 7 / 19 | 26 / 14 | 38 / 21 | .345 | .304 |
| Gemma | assets | .704 | 0.7042 | 25 / 11 / 10 | 35 / 36 | 24 / 13 | .656 | .521 |
| Gemma | instruments | .207 | 0.2069 | 3 / 0 / 23 | 26 / 3 | 24 / 13 | .178 | .154 |

## 5. Decomposition, both sides

Intervals: clip-cluster bootstrap, seed 20261027 (C3 side 20261028), 2,000 resamples, over evaluated clips. Omitted "invalid as miss" rows equal the valid row. Entities and extra columns: [`decomposition.csv`](decomposition.csv). Categories: [`category_cells.csv`](category_cells.csv).

**Assets**

| Model | Side, view | Rows / clips | GT / predicted | TP / FP / FN | P | R | F1 [95%] |
|---|---|---|---|---|---|---|---|
| Nano | Dev, valid | 48 / 24 | 60 / 136 | 40 / 96 / 20 | .294 | .667 | .408 [.315, .519] |
| Nano | Dev, invalid as miss | 50 / 25 | 60 / 136 | 40 / 96 / 20 | .294 | .667 | .408 [.315, .517] |
| Nano | C3, valid | 95 / 49 | 123 / 214 | 78 / 136 / 45 | .364 | .634 | .463 [.352, .570] |
| Nano | C3, invalid as miss | 110 / 55 | 134 / 214 | 78 / 136 / 56 | .364 | .582 | .448 [.346, .551] |
| Omni | Dev, valid | 26 / 16 | 28 / 24 | 13 / 11 / 15 | .542 | .464 | .500 [.195, .724] |
| Omni | Dev, invalid as miss | 50 / 25 | 60 / 24 | 13 / 11 / 47 | .542 | .217 | .310 [.103, .511] |
| Omni | C3, valid | 63 / 39 | 73 / 65 | 27 / 38 / 46 | .415 | .370 | .391 [.222, .531] |
| Omni | C3, invalid as miss | 110 / 55 | 134 / 65 | 27 / 38 / 107 | .415 | .201 | .271 [.153, .391] |
| Super | Dev, valid | 49 / 25 | 58 / 157 | 44 / 113 / 14 | .280 | .759 | .409 [.319, .494] |
| Super | Dev, invalid as miss | 50 / 25 | 60 / 157 | 44 / 113 / 16 | .280 | .733 | .406 [.316, .490] |
| Super | C3, valid | 26 / 26 | 35 / 159 | 21 / 138 / 14 | .132 | .600 | .216 [.100, .532] |
| Qwen | Dev, valid | 38 / 21 | 39 / 65 | 22 / 43 / 17 | .338 | .564 | .423 [.247, .587] |
| Qwen | Dev, invalid as miss | 49 / 25 | 58 / 65 | 22 / 43 / 36 | .338 | .379 | .358 [.211, .507] |
| Qwen | C3, valid | 65 / 41 | 85 / 107 | 55 / 52 / 30 | .514 | .647 | .573 [.446, .682] |
| Qwen | C3, invalid as miss | 105 / 55 | 128 / 107 | 55 / 52 / 73 | .514 | .430 | .468 [.350, .568] |
| Gemma | Dev, valid | 24 / 13 | 35 / 36 | 25 / 11 / 10 | .694 | .714 | .704 [.532, .866] |
| Gemma | Dev, invalid as miss | 50 / 25 | 60 / 36 | 25 / 11 / 35 | .694 | .417 | .521 [.324, .678] |
| Gemma | C3, valid | 65 / 35 | 72 / 77 | 44 / 33 / 28 | .571 | .611 | .591 [.453, .715] |
| Gemma | C3, invalid as miss | 107 / 55 | 130 / 77 | 44 / 33 / 86 | .571 | .338 | .425 [.297, .539] |

**Instruments**

| Model | Side, view | Rows / clips | GT / predicted | TP / FP / FN | P | R | F1 [95%] |
|---|---|---|---|---|---|---|---|
| Nano | Dev, valid | 48 / 24 | 36 / 15 | 6 / 9 / 30 | .400 | .167 | .235 [.000, .500] |
| Nano | Dev, invalid as miss | 50 / 25 | 36 / 15 | 6 / 9 / 30 | .400 | .167 | .235 [.000, .500] |
| Nano | C3, valid | 95 / 49 | 21 / 35 | 9 / 26 / 12 | .257 | .429 | .321 [.062, .528] |
| Nano | C3, invalid as miss | 110 / 55 | 28 / 35 | 9 / 26 / 19 | .257 | .321 | .286 [.064, .476] |
| Omni | Dev, valid | 26 / 16 | 18 / 10 | 3 / 7 / 15 | .300 | .167 | .214 [.000, .432] |
| Omni | Dev, invalid as miss | 50 / 25 | 36 / 10 | 3 / 7 / 33 | .300 | .083 | .130 [.000, .299] |
| Omni | C3, valid | 63 / 39 | 22 / 21 | 3 / 18 / 19 | .143 | .136 | .140 [.000, .353] |
| Omni | C3, invalid as miss | 110 / 55 | 28 / 21 | 3 / 18 / 25 | .143 | .107 | .122 [.000, .316] |
| Super | Dev, valid | 49 / 25 | 36 / 26 | 8 / 18 / 28 | .308 | .222 | .258 [.062, .435] |
| Super | Dev, invalid as miss | 50 / 25 | 36 / 26 | 8 / 18 / 28 | .308 | .222 | .258 [.062, .435] |
| Super | C3, valid | 26 / 26 | 6 / 3 | 1 / 2 / 5 | .333 | .167 | .222 [.000, .727] |
| Qwen | Dev, valid | 38 / 21 | 26 / 14 | 7 / 7 / 19 | .500 | .269 | .350 [.143, .621] |
| Qwen | Dev, invalid as miss | 49 / 25 | 32 / 14 | 7 / 7 / 25 | .500 | .219 | .304 [.121, .526] |
| Qwen | C3, valid | 65 / 41 | 10 / 13 | 3 / 10 / 7 | .231 | .300 | .261 [.000, .471] |
| Qwen | C3, invalid as miss | 105 / 55 | 28 / 13 | 3 / 10 / 25 | .231 | .107 | .146 [.000, .345] |
| Gemma | Dev, valid | 24 / 13 | 26 / 3 | 3 / 0 / 23 | 1.000 | .115 | .207 [.000, .421] |
| Gemma | Dev, invalid as miss | 50 / 25 | 36 / 3 | 3 / 0 / 33 | 1.000 | .083 | .154 [.000, .308] |
| Gemma | C3, valid | 65 / 35 | 16 / 13 | 4 / 9 / 12 | .308 | .250 | .276 [.000, .412] |
| Gemma | C3, invalid as miss | 107 / 55 | 28 / 13 | 4 / 9 / 24 | .308 | .143 | .195 [.000, .353] |

## 6. Harmonisation, step by step

Common clip ids do not exist, so every interval below is **unpaired** (two independent clip bootstraps) and descriptive. No paired test is possible, and no significance is claimed from point estimates. Points are F1 × 100. Steps 2 to 5 are checks that found no difference: both sides already use τ 0.40, the same matcher, micro F1 and two repeats (Super on C3 has repeat 1 only, so it cannot be equalised). Repeat-only and macro variants: [`harmonisation_ladder.csv`](harmonisation_ladder.csv).

| Model | Kind | Source (dev valid) | C3 reported | Steps 2–5 (τ, matcher, micro, repeats) | C3 valid only | Effect of invalid handling | Gap left, valid vs valid [unpaired 95%] | Dev invalid as miss | Gap, invalid as miss both [unpaired 95%] |
|---|---|---|---|---|---|---|---|---|---|
| Nano | assets | .408 | .448 | 0.0 | .463 | −1.5 | +5.5 [−10.3, +19.1] | .408 | +4.0 [−10.9, +17.9] |
| Nano | instruments | .235 | .286 | 0.0 | .321 | −3.6 | +8.6 [−27.5, +38.5] | .235 | +5.0 [−29.6, +34.5] |
| Omni | assets | .500 | .271 | 0.0 | .391 | −12.0 | −10.9 [−38.4, +21.2] | .310 | −3.8 [−27.5, +20.2] |
| Omni | instruments | .214 | .122 | 0.0 | .140 | −1.7 | −7.5 [−38.5, +24.7] | .130 | −0.8 [−27.0, +24.0] |
| Super | assets | .409 | .216 | 0.0 | .216 | +0.0 | −19.3 [−34.0, +13.5] | .406 | −18.9 [−33.6, +13.8] |
| Super | instruments | .258 | .222 | 0.0 | .222 | +0.0 | −3.6 [−39.3, +51.5] | .258 | −3.6 [−39.3, +51.5] |
| Qwen | assets | .423 | .468 | 0.0 | .573 | −10.5 | +15.0 [−4.9, +35.5] | .358 | +11.0 [−7.9, +27.7] |
| Qwen | instruments | .350 | .146 | 0.0 | .261 | −11.5 | −8.9 [−47.4, +19.4] | .304 | −15.8 [−42.9, +10.0] |
| Gemma | assets | .704 | .425 | 0.0 | .591 | −16.5 | −11.4 [−32.7, +9.8] | .521 | −9.6 [−30.0, +13.5] |
| Gemma | instruments | .207 | .195 | 0.0 | .276 | −8.1 | +6.9 [−25.8, +34.8] | .154 | +4.1 [−20.0, +28.6] |

The effect of invalid handling depends on the side it is applied to: moving dev to C3's rule instead lowers Gemma from .704 to .521. With no-output rows counted as well (view 3), Gemma assets becomes .417 and Qwen assets .456 on C3; no other C3 cell moves. On dev only Qwen moves (assets .358 to .352, instruments .304 to .280).

**Rates per valid row:** is the remainder more FP or more FN?

| Model | Kind | TP per valid row, dev → C3 | FP per valid row | FN per valid row | F1 change if only P moved | if only R moved |
|---|---|---|---|---|---|---|
| Nano | assets | 0.83 → 0.82 | 2.00 → 1.43 | 0.42 → 0.47 | +6.3 | −0.6 |
| Nano | instruments | 0.12 → 0.09 | 0.19 → 0.27 | 0.62 → 0.13 | −3.3 | +17.8 |
| Omni | assets | 0.50 → 0.43 | 0.42 → 0.60 | 0.58 → 0.73 | −6.2 | −6.0 |
| Omni | instruments | 0.12 → 0.05 | 0.27 → 0.29 | 0.58 → 0.30 | −6.0 | −2.7 |
| Super | assets | 0.90 → 0.81 | 2.31 → 5.31 | 0.29 → 0.54 | −18.4 | −2.7 |
| Super | instruments | 0.16 → 0.04 | 0.37 → 0.08 | 0.57 → 0.19 | +0.9 | −4.2 |
| Qwen | assets | 0.58 → 0.85 | 1.13 → 0.80 | 0.45 → 0.46 | +11.5 | +2.1 |
| Qwen | instruments | 0.18 → 0.05 | 0.18 → 0.15 | 0.50 → 0.11 | −10.1 | +2.5 |
| Gemma | assets | 1.04 → 0.68 | 0.46 → 0.51 | 0.42 → 0.43 | −6.9 | −5.4 |
| Gemma | instruments | 0.12 → 0.06 | 0.00 → 0.14 | 0.96 → 0.18 | −3.9 | +19.3 |

### Causes, ranked

| Rank | Cause | Evidence | Status |
|---|---|---|---|
| 1 | **Denominator (invalid handling)** | 52 to 59% of the reported fall for Gemma assets, Omni assets, Qwen instruments | Measured |
| 2 | **Different clips and valid subsets** | Omni's C3 valid F1 is .504 at dev's category mix, against dev .500. Instruments per clip .72 to .25 | Measured, cause inferred |
| 3 | **Small samples** | Gemma source 13 clips; Qwen instruments 7 TP, then 3 TP. Every gap interval spans zero | Measured |
| 4 | **Output behaviour** | Super: one run, RoadAccidents060, holds 98 of 138 FP. Without it .413 against dev .409 (sensitivity, not a score). Qwen empty replies 9 of 50 to 40 of 110 | Measured |
| 5 | More FP | Large only for Super assets (FP per valid row 2.31 to 5.31). Omni assets .42 to .60. Others small or lower | Measured |
| 6 | More FN | Per valid row only Omni assets (.58 to .73) and Super assets (.29 to .54). FN growth on the chart comes from rejected rows | Measured |
| 7 | Harder clips | **Not supported for assets**: Nano, the one complete and nearly fully valid model, rises .408 to .463 on valid rows. Instruments differ in prevalence, not shown harder | Inferred |
| 8 | GT | Same version. GT gaps exist on both sides (GA5). No GT change | Measured; size not estimated here |
| 9 | Labels or semantic matching | Same text rule both sides. False rejects and accepts appear in both halves (GA3, OA3, SA2) | Examples only |
| 10 | Stricter matching, aggregation | **None.** Same τ, same matcher, micro on both | Measured |

By cell: **Gemma assets** 1, 2, 3. **Omni assets** 1, 2. **Super assets** 4, incomplete run. **Qwen instruments** 1, 2 (prevalence), 3. **Nano** rises on every view.

## 7. Closest valid alternatives

Same-clip comparison is impossible, so these are stand-ins. All are exploratory.

| Model | Kind | Dev valid | C3 valid | C3 at dev category mix | Dev at C3 mix | Equal categories, dev / C3 | Without top-FP row, dev / C3 | Rejected replies re-matched, dev / C3 (diagnostic) |
|---|---|---|---|---|---|---|---|---|
| Nano | assets | .408 | .463 | .461 | .413 | .405 / .456 | .422 / .470 | .408 / .448 |
| Nano | instruments | .235 | .321 | .326 | .242 | .235 / .322 | .240 / .360 | .235 / .286 |
| Omni | assets | .500 | .391 | .504 | .421 | .459 / .462 | .511 / .406 | .384 / .329 |
| Omni | instruments | .214 | .140 | .060 | .128 | .154 / .108 | .222 / .146 | .328 / .115 |
| Super | assets | .409 | .216 | .222 | .433 | .411 / .224 | .413 / .413 | .400 / .216 |
| Super | instruments | .258 | .222 | .198 | .234 | .250 / .211 | .302 / .333 | .254 / .222 |
| Qwen | assets | .423 | .573 | .574 | .458 | .456 / .525 | .436 / .588 | .362 / .468 |
| Qwen | instruments | .350 | .261 | .261 | .262 | .235 / .242 | .438 / .273 | .292 / .146 |
| Gemma | assets | .704 | .591 | .617 | .685 | .717 / .614 | .727 / .607 | .693 / .656 |
| Gemma | instruments | .207 | .276 | .297 | .216 | .243 / .234 | .207 / .296 | .273 / .280 |

- **Difficulty through a common model.** Nano rises on valid rows: assets .408 to .463, instruments .235 to .321, object score .267 to .460. Its dev object score is held down by entity over-listing. Super cannot serve as an anchor: 26 rows, repeat 1, and an outage-selected subset. Its value without the one runaway row, .413, is close to dev. **[M]** Nothing here suggests the C3 clips are harder for assets. **[I]**
- **Category-reweighted.** Works well for Omni assets and little for Gemma (.591 to .617). Instrument cells are too small to read (Omni .140 to .060).
- **Common valid set within a half** (four complete models): dev 6 rows on 5 clips, C3 23 rows on 16 clips. The dev side is too small to use; values are in [`closest_views.csv`](closest_views.csv).
- **Valid-only against empty-report views:** §6, both directions.
- **Rejected replies re-matched:** real stored replies, not filled predictions; unparseable replies stay misses. Gemma .693 and .657 on assets, object score .591 and .621, the last reproducing `objects-crops.md`. Qwen and Nano barely change because their failures hold no text. Never a score.

## 8. Examples

The splits are disjoint, so **the same GT object cannot appear in both runs**. Rows in one group are parallel examples of the same behaviour, on different objects. All are real saved records. Candidates were drawn with seed 20261105 per cell, side and outcome, and classes are **one AI reader's, from stored text only, with no frame opened**. They illustrate; they do not estimate rates. Text, with GT object, prediction and class side by side: `/home/hengz/evalv2-data/v2/diagnostics/c2-c3-object-audit/examples.md`.

| Group | Cell | Side | Clip, repeat | GT / prediction id | Similarity | Match outcome | Class |
|---|---|---|---|---|---|---|---|
| GA1 | Gemma assets | dev | RoadAccidents017 r1 | A1 / A1 | 0.6582 | discarded_by_contract_would_match | different evaluated clip |
| GA1 | Gemma assets | C3 | RoadAccidents010 r2 | A1 / A1 | 0.8216 | discarded_by_contract_would_match | scoring difference |
| GA2 | Gemma assets | dev | Burglary093 r2 | A1 / – | – | fn_rejected_row | different evaluated clip |
| GA2 | Gemma assets | C3 | RoadAccidents008 r1 | A1 / – | – | fn_rejected_row | scoring difference |
| GA3 | Gemma assets | dev | Burglary004 r1 | A2 / A3 | 0.3842 | fp_fn_below_tau | synonym or semantic-matching |
| GA3 | Gemma assets | C3 | Burglary041 r1 | A2 / A1 | 0.4528 | tp | synonym or semantic-matching |
| GA4 | Gemma assets | dev | Assault015 r2 | – / A1 | – | fp_unassigned | genuine prediction difference |
| GA4 | Gemma assets | C3 | Animal007 r1 | – / A1 | – | fp_unassigned | genuine prediction difference |
| GA5 | Gemma assets | dev | Burglary004 r2 | – / A1 | 0.156704 | fp_unassigned | GT mismatch |
| GA5 | Gemma assets | C3 | Explosion051 r2 | – / A2 | 0.562678 | fp_unassigned | GT mismatch |
| OA1 | Omni assets | dev | RoadAccidents075 r1 | A2 / A2 | 0.7887 | discarded_by_contract_would_match | different evaluated clip |
| OA1 | Omni assets | C3 | RoadAccidents039 r1 | A1 / A1 | 0.6408 | discarded_by_contract_would_match | scoring difference |
| OA2 | Omni assets | dev | RoadAccidents012 r1 | A1 / A1 | 0.582 | tp | different evaluated clip |
| OA2 | Omni assets | C3 | Burglary020 r1 | A2 / – | – | fn_unassigned | genuine prediction difference |
| OA3 | Omni assets | dev | RoadAccidents017 r1 | A1 / A2 | 0.587 | tp | synonym or semantic-matching |
| OA3 | Omni assets | C3 | Burglary041 r2 | A1 / A1 | 0.3715 | fp_fn_below_tau | synonym or semantic-matching |
| OA4 | Omni assets | dev | Explosion028 r1 | – / A1 | 0.36492 | fp_unassigned | genuine prediction difference |
| OA4 | Omni assets | C3 | Explosion009 r1 | A1 / A2 | 0.3297 | fp_fn_below_tau | genuine prediction difference |
| SA1 | Super assets | dev | RoadAccidents012 r2 | – / A4 | 0.66346 | fp_unassigned | duplicate or hallucinated |
| SA1 | Super assets | C3 | RoadAccidents060 r1 | – / A88 | 0.445977 | fp_unassigned | duplicate or hallucinated |
| SA2 | Super assets | dev | RoadAccidents017 r2 | A1 / A4 | 0.6054 | tp | synonym or semantic-matching |
| SA2 | Super assets | C3 | RoadAccidents060 r1 | A2 / A3 | 0.5137 | tp | synonym or semantic-matching |
| SA3 | Super assets | dev | Burglary031 r1 | A2 / A2 | 0.3955 | fp_fn_below_tau | unresolved |
| SA3 | Super assets | C3 | RoadAccidents030 r1 | A2 / A2 | 0.3881 | fp_fn_below_tau | synonym or semantic-matching |
| SA4 | Super assets | dev | Assault007 r1 | A1 / A3 | 0.0476 | fp_fn_below_tau | unresolved |
| SA4 | Super assets | C3 | Burglary009 r1 | – / A3 | 0.071825 | fp_unassigned | unresolved |
| QI1 | Qwen instruments | dev | Assault011 r1 | I1 / I1 | 0.7317 | tp | different evaluated clip |
| QI1 | Qwen instruments | C3 | Assault013 r2 | I1 / – | – | fn_rejected_row | scoring difference |
| QI2 | Qwen instruments | dev | Assault011 r2 | I1 / I1 | 0.3256 | fp_fn_below_tau | synonym or semantic-matching |
| QI2 | Qwen instruments | C3 | Burglary036 r2 | I1 / I1 | 0.3495 | fp_fn_below_tau | unresolved |
| QI3 | Qwen instruments | dev | RoadAccidents051 r1 | – / I1 | – | fp_unassigned | duplicate or hallucinated |
| QI3 | Qwen instruments | C3 | Animal006 r2 | – / I1 | – | fp_unassigned | unresolved |
| QI4 | Qwen instruments | dev | Assault032 r2 | I1 / I1 | 0.6512 | tp | different evaluated clip |
| QI4 | Qwen instruments | C3 | Explosion004 r2 | I2 / I1 | 0.5681 | tp | different evaluated clip |
| QI5 | Qwen instruments | dev | Explosion002 r2 | I2 / A1 | 0.4229 | fn_filed_under_other_kind | synonym or semantic-matching |
| QI5 | Qwen instruments | C3 | Burglary052 r1 | I3 / A1 | 0.4945 | fn_filed_under_other_kind | category ambiguity |

`discarded_by_contract_would_match` is a pairing that a rejected reply would have got. The official score counts that GT item as FN. Dev rows of that type lie outside the slide's denominator altogether, hence "different evaluated clip"; C3 rows lie inside the chart's as misses, hence "scoring difference".

## 9. Threshold

Exploratory; nothing here proposes a change. The existing sweeps are in the chart's view, and I reproduced all 240 cells. Valid-view sweep: [`threshold_by_view.csv`](threshold_by_view.csv).

| Cell (valid view) | τ 0.30 dev / C3 (gap) | τ 0.40 | τ 0.50 | Gap sign over τ 0.20–0.50 |
|---|---|---|---|---|
| Gemma assets | .761 / .644 (−11.6) | .704 / .591 (−11.4) | .592 / .483 (−10.8) | always negative |
| Omni assets | .500 / .449 (−5.1) | .500 / .391 (−10.9) | .308 / .304 (−0.3) | always negative |
| Super assets | .437 / .247 (−19.0) | .409 / .216 (−19.3) | .326 / .113 (−21.2) | always negative |
| Qwen instruments | .450 / .348 (−10.2) | .350 / .261 (−8.9) | .300 / .174 (−12.6) | always negative |
| Nano assets | .408 / .546 (+13.8) | .408 / .463 (+5.5) | .327 / .320 (−0.6) | changes sign |

**τ does not explain the comparison. [M]** No common τ in 0.20–0.50 closes the Gemma, Super or Qwen gaps, and their sign holds across that range. Gemma reaches about zero only at 0.60, where both halves are low (.310, .322). Both halves move together, because both use the same rule. The size moves a lot in places (Omni's gap is −5.1 at 0.30, −10.9 at 0.40, −0.3 at 0.50), which is a warning about small cells, not a result. Nano changes sign near 0.45. The conclusion that 0.40 stays primary is unchanged.

## 10. Limits

- Unpaired, disjoint and small. The intervals describe sampling over clips, and they do not make the two halves exchangeable.
- The cause ranking is a reading of the ladder and per-row rates, and order matters: the effects are not additive, so the shares are one path through them.
- Reweighting uses five categories only. It does not adjust for clip length or the mechanism of rejection.
- Model weights are not pinned, and C3 ran one to two days after dev. Drift is not tested.
- Dev clips informed choices, and the evaluation clips were exposed earlier (see the threshold README), so neither half is unseen.
- Example classes are AI, text only, no frames, no human review.

## 11. Reproduce

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/eval
export OMP_NUM_THREADS=1
S=scripts/v2_c2_c3_object_audit.py
nice -n 19 uv run --frozen python $S embed      # local MiniLM, private cache; needed for §7 and cross_kind.csv
nice -n 19 uv run --frozen python $S audit      # every CSV and replay.json
nice -n 19 uv run --frozen python $S examples   # private candidates; index and examples.md from example-labels.json
nice -n 19 uv run --frozen pytest tests/v2/test_v2_c2_c3_object_audit.py -q
```

**Files:** [`source_figures.csv`](source_figures.csv), [`provenance.csv`](provenance.csv), [`populations.csv`](populations.csv), [`outcomes_and_valid_subsets.csv`](outcomes_and_valid_subsets.csv), [`decomposition.csv`](decomposition.csv), [`gap_attribution.csv`](gap_attribution.csv), [`harmonisation_ladder.csv`](harmonisation_ladder.csv), [`object_scores.csv`](object_scores.csv), [`closest_views.csv`](closest_views.csv), [`category_cells.csv`](category_cells.csv), [`threshold_by_view.csv`](threshold_by_view.csv), [`rankings.csv`](rankings.csv), [`cross_kind.csv`](cross_kind.csv), [`salvage_diagnostic.csv`](salvage_diagnostic.csv), [`examples_index.csv`](examples_index.csv), `replay.json`. Repo files hold ids, counts and scores. GT and prediction text stays in `/home/hengz/evalv2-data/v2/diagnostics/c2-c3-object-audit/`.

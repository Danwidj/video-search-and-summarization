# C3-E evaluation-half results v1: evidence crops (2026-11-05)

**EVALUATION HALF, AI-REFERENCED.** 55 previously exposed clips. References are C3-E v0.2 AI-consensus and AI-adjudicated annotations from one model family (Claude). They are **not human-verified**. IoU is agreement with AI boxes, not physical accuracy. Adjudication does not establish correctness. References favour objects a machine can find. The profile is historical, tracking off, not production. Freeze `34dd77553e50…` verified unchanged before and after the tiers. Rules were not changed after development results. Raw output: `v2/references/c3e-v1/results/c3e-test-v1.json` (private). Script: `scripts/v2_c3e_test_report.py`.

**Which run:** the VSS Nano contingency (A5-B), all stages on Nano. Original C3 Track B has only 2 scored Super runs, reported as counts. No Nano − Super comparison is possible on this half. Do not compare these values with the development table as a change: development used Super grounding on a different clip set.

## 1. Reference generation

| Stage | Count |
|---|---|
| Sampled box items / frames | 169 items, 695 generator frames, 691 validator frames |
| Second round (extra OWLv2 pass) | 96 items, 250 seconds |
| Box seconds | 695: consensus 202, adjudicated 135, unresolved 358 |
| Adjudication packets | 364 per order, two separate orders |
| Visibility seconds | consensus 10,104, adjudicated 243, unresolved 4,146 |
| Detector proposals | Sampled-frame OWLv2 for 26 clips where full RA1 had not reached; same runner and parameters |

## 2. Reference coverage at the evidence seconds

Unit: ground-truth object × anchor second of its own kind. `scripts/v2_c3e_anchor_coverage.py` reproduces the development table exactly.

| Kind | Object-seconds | Box reference (consensus + adjudicated) | "Not visible" | Timing-scorable | Visibility unresolved | Box unresolved | GT identity flag |
|---|---|---|---|---|---|---|---|
| Entities | 358 | 118 (72 + 46) | 86 | 228 | 119 | 24 | 11 |
| Assets | 115 | 77 (58 + 19) | 9 | 102 | 7 | 16 | 6 |
| Instruments | 13 | 3 (1 + 2) | 6 | 10 | 3 | 1 | 0 |
| **All** | **486** | **198 (131 + 67)** | **101** | **340** | **129** | **41** | **17** |

## 3. Evidence-generation reliability (no reference needed)

Contingency, 50 answered runs: 367 entries, 351 located (95.6%), 2 not located, 14 no verdict. The crop cap was reached in 1 run.

## 4. Results at IoU ≥ 0.5 (combined references), contingency

Of 367 entries, 251 belong to predicted items matched to no ground-truth object. 116 belong to matched items; 0 matched objects lacked evidence.

| Kind | Entries of matched items | Scorable | Correct evidence (conditional) [95% CI] | Correct over all matched | Median IoU | IoU ≥ 0.5 | Temporal alignment |
|---|---|---|---|---|---|---|---|
| All | 116 | 77 (66%) | **44/77 = 0.571** [0.471, 0.671] | 44/116 = 0.379 | 0.689 | 44/67 | 77/87 = 0.885 [0.798, 0.963] |
| Entities | 74 | 46 | 29/46 = 0.630 [0.500, 0.767] | 29/74 | 0.768 | 29/37 | 42/51 = 0.824 |
| Assets | 40 | 31 | 15/31 = 0.484 [0.290, 0.677] | 15/40 | 0.542 | 15/30 | 35/36 = 0.972 |
| Instruments | 2 | 0 | none scorable | 0/2 | n/a | n/a | n/a |

Outcome classes over 367: correct 44, spatial miss 23, temporal miss 10, unmatched 251, unscorable 29, temporal hit without a resolved box 10.

| Sensitivity | Value |
|---|---|
| Consensus-only | 25/51 = 0.490 [0.367, 0.612] |
| Adjudicated-only | 19/26 = 0.731 [0.591, 0.870] |
| IoU ≥ 0.3 / 0.5 / 0.7 | 46/77, 44/77, 33/77 |
| Bounds, unresolved as miss / hit, over matched entries | 0.379–0.716 |
| Excluding all noted GT items | 43/76 = 0.566 [0.468, 0.667] |

**Original C3 Super, 2 runs, counts only:** 10 entries, 3 matched, correct 2/3, temporal 2/3. Not interpretable.

## 5. What this supports

- **Supported:** with a scorable AI reference, the Nano contingency put the evidence box on the AI-referenced object 57% of the time; temporal alignment was 88.5%.
- **Supported:** 68% of entries (251/367) belong to predicted items matched to no ground-truth object.
- **Not supported:** any claim across all predicted evidence. Conditional IoU results cover 77 of 367 entries.
- **Not supported:** any Nano − Super conclusion on this half, any production claim, any human-verified accuracy claim, or instrument conclusions.
- The adjudicated-only subset again scores above consensus-only. This may be selection and is not a finding.

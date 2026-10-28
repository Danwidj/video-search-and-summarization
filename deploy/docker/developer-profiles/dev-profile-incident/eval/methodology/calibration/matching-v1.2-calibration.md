# Item-matching calibration for evaluation-methodology-v1.2 (provisional)

> **Provisional, 2026-10-28.** The labels are AI labels, pending the human audit that [methodology v1.2](../evaluation-methodology-v1.2.md#calibration-procedure-fixed-before-any-label-or-similarity-was-looked-at) requires. Neither the rule's result nor v1.2 is in force until the owner approves it. Machine-readable summary: [`matching-v1.2-calibration.json`](matching-v1.2-calibration.json).

## Inputs

| Item | Value |
|---|---|
| Source | Stage 1 dev results only: `direct-vlm-baseline` and `vss-baseline`, `20261028T031009Z` |
| Sample | 22 blocks, 70 pairs (entities 30, instruments 15, assets 25), all five categories, seed 20261028, ≤ 9 pairs per block |
| Label sheet | `eval_data/matching_calibration/label-sheet.json` (local; holds ground-truth text), SHA-256 `ac74663e5e87…` |
| Labels | `labels-ai-v1.jsonl` (local, read-only after labelling), SHA-256 `c53bae83b07f…` |
| Labeller | An AI subagent that **never saw a similarity value**. It had no access to results, provenance, the matcher or embeddings, and could not call any model. 45 of 70 pairs were checked against the clip's frames |
| Labels | 21 `same`, 41 `different`, 8 `ambiguous` |
| Sequence | Labels written and locked (hash recorded, file made read-only) before `evaluate` computed any similarity |

The ambiguous pairs are:
- **B16, Assault015, instruments, all four pairs:** two dark hand-held objects, told apart only by the holder ids.
- **B19, Burglary010, A1 against GT A1 and A2:** two identical ATMs side by side.
- **B21, Explosion028, A5 and A6 against GT A1:** a vague "building on the left/right".

## Result (pre-registered rule: highest pooled F1, ties within 0.01 to the higher τ)

| τ | TP | FP | FN | Precision | Recall | F1 (pooled) | F1 entities / instruments / assets |
|---|---|---|---|---|---|---|---|
| **0.30 (selected)** | 18 | 3 | 3 | 0.857 | 0.857 | **0.857** | 0.96 / 0.57 / 0.75 |
| 0.35 | 16 | 2 | 5 | 0.889 | 0.762 | 0.821 | 0.88 / 0.67 / 0.75 |
| 0.40 | 16 | 1 | 5 | 0.941 | 0.762 | 0.842 | 0.88 / 0.80 / 0.75 |
| 0.45 | 13 | 1 | 8 | 0.929 | 0.619 | 0.743 | 0.73 / 0.80 / 0.75 |
| 0.50 | 11 | 1 | 10 | 0.917 | 0.524 | 0.667 | 0.67 / 0.50 / 0.75 |
| 0.55 | 9 | 1 | 12 | 0.900 | 0.429 | 0.581 | 0.60 / 0.50 / 0.57 |
| 0.60 | 4 | 0 | 17 | 1.000 | 0.190 | 0.320 | 0.44 / 0 / 0 |
| 0.65 | 3 | 0 | 18 | 1.000 | 0.143 | 0.250 | 0.35 / 0 / 0 |
| 0.70 | 1 | 0 | 20 | 1.000 | 0.048 | 0.091 | 0.13 / 0 / 0 |
| **0.75 (v1.1)** | 1 | 0 | 20 | 1.000 | 0.048 | **0.091** | 0.13 / 0 / 0 |
| 0.80 | 0 | 0 | 21 | – | 0 | 0 | 0 / 0 / 0 |

**At the selected τ = 0.30:**
- **Pooled F1:** 0.857, 95% block-bootstrap interval [0.69, 0.98].
- **Per kind:** entities 0.96 [0.88, 1.00], instruments 0.57 [0, 1], assets 0.75 [0, 1].
- **No per-kind τ is adopted:** at 0.40, instruments reach 0.80, but the intervals of both kinds span 0–1.
- **Treating ambiguous pairs as `same`:** P 0.88, R 0.76, F1 0.81.
- **Treating ambiguous pairs as `different`:** P 0.72, R 0.86, F1 0.78.

**False matches at τ = 0.30, the cost of the low threshold:**
- **B12 (Explosion029, instruments):** predicted "cigarette" matched to ground-truth "fuel nozzle" (cosine 0.399).
- **B14 (Assault007, instruments):** the predicted stick matched to the wrong one of two ground-truth sticks (0.335).
- **B18 (RoadAccidents075, assets):** predicted "bus" matched to ground-truth "load" (0.588).

At 0.40 only B18 remains (1 FP), and recall falls from 18 to 16 TP. At 0.75 there are no false matches, but 20 of 21 true pairs are missed.

## What this shows, and what it does not

- **Supported:** 0.75 is far too strict for these description styles. It rejects 20 of 21 true pairs. Any τ in 0.30–0.45 recovers most true matches at precision 0.86–0.94.
- **Warning 1, grid edge:** the rule selected the **lowest candidate on the grid** (0.30). The true optimum on this sample may lie below the grid. The grid was fixed in advance and the rule is applied as written. It is not extended after seeing the result.
- **Warning 2, coverage:** the sample took blocks of ≤ 9 pairs only. In the Stage 1 dev results, **16 of 112 blocks are larger, and they hold 402 of the 795 pairs** (for example 16 predicted × 6 ground-truth entities). In large blocks a low τ has more chances of a false match, so precision at 0.30 may be optimistic for exactly the over-listing outputs Stage 2 targets.
- **Warning 3, small sample:** 21 positives, wide intervals and AI labels. The human audit is still to do.
- **Not an input:** model scores. Stage 1 item scores under the candidate τ were computed only **after** selection, for the record ([Stage 1](../../docs/experiments/stage1-baselines.md#v12-provisional-re-matching)).

## Needed before v1.2 is in force (owner decisions)

1. **Human audit** of at least 20 pairs: the 8 ambiguous pairs, the 3 false matches above, the 5 FN at 0.40, and a random rest. Then re-derive τ by the same rule.
2. **Coverage:** accept the ≤ 9-pair sample as is, or approve a **pre-declared extension** before τ is finalised. The proposed extension: label every pair of 4 randomly drawn large blocks, about 150 pairs.
3. **Adopt τ:** the rule's output, 0.30, or record a deliberate deviation (for example 0.40, which is within 0.015 F1 with higher precision) as a new decision with its reason. The rule itself picks 0.30.

# Item-matching calibration v2 (final, AI-assisted): the evidence for evaluation-methodology-v1.2

> **2026-10-28.**
> - **Rules:** fixed and committed (`dac60a9b2`) before any v2 label or result existed ([v1.2 §Calibration v2](../evaluation-methodology-v1.2.md#calibration-v2-owner-approved-extension-rules-fixed-2026-10-28-before-any-v2-label-or-result-existed)).
> - **Labels:** written by AI labellers and checked by an AI auditor. **No person has reviewed them.** The 8 pairs that need a person are listed below.
> - **v1 kept:** calibration v1 ([report](matching-v1.2-calibration.md), sheet, labels) is unchanged.
> - **Machine-readable:** [`matching-v1.2-calibration-v2.json`](matching-v1.2-calibration-v2.json).

## The calibration set

| Part | Blocks | Pairs | How it was built |
|---|---|---|---|
| v1 | B01–B22 (blocks of ≤ 9 pairs) | 70 | Seed 20261028, quotas per kind |
| v2 large blocks | B23–B26 | 62 | Seed 20261029, uniform draw from the 16 dev blocks of more than 9 pairs, one per clip |
| **v2 in total** | **26** | **132** | Entities 50, instruments 15, assets 67, over all five categories |

**The large blocks:**

| Block | Clip, kind | Size | What makes it hard |
|---|---|---|---|
| B23 | RoadAccidents012 assets | 5 × 2 | Colour words that contradict the vehicles' paths. The labeller matched by path |
| B24 | RoadAccidents017 assets | 11 × 2 | Over-prediction: 9 queued background SUVs |
| B25 | Assault007 entities | 4 × 5 | Several similar people across two camera views, so several one-to-one matches are possible |
| B26 | Burglary061 assets | 5 × 2 | Generic objects (bag, paper, chair) beside the relevant register and door |

- **Not covered:** no large instrument block exists in the dev results. Ambiguous instruments come from the v1 blocks (B12, B14, B16).

**The labellers:**
- **v1 labels:** unchanged, from the first blind labeller.
- **Large blocks:** a fresh blind labeller checked all 62 pairs on the video, with frames, timestamps, reasons and an uncertainty for each (9 same, 51 different, 2 ambiguous).
- **Audit:** an independent auditor, blind to the scores, to the earlier labels and to why each pair was chosen. It re-labelled 36 pairs on the video:
  - 24 v1 pairs: the 8 ambiguous, the 3 false matches at 0.30 (1 of them also false at 0.40), the 5 missed matches at 0.40, and 8 random (seed 20261030);
  - 12 random large-block pairs (seed 20261031).

**Audit outcome:**
- **Agreement:** 30 of 36 agree. **On every pair where both had a decisive label, they agree, including all 12 large-block double labels.**
- **5 v1-ambiguous pairs resolved** by the audit (medium uncertainty): B16 I1–I1 `different`, B16 I1–I2 `same`, B16 I2–I2 `different`, B21 A5–A1 `same`, B21 A6–A1 `different`.
- **1 disputed:** B16 I2–I1, `ambiguous` against an audit `same` with high uncertainty. It stays `ambiguous` and is listed for review.

**v2 labels:** 32 same, 95 different, 5 ambiguous. The labels file has SHA-256 `eda29ffb58a6…` and is kept locally, because it holds ground-truth text.

## Result (rule: highest pooled F1 over all 26 blocks, Hungarian per block, ambiguous pairs left out; ties within 0.01 to the higher τ)

| τ | TP / FP / FN | Precision | Recall | **F1** | Small blocks F1 | Large blocks TP / FP / FN, F1 | F1 entities / instruments / assets | F1, ambiguous as same / different |
|---|---|---|---|---|---|---|---|---|
| 0.10 | 27 / 10 / 5 | 0.730 | 0.844 | 0.783 | 0.824 | 6 / 3 / 3, 0.667 | 0.94 / 0.55 / 0.67 | 0.779 / 0.750 |
| 0.15 | 27 / 9 / 5 | 0.750 | 0.844 | 0.794 | 0.840 | 6 / 3 / 3, 0.667 | 0.94 / 0.60 / 0.67 | 0.789 / 0.761 |
| 0.20 | 26 / 8 / 6 | 0.765 | 0.812 | 0.788 | 0.833 | 6 / 3 / 3, 0.667 | 0.91 / 0.60 / 0.70 | 0.784 / 0.754 |
| 0.25 | 26 / 8 / 6 | 0.765 | 0.812 | 0.788 | 0.833 | 6 / 3 / 3, 0.667 | 0.91 / 0.60 / 0.70 | 0.784 / 0.754 |
| 0.30 | 26 / 6 / 6 | 0.812 | 0.812 | 0.812 | 0.870 | 6 / 3 / 3, 0.667 | 0.91 / 0.67 / 0.73 | 0.806 / 0.776 |
| 0.35 | 24 / 5 / 8 | 0.828 | 0.750 | 0.787 | 0.837 | 6 / 3 / 3, 0.667 | 0.84 / 0.75 / 0.73 | 0.783 / 0.750 |
| **0.40** | **24 / 3 / 8** | **0.889** | **0.750** | **0.814** | 0.857 | **6 / 2 / 3, 0.706** | 0.87 / 0.86 / 0.73 | 0.806 / 0.774 |
| 0.45 | 19 / 3 / 13 | 0.864 | 0.594 | 0.704 | 0.769 | 4 / 2 / 5, 0.533 | 0.64 / 0.86 / 0.73 | 0.689 / 0.679 |
| 0.50 | 17 / 3 / 15 | 0.850 | 0.531 | 0.654 | 0.703 | 4 / 2 / 5, 0.533 | 0.58 / 0.67 / 0.73 | 0.621 / 0.642 |
| 0.55 | 14 / 3 / 18 | 0.824 | 0.438 | 0.571 | 0.588 | 4 / 2 / 5, 0.533 | 0.52 / 0.67 / 0.60 | 0.519 / 0.571 |
| 0.60 | 8 / 2 / 24 | 0.800 | 0.250 | 0.381 | 0.357 | 3 / 2 / 6, 0.429 | 0.38 / 0.40 / 0.38 | 0.340 / 0.381 |
| 0.65 | 7 / 1 / 25 | 0.875 | 0.219 | 0.350 | 0.296 | 3 / 1 / 6, 0.462 | 0.30 / 0.40 / 0.40 | 0.311 / 0.350 |
| 0.70 | 4 / 1 / 28 | 0.800 | 0.125 | 0.216 | 0.160 | 2 / 1 / 7, 0.333 | 0.11 / 0.40 / 0.29 | 0.190 / 0.216 |
| **0.75 (v1.1)** | 2 / 0 / 30 | 1.000 | 0.062 | **0.118** | 0.160 | 0 / 0 / 9, 0 | 0.11 / 0.40 / 0 | 0.103 / 0.118 |
| 0.80 | 0 / 0 / 32 | – | 0 | 0 | 0 | 0 / 0 / 9, 0 | 0 / 0 / 0 | 0 / 0 |

- **Selected: τ = 0.40.** Pooled F1 0.814, 95% block-bootstrap interval [0.65, 0.94]; precision 0.889, recall 0.750.
  - 0.30 (F1 0.812) is within the 0.01 tie margin, so the rule takes the higher τ.
- **Selection stability** (2,000 block resamples):
  - 0.40 is chosen in 55.6% of resamples, 0.30 in 34.5% and 0.15 in 9.3%.
  - The central 90% range is 0.15–0.40.
  - The pre-registered conservative fallback needs fewer than 50% **and** a span over 0.10, so it does **not** trigger. 0.40 is also the highest τ in that range, so the conservative choice would be the same.
- **Large-block effect:**
  - On large blocks, 0.40 is the best τ: precision 0.75 against 0.67 at every lower τ.
  - Lower τ adds a false match in the large blocks (Assault007 E3–E5) without gaining a true one.
  - Large blocks score lower than small ones at every τ (0.706 against 0.857 at 0.40). Item F1 on output that over-lists heavily is the least certain.
- **Ambiguity sensitivity:** counting the 5 ambiguous pairs as `same` or as `different` leaves 0.40 and 0.30 joint best: F1 0.806 for both as same, 0.774 against 0.776 as different. The choice of τ does not depend on them.
- **False matches at 0.40 (3, all assets):**
  - B18: RoadAccidents075, predicted "bus" against ground-truth "load" (cosine 0.59);
  - two in B23 (RoadAccidents012, cosine 0.75 and 0.63), where the predicted colour words fit the wrong vehicles. No τ below 0.75 removes these: the matcher reads text, not paths.
- **Rejected at 0.40 but accepted at 0.30:** three more false matches (Assault007 E3 against GT E5, cigarette against fuel nozzle, the wrong one of two sticks).
- **Conclusion:** 0.40 is the rule's result and also the precision-favouring choice. The interval is wide. The evidence justifies "about 0.30–0.40, not 0.75" firmly, and 0.40 over 0.30 weakly.

## Human review still open (8 pairs; package `eval_data/matching_calibration/human-review-package-v2.md`, local)

| Pair | Why |
|---|---|
| B16 I2–I1 (Assault015 instruments) | Labeller `ambiguous`, auditor `same` (high uncertainty) |
| B19 A1–A1, A1–A2 (Burglary010 assets) | Two identical ATMs; ambiguous |
| B25 E2–E2, E2–E4 (Assault007 entities) | A dark-clothed person; ambiguous |
| B23 A2–A1, A2–A2 (RoadAccidents012 assets) | Decisive labels with high uncertainty (colour against path) |
| B25 E4–E5 (Assault007 entities) | Decisive label with high uncertainty |

**Effect if a person changes them:** τ is re-derived by the same rule. Since the ambiguous-as-same and ambiguous-as-different variants both keep 0.40 within the margin, a change of these labels is unlikely to move τ outside 0.30–0.40.

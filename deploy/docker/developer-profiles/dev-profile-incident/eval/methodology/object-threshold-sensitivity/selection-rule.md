# Object-threshold selection rule (fixed before any dev sweep, dev sample or label of this study)

> Written 2026-11-05, before the dev sweep was run. Its SHA-256 is recorded in `dev-selection.md`.
> It governs only this post-hoc study. Primary scoring stays `evaluation-methodology-v1.2`, tau = 0.40, unless the owner decides otherwise.

**What the author had already seen when writing this rule** (so it is not a blind rule):
- calibration v2's table (labelled-pair F1 by tau; 0.30 and 0.40 tied, 0.35 lower);
- from `diagnostics/objects-crops.md`, on the evaluation half: Nano and Gemma entity F1 at tau 0.30 to 0.50, and false-TP rates at 0.40 (Nano 30%, Gemma 3%);
- from the plan audit, Stage 3 F1 at stricter thresholds.

No dev sweep of the five Track A models and no pair sample had been computed.

**Why measured F1 cannot decide.** `matching.solve_assignment` assigns first and filters afterwards, so the pairing does not depend on tau. Lowering tau only moves pairs from fp + fn to tp: measured F1 cannot fall, whether the added pairs are right or wrong. Measured F1 therefore enters only as a minimum effect size. Quality comes from labelled pairs.

**Common tau only.** One tau for all models and kinds. No per-model tuning. Per-kind values are exploratory and cannot be adopted here.

**Default:** retain 0.40.

**Sample (fixed seed 20261105).** Assigned pairs on dev, by similarity band, stratified by kind and model within a band, blind to similarity, band and model at labelling:

| Band | Quota |
|---|---|
| [0.35, 0.40) | 30 |
| [0.30, 0.35) | 30 |
| [0.25, 0.30) | 18 |
| [0.20, 0.25) | 12 |
| [0.40, 0.45) | 36 |
| [0.45, 0.50) | 14 |

Label: `same`, `different` or `cannot_tell`, from stored texts. **Precision** = same / all labelled (primary; `cannot_tell` counts against), and same / (same + different) as a sensitivity. Pooled precision is weighted by each band x kind x model cell's population. Intervals: clip-cluster bootstrap, 2,000 resamples, seed 20261027.

**A lower tau' in {0.35, 0.30, 0.25, 0.20} is recommended only if ALL hold,** on the pairs newly accepted in [tau', 0.40):

| Gate | Requirement |
|---|---|
| L1 quality | Weighted precision >= 0.75 and its 95% lower bound >= 0.60 |
| L2 kinds | Entities and assets each >= 0.70. Instruments >= 0.50 if at least 10 are labelled, otherwise "not assessable" (does not block, is reported) |
| L3 models | Every model with at least 10 labelled pairs >= 0.60 |
| L4 effect | Dev object score rises by at least +0.02 for each of the four complete models, with a paired clip-cluster interval excluding 0. Super is reported, not gated |
| L5 no loss of discrimination | Precision is no more than 0.10 below that of [0.40, 0.45) |
| L6 calibration | Calibration v2 pooled F1 at tau' >= F1 at 0.40 minus 0.01. This set informed the original pick, so it can only veto |

**A higher tau' = 0.45 is recommended only if** precision of [0.40, 0.45) is <= 0.50 with an upper bound <= 0.65. Bands above 0.45 are sampled too thinly for any higher value, which therefore stays at "not assessable".

**More than one passes:** the highest tau' (the existing rule's precision preference). **None passes:** retain 0.40.

**Evaluation half:** computed only after `dev-selection.md` exists and its hash is recorded; reporting only, never an input to the choice. The hash check in `scripts/v2_object_threshold_sensitivity.py` refuses to run the evaluation sweep otherwise.

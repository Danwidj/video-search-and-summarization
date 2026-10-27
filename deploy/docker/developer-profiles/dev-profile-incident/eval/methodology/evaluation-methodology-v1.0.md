# Evaluation Methodology v1.0

> **Status: implemented in PR 1B (2026-10-27), except §6, which is a proposal awaiting approval.** Version id `evaluation-methodology-v1.0`. The pinned values are in [`../methodology.py`](../methodology.py) and recorded in every result file (`methodology`).

This document fixes how the P1 extraction benchmark scores a prediction against the ground truth. It is shared by every prompt experiment and by both arms of the direct-VLM vs VSS comparison ([plan](../../.docs/mvp2/ground-truth-and-prompt-experiments-plan.md) §B.2, §F). What a correct label is belongs to [`annotation-guidelines-v1.0`](../ground_truth/annotation-guidelines-v1.0.md), not to this document. A change to any pin is a new methodology version, and results from different versions are never pooled (`eval_aggregate.py` refuses to).

## 1. Pinned instruments

| Instrument | Pin | Recorded as |
|---|---|---|
| Description and item-text judge | `nvidia/nemotron-3-nano-30b-a3b`; prompt [`judge-prompt-v1.txt`](judge-prompt-v1.txt) (SHA-256 `093ddcd5…54fd`, byte-identical to the prompt of every earlier result); `temperature 0` | `methodology.judge` |
| Judge pass threshold | score ≥ 0.5 | `methodology.judge.pass_score` |
| Matching embedder | `sentence-transformers/all-MiniLM-L6-v2` at `http://127.0.0.1:8811/v1`; the run checks that the server reports this model and that `INCIDENT_EMBEDDING_BASE_URL` is that URL | `methodology.embedding` |
| Matching | one-to-one Hungarian assignment on cosine ≥ 0.75 | `methodology.match_threshold` |
| Timestamps | within ±5 s | `methodology.timestamp_tolerance_s` |
| Intervals | 95% percentile bootstrap over videos, 10,000 resamples, seed 20261027 | `methodology.bootstrap` |

`INCIDENT_JUDGE_MODEL` may be left unset or set to the pin. Any other value stops the run before any model call.

## 2. Field rules

| Field | Rule |
|---|---|
| type | Exact match after `canonical_incident_type` (the five categories, unchanged) |
| severity | Exact match (the field score). Also reported: within ±1, mean signed error (predicted − expected) and a 5×5 confusion matrix with a `missing` column |
| start / end | Within ±5 s, plus mean absolute error. Duration is derived (end − start) and reported, not a separate criterion |
| incident description | Judge score; pass at ≥ 0.5. An empty prediction scores 0 without a judge call |
| entities / instruments / assets | Hungarian matching on MiniLM cosine ≥ 0.75. Embedded text: `"type description"` (entities), `"name description"` (instruments, assets). TP = matched pairs, FP = unmatched predictions, FN = unmatched ground truth. P/R/F1 pooled per run |
| entity attributes | Type exact; description judged; on matched pairs |
| instrument attributes | Threat exact and within ±1. Holder accuracy = correct / (correct + incorrect) on matched instruments, with unresolved cases counted separately. Counts are always shown with the rates |
| asset attributes | Name and description judged, on matched pairs |
| empty arrays | Both sides empty: no TP/FP/FN. Ground truth empty, prediction not: every prediction is an FP |
| not scored | title, severity reason, location, timeline, uncertainties, confidence score, item timestamps and first/last-seen, labels, images, bounding boxes, RP1 prose |

## 3. Failures

| What failed | Treatment |
|---|---|
| The model's output is invalid (`contract_invalid`, `parse_failure`, `core_ok` false) | A **model miss**: an empty prediction, every field wrong, ground-truth items become FN. Counted in accuracy |
| No model output (`timeout`, `rate_limited`, `http_error` after the fixed retry policy) | **Not a model miss.** Excluded from accuracy and from both sides of a paired comparison, and counted (`no_model_output`) |
| The judge or the embedder (the scorer itself) | **Never a score.** Transient judge failures (network, timeout, HTTP 429/5xx) are retried twice with the identical request (backoff 2 s, 8 s). A failure that remains leaves the field `pass: null` with its error, and the embedder leaves the kind's counts `null`. Both are listed in `scoring_errors`, and `eval_run.py` stops (`check_scoring_complete`). The aggregate never counts a `null` as a fail: it is excluded from the denominator and counted under `unscored` |

## 4. Aggregation and uncertainty

- **Field accuracy:** over videos with a model output and a scored value. `field_intervals` gives `n`, `no_model_output`, `unscored`, the accuracy and its 95% interval.
- **Breakdowns:** per category and model (`by_category_and_model`), per model (`by_model`) and overall. Items are micro-pooled. There is no blended score.
- **Paired comparison** of two runs on the same videos (`extraction_stats.paired_difference`): videos are paired by incident id, a video unscored or without output on either side is dropped and counted, and the mean per-video difference gets a bootstrap interval. Intervals are descriptive.

## 5. Reproducibility

- Every result file carries `methodology` (all pins, including the judge prompt's SHA-256), and every video record carries `methodology_version` and `scoring_errors`.
- The same result files always give the same summary, including the intervals (the seed is fixed).
- Scoring through the offline store and through a database give identical results, including on judge and embedder failures (`tests/test_offline_store.py`, `tests/test_methodology.py`).
- Results written before this version are labelled `legacy (before evaluation-methodology-v1.0)`, and the aggregate refuses to pool them with v1.0 results.

## 6. Clips outside the five types (proposal, awaiting approval; not implemented)

[Annotation guideline A8](../ground_truth/annotation-guidelines-v1.0.md#212-burglary-robbery-force-and-clips-outside-the-five-types-a8) marks such clips `out_of_taxonomy`, records their nearest type, and leaves their scoring to this methodology. The ground truth will carry the flag from PR 5. Candidates in the v0.1 review are Explosion011 and Explosion014.

| Option | Type field | Other fields | Per-category tables | Trade-off |
|---|---|---|---|---|
| **A: exclude the clip entirely** | excluded | excluded | excluded | Simple, but discards valid annotations (window, severity, items, description) that still measure extraction |
| **B: score type against the nearest type** | scored vs nearest type | scored | under the nearest type | Uses every clip, but rewards a forced label the guidelines forbid, and penalises a model for not guessing it |
| **C (recommended): exclude from type only** | excluded from type accuracy; nearest-type agreement reported separately as a secondary figure | scored as usual | in a separate "outside the five types" row, not under the nearest type | P1 must output one of the five types, so its type cannot be right on such a clip; every other field is still a valid measurement |

**Effect of C on the numbers.** With N videos of which k are flagged:
- type accuracy uses N − k videos; every other field uses N;
- every table states k and the flagged ids;
- overall and per-model figures include the flagged clips for every field except type;
- the per-category rows of the five categories leave them out;
- paired comparisons are unaffected, because both sides cover the same videos;
- intervals resample each field's own videos.

**Not changed by any option:** the five categories, the labels, and the treatment of failures (§3).

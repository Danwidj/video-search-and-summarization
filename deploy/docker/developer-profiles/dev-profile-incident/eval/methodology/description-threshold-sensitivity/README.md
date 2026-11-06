# Description threshold sensitivity (EXPLORATORY, post hoc)

**The frozen 0.50 pass rule stays the primary metric.** This analysis changes no result, configuration, ground truth or scoring code. It used stored scores only: no VLM call, no judge call, and no spend. Written 2026-11-05.

Reproduce from `eval/`:

```bash
uv run --frozen python scripts/v2_description_threshold_sensitivity.py
~/.cache/vss-agent-venv/bin/python scripts/v2_description_threshold_plots.py
uv run --frozen pytest tests/v2/test_v2_description_threshold_sensitivity.py
```

**Update 2026-11-06:** Super closed at 50 valid (21/50 = 0.420 at 0.50). This analysis keeps its 26-row snapshot, as designed.

## Answers

| Question | Answer |
|---|---|
| How much do pass rates rise from 0.50 to 0.40? | +3.2 to +6.3 points. 14 descriptions move in total: Nano 3, Omni 4, Gemma 3, Qwen 4, Super 0 |
| Do rankings change? | Not among the four complete models, at any tested threshold. Super (26 rows, incomplete) swaps with Qwen below 0.45 |
| Are descriptions just below 0.50 incorrect? | Mixed. An AI reading of the 14 found 9 plausibly acceptable, 2 too vague and 3 likely wrong. Not a human judgement |
| Is 0.40 better aligned with human judgement? | Unknown. No human labels exist |
| How sensitive are conclusions to judge instability? | Ranking: not sensitive so far. Individual verdicts: sensitive: 4 of 31 repeat pairs flip at 0.50, 2 of 31 at 0.40. Too few pairs to prefer 0.40 |
| Enough evidence to change the threshold? | **No.** Keep 0.50 as primary until human calibration exists |

## Method

- **Score:** `evalv2/tasks/incident_objects/scoring.py::score_video` sends GT and generated descriptions to the judge and stores `score`; pass is `score >= v1.PASS_SCORE`, from `methodology.DESCRIPTION_PASS_SCORE` = 0.5.
- **Judge:** `openrouter-gpt-oss-20b-c3-v1` (`evalv2/tasks/judges.json`), temperature 0, prompt `methodology/judge-prompt-v1.txt`. It asks for 0.0 (unrelated) to 1.0 (semantically equivalent), allowing for wording and detail. It defines no anchors, so 0.50 has no established meaning here.
- **Stored scores:** every valid output has a numeric score except one Qwen row (Animal004 repeat 2: judge reply truncated at 1,500 tokens), which stays unscored.
- **Not judged:** invalid outputs and failed requests. Empty descriptions score 0 unjudged; none occurred among valid outputs.
- **Rows:** Track A original C3, with the same rule as the C3 analysis. A model output in an earlier run wins.
- **Super:** frozen snapshot of 26 valid rows, before A5-s. New Super rows are not read.
- **Intervals:** clip-cluster bootstrap, seed 20261027, 5,000 resamples. Rates are on valid judged descriptions; `per_model_pass_rates.csv` also gives rates of 110 planned.

## Pass rates

| Model (valid judged) | 0.30 | 0.35 | 0.40 | 0.45 | **0.50 frozen** | 0.55 | 0.60 | 0.70 | 0.40 vs 0.50 |
|---|---|---|---|---|---|---|---|---|---|
| Gemma 4 31B (65) | 0.708 | 0.692 | 0.692 | 0.646 | **0.646** [0.483, 0.794] | 0.646 | 0.646 | 0.569 | +4.6 |
| Nemotron 3 Nano Omni (63) | 0.619 | 0.571 | 0.571 | 0.508 | **0.508** [0.361, 0.645] | 0.508 | 0.492 | 0.365 | +6.3 |
| Qwen3.5-9B (64) | 0.531 | 0.469 | 0.469 | 0.406 | **0.406** [0.268, 0.547] | 0.391 | 0.375 | 0.297 | +6.2 |
| Cosmos 3 Nano (95) | 0.389 | 0.326 | 0.326 | 0.295 | **0.295** [0.176, 0.418] | 0.295 | 0.295 | 0.242 | +3.2 |
| Cosmos 3 Super, incomplete (26) | 0.500 | 0.423 | 0.423 | 0.423 | **0.423** [0.231, 0.625] | 0.423 | 0.423 | 0.346 | 0.0 |

The 0.35 and 0.40 columns match, as do 0.45 and 0.50, because the judge almost never uses scores between those values. Scores are coarse and two-humped (see `plots/`). Only 17 of 313 judged descriptions fall in 0.35–0.55.

**Ranking.** Gemma, Omni, Qwen, Nano at every threshold. Gemma ranks first in 90.2% of bootstrap resamples at 0.40 and 95.5% at 0.50. Intervals overlap heavily, so the middle order is not firm. On the 22 clip-repeats valid for all four, order holds for Gemma and Omni; Nano and Qwen are close (0.455 and 0.500 at 0.50), on a small sample. `common_valid_set_rates.csv`.

**Categories.** See `category_breakdown.csv`. Most cells have under 20 rows. The largest change among full cells is Gemma Burglary, 15/20 to 18/20.

## Descriptions near the cutoff

All 14 descriptions that move have score exactly 0.40, and all have the correct type. An AI reading (one Claude reader, not validated, stored in the private folder):

| Reading | Count | Examples |
|---|---|---|
| Plausibly acceptable | 9 | Right event, less detail |
| Too vague | 2 | "Enters and searches items", with no break-in stated |
| Likely wrong | 3 | Wrong subject or wrong object in the event |

So a lower threshold would add both genuine descriptions and errors. The problem is also not confined to 0.40: earlier review found likely false negatives at 0.30, which no sensible threshold would fix. This points at the rubric, not the cutoff.

## Judge repeatability

Stored verdicts for the same text pair exist across run caches for 31 of 259 unique description pairs (Nano 23, Omni 8). All are repeat judgements at temperature 0 from different scoring runs.

| Measure | Result |
|---|---|
| Score differs | 14 of 31 |
| Mean / maximum range | 0.103 / 0.6 |
| Pass/fail flips at 0.50 | 4 of 31 (12.9%) |
| Pass/fail flips at 0.40 | 2 of 31 (6.5%) |
| Flips at 0.30 / 0.60 / 0.70 | 2 / 5 / 5 |

**Correction:** the earlier "15 of 138 flip" figure pooled every judge pair, including entity and asset text. For incident descriptions the figure is 4 of 31.

0.40 shows fewer flips here, but that is a difference of 2 pairs, from Nano and Omni only. It is not evidence that 0.40 is more reliable. Rates may differ for the 228 pairs judged once. The flips come from wide swings (0.1 to 0.6, 0.2 to 0.8), so no threshold removes them.

## Human calibration

None exists. The owner ruled out human review on 2026-11-03 (`methodology/v2-ai-only-reference-review.md`), and AI consensus is not human validation. A blinded set is ready, with calibration **pending**:

- `/home/hengz/evalv2-data/v2/diagnostics/description-threshold/blinded_review_sample.csv`: 77 unique pairs, random order, no model or score.
- `review_key_DO_NOT_SHARE_WITH_REVIEWERS.csv` in the same folder: for computing precision, recall, F1, false-pass and false-fail per threshold afterwards.
- `human-review-rubric.md`: the rubric.

The strata cover low scores, 0.30, 0.40, 0.50–0.60 and high scores. They are not proportional, so weight results back to the score distribution.

## Limitations

- One judge, not human-calibrated; it sees text only, not video.
- GT is AI-assisted. Valid sets differ by model. OpenRouter and Switchyard differ.
- Scores may change if Super completes; the snapshot stays separate.
- The threshold was chosen for testing after results were seen, so this cannot support a claim. It is exploratory.

## Files

`per_model_pass_rates.csv`, `per_description_scores.csv` (ids, no text), `fail_to_pass_050_to_040.csv`, `category_breakdown.csv`, `common_valid_set_rates.csv`, `judge_repeatability_pairs.csv`, `summary.json`, `plots/pass_rate_vs_threshold.png`, `plots/score_distribution.png`, `human-review-rubric.md`, `annex-slide.md`.

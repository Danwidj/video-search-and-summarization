# Evaluation Methodology v1.1

> **Status: in force from 2026-10-27, for the Stage 0 pilot and every later experiment.** Version id `evaluation-methodology-v1.1`. It is [`evaluation-methodology-v1.0`](evaluation-methodology-v1.0.md) with **one pin changed: the judge's output limit** and the stricter reading of judge replies that comes with it. Everything else (judge model and prompt, pass threshold, embedder, matching, timestamps, failures, aggregation, intervals, Option C) is v1.0 unchanged. Results of v1.0 and v1.1 are never pooled (`eval_aggregate.py` refuses to).

## The change

| Instrument | v1.0 | v1.1 |
|---|---|---|
| Judge request settings | `temperature 0` | `temperature 0`, **`max_tokens 1500`** (`methodology.JUDGE_MAX_OUTPUT_TOKENS`). Reasoning tokens count towards the limit |

The settings are recorded in every result as `methodology.judge.request_settings`.

## Judge replies that are failures, never scores

| Reply | v1.0 | v1.1 |
|---|---|---|
| Cut off at the limit (`finish_reason: "length"`) | Not checked | **Failure** `judge response truncated at max_tokens=1500`. Not retried: the identical request at temperature 0 would be cut off again |
| Score outside 0–1 (e.g. `1.7`, `-0.2`, `7`) | Clamped into 0–1 | **Failure** (no valid score). Retried like any unparseable reply |
| Score only in `reasoning_content`, no final content | Read from the reasoning | **Failure**. Only the final `content` is read |
| Non-numeric or missing score | Failure | Failure (unchanged) |

As in v1.0, a failure leaves the field `pass: null` with its error. It is listed in `scoring_errors`, and the run stops (`check_scoring_complete`). It is never a zero and never a pass. Retries are unchanged: up to 2 parse retries and 2 transient retries (at most 5 attempts per judged field).

## Why

- **Bounded cost:** the judge's output now has a hard ceiling (1,500 tokens per attempt), so judge spend can be bounded before a run (D11).
- **No silent scores:** an incomplete or malformed reply must not be read as a score, so clamping and reading the reasoning are removed.

**Impact:** a judge whose reasoning often exceeds 1,500 tokens will produce scoring failures, which stop the run. The Stage 0 pilot measures how often this happens. If it does, a new version, not a silent change, decides the remedy.

Tests: [`../tests/test_judge_limits.py`](../tests/test_judge_limits.py).

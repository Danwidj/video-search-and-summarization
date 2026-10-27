# VLM benchmark: incident fields and processing time (incident-contract-v2)

Run `2026-10-02T09-56-18+00-00`: `eval_run.py --incident-only`, then `eval_benchmark_export.py`. All figures come from the run's result files (`eval_data/results/runs/<run>/`) and the exports in `eval_data/results/benchmark/<run>/`. Both are gitignored; the split manifests are tracked in `eval_reproducibility/`.

The earlier P1-v1 results (few-shot examples, base64 video, lenient parsing) are in this file's git history. They are not comparable with these.

## Setup

| | |
|---|---|
| Videos | 55 held-out videos (Animal Attack 10, Assault 10, Burglary 13, Explosion 10, Road Accident 12) |
| Video length | mean 61.7 s, median 41.8 s, range 10.0–332.6 s (MP4 header) |
| Video size | mean 14.32 MB, median 9.84 MB, range 1.06–83.10 MB (R2 `HeadObject`, MB = 10^6 bytes) |
| Request | incident-contract-v2 prompt and strict schema; signed R2 URL; `temperature 0`, `max_tokens 16384`, `num_frames 64`; 300 s timeout. The request is the same for every model, but `cosmos-3-super-reasoner` samples about 24 frames whatever is requested. |
| Validation | `core-scored-v1`: only database-backed fields decide scoring; nothing is repaired |
| Order | video by video, all three models per video, with the model order rotated per video; sequential calls |
| Rate limits | fixed policy: 20 s between P1 attempts; HTTP 429 only, retried after 60 s (or a longer `Retry-After`), at most 2 retries |
| Judge | `nvidia/nemotron-3-nano-30b-a3b` on Switchyard, used for the description only; an empty predicted description scores 0.0 without a judge call |
| Scope | incident fields only: no entities, instruments or assets; no RP1 |

## Outcomes per (video, model)

| Model | Scored | Contract-invalid | Parse failure | Rate-limited (after retries) | HTTP error | Timeout | 429 retries |
|---|---|---|---|---|---|---|---|
| `nvidia/cosmos-3-nano-reasoner` | 54 | 0 | 1 | 0 | 0 | 0 | 0 |
| `nvidia/cosmos-3-super-reasoner` | 48 | 0 | 0 | 2 | 5 | 0 | 16 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 26 | 10 | 10 | 9 | 0 | 0 | 34 |

- **Model outputs, which enter the field metrics:** `scored`, `contract_invalid` and `parse_failure`. The last two are misses on every field.
- **No model output, reported separately:** rate-limited, HTTP errors and timeouts.
- **Cosmos-3-Super HTTP errors:**
  - 3 × HTTP 524, a gateway timeout page returned before the 300 s client timeout.
  - 2 × HTTP 500, "Requested next frame while there are…", a server-side video decoding error.
- **Nemotron contract-invalid outputs:**
  - 4 × incident window beyond the video.
  - 4 × instrument holder unknown.
  - 2 × non-sequential instrument IDs.
- **Nemotron parse failures:** all ended with `finish_reason: length`.
  - 3 returned empty content: the whole budget went on reasoning.
  - 7 returned 43k–905k characters of unterminated output.
- **Cosmos-3-Nano parse failure:** one 62k-character output cut off at the token limit.

## Incident fields by model (model outputs only; each field separate, no blended score)

| Model | Model outputs | Type | Severity | Start ±5 s (MAE) | End ±5 s (MAE) | Description (mean judge, 0–1) |
|---|---|---|---|---|---|---|
| `nvidia/cosmos-3-nano-reasoner` | 55 of 55 | 70.9% | 27.3% | 63.6% (8.41 s) | 52.7% (11.22 s) | 0.314 |
| `nvidia/cosmos-3-super-reasoner` | 48 of 55 | 91.7% | 22.9% | 81.2% (3.62 s) | 62.5% (8.92 s) | 0.430 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 46 of 55 | 43.5% | 21.7% | 34.8% (11.38 s) | 30.4% (28.81 s) | 0.241 |

- **Denominators differ** because each model has a different set of model outputs.
- **The 40 videos with an output from all three models give the same ranking:**

| Model | Type | Severity | Start | End | Description |
|---|---|---|---|---|---|
| Cosmos-3-Nano | 77.5% | 30.0% | 72.5% | 57.5% | 0.328 |
| Cosmos-3-Super | 92.5% | 20.0% | 80.0% | 60.0% | 0.418 |
| Nemotron | 42.5% | 22.5% | 35.0% | 32.5% | 0.220 |

- **Derived duration** (end − start, diagnostic only), within ±5 s with MAE in brackets:
  - Nano: 40.0% (17.78 s)
  - Super: 60.4% (10.54 s)
  - Nemotron: 28.3% (29.65 s)

## Processing time (the successful P1 HTTP round trip; pacing and rate-limit waits excluded)

| Model | n | Mean | Median | p90 | Min | Max | Mean completion tokens |
|---|---|---|---|---|---|---|---|
| `nvidia/cosmos-3-nano-reasoner` | 55 | 11.6 s | 6.8 s | 29.4 s | 4.4 s | 124.3 s | 1,128 |
| `nvidia/cosmos-3-super-reasoner` | 48 | 21.7 s | 13.9 s | 66.3 s | 6.3 s | 90.2 s | 1,191 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 46 | 30.8 s | 23.1 s | 62.1 s | 12.5 s | 65.5 s | 7,448 |

- **What the time includes:** the endpoint fetching the video from R2, decoding and generation, on a shared hosted endpoint. Latency therefore reflects Switchyard's load as well as the model.
- **Calls with no model output** keep their own timing in the per-video CSV (`final_attempt_time_s`) and are not in these figures.

## Limitations

- **Infrastructure failures are not random across models:**
  - 9 of Nemotron's 55 pairs were rate-limited after retries, against its 30,000 tokens/min quota.
  - 7 of Cosmos-3-Super's pairs failed on rate limits, HTTP 524s or decoder errors.
- **Every number comes from one run at temperature 0.** There are no repeated runs, so there is no variance estimate.
- **The description score comes from one LLM judge** and is not a human rating.
- **Severity agreement is low for every model** (22–27%). It may say more about the severity rubric than about the models; not investigated.

## Reproduce

```bash
cd eval
uv run python scripts/eval_dataset_stats.py
uv run python scripts/eval_run.py --incident-only
uv run python scripts/eval_benchmark_export.py --run-dir eval_data/results/runs/<run>
```

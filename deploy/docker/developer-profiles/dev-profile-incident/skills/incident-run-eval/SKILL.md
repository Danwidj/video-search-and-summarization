---
name: incident-run-eval
description: Use to run the standalone P1/RP1 evaluation pipeline in eval/ - start the local embedding server, ingest ground truth, generate the seeded split, batch-score VLM incident extraction against ground truth, aggregate across models and categories, or run its hermetic tests. Not for producing a single report (use incident-analyze-video) and not NVIDIA's `nat eval`.
license: Apache-2.0
metadata:
  version: "0.5.0"
  profile: "dev-profile-incident"
  tags: "incident evaluation benchmark ground-truth vlm"
---
# Incident Run Eval

`eval/` is its own `uv` project. It shares no runtime with other services. Its scoring code began as a verbatim copy of the v1 console's modules (v1 is archived under `archived/incident-console/`).

Canonical facts:
- Setup and variables: [`eval/README.md`](../../eval/README.md)
- Methodology and recorded 3-model results: [`eval/docs/vlm_benchmark_results.md`](../../eval/docs/vlm_benchmark_results.md)
- Handoff and open items (including the dropped `gt_*` tables): [`.docs/mvp2/eval.md`](../../.docs/mvp2/eval.md)
- Retrieval benchmark (Track R): only the offline metrics module `eval/retrieval_metrics.py` exists (work-order step 1, tested by `tests/test_retrieval_metrics.py`). There is no retrieval run command yet; the harness is step 3 of [`.docs/mvp2/eval.md` §10](../../.docs/mvp2/eval.md#10-work-order-and-definition-of-done).

## Prerequisites

1. `cd deploy/docker/developer-profiles/dev-profile-incident/eval && uv sync`
2. `eval/.env.local` is a symlink to `../.env.local`. **Scoring needs no database:** by default `eval_run.py` loads the workbook into an in-memory store (`eval/offline_store.py`) and never connects to Supabase, even though the file holds finals credentials. Finals dropped the `gt_*` and relational report tables (`20261023000000`). Never pass `--db` against finals; `--db --init-schema` creates tables and is for a local or throwaway database only. Beyond the R2 variables, it needs `VLM_GATEWAY_API_KEY` (or `INCIDENT_LLM_API_KEY`), `INCIDENT_LLM_BASE_URL` (the real Switchyard gateway, not the mock), `INCIDENT_JUDGE_MODEL` and `INCIDENT_EMBEDDING_BASE_URL`. These are **not** in the committed `.env`, so check they exist before any live run.
3. The ground-truth workbook and all working data stay under `eval/eval_data/`, which `eval/.gitignore` excludes. Never commit it.

## What a run sends

P1 uses the shared [incident contract](../../contracts/README.md) (`incident-contract-v4`):
- a signed R2 URL, then the contract prompt, with the schema enforced via `response_format`;
- no few-shot examples;
- a fixed `max_tokens 16384` and `num_frames 64` (the same request for every model, but `cosmos-3-super-reasoner` samples about 24 frames whatever is requested; never call the visual input identical);
- a 300 s timeout per call, the console's `contracts/inference.json` value.

Responses are judged under validation policy `core-scored-v1`. A core failure is scored as a miss and listed under `core_failures`, and its RP1 is skipped. When core fields are valid (`core_ok`), RP1 runs on the unchanged prediction with timeline context. **Never loosen the parser to raise a score.** A model with many contract or core failures is a finding, not a bug to paper over. Details: [`eval/README.md`](../../eval/README.md).

## Instructions

```bash
# 0. Dataset videos: inventory, download and verify (resumable; R2 read-only), split keys current
uv run python scripts/eval_fetch_videos.py --list
uv run python scripts/eval_fetch_videos.py               # exits non-zero on any integrity finding
uv run python scripts/eval_refresh_split_keys.py --check  # non-zero when split manifests name moved R2 keys
cp eval_reproducibility/split_*.json eval_data/

# 1. Local embedding server (separate terminal; prints the INCIDENT_EMBEDDING_BASE_URL to set)
uv run python scripts/eval_embedding_server.py

# 2. One-off: validate the ground-truth workbook (no database), then generate the seeded split
uv run python scripts/eval_ingest_gt.py --dry-run
uv run python scripts/eval_generate_split.py

# 3. Smoke test first (1 model, 1 category, 1 video), then the full run
uv run python scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner --categories Assault --limit 1
uv run python scripts/eval_run.py

# 4. Aggregate across models/categories
uv run python scripts/eval_aggregate.py

# Ground-truth review (proposed corrections, not ground truth): workbook + audit + manifest
uv run python scripts/gt_review_build.py                 # source: ../Complete Ground Truth Labelling.xlsx (never modified)
```

The review workbook (`ground_truth/review/Ground Truth Review v0.1.xlsx`) is gitignored on purpose; its storage and the review workflow are in [`eval/ground_truth/review/README.md`](../../eval/ground_truth/review/README.md). Never edit the source workbook, and never treat a proposed value as final before PR 5 freezes it.

**Always smoke-test before a full run.** A full run spends hosted-inference quota across 3 models × 5 categories.

### VLM benchmark (incident fields + processing time)

```bash
cp eval_reproducibility/split_*.json eval_data/       # if the manifests are missing
uv run python scripts/eval_dataset_stats.py           # first: all 55 videos resolve? mean length and size (no model calls)
uv run python scripts/eval_run.py --incident-only --categories Assault --limit 1   # smoke: 3 P1 calls + 3 judge calls
uv run python scripts/eval_run.py --incident-only     # full: 165 (video, model) pairs, ~4 h; judge: 1 probe + 1 per scored row
uv run python scripts/eval_benchmark_export.py        # tables -> eval_data/results/benchmark/<run start>/
```

- `--incident-only` needs no embedding server and skips RP1.
- Processing time is the successful P1 HTTP round trip (`timing.p1_elapsed_s`), never waiting.
- Fixed rate-limit policy (`P1_RATE_LIMIT_POLICY`): 20 s between P1 attempts; HTTP 429 only is retried after 60 s (or a longer `Retry-After`), at most twice. Never tune it per model or per run.
- Field metrics cover model outputs only. `rate_limited`, `timeout` and `http_error` rows are reported separately; timeouts are never model misses.
- An empty predicted description scores 0.0 with no judge call.
- Models run interleaved per video, in rotating order.
- Every attempted `(video, model)` pair stays a row, failures included.
- There is no blended score. `duration` is a derived diagnostic.
- Details: [`eval/README.md`](../../eval/README.md#vlm-benchmark-incident-fields-processing-time).

## Verify

- `uv run pytest tests/` passes. The tests are hermetic: no live Postgres, agent or GPU.
- `eval_fetch_videos.py --verify-only` prints `OK`, and `eval_reproducibility/dataset-manifest-v1.json` has `"integrity": {"ok": true, ...}` with 80 clips.
- Result files say `"scoring_backend": "offline"` in their `benchmark` block unless `--db` was passed.
- `eval_ingest_gt.py --dry-run` prints no `WARNING: ... has incident type` line. If it does, a workbook `Type` is not one of the five standard types. Scoring still uses the row, normalised to lowercase; fix the workbook.
- The smoke run writes `eval_data/results/<category>__<model>.json` with non-null field scores.
- A benchmark smoke run also has `timing.p1_elapsed_s > 0` and a `video` block (size, length) on every video.

## Scoring (what the numbers mean)

The rules are fixed by [`evaluation-methodology-v1.0`](../../eval/methodology/evaluation-methodology-v1.0.md), and every pin is recorded in each result file.

| Field | Method |
|---|---|
| type, severity | Exact match (severity also within ±1, bias and confusion matrix) |
| description | Pinned judge (`nvidia/nemotron-3-nano-30b-a3b`, `judge-prompt-v1`, temperature 0); pass ≥ 0.5 |
| start, end, duration | ±5 s, plus mean absolute error |
| entities, instruments, assets | MiniLM + Hungarian matching at cosine ≥ 0.75 → precision / recall / F1; threat and holder accuracy |

- `INCIDENT_JUDGE_MODEL` must be unset or equal to the pin, or the run refuses to start.
- A judge or embedder failure is a scoring error that stops the run; it never counts as a wrong answer.
- Request failures (timeout, 429, HTTP error) are excluded from accuracy and counted.
- `eval_aggregate.py` refuses to pool results from different methodology versions.

## After changing anything

- If methodology or results change, update `eval/docs/vlm_benchmark_results.md`.
- `eval/` is the only maintained copy of the scoring code. Never update `archived/incident-console/` to match it.

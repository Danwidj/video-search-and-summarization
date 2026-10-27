# P1/RP1 evaluation pipeline

A standalone Python project that benchmarks structured incident extraction (P1) by three VLMs against human ground truth, and writes an unscored prose report (RP1) per prediction. It shares no runtime with the other services. The recorded benchmark in [`docs/vlm_benchmark_results.md`](docs/vlm_benchmark_results.md) is the incident-contract-v2 run of 2026-10-02 (incident fields and processing time, 55 videos × 3 models).

> **Scoring is offline by default.** `eval_run.py` loads the ground-truth workbook into an in-memory store (`offline_store.py`), writes each prediction there and scores it with the unchanged scorer. It opens no database, so nothing reaches finals, which no longer has the eval tables ([eval open item 1](../.docs/mvp2/eval.md)). `--db` uses the legacy database path instead, and only `--db --init-schema` creates tables: use those for a local or throwaway database, never finals. `tests/test_offline_store.py` shows both paths give identical scores.

## Run it

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/eval
uv sync

uv run python scripts/eval_embedding_server.py   # 1. local embedding server (own terminal); prints INCIDENT_EMBEDDING_BASE_URL
uv run python scripts/eval_ingest_gt.py --dry-run   # 2. validate the ground-truth workbook (no database)
uv run python scripts/eval_generate_split.py     # 3. seeded demonstration/evaluation split, once
uv run python scripts/eval_run.py                # 4. full run: 3 models, 5 categories
uv run python scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner --categories Assault --limit 1   # smoke test
uv run python scripts/eval_aggregate.py          # 5. aggregate across models and categories

uv run pytest tests/                             # hermetic tests: no live database, agent or GPU
```

Settings come from `.env.local`, a symlink to the profile's shared `../.env.local`; the variables it needs are listed in [`../.docs/mvp2/eval.md`](../.docs/mvp2/eval.md#11-eval-p1rp1-extraction-benchmark). The workbook and all working data stay in the gitignored `eval_data/`.

`retrieval_metrics.py` is the offline metrics module of the MVP2 retrieval benchmark (Track R, work-order step 1): pure functions that cut the baseline, post-filter and fill-to-K lists from a search response's candidate pool and compute the §3.5 metrics with paired seed-cluster bootstrap intervals. It has no script and calls no service; the harness that feeds it is step 3 ([`../.docs/mvp2/eval.md`](../.docs/mvp2/eval.md#10-work-order-and-definition-of-done)).

## VLM benchmark (incident fields, processing time)

```bash
cp eval_reproducibility/split_*.json eval_data/       # if eval_data/ has no manifests yet
uv run python scripts/eval_dataset_stats.py           # 1. size and length of every video; no model calls
uv run python scripts/eval_run.py --incident-only --categories Assault --limit 1   # 2. smoke: 1 video x 3 models
uv run python scripts/eval_run.py --incident-only     # 3. full: 55 videos x 3 models
uv run python scripts/eval_benchmark_export.py        # 4. tables from the newest run (or --run-dir runs/<run start>)
```

`--incident-only` scores the incident fields only (no entity/instrument/asset matching, so no embedding server, and no RP1). Each record keeps its P1 round-trip time (`timing.p1_elapsed_s`), the video's size and length, its `outcome` (`scored`, `contract_invalid`, `parse_failure`, or no model output: `timeout`, `rate_limited`, `http_error`) and its judge-call count. P1 follows the fixed rate-limit policy `eval_vlm_client.P1_RATE_LIMIT_POLICY` (20 s between attempts; HTTP 429 only is retried, after 60 s or a longer `Retry-After`, at most twice), and an empty predicted description scores 0.0 without a judge call. The rules and their reasons are in [`../.docs/decisions.md`](../.docs/decisions.md) (2026-10-02 benchmark entry).

How P1 is sent, validated and scored: [`../.docs/mvp2/eval.md`](../.docs/mvp2/eval.md#11-eval-p1rp1-extraction-benchmark) and [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md). Operating it: the [`incident-run-eval`](../skills/incident-run-eval/SKILL.md) skill.

---
name: incident-run-eval
description: Use to run the standalone P1/RP1 evaluation pipeline in eval/ - start the local embedding server, ingest ground truth, generate the seeded split, batch-score VLM incident extraction against ground truth, aggregate across models and categories, or run its hermetic tests. Not for producing a single report (use incident-analyze-video) and not NVIDIA's `nat eval`.
license: Apache-2.0
metadata:
  version: "0.1.0"
  profile: "dev-profile-incident"
  tags: "incident evaluation benchmark ground-truth vlm"
---
# Incident Run Eval

`eval/` is its own `uv` project. It shares no runtime with other services. Its scoring code is a verbatim copy of `incident-console`'s modules.

Canonical facts:
- Setup and variables: [`eval/README.md`](../../eval/README.md)
- Methodology and recorded 3-model results: [`eval/docs/vlm_benchmark_results.md`](../../eval/docs/vlm_benchmark_results.md)
- `gt_*` and `*_matches` tables: [`.docs/data.md`](../../.docs/data.md)

## Prerequisites

1. `cd deploy/docker/developer-profiles/dev-profile-incident/eval && uv sync`
2. `eval/.env.local` is a symlink to `../.env.local`. Beyond the standard Supabase and R2 variables, it needs `VLM_GATEWAY_API_KEY` (or `INCIDENT_LLM_API_KEY`), `INCIDENT_LLM_BASE_URL` (the real Switchyard gateway, not the mock), `INCIDENT_JUDGE_MODEL` and `INCIDENT_EMBEDDING_BASE_URL`. These are **not** in the committed `.env`, so check they exist before any live run.
3. The ground-truth workbook and all working data stay under `eval/eval_data/`, which `eval/.gitignore` excludes. Never commit it.

## Instructions

```bash
# 1. Local embedding server (separate terminal; prints the INCIDENT_EMBEDDING_BASE_URL to set)
uv run python scripts/eval_embedding_server.py

# 2. One-off: ingest real ground truth, then generate the seeded split
uv run python scripts/eval_ingest_gt.py
uv run python scripts/eval_generate_split.py

# 3. Smoke test first (1 model, 1 category, 1 video), then the full run
uv run python scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner --categories Assault --limit 1
uv run python scripts/eval_run.py

# 4. Aggregate across models/categories
uv run python scripts/eval_aggregate.py
```

**Always smoke-test before a full run.** A full run spends hosted-inference quota across 3 models × 5 categories.

## Verify

- `uv run pytest tests/` passes. The tests are hermetic: no live Postgres, agent or GPU.
- The smoke run writes `eval_data/results/<category>__<model>.json` with non-null field scores.

## Scoring (what the numbers mean)

| Field | Method |
|---|---|
| type, severity | Exact match |
| description | LLM-judge score (`INCIDENT_JUDGE_MODEL`) |
| start, end, duration | Temporal tolerance |
| entities, instruments, assets | Embedding similarity + Hungarian matching → precision / recall / F1 |

## After changing anything

- If methodology or results change, update `eval/docs/vlm_benchmark_results.md`.
- If scoring code changes, remember `incident-console/` holds the original copy. Record whether the two are meant to stay in sync in [`.docs/decisions.md`](../../.docs/decisions.md).

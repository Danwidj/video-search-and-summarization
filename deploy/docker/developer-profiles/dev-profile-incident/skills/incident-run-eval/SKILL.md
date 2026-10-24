---
name: incident-run-eval
description: Use to run the standalone P1/RP1 evaluation pipeline in eval/ - start the local embedding server, ingest ground truth, generate the seeded split, batch-score VLM incident extraction against ground truth, aggregate across models and categories, or run its hermetic tests. Not for producing a single report (use incident-analyze-video) and not NVIDIA's `nat eval`.
license: Apache-2.0
metadata:
  version: "0.1.1"
  profile: "dev-profile-incident"
  tags: "incident evaluation benchmark ground-truth vlm"
---
# Incident Run Eval

`eval/` is its own `uv` project. It shares no runtime with other services. Its scoring code began as a verbatim copy of the v1 console's modules (v1 is archived under `archived/incident-console/`).

Canonical facts:
- Setup and variables: [`eval/README.md`](../../eval/README.md)
- Methodology and recorded 3-model results: [`eval/docs/vlm_benchmark_results.md`](../../eval/docs/vlm_benchmark_results.md)
- Handoff and open items (including the dropped `gt_*` tables): [`.docs/mvp2/eval.md`](../../.docs/mvp2/eval.md)

## Prerequisites

1. `cd deploy/docker/developer-profiles/dev-profile-incident/eval && uv sync`
2. `eval/.env.local` is a symlink to `../.env.local`. Its Supabase values (`INCIDENT_DB_DSN`, `INCIDENT_SUPABASE_*`) must name the **finals** project; midterm is a frozen read-only record and refuses writes. Finals dropped the `gt_*` and relational report tables (`20261023000000`), and `init_schema()` creates any of eval's tables that are missing, so do not run a live eval against finals until eval's storage is decided ([eval open item 1](../../.docs/mvp2/eval.md)). Beyond the standard Supabase and R2 variables, it needs `VLM_GATEWAY_API_KEY` (or `INCIDENT_LLM_API_KEY`), `INCIDENT_LLM_BASE_URL` (the real Switchyard gateway, not the mock), `INCIDENT_JUDGE_MODEL` and `INCIDENT_EMBEDDING_BASE_URL`. These are **not** in the committed `.env`, so check they exist before any live run.
3. The ground-truth workbook and all working data stay under `eval/eval_data/`, which `eval/.gitignore` excludes. Never commit it.

## What a run sends

P1 uses the shared [incident contract](../../contracts/README.md) (`incident-contract-v4`):
- a signed R2 URL, then the contract prompt, with the schema enforced via `response_format`;
- no few-shot examples;
- a fixed `max_tokens 16384` and `num_frames 64`.

Responses are judged under validation policy `core-scored-v1`. A core failure is scored as a miss and listed under `core_failures`, and its RP1 is skipped. When core fields are valid (`core_ok`), RP1 runs on the unchanged prediction with timeline context. **Never loosen the parser to raise a score.** A model with many contract or core failures is a finding, not a bug to paper over. Details: [`eval/README.md`](../../eval/README.md).

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
- `eval_ingest_gt.py` prints no `WARNING: ... has incident type` line. If it does, a workbook `Type` is not one of the five standard types. The row is still stored, normalised to lowercase; fix the workbook and re-ingest.
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
- `eval/` is the only maintained copy of the scoring code. Never update `archived/incident-console/` to match it.

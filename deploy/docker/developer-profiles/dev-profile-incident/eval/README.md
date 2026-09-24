# P1/RP1 evaluation pipeline

This is a standalone **Python** subproject, living at the `dev-profile-incident` profile root alongside
`incident-console/`, `incident-console-v2/`, and `vlm-gateway/` - not nested inside any of them. It runs as its own
separate Python process with its own virtual environment and shares no code or runtime with any other service in
this profile beyond the copied modules below.

It evaluates structured incident extraction ("P1") across three VLMs on held-out video, and generates ("RP1", never
scored) a human-readable report per prediction. Full methodology and the three-model benchmark results are in
[`docs/vlm_benchmark_results.md`](docs/vlm_benchmark_results.md).

## Why it needs incident-console's modules

The scoring/matching/DB-access code this pipeline depends on (`matching.py`, `eval_gt.py`, `config.py`, `db.py`,
`db_connection.py`, `embed_client.py`, `incident_report.py`, `r2_videos.py`) is copied verbatim from
`incident-console` - it is the same scoring and data-access code, not a reimplementation, and not wired back to the
original (no shared imports, no shared `sys.path` entry). The original `incident-console` copy is unaffected by
this and continues to work independently. Two files carry a small, deliberate path-resolution note for their
directory depth (one level under `dev-profile-incident/`, the same depth as `incident-console/`) - see the comments
in `config.py` (`.env` loading) and `scripts/eval_vlm_client.py` (`ENV_LOCAL`).

The Streamlit UI itself (`app.py`, `report_detail.py`, and the other page modules) was **not** copied - this
project only runs the batch evaluation, never a UI.

## Setup

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/eval
uv sync
```

Required environment variables (read from `.env.local`, a symlink to `../.env.local`, i.e. the same
`dev-profile-incident/.env.local` every other service in this profile shares):

| Variable | Purpose |
|---|---|
| `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | PostgREST access to the ground-truth/incidents tables (used when direct Postgres, `INCIDENT_DB_DSN`, is unreachable) |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` | Video resolution/caching from Cloudflare R2 |
| `VLM_GATEWAY_API_KEY` (or `INCIDENT_LLM_API_KEY`, same value) | P1/RP1 inference calls through `vlm-gateway` |
| `INCIDENT_LLM_BASE_URL` | Chat-completions endpoint (the switchyard gateway URL, not the mock) |
| `INCIDENT_JUDGE_MODEL` | LLM-judge model for the `description` field's semantic score |
| `INCIDENT_EMBEDDING_BASE_URL` | Points at a locally-run `scripts/eval_embedding_server.py` instance (`sentence-transformers/all-MiniLM-L6-v2`; no remote embeddings endpoint exists for this deployment) |

None of `INCIDENT_LLM_API_KEY`, `INCIDENT_JUDGE_MODEL`, or a real `INCIDENT_EMBEDDING_BASE_URL` value ship in the
committed `.env` placeholder - if they're missing from `.env.local`, add them before running anything live.

## Running

```bash
# 1. Start the local embedding server (separate terminal, stays running)
uv run python scripts/eval_embedding_server.py   # prints the INCIDENT_EMBEDDING_BASE_URL to set

# 2. Ground truth: ingest the real (not demo) workbook once
uv run python scripts/eval_ingest_gt.py

# 3. Generate the per-category demonstration/evaluation split once (seeded, persisted)
uv run python scripts/eval_generate_split.py

# 4. Run the batch evaluation
uv run python scripts/eval_run.py                 # full run: all 3 models, all 5 categories
uv run python scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner --categories Assault --limit 1  # smoke test

# 5. Cross-category/cross-model aggregation
uv run python scripts/eval_aggregate.py
```

Tests: `uv run pytest tests/` - hermetic, no live Postgres/agent/GPU required (see `tests/conftest.py`).

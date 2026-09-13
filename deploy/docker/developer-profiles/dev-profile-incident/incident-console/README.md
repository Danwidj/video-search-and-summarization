<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# incident-console

Streamlit console for the VSS incident search & reporting capstone. Front-end
migrated from the sibling `rise-up` project onto this blueprint fork. See
[`docs/incident-plan/`](../../../../../docs/incident-plan/) for the full plan;
this app implements the frontend half of
`incident-plan-implementation-shared.md` §3 and §5.

This package is **profile-exclusive** — it lives here, not under the shared
`deploy/docker/services/` tree.

## Local dev loop (no Docker, no GPU)

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
uv sync
uv run streamlit run app.py
```

The app imports and starts with nothing else running, but it is **database-backed
and has no offline mode**: `INCIDENT_DB_DSN` must be set for any page to show
data (see the next section). Other dependencies still degrade gracefully:

- **No `INCIDENT_DB_DSN`** → every page shows a visible *database not configured*
  state instead of erroring; no incident data is rendered.
- **No agent** → the AI-trigger calls fail soft with a notice.
- **No `INCIDENT_VIDEO_BASE_URL` and no R2 keys** → playback shows the stored key
  and the incident window instead of a player.

## Supabase Postgres + the 8-mock seed

With `INCIDENT_DB_DSN` set, the pages read and write incidents through `db.py`
(`IncidentDB`), so field edits, review-status changes, video re-links and
severity ratings persist across a refresh. `init_schema()` creates every table
on first use (`checkfirst=True`; no additive column backfill — the schema is
created fresh, not migrated).

**Secrets never go in a tracked file.** `dev-profile-incident/.env` is committed
and stays placeholders. Put the real Supabase DSN and Cloudflare R2 keys in
`incident-console/.env.local`, which `incident-console/.gitignore` keeps out of
git and `config.py` loads with `override=True` on top of `.env`:

```dotenv
# incident-console/.env.local  (untracked)
INCIDENT_DB_DSN=postgresql+psycopg2://USER:PASSWORD@HOST:5432/postgres?sslmode=require
R2_ACCOUNT_ID=...
R2_ACCESS_KEY=...
R2_SECRET_KEY=...
R2_BUCKET=anomaly-detection-dataset
```

Use the Supabase **session pooler** (port 5432) so DDL and `SELECT ... FOR
UPDATE` work. Percent-encode reserved characters in the password (`@` → `%40`).

Load the 72 CSV-fixture incidents once (idempotent, manual, never runs on
startup):

```bash
uv run python scripts/seed_supabase.py
```

It upserts one `videos` row per incident (natural key: the incident id itself
- 1 video = 1 incident), one shared `model_runs` row (`MR-SEED`), and each
incident's `incidents` / `entities` / `instruments` / `assets` rows. Re-running
updates in place — row counts do not grow. The dataset lives in
`fixtures/data/*.csv`, parsed via `scripts/seed_data.py`.

### Mock LLM (exercise the AI-trigger path with zero GPU)

`mock_llm_server.py` is a tiny OpenAI-compatible stub. It is **local-dev only**
and is never deployed to the VM.

```bash
uv run uvicorn mock_llm_server:app --port 8900
# then, in the console's environment:
export INCIDENT_LLM_BASE_URL=http://localhost:8900/v1
```

`POST /v1/chat/completions` returns a canned completion whose `content` is an
`IncidentReport`-shaped JSON blob (`incident_type`, `severity` 1–5,
`confidence`, `incident_start`/`incident_end`, `description`, `persons[]`). It
exercises the same route → parse → Postgres-write path the real agent will use
for the deferred report-generation flow (`agent_client.py`).

The two agent AI-trigger endpoints —
`POST /api/v1/incidents/{id}/analyze` and `POST /api/v1/search` — do **not**
exist server-side yet (follow-up task). The client is written against the
plan's contract and returns a "not implemented yet" notice when they 404.

### Tests

```bash
uv run pytest
```

Fast and hermetic — SQLite fixture for the data layer, `httpx.MockTransport`
for the agent client. No live Postgres / agent / GPU.

### Lint

```bash
uv run ruff check .
uv run ruff format --check .
```

## Environment variables

All are read by `config.py`, which loads `../.env` (committed placeholders) then
`./.env.local` (untracked real secrets) with override. Real values and their
source are documented in [`dev-profile-incident/.env`](../.env).

| Variable | Purpose | Real source |
|---|---|---|
| `INCIDENT_DB_DSN` | SQLAlchemy sync URL for the incident Postgres | Supabase Postgres (session pooler, port 5432); put it in `.env.local`. `incident-plan-implementation-shared.md` §1. A SQLite DSN also works, but only for the local-dev loop in [`LOCAL_MOCK_LOOP.md`](../LOCAL_MOCK_LOOP.md) — production stays Supabase Postgres via the session pooler |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_BUCKET` | Cloudflare R2 for video clips + evidence screenshots (`r2_videos.py`) | The R2 bucket the captain uploaded footage to; put keys in `.env.local` |
| `INCIDENT_AGENT_BASE_URL` | Base URL of vss-agent's upload + AI-trigger API | The running `vss-agent` service (`VSS_AGENT_PORT`, default `8000`) |
| `INCIDENT_LLM_BASE_URL` | OpenAI-compatible chat-completions base URL | `mock_llm_server.py` locally; vss-agent's `LLM_BASE_URL` / a real NIM on the VM |
| `INCIDENT_EMBEDDING_BASE_URL` | OpenAI-compatible embeddings base URL for `matching.py` | The platform's embedding endpoint; unset means matching fails soft to no matches |
| `INCIDENT_VIDEO_BASE_URL` | Optional playback URL prefix; unset uses R2 presigned URLs | The R2 bucket public/presigned URL prefix |
| `INCIDENT_SEVERITY_NOTIFY_THRESHOLD` | Severity ≥ this raises a notification on verify (default `4`) | **Plan default, not spec** — confirm with the team |

## VM deploy

`Dockerfile` + `compose.yml` here are for the VM deploy only (service
`incident-console`, compose profile `bp_developer_search_2d`). Local dev never
uses them. The image is a `uv sync --frozen --no-dev` multi-stage build per
`incident-plan-implementation-shared.md` §3.

## Layout

| File | Role |
|---|---|
| `app.py` | Entry point / navigation home + environment panel |
| `pages/1_Catalog.py` | Browse ingested videos with filename / status filters + per-video incident-report count (browse-only, database-backed) |
| `pages/2_Report_Review.py` | Report review + edit + review status + jump-to-timestamp (database-backed) |
| `pages/3_Dashboard.py` | Filters + aggregate insights over DB incidents + linked evidence (database-backed) |
| `pages/4_Severity_Eval.py` | Human-vs-AI severity rating + running exact-agreement rate (database-backed) |
| `db.py` | Direct-Postgres data layer (sync SQLAlchemy Core): `videos` / `queries` / `model_runs`, model-output `incidents` / `entities` / `instruments` / `assets` (keyed by `model_run_id`), ground-truth `gt_incidents` / `gt_entities` / `gt_instruments` / `gt_assets`, `entity_matches` / `instrument_matches` / `asset_matches`, `review_status`, `notifications`, `severity_eval_log` |
| `db_reports.py` | Postgres-backed Incident view model (edits persist; reads the most recent model run per incident) |
| `r2_videos.py` | Read-only R2 catalog, presigned playback / screenshot URLs, bucket picker helpers |
| `embed_client.py` | Embedding-endpoint HTTP client (fail-soft), used by `matching.py` |
| `matching.py` | Similarity-based matching of one model run's entities/instruments/assets against ground truth (Hungarian assignment + threshold) |
| `scripts/seed_data.py` / `scripts/seed_supabase.py` | The 72 CSV-fixture incidents (one shared `model_run_id`) + evidence, and the one-time idempotent importer |
| `agent_client.py` | vss-agent upload + AI-trigger HTTP client (fail-soft) |
| `incident_report.py` | `IncidentReport` schema + `INCIDENT_TYPES` (road accident / burglary / explosion / fighting / animal) + pure helpers |
| `config.py` | Env-driven configuration (`.env` then untracked `.env.local`) |
| `theme.py` / `ui.py` | Shared look-and-feel and page helpers |
| `mock_llm_server.py` | Local-dev-only OpenAI-compatible stub |

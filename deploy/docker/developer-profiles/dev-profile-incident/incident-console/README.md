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

## Local dev loop (no Docker, no GPU, no live backend)

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
uv sync
uv run streamlit run app.py
```

The app starts cleanly with nothing else running. Every screen degrades
gracefully:

- **No `INCIDENT_DB_DSN`** → catalog / review / dashboard / eval show a visible
  *database not configured* state instead of erroring. Report Review and the
  Dashboard fall back to the offline CSV fixture (`fixtures/`), session-only:
  edits do not persist.
- **No agent** → upload and the two AI-trigger calls fail soft with a notice.
- **No `INCIDENT_VIDEO_BASE_URL` and no R2 keys** → playback shows the stored key
  and the incident window instead of a player.

## Supabase Postgres + the 8-mock seed

With `INCIDENT_DB_DSN` set, Report Review and the Dashboard read and write
incidents through `db.py` (`IncidentDB`), so field edits, review-status changes
and video re-links persist across a refresh. `init_schema()` creates every table
(and back-fills the additive columns on a pre-existing schema) on first use.

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

Load the 8 mock incidents once (idempotent, manual, never runs on startup):

```bash
uv run python scripts/seed_supabase.py
```

It upserts 8 `videos` rows (natural key: `r2_key`, all under `normal_videos/`),
one `incident_reports` row per clip linked by a fixed FK, and each incident's
fabricated entities / instruments / assets. Re-running updates in place — row
counts do not grow. The dataset lives in `scripts/seed_data.py`.

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
`confidence`, `incident_start`/`incident_end`, `description`, `persons[]`). The
"Draft report via mock LLM" button on the Catalog page calls it through the same
route → parse → Postgres-write path the real agent will use.

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
| `INCIDENT_DB_DSN` | SQLAlchemy sync URL for the incident Postgres | Supabase Postgres (session pooler, port 5432); put it in `.env.local`. `incident-plan-implementation-shared.md` §1 |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_BUCKET` | Cloudflare R2 for video clips + evidence screenshots (`r2_videos.py`) | The R2 bucket the captain uploaded footage to; put keys in `.env.local` |
| `INCIDENT_AGENT_BASE_URL` | Base URL of vss-agent's upload + AI-trigger API | The running `vss-agent` service (`VSS_AGENT_PORT`, default `8000`) |
| `INCIDENT_LLM_BASE_URL` | OpenAI-compatible chat-completions base URL | `mock_llm_server.py` locally; vss-agent's `LLM_BASE_URL` / a real NIM on the VM |
| `INCIDENT_VIDEO_BASE_URL` | Optional playback URL prefix; unset uses R2 presigned URLs | The R2 bucket public/presigned URL prefix |
| `INCIDENT_SEVERITY_NOTIFY_THRESHOLD` | Severity ≥ this raises a notification on verify (default `4`) | **Plan default, not spec** — confirm with the team |
| `INCIDENT_SEVERITY_EVAL_DISAGREE_THRESHOLD` | Human/AI severity delta that flags a disagreement (default `1`) | **Plan default, not spec** — confirm with the team |

## VM deploy

`Dockerfile` + `compose.yml` here are for the VM deploy only (service
`incident-console`, compose profile `bp_developer_search_2d`). Local dev never
uses them. The image is a `uv sync --frozen --no-dev` multi-stage build per
`incident-plan-implementation-shared.md` §3.

## Layout

| File | Role |
|---|---|
| `app.py` | Entry point / navigation home + environment panel |
| `pages/1_Catalog.py` | Catalog + upload + metadata edit |
| `pages/2_Report_Review.py` | Report review + edit + review status + jump-to-timestamp; DB-backed when a DSN is set, offline CSV otherwise |
| `pages/3_Dashboard.py` | Filters + aggregate insights; DB incidents + evidence when a DSN is set, offline CSV otherwise |
| `pages/4_Severity_Eval.py` | Human-vs-AI severity eval |
| `db.py` | Direct-Postgres data layer (sync SQLAlchemy Core): `videos`, `incident_reports`, `incident_entities` / `incident_instruments` / `incident_assets`, `notifications`, `severity_eval_log` |
| `db_reports.py` | Postgres-backed Incident view model (same shape as `local_reports.py`; edits persist) |
| `local_reports.py` | Offline CSV-fixture view model (session-only edits) |
| `r2_videos.py` | Read-only R2 catalog, presigned playback / screenshot URLs, bucket picker helpers |
| `scripts/seed_data.py` / `scripts/seed_supabase.py` | The 8 mock incidents + evidence, and the one-time idempotent importer |
| `agent_client.py` | vss-agent upload + AI-trigger HTTP client (fail-soft) |
| `incident_report.py` | `IncidentReport` schema + `INCIDENT_TYPES` + pure helpers |
| `config.py` | Env-driven configuration (`.env` then untracked `.env.local`) |
| `theme.py` / `ui.py` | Shared look-and-feel and page helpers |
| `mock_llm_server.py` | Local-dev-only OpenAI-compatible stub |

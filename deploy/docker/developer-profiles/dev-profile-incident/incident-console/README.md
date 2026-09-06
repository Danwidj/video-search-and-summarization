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
  *database not configured* state instead of erroring.
- **No agent** → upload and the two AI-trigger calls fail soft with a notice.
- **No `INCIDENT_VIDEO_BASE_URL`** → playback shows the stored key and the
  incident window instead of a player.

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

All are read by `config.py`; real values and their source are documented in
[`dev-profile-incident/.env`](../.env).

| Variable | Purpose | Real source |
|---|---|---|
| `INCIDENT_DB_DSN` | SQLAlchemy sync URL for the incident Postgres (via Hyperdrive) | Team's Hyperdrive-fronted Postgres (Neon/Supabase/self-managed), `incident-plan-implementation-shared.md` §1 |
| `INCIDENT_AGENT_BASE_URL` | Base URL of vss-agent's upload + AI-trigger API | The running `vss-agent` service (`VSS_AGENT_PORT`, default `8000`) |
| `INCIDENT_LLM_BASE_URL` | OpenAI-compatible chat-completions base URL | `mock_llm_server.py` locally; vss-agent's `LLM_BASE_URL` / a real NIM on the VM |
| `INCIDENT_VIDEO_BASE_URL` | Public/presigned URL prefix `st.video` plays from | The R2 bucket public/presigned URL prefix |
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
| `pages/2_Report_Review.py` | Report review + verify + edit + jump-to-timestamp |
| `pages/3_Dashboard.py` | Filters + aggregate insights |
| `pages/4_Severity_Eval.py` | Human-vs-AI severity eval |
| `db.py` | Direct-Postgres data layer (sync SQLAlchemy Core, 4 tables) |
| `agent_client.py` | vss-agent upload + AI-trigger HTTP client (fail-soft) |
| `incident_report.py` | `IncidentReport` schema + pure helpers (severity/notification thresholds, insights, timestamp fallback, completion parsing) |
| `config.py` | Env-driven configuration |
| `theme.py` / `ui.py` | Shared look-and-feel and page helpers |
| `mock_llm_server.py` | Local-dev-only OpenAI-compatible stub |

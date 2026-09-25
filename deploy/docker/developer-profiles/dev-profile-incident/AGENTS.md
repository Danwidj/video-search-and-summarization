# AGENTS.md - dev-profile-incident

## Project overview

Incident search and reporting capstone on the VSS blueprint (sponsor: NVIDIA NVAITC). A reviewer uploads a clip, a VLM extracts a structured incident report, and the report is stored in Supabase (rows) and Cloudflare R2 (video). Reviewers then verify it, and it is scored against ground truth. MVP1 (reporting) is done. MVP2 (natural-language search) is not started.

- **Operate the profile** (launch, VM ops, analyse, migrate, evaluate): use the skills in [`skills/README.md`](skills/README.md).
- **Understand it:** [`.docs/`](#docs-map). Start with [`.docs/status.md`](.docs/status.md) for what is true today.
- **Change code:** this file.

## Components

| Path | Stack | Role | Status |
|---|---|---|---|
| `incident-console-v2/` | Next.js 15, TypeScript, Zod | Primary UI :3200: upload, analysis orchestration, review, eval form | Active |
| `vlm-gateway/` | FastAPI, `uv` | Holds the Brev key server-side; `/v1/chat/completions` :8600 | Active |
| `mock-backend/base_profile_mock/` | FastAPI, `uv` | Zero-GPU mock of vss-agent + VST :7777 | Active |
| `mock-backend/search_profile_mock/` | FastAPI, `uv` | Search-profile superset mock :7778 | Active (MVP2 prep) |
| `eval/` | Python, `uv` | Standalone P1/RP1 VLM benchmark | Active |
| `supabase/migrations/` | SQL | Schema authority for new changes; `insert_incident` RPC | Active |
| `start.sh`, `.scripts/`, `.dotfiles/` | Bash | Laptop launcher; VM lifecycle scripts; VM shell bootstrap | Active |
| `incident-console/` | Streamlit | v1 console | **Retired.** Fix only; no features. |
| `services/agent/` (outside this dir) | Python, NAT | `POST /api/v1/incidents/{id}/analyze`, `incident_report_gen`, `utils/incident_db.py` | Follow [`services/agent/AGENTS.md`](../../../../services/agent/AGENTS.md) |

## Commands

Run from each component's directory. Run a component's checks after every change to it.

```bash
# incident-console-v2
npm install && npm run typecheck && npm test

# vlm-gateway (no tests dir yet)
uv sync && uv run ruff check .

# mock-backend/base_profile_mock (same pattern for search_profile_mock)
uv sync && uv run ruff check . && uv run pytest

# eval (hermetic: no live DB, agent or GPU)
uv sync && uv run pytest tests/

# services/agent incident code: see services/agent/AGENTS.md (ruff, ruff format, mypy, pytest)
```

## Architecture rules

- **1 video = 1 incident:** `videos.id` == `incidents.incident_id`, with no separate `video_id`. Every analysis gets its own `model_run_id`, and evidence tables key on `(incident_id, model_run_id)`.
- **Two analysis modes:**
  - `ANALYSIS_MODE=gateway`: the console calls `vlm-gateway` and writes Supabase itself.
  - `ANALYSIS_MODE=agent`: the console calls the native `vss-agent`, which writes `incidents` and evidence.
  - A change to one mode's persistence must be checked against the other. See [`.docs/analysis-schema.md`](.docs/analysis-schema.md).
- **PostgREST only from `kwanz-ws`:** port 5432 is DPI-blocked there. All PostgREST writers use `/rpc/insert_incident` for atomic `incidents` + `review_status`.
- **Storage split:**
  - R2 holds videos, and `videos.filepath` must hold an **R2 key**, never a VST URL.
  - Supabase holds rows.
  - VIOS disk is only a cache.
- **Secrets are server-side only:**
  - In the console, never use `NEXT_PUBLIC_` for any credential or URL. `/api/health` returns booleans only.
  - The gateway, not the browser, owns `VLM_GATEWAY_API_KEY`.
- **Remote models use `_type: openai`,** never `_type: nim`, with bare base URLs (no `/v1`).

## Boundaries

- **Always:**
  - Run the component's checks.
  - Add the SPDX license header used by neighbouring files.
  - Update the affected `.docs/` file and skill in the same PR (see [Docs rule](#docs-rule)).
- **Ask first:**
  - Applying a migration to the live Supabase DB.
  - Anything that restarts or stops shared services on `kwanz-ws`.
  - Editing `generated.env.remote`.
  - Starting Option B work ([`.docs/restructure-plan.md`](.docs/restructure-plan.md) is awaiting approval).
  - Adding dependencies.
- **Never:**
  - Commit or print `.env.local`, keys or DSNs.
  - Run `dev-profile.sh down` or `up` for this profile. It wipes the VM model cache and does not know the profile.
  - Start the Docker `vss-agent` while the native one runs.
  - Add features to the retired `incident-console/`.
  - Skip failing tests.

## Docs rule

Stale docs are a defect, not a follow-up. Any change in this directory updates, in the same PR:

| Change | Update |
|---|---|
| Scope or milestones | [`.docs/action-plan.md`](.docs/action-plan.md) |
| Implementation status, known issues, live VM config | [`.docs/status.md`](.docs/status.md) (a snapshot: rewrite it, don't append) |
| Topology, components, sequences | [`.docs/architecture.md`](.docs/architecture.md) |
| Schema or R2 layout | [`.docs/data.md`](.docs/data.md) |
| Report model or field translation | [`.docs/analysis-schema.md`](.docs/analysis-schema.md) |
| Runtime, deploy, troubleshooting facts | [`.docs/incident-profile-operations.md`](.docs/incident-profile-operations.md) |
| A command, port, script or API contract that a skill uses | The matching `skills/incident-*/SKILL.md` |
| Any architectural or tooling decision | New entry at the top of [`.docs/decisions.md`](.docs/decisions.md): Decision / Why / Alternatives rejected / Links |
| A doc or skill added, moved or renamed | [`README.md`](README.md) doc index and [`skills/README.md`](skills/README.md) |

## Docs map

| File | Read when |
|---|---|
| [`.docs/status.md`](.docs/status.md) | Starting any task: what's done, known issues, live VM config |
| [`.docs/action-plan.md`](.docs/action-plan.md) | Checking scope or MVP1/MVP2 goals |
| [`.docs/architecture.md`](.docs/architecture.md) | Touching more than one component, or tracing a request |
| [`.docs/data.md`](.docs/data.md) | Touching tables, the RPC, cascades or R2 keys |
| [`.docs/analysis-schema.md`](.docs/analysis-schema.md) | Touching report fields, prompts or translation |
| [`.docs/incident-profile-operations.md`](.docs/incident-profile-operations.md) | Anything on `kwanz-ws` |
| [`.docs/decisions.md`](.docs/decisions.md) | Before reversing an existing choice |
| [`.docs/restructure-plan.md`](.docs/restructure-plan.md) | Option B (proposed, not approved) |
| [`.docs/archive/`](.docs/archive/) | Historical plans only. Not current truth. |

# AGENTS.md - dev-profile-incident

## Project overview

Incident search and reporting capstone on the VSS blueprint (sponsor: NVIDIA NVAITC). A reviewer uploads a clip, a VLM extracts a structured incident report, and the report is stored in Supabase (rows) and Cloudflare R2 (video). Reviewers then verify it, and it is scored against ground truth. MVP2 adds natural-language search ([`.docs/mvp2/README.md`](.docs/mvp2/README.md)).

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
| `contracts/` | JSON Schema, Markdown, JSON | Shared P1/RP1 prompts, incident output schema (`incident-contract-v3`), model allowlist + P1 settings (`inference.json`), shared validator fixtures | Active: eval, console (gateway and agent mode) and vss-agent all use it ([schema](.docs/analysis-schema.md)) |
| `supabase/` | SQL, Python | Finals schema authority (`migrations/`: one baseline, then later finals migrations), SQL harness (`tests/`), midterm-to-finals copy (`copy/`) | Active. `supabase/midterm/` is the frozen midterm record: never push |
| `start.sh`, `.scripts/`, `.dotfiles/` | Bash | Laptop launcher; VM lifecycle scripts; VM shell bootstrap | Active |
| `archived/incident-console/` | Streamlit | v1 console | **Archived.** Read-only history; never launched, set up, tested or changed. `incident-console-v2/` is the only console. |
| `services/agent/` (outside this dir) | Python, NAT | `POST /api/v1/incidents/{id}/analyze`, `incident_report_gen`, `utils/incident_db.py` | Follow [`services/agent/AGENTS.md`](../../../../services/agent/AGENTS.md) |

## Commands

Run from each component's directory. Run a component's checks after every change to it.

```bash
# incident-console-v2 (tests need a Node build with TypeScript stripping; otherwise use npx -y node@22)
npm install && npm run typecheck && npm test

# vlm-gateway (no tests dir yet)
uv sync && uv run ruff check .

# mock-backend/base_profile_mock (same pattern for search_profile_mock)
uv sync && uv run ruff check . && uv run pytest

# eval (hermetic: no live DB, agent or GPU)
uv sync && uv run pytest tests/

# supabase (hermetic SQL harness on a throwaway Postgres: no Supabase, no network)
cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py

# services/agent incident code: see services/agent/AGENTS.md (ruff, ruff format, mypy, pytest)
```

## Architecture rules

- **1 video = 1 incident:** `videos.id` == `incidents.incident_id` (no `video_id`). Every analysis gets its own `model_run_id`; evidence tables key on `(incident_id, model_run_id)`.
- **Two analysis modes** (`ANALYSIS_MODE`): `gateway` (console calls `vlm-gateway`) and `agent` (console calls the native `vss-agent` for P1 only, `skip_rp1`). In both the console writes Supabase; the agent persists nothing when given a `model_run_id` and never writes `videos`. Check a persistence change against both modes. Details: [`.docs/analysis-schema.md`](.docs/analysis-schema.md).
- **Both modes use `incident-contract-v3`** from `contracts/` (vendored in `services/agent/src/vss_agents/incident_contract/`), with strict validation and only the ID-only `id-normalization-v1` recovery. Every attempt is recorded in `model_runs.notes` with its outcome.
  - Never modify `model_runs.notes` after an attempt is written.
  - Never add a repair step that changes semantic content, or let repair affect eval results.
  - Contract changes bump `contracts/VERSION` and update eval and the console together (shared `contracts/fixtures/` guard both validators).
- **Console database access goes through the middle layer:** `incident-console-v2` routes get ports from `getDbAdapters()`; only `lib/adapters/supabase/` builds PostgREST queries or names tables, columns and `p_*` arguments, and maps them to camelCase domain types. Callers not yet migrated are listed in [`.docs/mvp2/console-hexagonal-architecture.md`](.docs/mvp2/console-hexagonal-architecture.md) §7.
- **The AI report rows are never edited.** Reviewer edits and verification write a separate reviewer version (`human_reports`, via `save_human_report_edit` / `set_review_status`); readers meaning "the current report" use the `effective_*` views. Official reports are explicit (`select_official_report`); never infer "latest run wins".
- **Failed attempts** (`contract_failed` / `request_failed`) are `model_runs` rows only, never reports. Count runs by outcome, not raw rows.
- **PostgREST only from `kwanz-ws`** (port 5432 is DPI-blocked). All PostgREST writers use `/rpc/insert_incident`.
- **Storage:** R2 holds videos (`videos.filepath` is an **R2 key**, never a VST URL); Supabase holds rows; VIOS disk is only a cache.
- **Secrets are server-side only:** never `NEXT_PUBLIC_` for a credential or URL; `/api/health` returns booleans only; the gateway owns `VLM_GATEWAY_API_KEY`.
- **Remote models use `_type: openai`,** never `_type: nim`, with bare base URLs (no `/v1`).

## Boundaries

- **Always:** run the component's checks; add the neighbouring SPDX header; update the affected `.docs/` file and skill in the same PR ([Docs rule](#docs-rule)).
- **Ask first:** applying a migration to the live (finals) Supabase DB; restarting or stopping shared services on `kwanz-ws`; editing `generated.env.remote`; adding dependencies.
- **Never:**
  - Commit or print `.env.local`, keys or DSNs.
  - Write to, push to or apply anything to the frozen midterm Supabase project (`rfevukimyftzbxlehwel`), or edit `supabase/midterm/`; the only exceptions are its freeze and unfreeze files at the cutover.
  - Run `dev-profile.sh down` or `up` for this profile (it wipes the VM model cache and does not know the profile).
  - Start the Docker `vss-agent` while the native one runs.
  - Change, run or import from anything under `archived/` (the v1 console lives there as read-only history).
  - Skip failing tests.

## Docs rule

Stale docs are a defect. Update in the same PR:

| Change | Update |
|---|---|
| A command, port, script or API contract | The matching `skills/incident-*/SKILL.md` and [`.docs/incident-profile-operations.md`](.docs/incident-profile-operations.md) |
| Schema, R2 layout or report fields | A new `supabase/migrations/` file after the baseline, `supabase/tests/test_baseline.py`, [`.docs/data.md`](.docs/data.md), [`.docs/analysis-schema.md`](.docs/analysis-schema.md) |
| Topology, components, sequences | [`.docs/architecture.md`](.docs/architecture.md) |
| Implementation state, known issues, live VM config | [`.docs/status.md`](.docs/status.md) (rewrite, don't append) |
| An architectural or tooling decision | New entry at the top of [`.docs/decisions.md`](.docs/decisions.md): Decision / Why / Alternatives rejected / Links |
| A doc or skill added, moved or renamed | [`README.md`](README.md) doc index and [`skills/README.md`](skills/README.md) |

## Docs map

| File | Read when |
|---|---|
| [`.docs/status.md`](.docs/status.md) | Starting any task: what is done, known issues, live VM config |
| [`.docs/action-plan.md`](.docs/action-plan.md) | Checking scope or goals |
| [`.docs/architecture.md`](.docs/architecture.md) | Touching more than one component, or tracing a request |
| [`.docs/data.md`](.docs/data.md) | Touching tables, the RPCs, cascades, security or R2 keys |
| [`.docs/analysis-schema.md`](.docs/analysis-schema.md) | Touching report fields, prompts, VLM calls or output parsing |
| [`.docs/incident-profile-operations.md`](.docs/incident-profile-operations.md) | Anything on `kwanz-ws` |
| [`.docs/vm-api-contracts.md`](.docs/vm-api-contracts.md) | Calling or changing a `vss-agent` HTTP endpoint or the tunnel ports |
| [`.docs/decisions.md`](.docs/decisions.md) | Before reversing an existing choice |
| [`.docs/mvp2/README.md`](.docs/mvp2/README.md) | Natural-language search work |
| [`.docs/mvp2/eval.md`](.docs/mvp2/eval.md) | Planning or changing retrieval, critic, detector or embedding evaluation |
| [`.docs/mvp2/console-hexagonal-architecture.md`](.docs/mvp2/console-hexagonal-architecture.md) | Changing an `incident-console-v2` API route or its database access |

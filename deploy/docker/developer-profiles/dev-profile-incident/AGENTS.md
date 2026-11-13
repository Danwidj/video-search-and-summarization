# AGENTS.md - dev-profile-incident

## Project overview

Incident search and reporting capstone on the VSS blueprint (sponsor: NVIDIA NVAITC). A reviewer uploads a clip, a VLM extracts a structured incident report, and the report is stored as an append-only Supabase revision (JSONB) with the video in Cloudflare R2. Reviewers edit it into new human revisions, one revision per incident is marked official, and eval scores model output separately. Natural-language search runs over evidence crops ([architecture](.docs/architecture.md#evidence-search-and-incident-search)).

- **Operate the profile** (launch, VM ops, analyse, migrate, evaluate): use the skills in [`skills/README.md`](skills/README.md); UI work in `incident-console-v2` should read the `shadcn` skill first.
- **Understand it:** [`.docs/`](#docs-map).
- **Change code:** this file.

## Components

| Path | Stack | Role |
|---|---|---|
| [`incident-console-v2/`](incident-console-v2/README.md) | Next.js 15, TypeScript, Zod, Biome | Primary UI :3200: upload, analysis orchestration, report page (video, versions graph, official star) |
| [`vlm-gateway/`](vlm-gateway/README.md) | FastAPI, `uv` | Holds the Brev key server-side; `/v1/chat/completions` :8600 |
| [`mock-backend/base_profile_mock/`](mock-backend/README.md) | FastAPI, `uv` | Zero-GPU mock of vss-agent + VST :7777 |
| [`eval/`](eval/README.md) | Python, `uv` | Standalone P1/RP1 VLM benchmark |
| [`contracts/`](contracts/README.md) | JSON Schema, Markdown, JSON | Shared P1/RP1 prompts, incident output schema (`incident-contract-v4`), model allowlist + P1 settings (`inference.json`), shared validator fixtures; eval, console (gateway and agent mode) and vss-agent all use it ([schema](.docs/analysis-schema.md)) |
| [`supabase/`](supabase/README.md) | SQL, Python | Finals schema authority (`migrations/`: one baseline, then later finals migrations), SQL harness (`tests/`) |
| `scripts/` | Python | `refresh_revision_embeddings.py` (re-embeds revision summaries after the summary text recipe changes) and `backfill_content_hash.py` (fills `videos.content_sha256`) |
| [`start.sh`, `.scripts/`](.scripts/README.md) | Bash | Laptop launcher; VM lifecycle scripts |
| [`archived/`](archived/README.md) | - | Frozen midterm database record, copy and R2 scripts, kept as read-only history: never push, never run (see Boundaries) |
| `services/agent/` (outside this dir) | Python, NAT | `POST /api/v1/incidents/{id}/analyze`, `incident_report_gen` (writes `report_revisions`), `POST /api/v1/incidents/evidence-embeddings`, search over `evidence_crops`, `utils/incident_db.py`. Follow [`services/agent/AGENTS.md`](../../../../services/agent/AGENTS.md) |

## Commands

Run from each component's directory. Run a component's checks after every change to it.

```bash
# incident-console-v2 (lint is Biome plus tsc; `npm run format` applies Biome's formatter;
# tests, including the import-boundary check, need a Node build with TypeScript stripping; otherwise use npx -y node@22)
npm install && npm run lint && npm run typecheck && npm test

# contracts (schemas, fixtures, vendored copy; run `python sync.py` after editing a contract file)
cd contracts && python sync.py --check && uv run --no-project --with pytest --with jsonschema pytest test_schema.py

# vlm-gateway (no tests dir yet)
uv sync && uv run ruff check .

# Run and verify the app with `./start.sh --mode vm` (VM agent), never `--mode mock`.
# mock-backend/base_profile_mock: a mock that mimics the backend, so run its own unit tests here
uv sync && uv run ruff check . && uv run pytest

# eval (hermetic: no live DB, agent or GPU)
uv sync && uv run pytest tests/

# supabase (hermetic SQL harness on a throwaway Postgres: no Supabase, no network)
cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py

# services/agent incident code: see services/agent/AGENTS.md (ruff, ruff format, mypy, pytest)
# `uv sync --group dev` there needs a C compiler and the cairo headers for pycairo
```

## Architecture rules

Why each rule holds: [`.docs/architecture.md`](.docs/architecture.md#solution-strategy).

- **Reports are versioned snapshots, never edited.** Each analysis writes an append-only `report_revisions` row (`kind='ai'`, new `model_run_id`); a human edit is a later `kind='human'` revision; re-generation is a new AI branch (`parent_id` NULL) and copies no earlier edits. The official version is the video's `official_revision_id`, chosen explicitly (never infer "latest run wins"). `evidence_crops` and `query_results` key on `revision_id`.
- **Two analysis modes** (`ANALYSIS_MODE`): `gateway` (console calls `vlm-gateway` and writes the AI revision; no crops) and `agent` (console calls the native `vss-agent` for P1 only; the agent writes the AI revision and its R2 crops, and the console verifies it). Check a persistence change against both modes. Who writes which row: [`.docs/analysis-schema.md`](.docs/analysis-schema.md#6-agent-mode).
- **Both modes use `incident-contract-v4`** from `contracts/` (vendored in `services/agent/src/vss_agents/incident_contract/`), with strict validation and only the ID-only `id-normalization-v1` recovery. Every attempt is recorded in `model_runs.notes` with its outcome.
  - Never modify `model_runs.notes` after an attempt is written.
  - Never add a repair step that changes semantic content, or let repair affect eval results.
  - Contract changes bump `contracts/VERSION` and update eval and the console together (shared `contracts/fixtures/` guard both validators).
- **Console code keeps the hexagonal layout:** routes get ports from `src/lib/container.ts`; only `src/modules/*/infrastructure/supabase/` and `src/lib/postgrest/` name tables, columns and `p_*` arguments. `npm test` enforces the import boundaries. Layout and rules: [`.docs/architecture.md`](.docs/architecture.md#level-2-the-console).
- **Failed attempts** (`contract_failed` / `request_failed`) are `model_runs` rows only, never reports. Count runs by outcome, not raw rows.
- **PostgREST only from the VM** (direct Postgres from the VM has been blocked on and off, so do not rely on it). PostgREST has no client transactions, so `report_revisions` inserts retry on a `revision_no` clash (SQLSTATE 23505).
- **Storage:** R2 holds videos (`videos.filepath` is an **R2 key**, never a VST URL); Supabase holds rows; VIOS disk is only a cache.
- **Secrets are server-side only:** never `NEXT_PUBLIC_` for a credential or URL; `/api/health` returns booleans only; the gateway owns `VLM_GATEWAY_API_KEY`.
- **Remote models use `_type: openai`,** never `_type: nim`, with bare base URLs (no `/v1`); why: [`.docs/architecture.md`](.docs/architecture.md#model-inference).

## Boundaries

- **Always:** run the component's checks; add the neighbouring SPDX header to code files (not to Markdown); update the affected `.docs/` file and skill in the same PR ([Docs rule](#docs-rule)).
- **Ask first:** applying a migration to the live (finals) Supabase DB; restarting or stopping shared services on the VM; editing `.env.remote`; pruning native-service images; adding dependencies.
- **Never:**
  - Commit or print `.env.local`, keys or DSNs.
  - Commit screenshots: they are evidence for the PR description only. The exception is the README demo clips in `.docs/figures/`.
  - Write to, push to or apply anything to the frozen midterm Supabase project (`rfevukimyftzbxlehwel`), or edit `archived/supabase/midterm/`; the only exceptions are its freeze and unfreeze files at the cutover.
  - Run `dev-profile.sh down` or `up` for this profile (it wipes the VM model cache and does not know the profile).
  - Start the Docker `vss-agent` while the native one runs.
  - Change, run or import from anything under `archived/`.
  - Skip failing tests.

## Docs rule

Stale docs are a defect. Update in the same PR:

| Change | Update |
|---|---|
| A command, port or script | The matching `skills/incident-*/SKILL.md`, [`.docs/incident-profile-operations.md`](.docs/incident-profile-operations.md) and, for deployment steps, [`README.md`](README.md) |
| An agent HTTP contract | [`.docs/vm-api-contracts.md`](.docs/vm-api-contracts.md) and the matching `contracts/` README |
| Schema, R2 layout or report fields | A new `supabase/migrations/` file after the baseline, `supabase/tests/test_baseline.py`, [`.docs/data.md`](.docs/data.md), [`.docs/analysis-schema.md`](.docs/analysis-schema.md) |
| Topology, components, sequences | [`.docs/architecture.md`](.docs/architecture.md); what a console page or route does: [`.docs/console-reference.md`](.docs/console-reference.md) |
| A doc or skill added, moved or renamed | [`skills/README.md`](skills/README.md) |

## Docs map

| File | Read when |
|---|---|
| [`.docs/architecture.md`](.docs/architecture.md) | Touching more than one component, or tracing a request |
| [`.docs/console-reference.md`](.docs/console-reference.md) | Changing what a console page shows or does, a console route, or the console's configuration |
| [`.docs/data.md`](.docs/data.md) | Touching tables, the RPCs, cascades, security or R2 keys |
| [`.docs/analysis-schema.md`](.docs/analysis-schema.md) | Touching report fields, prompts, VLM calls or output parsing |
| [`.docs/incident-profile-operations.md`](.docs/incident-profile-operations.md) | Anything on the VM |
| [`.docs/vm-api-contracts.md`](.docs/vm-api-contracts.md) | Calling or changing a `vss-agent` HTTP endpoint or the tunnel ports |
| [`.docs/architecture.md`](.docs/architecture.md#level-2-the-console) | Changing an `incident-console-v2` API route or its database access |
| [`.docs/archive/`](.docs/archive/README.md) | History only; never a source for current behaviour |

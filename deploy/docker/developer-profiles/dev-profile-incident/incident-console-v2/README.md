# Incident Console v2

Next.js App Router frontend for video-first incident analysis. This application is intentionally independent of the
Streamlit incident console and uses the existing services only through their HTTP contracts.

## Local development

The frontend depends on two local services: the mock backend handles video upload and agent chat, while the VLM
gateway holds the upstream inference credential and handles video analysis. Run all three processes in separate
terminals.

### 1. Start the mock backend

From the repository root:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock
uv sync
uv run --env-file ../../.env.local \
  uvicorn base_profile_mock.app:create_app --factory --host 127.0.0.1 --port 7777 --reload
```

`../../.env.local` is the shared `dev-profile-incident/.env.local` secrets file (see the profile README's
"Secrets & environment files" section); the backend needs its `R2_*` and `INCIDENT_SUPABASE_*` values.

Verify it at `http://127.0.0.1:7777/health`. The v2 frontend should have
`INCIDENT_AGENT_BASE_URL=http://127.0.0.1:7777` in its local server configuration.

### 2. Start the VLM gateway

From the repository root:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/vlm-gateway
uv sync
uv run --env-file .env.local uvicorn app:app --host 127.0.0.1 --port 8600 --reload
```

Verify it at `http://127.0.0.1:8600/health`. The v2 frontend should have
`VLM_GATEWAY_URL=http://127.0.0.1:8600` in its local server configuration. The gateway process—not the frontend—owns
`VLM_GATEWAY_API_KEY` and `VLM_GATEWAY_BASE_URL`.

### 3. Start incident-console-v2

From the repository root:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/incident-console-v2
npm install
npm run dev
```

Open `http://localhost:3200`. `GET http://localhost:3200/api/health` should report the services as ready before testing the upload-to-report workflow (in `agent` mode, gateway readiness is omitted from the overall readiness check).

Checks: `npm run typecheck` and `npm test` (Node's built-in test runner over `tests/*.test.mjs`).

## Server-only configuration

Next.js loads them from `.env.local` in this directory, which is a symlink to the shared
`dev-profile-incident/.env.local` — edit that file, not the symlink. The application recognizes these variable names
at runtime:

- `ANALYSIS_MODE` — analysis pipeline mode: `'gateway'` (default, zero-GPU local flow calling `VLM_GATEWAY_URL`) or `'agent'` (VM flow calling the native `vss-agent`'s `POST /api/v1/incidents/{incident_id}/analyze` directly, with no gateway process required). In agent mode the agent persists the incident and its evidence; v2 only upserts the `videos` row (before the call, so the agent can resolve the sensor id, and again after it to keep `filepath` as the R2 key), the `model_runs` notes and the `reports` row.
- `VLM_GATEWAY_URL` — URL of the credential-holding VLM gateway, such as `http://127.0.0.1:8600`. Required when `ANALYSIS_MODE=gateway`.
- `VLM_MODEL` — optional hosted model ID; defaults to `nvidia/cosmos-3-nano-reasoner`.
- `INCIDENT_AGENT_BASE_URL` — mock or real vss-agent base URL used for video upload, agent chat, and incident analysis (in `agent` mode).
- `INCIDENT_SUPABASE_URL` / `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` — PostgREST access.
- `R2_ACCOUNT_ID` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_BUCKET` — private video storage.

Do not expose any of these through a `NEXT_PUBLIC_` variable. `GET /api/health` returns only configuration and
reachability booleans; it never returns URLs or credentials.

## Phase 2 workflow

Selecting a video immediately starts the three-step nvstreamer upload. If that upload has no durable R2 key (the
real VST/NvStreamer case, as opposed to the mock backend), the console uploads the file to R2 itself before
continuing — see [Real-VST R2 upload fallback](#real-vst-r2-upload-fallback) below. It then signs the resulting R2 object
for temporary model access, submits it to Cosmos through the gateway, validates the structured result, persists it
through PostgREST, and renders a timestamp-linked incident report (with `ANALYSIS_MODE=agent`, vss-agent analyzes
and persists the incident instead of the gateway; see the variable list above). Start with short clips while inference remains
synchronous.

### Real-VST R2 upload fallback

Real VST/NvStreamer's chunk-upload response never includes a durable R2 object key (`filePath`) — only
`mock-backend`'s own reimplementation (`../mock-backend/base_profile_mock/src/base_profile_mock/routers/vst_storage.py`) fakes that field by doing its own R2 upload. Since
`incident-console-v2`'s analysis flow (`app/api/analysis/route.ts`) hard-requires that key, `components/analysis-workspace.tsx`
checks the chunk-upload response for a valid key and, when missing (the real-VST case), uploads the file itself
through a new server-side-only route, `app/api/uploads/r2/route.ts` (R2 `PutObject` via `lib/r2/config.ts`'s
`putR2Video`, reusing the same client pattern as `createR2PlaybackUrl`/`deleteR2Video`), and uses its returned key
going forward. This is v2-only and does not touch `vss-agent` or `mock-backend`; the existing VST chunked-upload
flow for obtaining `sensorId` (`lib/upload/chunked-upload.ts`) is unchanged.

## Phase 3 report workspace

Completed analyses navigate to a durable route shaped like
`/reports/<video-id>?run=<model-run-id>`. Reloading or sharing that route reads the stored model-run notes from
PostgREST and creates a fresh one-hour R2 playback URL; it does not depend on browser local storage. Newly generated
reports retain raw and normalized model output for diagnostics alongside model, prompt, run, and generation metadata.
The report provides timestamp seeking, explicit empty states, a copy-link action, and print-specific presentation.

## Phase 4 report library and review

`/reports` lists persisted v2 reports with signed R2 previews. It supports full-text evidence search; incident type,
severity, and review-state filters; generated-date presets and custom date/time ranges; and severity, confidence, or
date sorting. Review transitions are persisted to `review_status`, and verifying severity 4–5 reports creates a
notification. Re-analysis creates a new model run and preserves prior results. Deleting only a report keeps its R2
video; deleting the video is a separate, explicit confirmation and removes all reports for that video through the
database cascade.

## Phase 5 review and operations workspace

The global header keeps Analyze, Reports, Dashboard, notifications, and service health consistent throughout the
application. The report library remembers filters, scroll position, and its originating card when a report is opened.
`/dashboard` summarizes report volume, review progress, confidence, severity, and incident types with drill-down
links. `/notifications` polls and acknowledges high-severity verification alerts.

Each report provides human-attributed structured corrections, non-streaming report-grounded follow-up chat through
the agent `/chat` contract, model-run history and side-by-side comparison, and a ground-truth/severity evaluation
form. Human corrections update structured incident fields while retained raw VLM output remains unchanged as
provenance.

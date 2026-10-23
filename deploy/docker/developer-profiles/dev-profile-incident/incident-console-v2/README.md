# Incident Console v2

Next.js App Router frontend for video-first incident analysis. This application is intentionally independent of the
archived Streamlit v1 console (`../archived/incident-console/`) and uses the existing services only through their HTTP contracts.

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

## Analysis contract

Both gateway and agent modes analyse with the shared **`incident-contract-v4`** from [`../contracts/`](../contracts/README.md), read at runtime (`CONTRACTS_DIR`, default `../contracts`):
- the same prompt, schema, P1 settings and model allowlist (`contracts/inference.json`) as `eval/`;
- strict validation (`lib/contract/validate.ts`, Ajv on the schema file);
- ID-only recovery (`lib/contract/repair.ts`, `id-normalization-v1`);
- every attempt recorded immutably in `model_runs.notes` with outcome `valid_first_pass`, `valid_after_structural_repair`, `contract_failed` or `request_failed`.

See [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md).

**Tests.** They need a Node.js with TypeScript type stripping (official Node 22+ builds). Some distro builds lack it (`ERR_NO_TYPESCRIPT`); run `npx -y node@22 --experimental-strip-types --experimental-test-module-mocks --test tests/*.test.mjs` there.

## Server-only configuration

Next.js loads them from `.env.local` in this directory, which is a symlink to the shared
`dev-profile-incident/.env.local` — edit that file, not the symlink. The application recognizes these variable names
at runtime:

- `ANALYSIS_MODE` — analysis pipeline mode: `'gateway'` (default, zero-GPU local flow calling `VLM_GATEWAY_URL`) or `'agent'` (VM flow calling the native `vss-agent`'s `POST /api/v1/incidents/{incident_id}/analyze` directly, with no gateway process required). In agent mode the console sends `{video_url, model_run_id, skip_rp1: true}`, the agent runs P1 only (as gateway mode does), and both modes run through the shared `core-scored-v1` validation policy and attempt recording. The console manages the `videos` row; the agent never writes `videos`.
- `VLM_GATEWAY_URL` — URL of the credential-holding VLM gateway, such as `http://127.0.0.1:8600`. Required when `ANALYSIS_MODE=gateway`.
- `VLM_MODEL` — optional default selection in the model picker; must be one of the models in `contracts/inference.json` (defaults to `nvidia/cosmos-3-nano-reasoner`).
- `CONTRACTS_DIR` — optional path to the shared `contracts/` directory (default `../contracts`).
- `INCIDENT_AGENT_BASE_URL` — mock or real vss-agent base URL used for video upload, agent chat, and incident analysis (in `agent` mode).
- `INCIDENT_SUPABASE_URL` / `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` — PostgREST access.
- `R2_ACCOUNT_ID` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_BUCKET` — private video storage.

Do not expose any of these through a `NEXT_PUBLIC_` variable. `GET /api/health` returns only configuration and
reachability booleans; it never returns URLs or credentials.

## Phase 2 workflow

Selecting a video immediately starts the three-step nvstreamer upload. If that upload has no durable R2 key (the
real VST/NvStreamer case, as opposed to the mock backend), the console uploads the file to R2 itself before
continuing — see [Real-VST R2 upload fallback](#real-vst-r2-upload-fallback) below. It then signs the resulting R2 object
for temporary model access only after `HeadObject` confirms the object exists and is nonempty, submits it to the selected VLM through the gateway, strictly validates the structured result against `incident-contract-v4` under `core-scored-v1` (applying ID-only recovery `id-normalization-v1` if needed), persists it through `persistContractRun`, reads the required row graph back through PostgREST, and renders a timestamp-linked incident report (with `ANALYSIS_MODE=agent`, vss-agent runs P1
instead of the gateway and the console still validates and persists the run; see the variable list above). Start with short clips while inference remains
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

For each new upload, the browser also attempts to capture the frame 25% into the already-local file, scale it to at most
640×360, and upload it through `/api/uploads/thumbnail` to `thumbnails/<video-key>.webp`. Thumbnail failure never blocks
analysis. Existing videos without this derived object retain the report-card skeleton until separately backfilled.

## Phase 3 report workspace

Completed analyses navigate to a durable route shaped like
`/reports/<video-id>?revision=<revision-id>`. Reloading or sharing that route reads the stored `report_revisions` row
and its model run from PostgREST and creates a fresh one-hour R2 playback URL; it does not depend on browser local storage. Newly generated
reports retain raw and normalized model output for diagnostics alongside model, prompt, run, and generation metadata.
The report provides timestamp seeking, explicit empty states, a copy-link action, and print-specific presentation.

## Phase 4 incident library

`/library` (the old `/reports` listing redirects there, keeping its query string) has two tabs.

- **Find incidents** lists one card per video as server-paginated pages of six lightweight summaries
  (`list_incident_report_summaries`): the official revision, else the newest. Cards show the severity, the
  "Official vN" marker with when it was made official or "No official version", the summary, and the evidence and
  version counts. Thumbnails are small signed R2 screenshots (falling back to the first evidence image, then a
  skeleton); the library never requests video. Filters: text, incident type, official-only status, severity band, added
  date and sort. Active filters show as removable chips, and the URL is the filter state (dashboard links, shared
  links and refresh all land on the same list). "Search evidence" on a card scopes the other tab to that incident
  for the visit only.
- **Find evidence** posts the text to `POST /api/search`, which asks the agent (`POST /api/v1/incidents/search`,
  `search-contract-v1`, `lib/adapters/agent/search.ts`) for the top 20 ranked hits with no similarity cutoff and the
  critic's rejections kept, then adds each video's searched version from the same summaries. Hits show the crop,
  match percentage, video time, kind, threat and relationship (held by / holds); kind, threat and incident-type
  filters and "Group by incident" work on the returned hits without a new search. Clicking a crop opens the viewer
  with the item's details and a link to its report. The viewer shows the full frame (`FrameViewer`, cut by `GET /api/reports/<id>/frame`) with every box found
  at that second, or the enlarged crop when the frame cannot be cut.

Every save appends a `human` revision; the AI revision is never changed, and each video has at most one official
revision. Re-generation creates a new model run and a new AI revision and preserves prior results. Deleting only a
report keeps its R2 video; deleting the video is a separate, explicit confirmation and removes all revisions for that
video through the database cascade.

## Phase 5 review and operations workspace

The global header keeps Analyze, Library, Videos, Dashboard, and service health consistent throughout the
application. The report library remembers filters, scroll position, and its originating card when a report is opened.
`/dashboard` summarizes report volume, confidence, severity, and incident types with drill-down links, counting the
official revision only.

Each report provides human-attributed structured corrections as new revisions, a versions graph with Save,
non-streaming follow-up chat through the agent `POST /api/v1/incidents/chat` (`chat-contract-v1`), scoped to the
report's video and showing cited evidence, and model-run history and side-by-side comparison. Retained raw VLM output
in `model_runs.notes` remains unchanged as provenance.

## Evidence frames and crops

A reviewer replacing or adding evidence picks a frame and draws a rectangle on it. Both routes decode with the `ffmpeg` on the console host's PATH (a missing binary answers 503), reading the signed R2 video by range request:

- `GET /api/reports/<videoId>/frame?t=<seconds>` answers the frame as a JPEG. A malformed `t` is 400, a `t` at or past the video's length 422, an unknown video 404.
- `POST /api/reports/<videoId>/evidence-crop` takes `{"itemId", "timestampSeconds", "region": {"x","y","w","h"}}`, the region as fractions (0-1) of the frame from the top-left. It stores the crop at a new `evidence/<videoId>/<uuid>/<itemId>.jpg` key and answers `{image, imageUrl, timestampSeconds, region}`; Save writes `image` into the next human revision. A region outside the frame or under 1% wide or high is 422. Nothing is overwritten or deleted.

## Videos, run history and the official revision

- **Pages:**
  - `/videos` lists uploaded videos, with "Awaiting official report" and "Without a report" views.
  - `/videos/<id>` shows the video, a re-generation card (any allowlisted model, optional reviewer prompt) and the full analysis history: every attempt with its model, time, outcome, failure reasons or repair operations. Failed attempts never appear as reports.
- **Re-generation** always creates a new run and a new AI revision, never changes the video's upload time, and never changes the official revision.
- **Official revision:** a reviewer explicitly chooses it with the star on the report page's versions graph (a filled star clears it) or in the history; marking it rebuilds the incident's `evidence_crops`.
- **Dashboard:** it counts official revisions only, and every number links to `/library?scope=official&...`. The library treats the URL as its filter state.
- **Report page (View mode):**
  - a fixed top band: the video, a vertical timeline with one lane per entity (first to last seen span, held instruments on the lane, then "Holder unknown" and Assets lanes; click a lane to seek) and the versions graph (each AI run is its own branch, human versions sit on their parent's; the star marks a version official, with no Restore);
  - a scrolling pane: version, report fields, evidence cards grouped by holder, read-only model output (title, severity rationale, timeline, uncertainties) and a "Run & model output details" panel;
  - a bottom bar with "Edit from vN", which opens the structured editor.
- **Timestamps** from the database are UTC and are rendered in the viewer's time zone (`lib/time.ts`). The dashboard heatmap and report library time-of-day filters detect the client's timezone on mount (`getViewerTimeZone()`) and pass `timezone` to the API routes and database RPCs (`get_incident_dashboard`, `list_incident_report_summaries`), ensuring heatmap buckets, hour labels, and filter bounds match the user's local shift and time of day.

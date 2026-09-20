# base_profile_mock

A lightweight mock of the `bp_developer_base` backend - `vss-agent` API + VIOS/VST
(video storage) + LLM/VLM inference - so you can run the real, unmodified UI
(`services/ui/apps/nv-metropolis-bp-vss-ui`) against it with **zero GPU, zero NIM
containers, and no VM deployment**.

Since only `vss-agent` itself ever calls the LLM/VLM (the UI never does), this mock
replaces vss-agent's own logic with canned/templated text generation. There is no
separate inference mock - one process plays the role that HAProxy + vss-agent + VIOS +
LLM/VLM NIMs jointly play in a real deployment, all on one port.

Most mock state is in-memory only and resets on restart. Completed uploads are
also copied to R2 immediately; the returned `filePath` is the durable object
key. The incident Analyze route writes report records to the shared
incident-console Postgres database.

When exercising the incident flow, set `INCIDENT_SUPABASE_URL` and
`INCIDENT_SUPABASE_SERVICE_ROLE_KEY` in the backend environment to the same
Supabase project used by the console (the console itself keeps using its own
`INCIDENT_DB_DSN` — the two config surfaces are independently maintained, see
`services/agent/src/vss_agents/utils/incident_db.py`'s module docstring).
Also load the
Cloudflare R2 upload settings used by the console: `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY`, `R2_SECRET_KEY`, and `R2_BUCKET` from an env file. R2 upload
returns `503` when those settings are unset or unreachable. The Catalog page
automatically triggers Analyze after the initial video row is committed. The
response is explicitly marked `mock: true`, and Analyze writes
the model run, incident entity, review status, and report through
`services/agent/src/vss_agents/utils/incident_db.py`.

## Run it

```sh
cd deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock
uv sync
uv run --env-file ../../incident-console/.env \
  uvicorn base_profile_mock.app:create_app --factory --host 127.0.0.1 --port 7777 --reload
```

For the complete local loop, from `dev-profile-incident/` run
`./local-start.sh`. It loads `incident-console/.env.local` for the backend,
starts the mock backend, and launches the Streamlit console; no secret exports
are needed.

`GET http://127.0.0.1:7777/health` should return `{"value": {"isAlive": true}}`.
For local runs, keep `MOCK_PUBLIC_BASE_URL=http://127.0.0.1:7777` if you override it; using
`localhost` can fail on systems where clients try IPv6 while uvicorn is bound to IPv4.

## Point the real UI at it

Set these in `services/ui/apps/nv-metropolis-bp-vss-ui/.env.local` (or export them
before `npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui`):

```
NEXT_PUBLIC_AGENT_API_URL_BASE=http://localhost:7777/api/v1
NEXT_PUBLIC_VST_API_URL=http://localhost:7777/vst/api
NEXT_PUBLIC_SIDEBAR_CHAT_WEBSOCKET_CHAT_COMPLETION_URL=ws://localhost:7777/websocket
NEXT_PUBLIC_SIDEBAR_CHAT_HTTP_CHAT_COMPLETION_URL=http://localhost:7777/chat/stream
NEXT_PUBLIC_SIDEBAR_CHAT_WEB_SOCKET_DEFAULT_ON=true
NEXT_PUBLIC_ENABLE_CHAT_TAB=false
NEXT_PUBLIC_ENABLE_CHAT_SIDEBAR=true
NEXT_PUBLIC_ENABLE_SEARCH_TAB=false
NEXT_PUBLIC_ENABLE_ALERTS_TAB=false
NEXT_PUBLIC_ENABLE_VIDEO_MANAGEMENT_TAB=true
NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX=true
```

The last var isn't backend-related, but the UI's `pages/index.tsx` calls `fetchSearchData()` in
`getServerSideProps` unconditionally (even with the search tab disabled), and that function
serializes this env var directly with no fallback - leaving it unset causes Next.js to fail
the page with "`undefined` cannot be serialized as JSON" on every load. Set it to any defined
value (matching the real deployment's default of `true`) to avoid that.

These match the base deployment profile's own defaults
(`deploy/docker/developer-profiles/dev-profile-base/.env` and
`deploy/docker/services/ui/compose.yml`) - the sidebar chat is the real chat surface
for base profile (not the main chat tab), and WebSocket is its default transport.

**HITL (human-in-the-loop report-generation prompts) is WebSocket-only.** The UI
client has no HITL support over HTTP/SSE, so a report request over HTTP/SSE returns
one synchronous canned answer instead of the approve/edit/cancel round-trip.

## What's mocked

- `POST /api/v1/videos`, `POST /api/v1/videos/{sensor_id}/complete`,
  `DELETE /api/v1/videos/{id}` - video upload/delete, mirroring
  `services/agent/src/vss_agents/api/video_ingest.py` / `video_delete.py`.
- `POST /api/v1/incidents/{id}/analyze` - deterministic mock incident report
  generation, persisted through the shared incident DB writer; invoked
  automatically by the Catalog upload flow.
- `POST /api/v1/rtsp-streams/add`, `DELETE /api/v1/rtsp-streams/delete/{name}` -
  canned RTSP add/delete responses.
- `GET/POST /chat`, `/chat/stream`, `/generate`, `/generate/stream` - HTTP/SSE chat,
  no HITL.
- `WS /websocket` - primary chat transport, full HITL round-trip for report
  generation (approve, edit-once, or `/cancel`).
- `GET /static/{filename}` - fabricated Markdown reports.
- `/vst/api/v1/storage/file*`, `sensor/*`, `replay/*` - chunked video upload,
  stream catalog, timelines, and a static placeholder thumbnail for every
  snapshot/picture request.

Out of scope (base profile disables these tabs, so the UI never calls them):
search/alerts endpoints, Redis, Phoenix.

## Layout

- `src/base_profile_mock/app.py` - `create_app()` factory, mounts all routers.
- `src/base_profile_mock/state.py` - single in-memory `AppState`.
- `src/base_profile_mock/templates.py` - canned text, intent classification,
  Markdown report builder, and the real `hitl_vlm_prompt_template` text copied
  verbatim from
  `deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml`.
- `src/base_profile_mock/routers/` - one module per route group; see each file's
  docstring for which real file it mirrors.

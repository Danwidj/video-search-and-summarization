# Local mock loop (Phase 1, brute-force, native-only)

Empirically verified 2026-09-12 on this machine: both mock/frontend pairs run
natively with `uv` (Python side) and `npm` (UI side), zero GPU / zero NIM
containers / no Docker / no SSH. No source changes were needed — both mocks
and the real UI worked as documented once started with the wiring below
(the UI side needs a one-time `npm install` + workspace-package build, see
Pair (a)). Real Supabase/R2 secrets are NOT required: the incident-console
loop uses a local SQLite file as a placeholder DSN.

## Pair (a): base_profile_mock -> real UI

Terminal 1:

```sh
cd deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock
uv sync
uv run uvicorn base_profile_mock.app:create_app --factory --port 7777
```

Verify (all return 200 / sane payloads):

```sh
curl http://localhost:7777/health                                  # {"value":{"isAlive":true}}
curl -X POST http://localhost:7777/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'            # SSE canned chunks
curl http://localhost:7777/vst/api/v1/sensor/streams               # []
curl -X POST http://localhost:7777/api/v1/videos \
  -H 'Content-Type: application/json' -d '{"filename":"test.mp4"}' # {"url":"http://localhost:7777/vst/api/v1/storage/file"}
```

Point the real UI at it per `mock-backend/base_profile_mock/README.md`
(`NEXT_PUBLIC_AGENT_API_URL_BASE=http://localhost:7777/api/v1`, etc.), then
boot the real UI:

```sh
cd services/ui
npm install
cd packages/common && npm run build && cd ../..
cd packages/nemo-agent-toolkit-ui && npm run build && cd ../..
# apps/nv-metropolis-bp-vss-ui/.env.local: the NEXT_PUBLIC_* vars from
# mock-backend/base_profile_mock/README.md above
cd apps/nv-metropolis-bp-vss-ui
npm run dev   # http://localhost:3000
```

The two `npm run build` steps are required before `next dev` will resolve
`@aiqtoolkit-ui/common` / `@nemo-agent-toolkit/ui` (npm workspace packages
that ship pre-built `lib/` output, not present until built once locally).

Empirically verified 2026-09-12: `next dev` boots, `GET /` returns 200 with
the real page (title, Video Management tab present in the rendered HTML).
Interactive browser click-through could not be captured here (the available
browser-automation tool errored on every call with "Required at pageId" -
an environment tool bug, not a UI or mock issue). As a substitute, one
UI-driven call was replayed byte-for-byte against the running mock using the
exact wire shapes the UI's own code sends:

- Sidebar chat (`services/agent`-mirroring `websocket.py` handler; message
  shape from `packages/nemo-agent-toolkit-ui/types/websocket.ts` /
  `Chat.tsx`): a `user_message` with `content.messages[0].content` of
  `"list videos"` sent over `ws://localhost:7777/websocket` got back the
  real streamed `system_response_message` chunks ("No videos h" / "ave been
  up" / "loaded yet." / complete) - the full HITL-capable transport path,
  live.
- Video Management upload init: `POST /api/v1/videos {"filename":...}`
  returned `{"url":"http://localhost:7777/vst/api/v1/storage/file"}` per
  `video-management/chunkedUpload.ts`'s contract.

## Pair (b): mock_llm_server + SQLite -> incident-console (capstone loop)

Terminal 2:

```sh
cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
uv sync
uv run uvicorn mock_llm_server:app --port 8900
# health: curl http://localhost:8900/health -> {"status":"ok"}
```

Terminal 3 (same directory):

```sh
export INCIDENT_DB_DSN="sqlite:////tmp/incident-local.db"
export INCIDENT_LLM_BASE_URL="http://localhost:8900/v1"
uv run python scripts/seed_supabase.py   # idempotent: 72 videos / 1 model run / 72 incidents / 132 entities / 37 instruments / 40 assets
uv run streamlit run app.py              # http://localhost:8501
```

Verified: `/` + all four pages (`/1_Catalog`, `/2_Report_Review`,
`/3_Dashboard`, `/4_Severity_Eval`) return HTTP 200 with zero errors in the
server log; `/_stcore/health` returns `ok`.

One-command route -> parse -> write proof (mock LLM -> AgentClient parse ->
SQLite write -> read-back, plus the page view-model reads):

```sh
INCIDENT_DB_DSN="sqlite:////tmp/incident-local.db" \
INCIDENT_LLM_BASE_URL="http://localhost:8900/v1" uv run python -c "
from db import IncidentDB
from db_reports import DBReports
from agent_client import AgentClient
import config
d = IncidentDB.from_dsn(config.incident_db_dsn())
print('latest_incidents:', len(d.list_latest_incidents()))
c = AgentClient()
r = c.draft_report_via_llm(prompt='a car crash on the highway')
print('draft ok:', r.ok, 'type:', r.data.incident_type, 'sev:', r.data.severity)
d.upsert_video('E2E-LOCAL-001', filepath='local/e2e-001.mp4', duration=30)
d.insert_model_run('MR-LOCAL', model_name='mock-incident-llm')
d.insert_incident('E2E-LOCAL-001', 'MR-LOCAL', fields={'type': r.data.incident_type, 'description': r.data.description, 'severity_level': r.data.severity, 'confidence_score': r.data.confidence})
print('roundtrip:', d.get_latest_incident('E2E-LOCAL-001')['type'])
print('reports view:', len(DBReports(d).list_reports()))
"
```

Also verified on SQLite: keyword `ilike` filter, catalog status/counts,
`set_review_status` transitions, severity-eval insert, notifications list,
and fail-soft `get_db() -> None` with DSN unset. `uv run pytest` → 90 passed.

## Known gaps for later phases (do NOT fix here)

- Real Supabase Postgres + R2 wiring (`.env.local` real values), VM parity /
  deploy, git hooks / `.env` propagation, SSH tunnels, R2/direnv integration.
- Real browser click-through of the Next.js UI (blocked by a broken local
  browser-automation tool, see Pair (a) above); the boot, page render, and
  wire-protocol calls the UI issues were verified instead.
- `incident-console/.gitignore` ignores only `.env.local`; keep scratch
  SQLite files under `/tmp` (as above) so they can never be committed.

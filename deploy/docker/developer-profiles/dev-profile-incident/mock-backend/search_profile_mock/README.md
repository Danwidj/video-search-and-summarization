# search_profile_mock

A lightweight mock of the `bp_developer_search` backend - everything
`base_profile_mock` covers (vss-agent API + VIOS/VST + LLM/VLM inference)
**plus** the search-profile superset: agent search endpoints, VST sensor
list, video-analytics-api frame metadata (2D visual-search bbox overlay),
Kibana dashboard stubs, and Elasticsearch/Logstash info stubs - so you can
run the real, unmodified UI
(`services/ui/apps/nv-metropolis-bp-vss-ui`) against it with **zero GPU,
zero NIM containers, and no VM deployment**.

Since only `vss-agent` itself ever calls the LLM/VLM and embeddings
(the UI never does), this mock replaces vss-agent's own logic with
canned/templated generation. There is no separate inference mock - one
process plays the role that HAProxy + vss-agent + VIOS + analytics +
Elasticsearch + Kibana jointly play in a real deployment, all on one port.

State is in-memory only and resets on restart. This is a local dev tool, not a
persistence layer.

Upload a video first (video-management tab or the base upload flow) - the
search index IS the stream catalog, so search returns hits only for
uploaded streams.

## Run it

```sh
cd deploy/docker/developer-profiles/dev-profile-incident/mock-backend/search_profile_mock
uv sync
uv run uvicorn search_profile_mock.app:create_app --factory --port 7778 --reload
```

`GET http://localhost:7778/health` should return `{"value": {"isAlive": true}}`.

Port 7778 keeps it runnable side-by-side with `base_profile_mock` (7777).

## Point the real UI at it

Set these in `services/ui/apps/nv-metropolis-bp-vss-ui/.env.local` (or export them
before `npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui`):

```
NEXT_PUBLIC_AGENT_API_URL_BASE=http://localhost:7778/api/v1
NEXT_PUBLIC_VST_API_URL=http://localhost:7778/vst/api
NEXT_PUBLIC_MDX_WEB_API_URL=http://localhost:7778/video-analytics-api
NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL=http://localhost:7778/kibana
NEXT_PUBLIC_SIDEBAR_CHAT_WEBSOCKET_CHAT_COMPLETION_URL=ws://localhost:7778/websocket
NEXT_PUBLIC_SIDEBAR_CHAT_HTTP_CHAT_COMPLETION_URL=http://localhost:7778/chat/stream
NEXT_PUBLIC_SIDEBAR_CHAT_WEB_SOCKET_DEFAULT_ON=true
NEXT_PUBLIC_ENABLE_CHAT_TAB=false
NEXT_PUBLIC_ENABLE_CHAT_SIDEBAR=true
NEXT_PUBLIC_ENABLE_SEARCH_TAB=true
NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX=false
NEXT_PUBLIC_ENABLE_DASHBOARD_TAB=true
NEXT_PUBLIC_ENABLE_ALERTS_TAB=false
NEXT_PUBLIC_ENABLE_VIDEO_MANAGEMENT_TAB=true
NEXT_PUBLIC_SIDEBAR_CHAT_CHAT_API_CUSTOM_AGENT_PARAMS_JSON='{"params":[{"name":"search_source_type","label":"Search media source type","type":"select","default-value":"video_file","options":["video_file","rtsp"],"changeable":true,"tooltip-info":"Media Source type for Search Agent Query"},{"name":"use_critic","label":"Enable Critic","type":"boolean","default-value":true,"changeable":true,"tooltip-info":"Verify results with Critic Agent"}]}'
```

The sidebar-chat custom-agent-params JSON mirrors
`deploy/docker/developer-profiles/dev-profile-search/.env`
(`search_source_type` + `use_critic`); the mock accepts but does not
interpret them. `SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX=false` matches the
search profile default (bbox overlay still works - the `/frames` stub
always returns boxes; the flag only controls the UI default).

**HITL (human-in-the-loop report-generation prompts) is WebSocket-only.** The UI
client has no HITL support over HTTP/SSE, so a report request over HTTP/SSE returns
one synchronous canned answer instead of the approve/edit/cancel round-trip.

## What's mocked

Everything `base_profile_mock` mocks (same routes, same behavior), plus:

- `POST /api/v1/search` - visual/text search; request/response shapes mirror
  `search/lib-src/hooks/useSearch.ts` (`{data: [...]}` with video_name,
  similarity, screenshot_url, description, start_time/end_time, sensor_id,
  object_ids, critic_result). Agent-mode bodies (`{agent_mode, query,
  top_k, source_type}`) are accepted too.
- `POST /api/v1/embed_search`, `POST /api/v1/attribute_search`,
  `POST /api/v1/critic` - mirror the `endpoints:` block in the search
  profile's `vss-agent/configs/config.yml`. Critic verdicts are always
  `unverified` (no real critic model). `embed_search` returns a stub
  `query_embedding` plus canned `results`.
- `PUT /api/v1/videos-for-search/{filename}` (deprecated) - compat shim
  mirroring `services/agent/src/vss_agents/api/video_search_ingest.py`,
  same Content-Type/Content-Length validation.
- Chat (WS + HTTP/SSE) search intent - a search-flavored question
  ("search for ...", "find ...") returns an answer carrying a
  ```json {"data": [...]}}``` block, which the search tab's agent mode
  parses via `utils/agentResponseParser.ts`.
- `GET /vst/api/v1/sensor/list`, `GET /vst/api/v1/live/streams` - flat
  sensor catalog for the search filter (`hooks/useFilter.ts`) and the
  shared `fetchSensorMap` helper.
- `GET /video-analytics-api/frames?sensorId&fromTimestamp&toTimestamp` -
  frame bbox metadata for the search-by-image overlay
  (`hooks/useSearchByImage.ts`); deterministic boxes, no real DeepStream
  perception.
- `/kibana/api/saved_objects/_find`, `/kibana/api/status`,
  `/kibana/app/dashboards` - dashboard-tab SSR listing + iframe
  placeholder (see `dashboard/lib-src/server.ts`).
- `GET /`, `GET /_cluster/health`, `GET|POST /{index}/_search` -
  Elasticsearch info stubs for smoke checks (hit counts derive from the
  stream catalog). `GET /_node/stats` - Logstash monitoring-API-shaped
  stub.

Out of scope (no UI-facing HTTP surface to mock): Kafka broker protocol,
Redis, Phoenix, GPU DeepStream/RTVI inference (its observable output -
indexed embeddings and frame bboxes - is what `/api/v1/search` and
`/frames` fake).

## Layout

- `src/search_profile_mock/app.py` - `create_app()` factory, mounts all routers.
- `src/search_profile_mock/state.py` - single in-memory `AppState`.
- `src/search_profile_mock/templates.py` - canned text, intent classification,
  Markdown report builder, search-result/frames/Kibana builders, and the real
  `hitl_vlm_prompt_template` text copied verbatim from
  `deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml`.
- `src/search_profile_mock/routers/` - one module per route group; base
  routers mirror `base_profile_mock` exactly, `agent_search.py`,
  `vst_sensor_list.py`, `analytics_frames.py`, `kibana.py`, `elastic.py`
  are the search-profile additions (see each file's docstring for which
  real file it mirrors).

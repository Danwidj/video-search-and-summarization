# Search profile mock

A zero-GPU mock of NVIDIA's stock search-profile backend on port 7778: agent search, VST sensor list, video-analytics frames, and Kibana and Elasticsearch stubs, plus incident search and revision search from the [base profile mock](../base_profile_mock/README.md#refresh-the-finals-snapshot) finals snapshot. It runs on its own, beside the base mock; `start.sh` does not start it. State is in memory and resets on restart. It is a mock that mimics the backend, not the real one.

## Run it

```sh
cd deploy/docker/developer-profiles/dev-profile-incident/mock-backend/search_profile_mock
uv sync
uv run uvicorn search_profile_mock.app:create_app --factory --port 7778 --reload
```

`GET http://localhost:7778/health` should return `{"value": {"isAlive": true}}`. Upload a video first: the stock search returns hits only for uploaded streams. Run the tests with `uv run pytest`.

## Point the stock UI at it

Set these in `services/ui/apps/nv-metropolis-bp-vss-ui/.env.local`, or export them before `npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui`:

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

## Read more

- [Architecture: Containers](../../.docs/architecture.md#level-1-containers): what the mock serves
- [Base profile mock](../base_profile_mock/README.md#refresh-the-finals-snapshot): how the snapshot is refreshed

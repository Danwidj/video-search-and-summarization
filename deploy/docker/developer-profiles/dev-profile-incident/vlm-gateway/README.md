# VLM Gateway

A thin proxy that keeps the Brev inference key on the server, so `incident-console-v2` can call the hosted VLMs in mock (gateway) mode without exposing it.

## Run it

`./start.sh --mode mock` starts it for you. To run it alone:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/vlm-gateway
uv sync
uv run --env-file .env.local uvicorn app:app --host 127.0.0.1 --port 8600
```

`.env.local` is a symlink to the profile's shared `../.env.local`, which must set `VLM_GATEWAY_API_KEY`. Check it with `curl http://127.0.0.1:8600/health`.

Its route, settings and defaults: [`../.docs/architecture.md`](../.docs/architecture.md#component-reference-table).

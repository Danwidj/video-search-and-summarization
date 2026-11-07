# VLM gateway

A small proxy that holds the hosted (Brev) inference key on the server, so the console can call the hosted VLMs in the mock flow without exposing the key. Mock mode only: in vm mode the console never calls it.

## Run it

`./start.sh --mode mock` starts it. To run it alone:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/vlm-gateway
uv sync
uv run --env-file .env.local uvicorn app:app --host 127.0.0.1 --port 8600
```

`.env.local` is a symlink to the profile's `../.env.local` and must set `VLM_GATEWAY_API_KEY`. Check it with `curl http://127.0.0.1:8600/health`.

## What is inside

| Name | What it is |
|---|---|
| `POST /v1/chat/completions` | Forwards the caller's JSON body unchanged with the server-side key. No streaming, any model |
| `GET /health` | Answers `{"status": "ok"}` |
| `VLM_GATEWAY_API_KEY` | The hosted inference key. Required: without it the route answers an error naming the variable |
| `VLM_GATEWAY_BASE_URL` | The endpoint it forwards to. Required, no default: set it in `.env.local`; without it the route answers an error naming the variable |
| `VLM_GATEWAY_TIMEOUT_SECONDS` | Upstream timeout, default 330 s, longer than the slowest model timeout in [inference.json](../contracts/inference.json) |
| [compose.yml](compose.yml) | A Compose service for the gateway that `start.sh` never starts |

## Read more

- [Architecture: Containers](../.docs/architecture.md#level-1-containers): where the gateway sits

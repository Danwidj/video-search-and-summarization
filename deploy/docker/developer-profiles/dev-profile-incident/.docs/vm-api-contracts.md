# VM API contracts (frontend reference)

HTTP contracts of the native `vss-agent` on `kwanz-ws` and the SSH tunnel the frontend uses to reach them. VM side only. Source of truth: `services/agent/src/vss_agents/api/` (Pydantic models) and `custom_fastapi_worker.py` (route registration). Last checked against main at `8f9b6d1b7` and the live VM on 2026-10-18.

## Tunnel

`./start.sh --mode vm` opens one backgrounded `ssh -N -L ...` (standalone: `.scripts/tunnel.sh`). The frontend always addresses `http://localhost:<port>`.

| Local port | VM target | Service | Frontend use |
|---|---|---|---|
| `8000` | `127.0.0.1:8000` (loopback) | native `vss-agent` (FastAPI) | all endpoints below; set `INCIDENT_AGENT_BASE_URL=http://localhost:8000` (start.sh exports it) |
| `7777` | `<vm-ip>:7777` | `vss-haproxy-ingress` (VIOS/VST) | video upload and storage API |

- In local mode `7777` is the mock backend instead, and it also serves `POST /api/v1/incidents/search`. There is no tunnel.
- `VSS_VM_IP`: used as given if set. Otherwise start.sh runs `ip -4 route get 1.1.1.1` on the VM over SSH and takes the `src` address. If that fails it prints `could not detect the VM address; falling back to 10.131.1.5` and uses `10.131.1.5`. Override with `VSS_VM_IP=<lan-ip>` when the tunnel cannot reach the address.
- A local port already in use stops start.sh before the tunnel opens: `laptop port <p> is already in use by <holder>`.
- After opening, start.sh polls `localhost:8000/health` and `localhost:7777/storage` (HEAD) for up to 60 s each. Run `./.scripts/tunnel-check.sh` to check tunneled routes.

### When the VM is unreachable

start.sh probes SSH first (`vm_preflight_ssh`, `.scripts/vm-preflight.sh`), exits 1 and prints to stderr, with no tunnel opened:

```
start.sh: cannot reach the VM over SSH ('daniel@kwanz-ws').
  SSH said: <ssh stderr>
  Cause: <classified cause>
  Fix:   <next step>
```

Classified causes: Tailscale not logged in, stopped or daemon down, VM offline in the tailnet, host does not resolve, SSH timeout (`VSS_SSH_CONNECT_TIMEOUT`, default 10 s), connection refused, no route, host key changed, permission denied, connection dropped, otherwise unclassified.

When SSH works but a tunnelled health check fails, start.sh says whether the agent or proxy is healthy on the VM (SSH forward blocked or wrong host bind) or dead on the VM (crashed agent or stopped vss-haproxy-ingress container), then exits non-zero.

## Common behaviour

- Base URL `http://localhost:8000`, JSON bodies, `Content-Type: application/json`. No authentication.
- Validation errors (FastAPI): `422` with `{"detail":[{"type","loc","msg","input"}]}`.
- Handler errors: `{"detail": "<message>"}` with the status given per endpoint.
- Routes are registered on every profile; all incident routes are unconditional.

## `GET /health`

Reachable at `/health` on `:8000`. Returns `200` `{"value":{"isAlive":true}}`. Use it for liveness only.

## `POST /api/v1/incidents/search`

Natural-language search over evidence crops (entity, instrument, asset) with an always-on VLM critic. Contract: search-contract-v1.

Request (`extra` fields are rejected with 422):

| Field | Type | Default | Constraint |
|---|---|---|---|
| `query` | string | required | 1-500 chars |
| `top_k` | int | 10 | 1-50 |
| `min_similarity` | float | 0.0 | 0.0-1.0 (no cutoff by default: top_k by score, the critic judges relevance) |
| `hide_rejected` | bool | true | drop hits the critic marked `rejected` from `hits[]` (`rank` keeps its pre-filter value); `false` returns them |
| `filters.incident_types` | string[] | none | |
| `filters.min_severity`, `filters.max_severity` | int | none | 1-5 |
| `filters.item_types` | `"entity"\|"instrument"\|"asset"`[] | all three | |

Response `200`:

| Field | Type | Notes |
|---|---|---|
| `query_id` | string | `q-<12 hex>` |
| `query` | string | echo |
| `total_hits` | int | `len(hits)`; 0 is a normal answer |
| `execution_time_ms` | float | server time |
| `hits[]` | | ranked, `rank` starts at 1 |
| `hits[].result_id` | string | `res-<32 hex>` (36 chars, fits `query_results.id` VARCHAR(36)) |
| `hits[].rank` | int | |
| `hits[].similarity_score` | float 0-1 | |
| `hits[].item` | object | `item_type`, `item_id`, `name`, `label`, `description`, `threat_level` (int or null), `holder_entity_id` (string or null), `crop_image_url`, `timestamp_seconds` (int), `bounding_box` (null or `[ymin, xmin, ymax, xmax]`, 4 normalised ints) |
| `hits[].incident` | object | `incident_id`, `model_run_id`, `incident_type`, `severity_level` (1-5), `title` (string or null), `description`, `playback_url`, `incident_window` (`[start_s, end_s]`) |
| `hits[].critic` | object | `verdict` (`confirmed`, `rejected`, `unverified`), `confidence` (0-1, null, or observed 0.0), `rationale` |

Behaviour:
- `hide_rejected` defaults to true: hits marked `rejected` by the critic are excluded from `hits[]` by default (`rank` retains its pre-filter value). Pass `hide_rejected: false` to return them.
- A failing critic never drops a hit: it degrades to `verdict: "unverified"`, with `confidence` typically null (or 0.0 observed on some unverified responses), with the failure in `rationale`.
- `crop_image_url` and `playback_url` are resolved from R2 by the agent. Use them as given.
- Errors: 422 on validation. `503` `{"detail":"Query embedding unavailable: ..."}` when the query cannot be embedded: an embedder error, or no embedding API key with the Supabase store (the deterministic placeholder embedding is only used with the in-memory store). A store failure is not caught, so expect `500` (plain-text `Internal Server Error`, not the `detail` shape).
- Timing: embedding plus pgvector query, then critic calls spaced by `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` (default 1.0 s between hits). Expect about 7 s for no hits (measured ~7.2 s on the VM) and roughly `top_k` seconds plus critic latency (30 s timeout each) for `top_k` hits. Use a client timeout of at least 90 s for `top_k` up to 50, and show a loading state.
- Side effect: each call writes one `queries` row and one `query_results` row per hit (audit trail, failures only logged).

Example (illustrative hit shape built from the Pydantic models; the live VM returns hits as detailed in the retest reports):

```bash
curl -s localhost:8000/api/v1/incidents/search -H 'content-type: application/json' \
  -d '{"query":"edged weapon","top_k":5,"filters":{"item_types":["instrument"],"min_severity":3}}'
```

```json
{
  "query_id": "q-f563deb1f578",
  "query": "edged weapon",
  "total_hits": 1,
  "execution_time_ms": 3612.4,
  "hits": [{
    "result_id": "res-1a2b3c4d5e6f70818293a4b5c6d7e8f9",
    "rank": 1,
    "similarity_score": 0.89,
    "item": {
      "item_type": "instrument", "item_id": "I1", "name": "machete", "label": "machete",
      "description": "Long curved blade held by assailant during storefront altercation.",
      "threat_level": 4, "holder_entity_id": "E1",
      "crop_image_url": "https://<r2-host>/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg",
      "timestamp_seconds": 14, "bounding_box": [320, 450, 510, 600]
    },
    "incident": {
      "incident_id": "Assault007_x264", "model_run_id": "m86a5c319e26659804b0",
      "incident_type": "assault", "severity_level": 4,
      "title": "Physical altercation with edged weapon in ATM lobby",
      "description": "An altercation ensues where a perpetrator brandishes a large blade against a victim.",
      "playback_url": "https://<r2-host>/videos/anomaly/assault/Assault007_x264.mp4",
      "incident_window": [10.0, 28.0]
    },
    "critic": {"verdict": "confirmed", "confidence": 0.96, "rationale": "The crop shows a machete held in the assailant's hand."}
  }]
}
```

## `POST /api/v1/incidents/{incident_id}/analyze`

Runs the `incident_report_gen` tool (P1 extraction, then RP1 prose report) on an uploaded video. Called by `incident-console-v2` in agent mode; `incident_id` is the console's `videos.id`. Field-level report schema: [analysis-schema.md](analysis-schema.md).

Request:

| Field | Type | Default | Notes |
|---|---|---|---|
| `video_url` | string | required | signed R2 URL, min 1 char |
| `model_run_id` | string | none | 1-20 chars; when given the caller records the run and the agent persists nothing |
| `skip_rp1` | bool | false | P1 only; `report_text` stays null |

Response `200`: the validated contract report (`core-scored-v1`), as a JSON object. Takes tens of seconds to minutes (VLM calls); use a long timeout.

Errors:

| Status | `detail` |
|---|---|
| 422 | validation, or contract violation: object with `message`, `raw_output`, `finish_reason`, `model`, `contract_version` (nothing persisted; record the attempt) |
| 501 | string: `incident_report_gen tool is not configured on this profile` |
| 504 | string: `Incident analysis timed out: ...` (P1 timeout) |
| 500 | string: `Analysis failed: ...` |

Example:

```bash
curl -s localhost:8000/api/v1/incidents/<videos.id>/analyze -H 'content-type: application/json' \
  -d '{"video_url":"https://<signed-r2-url>","model_run_id":"m86a5c319e26659804b0","skip_rp1":true}'
```

Live check of the error shape: `{}` body returns `422` `{"detail":[{"type":"missing","loc":["body","video_url"],"msg":"Field required","input":{}}]}`.

## `POST /api/v1/incidents/chat`

Q&A with evidence citations (chat-contract-v1). **Not backed by real data yet**: the route is wired to an in-memory keyword matcher over four canned seed hits (`Assault007`, `Burglary005`), never the database (the code carries a TODO to wire the live search). Do not build UI that depends on its answers being real.

Request:

| Field | Type | Notes |
|---|---|---|
| `messages[]` | `{role, content}` | required, at least one; `content` min 1 char; the last `user` message is the query |
| `session_id` | string | optional, max 128; generated (`session_<12 hex>`) if absent |
| `context.scope` | `"global"\|"incident"` | default `global` |
| `context.incident_id` | string | filters to one incident when scope is `incident` |
| `context.evidence_crop_ids` | string[] | accepted, unused |

Response `200`: `{"session_id", "message": {"role": "assistant", "content", "citations": [{"incident_id","item_id","item_type","timestamp_seconds","crop_image_url"}]}}`. No match gives a "No matching incidents..." message with empty `citations`.

Errors: `422` invalid scope (string `detail`) or validation, `400` no `user` message, `502` search client failure. Synchronous and fast (no model call).

Example: `{"messages":[{"role":"user","content":"edged weapon"}]}` returns `200` with 2 citations from the canned `Assault007` data.

## Other routes on `:8000` (not used by the incident frontend)

Registered by the same worker; documented upstream. Video: `POST /api/v1/videos`, `POST /api/v1/videos/{sensor_id}/complete`, `DELETE /api/v1/videos/{video_id}`, `PUT /api/v1/videos-for-search/{filename}` (deprecated). RTSP: `POST /api/v1/rtsp-streams/add`, `DELETE /api/v1/rtsp-streams/delete/{name}`. Plus NAT's standard routes (`/docs`, `/openapi.json`, `/generate`, `/chat`, ...). Use `/docs` on the tunnel for the full generated schema.

## Live VM check (2026-10-18, read-only)

| Check | Result |
|---|---|
| `GET /health` | `200` `{"value":{"isAlive":true}}` |
| `/openapi.json` incident paths | `analyze`, `search`, `chat` present |
| `POST search` `{"query":"edged weapon","top_k":5}` | `200` in 2.5 s, envelope matches, `total_hits: 0` |
| `POST search` `{}` / `top_k: 99` | `422` FastAPI detail list, as documented |
| `POST analyze` `{}` | `422` missing `video_url`, as documented |
| `POST chat` | `200`, canned `Assault007` citations |
| listening ports | `8000`, `7777` yes; `30081`, `30082` no (dropped from tunnel) |

Differences from main: the VM checkout was at `f7847e1d2` (PR 134), before the evidence loader and embedding changes of PR 138, and its search returned no hits. Hit contents above are therefore documented from main's models, not observed live. Re-check after the VM is updated (`incident-operate-vm`).

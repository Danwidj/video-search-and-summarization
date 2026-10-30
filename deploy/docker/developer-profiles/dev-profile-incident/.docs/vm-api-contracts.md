# VM API contracts (frontend reference)

HTTP contracts of the native `vss-agent` on `kwanz-ws` and the SSH tunnel the frontend uses to reach them. VM side only. Source of truth: `services/agent/src/vss_agents/api/` (Pydantic models) and `custom_fastapi_worker.py` (route registration). Last checked against main on 2026-10-24; the live VM was last checked on 2026-10-24 (below).

## Tunnel

`./start.sh --mode vm` opens one backgrounded `ssh -N -L ...` (standalone: `.scripts/tunnel.sh`). The frontend always addresses `http://localhost:<port>`.

| Local port | VM target | Service | Frontend use |
|---|---|---|---|
| `8001` | `127.0.0.1:8001` (loopback) | native `vss-agent` (FastAPI) | all endpoints below; set `INCIDENT_AGENT_BASE_URL=http://localhost:8001` (start.sh exports it) |
| `7777` | `<vm-ip>:7777` | `vss-haproxy-ingress` (VIOS/VST) | video upload and storage API |

- In mock mode `7777` is the mock backend instead (it also serves the incident search, revision search, chat, analyze and evidence-embeddings routes). There is no tunnel.
- `<vm-ip>` is detected over SSH unless `VSS_VM_IP` is set ([how](incident-profile-operations.md#ssh-port-tunneling-manual--standalone)).
- A local port already in use stops start.sh before the tunnel opens: `laptop port <p> is already in use by <holder>`.
- After opening, start.sh polls `localhost:8001/health` and `localhost:7777/storage` (HEAD) for up to 60 s each. Run `./.scripts/tunnel-check.sh` to check tunneled routes.

### When the VM is unreachable

start.sh probes SSH before it opens the tunnel and, when the VM or a tunnelled health check fails, prints the cause and the next step; the causes are listed in [`incident-profile-operations.md`](incident-profile-operations.md#ssh-username-resolution--troubleshooting).

## Common behaviour

- Base URL `http://localhost:8001`, JSON bodies, `Content-Type: application/json`. No authentication.
- Validation errors (FastAPI): `422` with `{"detail":[{"type","loc","msg","input"}]}`.
- Handler errors: `{"detail": "<message>"}` with the status given per endpoint.
- Routes are registered on every profile; all incident routes are unconditional.

## `GET /health`

Reachable at `/health` on `:8001`. Returns `200` `{"value":{"isAlive":true}}`. Use it for liveness only.

## `POST /api/v1/incidents/search`

Natural-language search over evidence crops (entity, instrument, asset) with the VLM critic off by default (`INCIDENT_SEARCH_CRITIC`). Contract: search-contract-v1. Incident search (`/revisions/search`) shares its embed-then-retrieve step (`semantic_search` in `incident_search.py`); the two routes differ only in what they retrieve.

Request (`extra` fields are rejected with 422):

| Field | Type | Default | Constraint |
|---|---|---|---|
| `query` | string | required, except with `filters.incident_id` or `filters.video_id` | 1-500 chars; may be empty only when `filters.incident_id` or `filters.video_id` is set (lists that scope's evidence, no embedding call) |
| `top_k` | int | 10 | 1-50 |
| `min_similarity` | float | 0.0 | 0.0-1.0 (no cutoff by default: top_k by score) |
| `hide_rejected` | bool | true | only matters when the critic is on: drop hits it marked `rejected` from `hits[]` (`rank` keeps its pre-filter value) |
| `filters.incident_types` | string[] | none | |
| `filters.min_severity`, `filters.max_severity` | int | none | 1-5 |
| `filters.item_types` | `"entity"\|"instrument"\|"asset"`[] | all three | |
| `filters.incident_id` | int | none | >= 1; searches one incident, every camera (applied inside `search_evidence_items(p_incident_id)` before ranking). With an empty `query` the hits are that incident's crops, `similarity_score` 0 |
| `filters.video_id` | string | none | 1-255 chars; searches only that video (`videos.id`, its real file name), applied inside `search_evidence_items(p_video_id)` before ranking, so the top `top_k` all belong to it |

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
| `hits[].item` | object | `item_type`, `item_id`, `video_id` (the camera the item was seen in), `name`, `label`, `description`, `threat_level` (int or null), `holder_entity_id` (string or null), `crop_image_url`, `timestamp_seconds` (int), `bounding_box` (null or `[ymin, xmin, ymax, xmax]`, 4 normalised ints) |
| `hits[].incident` | object | `incident_id` (int), `model_run_id`, `incident_type`, `severity_level` (1-5), `title` (string or null), `description`, `playback_url`, `incident_window` (`[start_s, end_s]`) |
| `hits[].critic` | object | `verdict` (`confirmed`, `rejected`, `unverified`), `confidence` (0-1, null, or observed 0.0), `rationale` |

Behaviour:
- The critic is dormant: unless the agent runs with `INCIDENT_SEARCH_CRITIC` set to a truthy value (`1`, `true`, `yes`, `on`), no VLM call is made and every hit is `verdict: "unverified"` with the rationale `Critic not run`. `hide_rejected` then has nothing to hide.
- With the critic on, `hide_rejected` (default true) excludes hits marked `rejected` from `hits[]` (`rank` retains its pre-filter value), and a failing critic never drops a hit: it degrades to `verdict: "unverified"` with the failure in `rationale`.
- `filters.video_id` needs migration `20261028090000_search_evidence_items_video_id.sql`; the agent sends `p_video_id` only for a scoped search, so an agent ahead of the migration still serves unscoped searches.
- `crop_image_url` and `playback_url` are resolved from R2 by the agent. Use them as given.
- Errors: 422 on validation. `503` `{"detail":"Query embedding unavailable: ..."}` when the query cannot be embedded: an embedder error, or no embedding API key with the Supabase store (the deterministic placeholder embedding is only used with the in-memory store). A store failure is not caught, so expect `500` (plain-text `Internal Server Error`, not the `detail` shape).
- Timing: embedding plus one pgvector query, with no critic delay while the critic is off. With the critic on, calls are spaced by `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` (default 1.0 s between hits, 30 s timeout each), so latency grows by about one second per hit; use a client timeout of at least 90 s and a loading state in that case.
- Side effect: each call writes one `queries` row and one `query_results` row per hit (audit trail, failures only logged).

Example (illustrative hit shape built from the Pydantic models; the live VM returns hits as detailed in the retest reports):

```bash
curl -s localhost:8001/api/v1/incidents/search -H 'content-type: application/json' \
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
      "item_type": "instrument", "item_id": "I1", "video_id": "Assault007_x264.mp4", "name": "machete", "label": "machete",
      "description": "Long curved blade held by assailant during storefront altercation.",
      "threat_level": 4, "holder_entity_id": "E1",
      "crop_image_url": "https://<r2-host>/evidence/uploads/Assault007_x264.mp4/run-1/I1.jpg",
      "timestamp_seconds": 14, "bounding_box": [320, 450, 510, 600]
    },
    "incident": {
      "incident_id": 1, "model_run_id": "Assault007_x264.mp4@2026-10-30T06:00:00Z",
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

## `POST /api/v1/incidents/evidence-embeddings`

Called by the console when a revision becomes its incident's searchable revision: made official, a new AI revision of an incident with no official one, or, before a Save, the new human revision's evidence. Items carry the `video_id` (camera) they were seen in. It embeds each item with the model search uses (`nvidia/llama-nemotron-embed-vl-1b-v2`, 1024 dimensions, `passage` input of `"{item_name}: {description}"`). The agent writes nothing; the console writes the `evidence_crops` rows.

Request: exactly one of `{"revision_id": <int >= 1>}` (the route reads that revision's `evidence`) or `{"evidence": [{"item_type", "item_id", "item_name"?, "description"?}, ...]}` (nothing is read). Response `200`: a list of `{"item_type", "item_id", "embedding"}` (empty when there are no items). Errors: `404` unknown revision, `422` neither or both sources, `502` embedding service failed, `503` database or embedding key not configured.

## `POST /api/v1/incidents/revisions/search`

Searches saved report revisions by their summary embedding. The route embeds `query` with the search query model (1024 dimensions, `query` input type), then calls `search_report_revisions`. Only revisions with a stored vector are searched: AI revisions saved with an embedding; human revisions and AI revisions saved while the embedding endpoint was unavailable are not. The zero-GPU mocks answer this route from their finals snapshot.

Request: `{"query": <1-1000 chars>, "top_k": <1-50, default 10>, "min_similarity": <-1.0 to 1.0, default 0.0>}`. Response `200`: a list, best first, of `{incident_id, revision_id, video_names, revision_no, kind, model_run_id, title, description, incident_type, severity_level, start_seconds, end_seconds, similarity_score}` (`video_names` is the revision's immutable coverage); empty when nothing matches. Errors: `422` invalid body, `502` embedding service failed, `503` database or query embedding key not configured.

## `POST /api/v1/incidents/{video_name}/analyze`

Runs the `incident_report_gen` tool (P1 extraction, then RP1 prose report) on an uploaded video and **stores the analysis**: one `video_analyses` row, the evidence crops (under `R2_KEY_PREFIX`) and the `model_runs` row. It creates **no report revision**; the console builds incident versions from stored analyses ([Synthesize](#post-apiv1incidentssynthesize)). Called by `incident-console-v2`; `video_name` is the video's real file name (`videos.id`, URL-encoded). Field-level report schema: [analysis-schema.md](analysis-schema.md).

Request:

| Field | Type | Default | Notes |
|---|---|---|---|
| `video_url` | string | required | signed R2 URL, min 1 char |
| `video_key` | string | none | the video's R2 key (prefix-free); the agent applies `R2_KEY_PREFIX` itself |
| `model_run_id` | string | none | readable id `<video name>@<UTC timestamp>`, any length; when given the caller owns the `model_runs` row (the agent inserts only a placeholder if it is absent) |
| `model` | string | agent `VLM_NAME` | a model id from the `contracts/inference.json` allowlist; anything else is `400` |
| `reviewer_prompt` | string | none | max 1000 chars (`422` above). Added to the report prompt for this run only, framed as `ADDITIONAL REVIEWER CONTEXT FOR THIS VIDEO`; copies nothing from earlier revisions |
| `skip_rp1` | bool | false | P1 only; `report_text` stays null |
| `video_duration_seconds` | number | none | video length in seconds as the caller read it; a finite number above 0, else `422`. Without it the agent reads the MP4 header from `video_url` (ranged GETs) |
| `experiment_prompt_id` | string | none | **Experimental**, prompt experiments only (below): a prompt id from `contracts/experiments/registry.json` |
| `skip_crops` | bool | false | **Experimental**, prompt experiments only (below): skip post-P1 evidence cropping |

Response `200`: an `IncidentReportGenOutput` JSON object, not the bare report: `report` (the validated contract report under `core-scored-v1`), `report_text` and `report_text_error` (RP1 output; `null` when `skip_rp1`), `model`, `contract_version`, `raw_output` (the raw P1 text, which the console re-validates and records), `finish_reason`, and, when the database is configured, `analysis_id` (the stored `video_analyses` row), `model_run_id`, `outcome` (`stored`, or `not_stored` when the best-effort write failed) and `evidence` (one entry per entity, instrument and asset: `item_type`, `item_id`, `timestamp_seconds`, for entities also `first_seen_seconds` and `last_seen_seconds` (falling back to `timestamp_seconds` for reports without them), `bounding_box`, `image` R2 key or `null`, `image_gap` reason when there is no image), and the video-bounds outcome: `video_duration_seconds` (the length `WINDOW_BEYOND_VIDEO` and `TIMELINE_BEYOND_VIDEO` used, or `null`), `video_duration_source` (`request`, `mp4_header` or `null`), `video_bounds_checked` and `video_bounds_unchecked_reason` (why the rules did not apply, e.g. `video length unknown: a ranged read of the video returned HTTP 403`). Takes tens of seconds to minutes (VLM calls); use a long timeout.

Errors:

| Status | `detail` |
|---|---|
| 422 | validation (including an invalid `video_duration_seconds`), or contract violation (including a window beyond the video): object with `message`, `raw_output`, `finish_reason`, `model`, `contract_version` (nothing persisted by the agent; the caller records the attempt) |
| 501 | string: `incident_report_gen tool is not configured on this profile` |
| 504 | string: `Incident analysis timed out: ...` (P1 timeout) |
| 500 | string: `Analysis failed: ...` |

Example:

```bash
curl -s localhost:8001/api/v1/incidents/<video_name>/analyze -H 'content-type: application/json' \
  -d '{"video_url":"https://<signed-r2-url>","model_run_id":"<video_name>@2026-10-30T06:00:00Z","skip_rp1":true}'
```

Live check of the error shape: `{}` body returns `422` `{"detail":[{"type":"missing","loc":["body","video_url"],"msg":"Field required","input":{}}]}`.

## `POST /api/v1/incidents/synthesize`

Stateless. Turns the stored analyses of one incident's videos into the incident overview and its search vector. The console calls it from Regenerate ([architecture §5](architecture.md#5-mvp3-incidents-with-several-videos)), then writes the version itself with the `create_ai_revision` database function. The agent writes nothing.

Request: `{"videos": [{"video_name": <string>, "payload": <the video's stored analysis report, incident-contract-v4>}, ...]}`. Response `200`: `{"overview": {title, type, severity_level, description, location}, "embedding": [<1024 floats>]}`. The embedding is the summary vector of the revision (title and description), the same model as revision search.

**Status on origin/mvp3:** the route is defined (`api/incident_synthesize.py`) but `register_incident_synthesize_routes` is not called in `custom_fastapi_worker.py`, so the VM agent answers `404` and Regenerate fails with `502` until open PR #320 ("mount POST /api/v1/incidents/synthesize in the worker") merges. Re-check before relying on it.

## `POST /api/v1/incidents/match-judge`

Stateless. Scores how likely a newly analysed video belongs to each shortlisted incident. The database shortlists by vector similarity (`shortlist_similar_incidents`); this route judges only that shortlist. Time is a soft hint, never a filter.

Request: `{"analysis": <the new video's report>, "recorded_at_start"?: <epoch s>, "recorded_at_end"?: <epoch s>, "candidates": [{"incident_id": <int>, "overview": <object|null>, "video_names": [<string>], "recorded_at_start"?: <epoch s>, "recorded_at_end"?: <epoch s>}, ...]}`. Response `200`: `{"judgements": [{"incident_id": <int>, "score": <0.0-1.0>, "reasons": [<string>]}]}`. The console keeps scores at or above 0.5 and records them with `record_match_suggestion`. The agent only suggests; it never merges or moves a video.

### Experimental settings (prompt experiments, PR 6B)

`experiment_prompt_id` and `skip_crops` exist for the eval prompt experiments ([`eval/experiments/README.md`](../eval/experiments/README.md)). **A request without either one is a production request: the same P1 body, persistence, cropping and response keys as before.**

- **Opt-in:** an experimental request is refused with **403** unless the agent process runs with `INCIDENT_EXPERIMENTS_ENABLED=1` (exactly `1`). The shared VM agent does not set it.
- **Prompt:** read from `contracts/experiments/registry.json` in the checkout, or from `INCIDENT_EXPERIMENT_REGISTRY`, and served only if the file matches its registered SHA-256 and the entry's contract version is the vendored one. Otherwise **400**. Only the prompt text of the P1 body changes.
- **400:** combined with `reviewer_prompt`.
- **409:** cropping is on (`skip_crops` false) while the agent has R2 settings. An experiment agent must hold no shared-storage settings at all.
- **Experimental crops** (`skip_crops` false, no R2): images go to a fresh in-memory store for that request only. They are discarded on return, never written to disk or R2, and `experiment.evidence_store` says so. Evidence `image` keys therefore point at nothing durable.
- **Never persisted:** an experimental request writes no `report_revisions` row and no `model_runs` placeholder (`revision_id` is `null`). With `skip_crops` every evidence entry has `image: null` and `image_gap: "evidence cropping skipped (skip_crops)"`.
- **Response additions:** `experiment` (`prompt_id` (null for the production prompt), `prompt_sha256`, `skip_crops`, `persisted: false`), `p1_elapsed_ms` (the P1 HTTP round trip) and `usage` (P1 token usage). A 422 contract violation of an experimental request carries the same three in `detail`.
- **Where it runs:** a local agent started for the experiment with no Supabase or R2 settings (plan decision D14 (b)). Restarting or reconfiguring the shared VM agent is ask-first.

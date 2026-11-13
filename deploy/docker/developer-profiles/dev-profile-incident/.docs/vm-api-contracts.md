# VM API contracts (frontend reference)

HTTP contracts of the native `vss-agent` on the VM and the SSH tunnel the console uses to reach them. Source of truth: `services/agent/src/vss_agents/api/` (Pydantic models) and `custom_fastapi_worker.py` (route registration).

| Endpoint | Purpose |
|---|---|
| [`GET /health`](#get-health) | Liveness |
| [`POST /api/v1/incidents/{incident_id}/analyze`](#post-apiv1incidentsincident_idanalyze) | Analyse an uploaded video into a report |
| [`POST /api/v1/incidents/search`](#post-apiv1incidentssearch) | Search evidence crops |
| [`POST /api/v1/incidents/revisions/search`](#post-apiv1incidentsrevisionssearch) | Search report versions by their summary |
| [`POST /api/v1/incidents/evidence-embeddings`](#post-apiv1incidentsevidence-embeddings), [`.../revision-embedding`](#post-apiv1incidentsrevision-embedding) | Embeddings the console stores |
| [`POST /api/v1/incidents/chat`](#post-apiv1incidentschat) | Answer a question from a report |
| [`POST /api/v1/incidents/{video_id}/video-check`](#post-apiv1incidentsvideo_idvideo-check) | A fresh look at the video for one question |
| [`POST /api/v1/incidents/{video_id}/investigate`](#post-apiv1incidentsvideo_idinvestigate) | Tool-using agent: investigator and report editor |
| [`POST /api/v1/incidents/{video_id}/draft-edits`](#post-apiv1incidentsvideo_iddraft-edits), [`.../evidence-asks`](#post-apiv1incidentsvideo_idevidence-asks) | Check proposed edits against a draft |
| [`POST` and `GET /api/v1/incidents/{video_id}/gap-retries`](#post-apiv1incidentsvideo_idgap-retries-and-get-apiv1incidentsvideo_idgap-retriesjob_id) | Look again for items with no box |
| [`POST /api/v1/incidents/{video_id}/box/describe`](#post-apiv1incidentsvideo_idboxdescribe), [`.../box/track`](#post-apiv1incidentsvideo_idboxtrack) | The reviewer box tool |
| [`POST /api/v1/incidents/chart-requests`](#post-apiv1incidentschart-requests), [`.../charts`](#post-apiv1incidentscharts) | Dashboard charts |

## Tunnel

`./start.sh --mode vm` opens one backgrounded `ssh -N -L ...` (standalone: `.scripts/tunnel.sh`). The console always addresses `http://localhost:<port>`.

| Local port | VM target | Service | Use |
|---|---|---|---|
| `8000` | `127.0.0.1:8000` (loopback) | native `vss-agent` (FastAPI) | all endpoints below; `INCIDENT_AGENT_BASE_URL=http://localhost:8000` (start.sh exports it) |

- Nothing else is forwarded. The console uploads each video straight to R2 through its own `/api/uploads/r2` route.
- A laptop port 8000 already in use stops start.sh before the tunnel opens. After opening, start.sh polls `localhost:8000/health` for up to 60 s. Run `./.scripts/tunnel-check.sh` to check the tunnelled routes.
- When the VM is unreachable, start.sh prints the cause and the next step ([operations](incident-profile-operations.md#ssh-login)).

## Common behaviour

- Base URL `http://localhost:8000`, JSON bodies, `Content-Type: application/json`. No authentication.
- Validation errors (FastAPI): `422` with `{"detail":[{"type","loc","msg","input"}]}`.
- Handler errors: `{"detail": "<message>"}` with the status given per endpoint.

## `GET /health`

Returns `200` `{"value":{"isAlive":true}}`. Use it for liveness only.

## `POST /api/v1/incidents/{incident_id}/analyze`

Runs the `incident_report_gen` tool (P1 extraction, then RP1 prose report) on an uploaded video. Called by `incident-console-v2` in agent mode; `incident_id` is the console's `videos.id`. Field-level report schema: [analysis-schema.md](analysis-schema.md).

Request:

| Field | Type | Default | Notes |
|---|---|---|---|
| `video_url` | string | required | signed R2 URL |
| `video_key` | string | none | 1-900 chars; the video's R2 key (the console sends it). Evidence is stored under `evidence/<video_key>/run-<n>/` |
| `model_run_id` | string | none | 1-20 chars; when given the caller owns the `model_runs` row (the agent inserts only a placeholder if it is absent) |
| `model` | string | agent `VLM_NAME` | a model id from the `contracts/inference.json` allowlist; anything else is `400` |
| `reviewer_prompt` | string | none | max 1000 chars. Added to the report prompt for this run only |
| `skip_rp1` | bool | false | P1 only; `report_text` stays null |
| `video_duration_seconds` | number | none | a finite number above 0, else `422`. Without it the agent reads the MP4 header from `video_url` |
| `experiment_prompt_id`, `skip_crops`, `max_crop_calls` | | none | **Experimental** ([below](#experimental-settings-prompt-experiments)) |

Response `200` (an `IncidentReportGenOutput`, not the bare report). It takes tens of seconds to minutes; use a long timeout.

| Field | Notes |
|---|---|
| `report` | the validated contract report under `core-scored-v1` |
| `report_text`, `report_text_error` | RP1 output; `null` when `skip_rp1` |
| `model`, `contract_version`, `finish_reason` | |
| `raw_output` | the raw P1 text, which the console re-validates and records |
| `p1_attempts` | every P1 call of the request, in order: `attempt`, `outcome` (`valid`/`retried`/`failed`), `finish_reason`, `output_chars`. A first output cut off by length or over 30,000 characters is retried once with the identical request, never repaired |
| `revision_id` | the new `report_revisions` row; `null` if the best-effort write failed |
| `evidence` | one entry per entity, instrument and asset ([entry fields](data.md#the-report-model)) |
| `video_duration_seconds`, `video_duration_source`, `video_bounds_checked`, `video_bounds_unchecked_reason` | the video-bounds outcome; the source is `request`, `mp4_header` or `null` |
| `provenance` | the run provenance, schema `incident-run-provenance-v1`: the agent's commit, `contract_version`, `flags` (what this analysis ran) and one entry per stage (`caption`, `p1`, `rp1`, `grounding`, `zoom`, `object_tracking`, `embedding`) with `{model, prompts, calls, failed, refused, prompt_tokens, completion_tokens, total_tokens, calls_without_usage, elapsed_ms}`. Also in the `422` detail |
| `tracking` | person tracking summary, only when `INCIDENT_TRACKING_ENABLED` is on: `{enabled, matched, matched_by_time, tracks, elapsed_ms, skipped}`; `tracking.marks` when `INCIDENT_SOM_ENABLED` is on as well |
| `object_tracking` | object tracker summary, only when `INCIDENT_OBJECT_TRACKING_ENABLED` is on: `{enabled, seeds, tracked, tracker, elapsed_ms, time_cap_reached, skipped, detector, items}` |

Errors:

| Status | `detail` |
|---|---|
| 422 | validation, or contract violation (including a window beyond the video): object with `message`, `raw_output`, `finish_reason`, `model`, `p1_attempts`, `contract_version`. Nothing is persisted by the agent; the caller records the attempt |
| 499 | the caller disconnected; the analysis was stopped and no revision written |
| 501 | `incident_report_gen tool is not configured on this profile` |
| 502 | `Video model returned no answer: ...`: the VLM answered HTTP 200 with a null body or no choices. The video is probably in an unsupported format (for example 10-bit H.264) or unreadable |
| 504 | `Incident analysis timed out: ...` (P1 timeout) |
| 500 | `Analysis failed: ...` |

```bash
curl -s localhost:8000/api/v1/incidents/<videos.id>/analyze -H 'content-type: application/json' \
  -d '{"video_url":"https://<signed-r2-url>","model_run_id":"m86a5c319e26659804b0","skip_rp1":true}'
```

What the stages do:

- **Tracking never fails an analysis.** A person without a track gains `track_gap` on its evidence entry, and a skipped stage sets `skipped` to the reason. With set-of-marks (`INCIDENT_SOM_ENABLED`), P1 sees a copy of the clip with numbered person boxes, deleted right after P1.
- **Object tracking** follows each located instrument and asset; a tracked item's evidence entry gets `track_source: "object-tracker"` and the frame, image and box of the track's first sample.
- **Time budget:** a production request has `INCIDENT_ANALYSIS_BUDGET_SECONDS` (default 540; the console's agent-mode limit is 600 s). Past it, an item not yet located gets `image_gap` and an unchecked second look gets `zoom_gap`, both `analysis time budget exhausted`, and the report is saved. The main P1 call itself is not bounded by the budget.
- **Gap retry:** after locate, an item with no box is looked for again within 24 detector calls (10 per item) and not once less than 90 s of the budget remain; a new box needs the video model to confirm it, and the entry then has `box_source: "gap-retry"`.
- **Caller disconnect:** when the console aborts, the agent cancels the run, writes no `report_revisions` row and answers `499`.

Agent environment: person tracking reads `INCIDENT_TRACKING_ENABLED` (off unless `1`, `true`, `yes` or `on`), `NVSTREAMER_BASE_URL` (default `http://localhost:31000`), `PERCEPTION_PROVISION_URL` (`http://localhost:9000`) and `VIDEO_ANALYTICS_API_URL` (`http://localhost:8081`), and needs `ffmpeg` and `ffprobe` on the agent host's PATH. Object tracking reads `INCIDENT_OBJECT_TRACKING_ENABLED`, `INCIDENT_OBJECT_TRACKING_MAX_SECONDS` (120), `INCIDENT_OBJECT_TRACKING_MAX_DETECTOR_CALLS` (80) and `INCIDENT_OBJECT_TRACKING_MODEL_DIR`.

### Caption pass (chunked captioning, `INCIDENT_CHUNKING_ENABLED`)

Off by default in code; `native-services.sh` starts the VM agent with it on (`1`) unless its env file sets `0`. Only the exact value `1` turns it on. A production request then runs a first pass before P1 ([`chunk_captions.py`](../../../../../services/agent/src/vss_agents/utils/chunk_captions.py)):

1. The clip is downloaded once from `video_url` and cut with `ffmpeg` into windows of `INCIDENT_CHUNK_WINDOW_SECONDS` (20) overlapping by `INCIDENT_CHUNK_OVERLAP_SECONDS` (2).
2. Each window is uploaded to `scratch/analyze/<video_key>/<model_run_id>/<index>.mp4` and captioned by the P1 model with NVIDIA's stock caption prompt (`INCIDENT_CHUNK_NUM_FRAMES`, 32; at most `INCIDENT_CHUNK_CONCURRENCY`, 4, calls in flight).
3. The timed captions are sent to P1 as one more user message (`CONTEXT FROM A FIRST PASS OVER THE SAME VIDEO`), with the instruction to trust the video. The prompt file, `inference.json`, the schema and every other request field are unchanged.
4. The scratch prefix is deleted when the pass ends, whether or not it succeeded.

Clips of `INCIDENT_CHUNK_MIN_CLIP_SECONDS` (30) or less are not chunked. The captions are context for P1 only: the response does not return them and nothing stores them. A skipped pass never fails the analysis: P1 runs without context, and the agent log says why (`caption pass skipped for <id>: <reason>`). It needs `ffmpeg` on the agent's `PATH` ([operations](incident-profile-operations.md#default-analysis-stack-in-vm-mode)).

### Experimental settings (prompt experiments)

`experiment_prompt_id`, `skip_crops`, `max_crop_calls`, `max_zoom_calls`, `experiment_object_tracking`, `experiment_captions` and `max_caption_calls` exist for the eval prompt experiments ([`eval/experiments/README.md`](../eval/experiments/README.md)). **A request without any of them is a production request.**

- **Opt-in:** an experimental request is refused with **403** unless the agent process runs with `INCIDENT_EXPERIMENTS_ENABLED=1` (exactly `1`). The shared VM agent does not set it.
- **Prompt:** read from `contracts/experiments/registry.json` and served only if the file matches its registered SHA-256, otherwise **400**. Only the prompt text of the P1 body changes.
- **Caps:** `max_crop_calls`, `max_zoom_calls` and `max_caption_calls` (each 1-200) cap the HTTP attempts of their stage, retries included.
- **Never persisted:** an experimental request writes no `report_revisions` row and no `model_runs` placeholder (`revision_id` is `null`), and cropping with R2 settings on the agent is a **409**.
- **Response additions:** `experiment`, `p1_report`, `p1_elapsed_ms` and `usage`.

### Other agent settings

Read from the agent's environment (`.env.remote` on the VM); none is in the tracked `.env`.

| Variable | Effect |
|---|---|
| `INCIDENT_VIDEO_BASE_URL` | A public base URL for stored videos: when set, the agent builds playback and crop URLs from it instead of signing R2 URLs |
| `INCIDENT_SEARCH_STORE` | `memory` or `supabase` picks the search store; unset uses `supabase` when the database is configured, else `memory` |
| `INCIDENT_TRACKING_MIN_IOU` | Minimum overlap (default 0.3) between a located box and a solid track for the track to confirm the box |
| `INCIDENT_TRACKING_END_MARGIN_SECONDS` | Seconds (default 20) after a track's last sample within which it still counts |
| `INCIDENT_EXPERIMENT_REGISTRY` | Path to the prompt-experiment registry, instead of `contracts/experiments/registry.json` in the checkout |

## `POST /api/v1/incidents/search`

Natural-language search over evidence crops (entity, instrument, asset). Contract: [`search-contract-v1`](../contracts/search-contract-v1/README.md).

Request (`extra` fields are rejected with 422):

| Field | Type | Default | Constraint |
|---|---|---|---|
| `query` | string | required, except with `filters.video_id` | 1-500 chars; may be empty only when `filters.video_id` is set (lists that incident's evidence, no embedding call) |
| `top_k` | int | 10 | 1-50 |
| `min_similarity` | float | 0.0 | 0.0-1.0 (the console sends 0.35 for an evidence query and 0.25 for the Find incidents text search) |
| `hide_rejected` | bool | true | only matters when the critic is on |
| `filters.incident_types` | string[] | none | |
| `filters.min_severity`, `filters.max_severity` | int | none | 1-5 |
| `filters.item_types` | `"entity"\|"instrument"\|"asset"`[] | all three | |
| `filters.video_id` | string | none | 1-64 chars; searches only that video. With an empty `query` the hits are the video's crops in video time order, `similarity_score` 0 |

Response `200`:

| Field | Notes |
|---|---|
| `query_id`, `query`, `total_hits`, `execution_time_ms` | `total_hits` 0 is a normal answer |
| `hits[].result_id`, `hits[].rank`, `hits[].similarity_score` | ranked, `rank` starts at 1 |
| `hits[].item` | `item_type`, `item_id`, `name`, `label`, `description`, `threat_level`, `holder_entity_id`, `crop_image_url`, `timestamp_seconds`, `bounding_box` (null or `[ymin, xmin, ymax, xmax]`), `slice_start_seconds` and `slice_end_seconds` (optional: the item's time range to play, first to last seen where it has a track, else the box second minus or plus 3 s), `frame_image_url` (optional signed URL of the whole frame; null or absent when none is stored) |
| `hits[].incident` | `incident_id`, `model_run_id`, `incident_type`, `severity_level` (1-5), `title`, `description`, `playback_url`, `incident_window` (`[start_s, end_s]`) |
| `hits[].critic` | `verdict` (`confirmed`, `rejected`, `unverified`), `confidence`, `rationale` |

- **The critic is dormant:** unless the agent runs with `INCIDENT_SEARCH_CRITIC` set to a truthy value, no VLM call is made and every hit is `verdict: "unverified"` with the rationale `Critic not run`. With it on, calls are spaced by `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` (default 1.0 s), so latency grows by about one second per hit, and a failing critic never drops a hit.
- `crop_image_url` and `playback_url` are resolved from R2 by the agent. Use them as given.
- **Errors:** 422 on validation; `503` `{"detail":"Query embedding unavailable: ..."}` when the query cannot be embedded; a store failure is a plain-text `500`.
- **Side effect:** each call writes one `queries` row and one `query_results` row per hit.

```bash
curl -s localhost:8000/api/v1/incidents/search -H 'content-type: application/json' \
  -d '{"query":"edged weapon","top_k":5,"filters":{"item_types":["instrument"],"min_severity":3}}'
```

## `POST /api/v1/incidents/revisions/search`

Searches saved report revisions by their summary embedding (`search_report_revisions`). Only a video's searchable version (official, else newest) is searched, and only when it has a stored vector, so one video returns at most one hit.

Request: `{"query": <1-1000 chars>, "top_k": <1-50, default 10>, "min_similarity": <-1.0 to 1.0, default 0.0>}`. Response `200`: a list, best first, of `{revision_id, video_id, revision_no, kind, model_run_id, title, description, incident_type, severity_level, start_seconds, end_seconds, similarity_score}`. Errors: `422` invalid body, `502` embedding service failed, `503` database or query embedding key not configured.

## `POST /api/v1/incidents/evidence-embeddings`

Called by the console when a revision becomes a video's searchable revision. It embeds each item with the model search uses (`nvidia/llama-nemotron-embed-vl-1b-v2`, 1024 dimensions, `passage` input of `"{item_name}: {description}"`). The agent writes nothing; the console writes the `evidence_crops` rows.

Request: exactly one of `{"revision_id": <int >= 1>}` or `{"evidence": [{"item_type", "item_id", "item_name"?, "description"?}, ...]}`. Response `200`: a list of `{"item_type", "item_id", "embedding"}`. Errors: `404` unknown revision, `422` neither or both sources, `502` embedding service failed, `503` database or embedding key not configured.

## `POST /api/v1/incidents/revision-embedding`

Embeds one version's summary (`incident_type: title`, a newline, then the description). The agent writes nothing; the console stores the vector.

Request: `{"incident_type": <str|null>, "title": <str>, "description": <str>}`. Response `200`: `{"embedding": [<1024 numbers>]}`. Errors: `422` both texts empty, `502` embedding service failed, `503` embedding key not configured.

## `POST /api/v1/incidents/chat`

Answers a question from stored evidence ([`chat-contract-v1`](../contracts/chat-contract-v1/README.md); code `services/agent/src/vss_agents/api/incident_chat.py`). The console calls it from `POST /api/chat`.

Request: `{"session_id"?: <1-128 chars>, "messages": [{"role": "user"|"assistant"|"system", "content": <non-empty>}, ...] (at least one `user` message), "context"?: {"scope": "global"|"incident", "incident_id"?, "evidence_crop_ids"?: [...]}, "version_id"?: <int >= 1>, "draft_report"?: {...}}`. `draft_report` (an unsaved edit of the version) requires `version_id`, else `422`.

Response `200`: `{"session_id", "message": {"role": "assistant", "content", "citations": [{"incident_id", "item_id", "item_type", "timestamp_seconds", "crop_image_url"}, ...]}}`. Errors: `400` no non-empty `user` message, or a `version_id` that belongs to another incident than `context.incident_id`; `404` unknown `version_id`; `502` evidence search or revision error; `503` report revisions unavailable.

`INCIDENT_CHAT_MODE` selects how a question is answered:

| Mode | How | Response |
|---|---|---|
| `template` (default) | No model. The answer is composed from the version's report (`utils/report_answers.py`) by the kind of question: what happened, who, objects, what was taken, weapons, when, severity and type, where. A question the report cannot answer gets "This report doesn't mention ..." and no citations | `chat-contract-v1` |
| `routed` | Code answers a report-field question with no model call; the chat model reads the version for the rest. `grounding.route` is `deterministic` for a question that asks only for report fields (also greetings and unrelated questions), `report_llm` for anything that names, reasons or leans on the conversation, and `insufficient` when the report cannot answer. An optional video check runs only on the reviewer's click after an offer, and is off | [`chat-contract-v3`](../contracts/chat-contract-v3/README.md): adds `message.source` and `grounding.route` (`deterministic`, `report_llm` or `insufficient`) |
| `grounded` | A chat model (`INCIDENT_CHAT_MODEL`, default `nvidia/nemotron-3-ultra`) answers from one report version: `version_id`, else the incident's official version (`409` when it has none), or the reviewer's `draft_report`. Citations are checked against the version's item ids. A library question (no incident and no version) is planned by the model, filtered and counted exactly by code | [`chat-contract-v2`](../contracts/chat-contract-v2/README.md): adds `message.insufficient_evidence` and `grounding` |

- **Prose and citations:** items are named by their labels or descriptions; the prose holds no item or incident id unless the question asks for ids. The citations are the items the answer relies on, each with its evidence entry's crop and the second that crop was found at.
- **A library question in template mode** gets "This chat mode doesn't answer questions across the whole library yet".
- **Model failures:** in grounded mode a model failure or a malformed answer is a `502` with a plain `detail`; routed mode instead answers `200` with what the report settles and a note that the reader is unavailable, or a request to try again.

## `POST /api/v1/incidents/{video_id}/video-check`

A reviewer's confirmed fresh look at the video. Off unless `INCIDENT_VIDEO_CHECK_ENABLED` is set: a request is then a `404` and no model is called. It writes nothing. The console calls it from `POST /api/chat/video-check`.

Request: `{"question": <1-500 chars>, "stored_answer": <1-4000 chars>}`. Response `200`: `{"content", "source": "video", "can_answer", "relation", "model", "usage"}`; `relation` is `agrees`, `conflicts`, `unrelated` or `unclear`. The VLM sees only the question and the clip. Errors: `404` no video file; `502` with a reason for a timeout, rate limit or unreadable reply.

## `POST /api/v1/incidents/{video_id}/investigate`

An agent that chooses its own tools to answer one question about one video. It writes nothing. With a `draft` it runs the report editor instead (the `report_editor` agent). Code: [`incident_investigate.py`](../../../../../services/agent/src/vss_agents/api/incident_investigate.py).

Request: `{"question": <1-500 chars>, "draft": <snapshot>, "history": <turns>}` (`draft` and `history` optional; other keys are `422`). `history` is the last few chat turns, oldest first, at most 6: `[{"role": "user" | "assistant", "text": 1-4000 chars}]`.

Response `200`: `{"status", "answer", "steps", "actions", "wall_ms"}`.

- **`status`:** `ok`, `cap_reached`, `timeout` (90 s), `busy` (the model endpoint still answered 429 after its retries), `aborted:step_budget`, `aborted:tool_failed:<tool>` or `error`. All are HTTP `200`. A run that ends with no answer gets one plain sentence in `answer`.
- **`steps`:** every tool that ran, in order: `{tool, args, ok, ms, error?}`.
- **`actions`:** the arguments of each `propose_*` tool that ran (`{tool, args}`). An editor run lists its edits, and for new evidence `propose_open_box_tool` (`{seconds, name}`, or `{item_key}` for an existing draft item to redraw).
- **Limits:** 4 iterations, 5 tool steps, 90 s for the run, 30 s per model call with 2 retries.
- **The video is bound by the route.** The tools take no `video_id` argument, so the model cannot read another video.
- **Tools:** the investigator has `incident_read_report` and `incident_list_versions`; the editor has the `propose_*` checks of `tools/incident_editor.py`, plus `propose_open_box_tool` and `propose_retry_gaps`.
- **Status codes:** `422` bad body, `501` the profile does not declare `investigator`.

## `POST /api/v1/incidents/{video_id}/draft-edits`

Checks proposed edits against the reviewer's unsaved draft. It writes nothing; the console applies the proposals and the reviewer saves.

Request: `{"draft": <snapshot>, "calls": [{"tool", "args"}]}`, 1-6 calls. The snapshot carries each item's draft `key`, which is the only way a call names an item. Tools: `set_incident_fields`, `set_timeline_item`, `upsert_entity`, `upsert_instrument`, `upsert_asset`, `set_instrument_holder`, `delete_item`. Seconds must lie inside the incident window when it is set. Response `200`: `{"proposals": [{"tool", "args", "summary", "also_removes"}], "rejected": [{"tool", "reason"}]}`. Any other unknown key or field is `422`.

## `POST /api/v1/incidents/{video_id}/evidence-asks`

Checks the new-evidence box tool call `open_box_tool`. It writes and asks nothing. The console does not call this route: it uses the report editor's `propose_open_box_tool` tool through the investigate route, which runs these same checks.

Request: `{"incident": {"start_timestamp", "end_timestamp"} (optional), "calls": [{"tool", "args"}]}`, 1-6 calls; `open_box_tool` args are `{"seconds": >= 0, "name": 1-80 characters}`. Response `200`: `{"proposals": [...], "rejected": [...]}`.

## `POST /api/v1/incidents/{video_id}/gap-retries` and `GET /api/v1/incidents/{video_id}/gap-retries/{job_id}`

Looks again in the video for the items of a saved report that have no box. The `POST` returns `202` at once with the job, and the console polls the `GET` until `status` is `done`. Nothing is written: a found box is a proposal the reviewer confirms or adjusts before Save. The console reaches these through `POST` and `GET /api/chat/gap-retry`.

Request (`POST`): `{"item_key": "E2"}` (optional: one item, by its id in the report; left out, every item with no box) and `"revision_id"` (optional; left out, the official revision, else the newest).

Response (`GET` and `POST`): `{"job_id", "video_id", "revision_id", "status": "running"|"done", "items": [{"item_key", "name", "status", "reason", "seconds", "box"}]}`. Per item, `status` is `pending`, `found` (with `seconds` and `box`), `not_found` or `not_retried`.

Limits: per request, 300 s and 40 detector calls for all its items. The agent keeps the last 20 jobs in memory, so a restart loses them and a `GET` then returns `404`. Status codes: `404` for an unknown video, report or job, `409` when a retry of this video is already running, `422` for an `item_key` the report does not have, `503` when the incident database is not configured.

## `POST /api/v1/incidents/{video_id}/box/describe`

What is the box a reviewer drew? The agent reads the frame at `seconds` from the video's stored file, cuts the box with a margin and asks the VLM with the `zoom/describe-box` prompt, reasoning off: first the Nano model (25 s, one try), then, if that fails or cannot tell, the analysis's own model (150 s, one more try after a timeout). At most 325 s; the console waits 330 s. Nothing is stored.

Request: `{"seconds": <float >= 0>, "box": [ymin, xmin, ymax, xmax]}`, the box normalised 0-1000. Response `200`: `{"proposal": {"item_type": "entity"|"instrument"|"asset", "name", "description", "holder": str|null, "threat_level": 1-5|null, "confidence": 0-1} | null, "reason": str|null}`. `proposal` is null with a plain `reason` when the model cannot tell. Errors: `404` unknown video, `422` bad body or no frame at that second, `502` the model failed, `503` database or VLM key not configured.

## `POST /api/v1/incidents/{video_id}/box/track`

Edit mode's tracker: the reviewer boxed an item at a second and named it; the agent follows that box back and forward with the object tracker, re-anchoring with the open-vocabulary detector, under a 50 s cap. Nothing is stored. Code: [`incident_box_track.py`](../../../../../services/agent/src/vss_agents/api/incident_box_track.py).

Request: `{"seconds": float >= 0, "box": [ymin, xmin, ymax, xmax] (0-1000), "item_type": str, "name": str, "description": str = "", "back_seconds": float = 3, "forward_seconds": float = 3}` (windows 0-30 s). Response `200`: `{"track": {"source": "reviewer", "samples": [{"t", "box", "conf", "score"}], "span": [first_t, last_t], "partial": bool, "lost_at": float|null, "reason": str|null}}`. `partial` is true when the item was lost inside the window, a cap stopped the run, or nothing could be followed. Errors: `404` unknown video or no stored file, `422` invalid body, `502` the clip cannot be read, `503` database or tracker unavailable.

## Reviewer box tool (console proxy)

The console proxies the two box endpoints for the report page's box tool and answers camelCase.

| Console route | Agent route | Body | Answer |
|---|---|---|---|
| `POST /api/reports/[videoId]/box/describe` | `POST /api/v1/incidents/{video_id}/box/describe` | `{seconds, box}` | `{proposal: {itemType, name, description, holder, threatLevel, confidence} or null, reason}` |
| `POST /api/reports/[videoId]/box/track` | `POST /api/v1/incidents/{video_id}/box/track` | `{seconds, box, itemType, name, description, backSeconds=3, forwardSeconds=3}` | `{track: {source: "reviewer", samples: [{t, box, conf}], span, partial, lostAt, reason}}` |

A bad body is 400, an agent 4xx is passed on, an unreachable agent or a 5xx is 502.

## `POST /api/v1/incidents/chart-requests`

Reads one dashboard chart request with the agent's own LLM (the `llms:` entry named by `chart_generator.llm_name`). The console sends the two messages the model gets, and the route passes them on unchanged and returns the JSON object the model wrote. The console checks the object against its allowlist.

Request: `{"messages": [{"role": "system", "content": "<the chart prompt, 1-20000 characters>"}, {"role": "user", "content": "Today is <YYYY-MM-DD> (time zone <IANA zone>).\nRequest: <the request, 1-300 characters>"}]}`. Exactly those two messages in that order. Response `200`: `{"reply": {...} | null}`, with `null` when the model wrote no JSON object. Status codes: `422` any other shape; `501` when `chart_generator.llm_name` is unset or names no LLM; `502` when the model call fails or takes longer than 40 s.

## `POST /api/v1/incidents/charts`

Builds the charts the dashboard's chart requests ask for with the `chart_generator` tool. The console computes every figure and sends it here; the route chooses and computes nothing.

Request: `{"charts_data": [<item>], "output_dir": "<dir>", "file_prefix": "<prefix>"}`. Each item is one of:

- **Chart.js** (`"output": "chartjs"`): `{"output", "kind", "title", "x_label", "y_label", "y2_label", "labels": [...], "series": [{"label", "values": [...], "color": "#rrggbb"}], "slice_colors": [...]}`. `kind` is `bar`, `stacked_bar`, `horizontal_bar`, `donut`, `line`, `area`, `combo_dual_axis` or `stacked_by_severity`. Up to 200 labels and 3 series.
- **Chart.js bubble** (`"kind": "bubble"`): `{"output", "kind", "title", "x_label", "y_label", "series_label", "points": [{"label", "x", "y", "count", "color"}]}`. Up to 200 points; `count` sets the radius.
- **PNG** (the fallback): a bar is `{"title", "chart_file_format": "png", "x_categories": [...], "series": {"<name>": [...]}, "x_label", "y_label"}`; a pie is `{"title", "chart_file_format": "png", "sizes": [...], "labels": [...]}`.

Response `200`: one entry per item, `{"success", "error_message", "object_store_key", "chart_config"}`. A Chart.js item returns `object_store_key: null` and `chart_config`, a plain Chart.js configuration with the figures exactly as sent and no functions. A PNG item returns `chart_config: null` and a key; `GET /static/<object_store_key>` returns the image. Status codes: `422` for a body that does not validate, `501` when the profile does not configure the tool, `500` when it fails.

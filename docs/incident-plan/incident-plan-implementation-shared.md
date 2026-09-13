# VSS Customization Plan — Incident Search & Reporting Capstone (Implementation — Shared Components)

*This is the AI/implementer-facing half of the plan - exact file paths, config keys, and technical findings, written for whoever is actually building this. The human-facing current-state summary is the companion document, `incident-plan-overview.md` ("the Overview doc"). Cross-references below point to it by name.*

*This file covers everything that's identical regardless of where the LLM/VLM run: Postgres, R2, the frontend app, the AI-trigger API, feature implementation, engineering evaluation, and the resulting directory tree. Deployment-mode-specific setup (profile creation, LLM/VLM config, GPU topology, the dev/deploy guide, and the NVIDIA stock-profile reference) lives in whichever of `incident-plan-implementation-local.md` or `incident-plan-implementation-remote.md` matches how you're actually deploying — read that file's §1–§2 first, this file second.*

*Terms used below: **VIOS** = VSS's Video I/O Storage service (ingestion/decode/encode); **RT-CV** = VSS's real-time computer-vision perception service (`vss-rtvi-cv`).*

**Note on scope:** this plan was originally organized around the team's epic/story numbering. Since that document is still being refined, every citation like "Story X.Y" has been replaced with a plain description of the capability itself — the technical content is unchanged, it's just no longer pinned to a numbering scheme that will drift. If a specific number/threshold below (e.g. a severity cutoff) isn't explicitly marked as sourced from the team's own spec, treat it as a reasonable default proposed here, not a confirmed requirement — check it against whatever the current epic/story doc says before building.

---

## 1. Postgres schema (Cloudflare Hyperdrive)
Use a real Postgres instance behind Cloudflare Hyperdrive (a pooler/accelerator - you still need to provision an actual Postgres server, e.g. Neon/Supabase/self-managed, behind it), not the existing `DuckDBIncidentsManager` pattern (`services/agent/src/vss_agents/tools/incidents.py`) - that class is a read-only cache rebuilt from bulk-rescanned S3 JSON files, has no single-record write API, isn't wired into base profile's flow today, and its DuckDB connection is a per-process singleton unsuited to a separate dashboard app reading the same data concurrently.

The schema itself already exists and is authoritative in code: `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py` (module docstring) plus `incident-console/README.md`. Do not design from the table sketch below - it predates the built schema and is kept only as a rough map of which areas exist.

Identity rule: 1 video = 1 incident (`incidents.incident_id` == `videos.id`; no `video_id` column anywhere). Model output is keyed by `(incident_id, model_run_id)` so multiple model runs score the same video without overwriting each other; the parallel `gt_*` tables hold the human ground-truth set (no `model_run_id`); `entity_matches` / `instrument_matches` / `asset_matches` hold accepted similarity pairings (see `matching.py`); `review_status` carries the human review workflow (`unreviewed` / `under review` / `verified`) keyed like `incidents`; `notifications` / `severity_eval_log` hang off `(incident_id, model_run_id)`.

| Area | Tables in `db.py` |
|---|---|
| Shared reference | `videos` (`id`, `filepath`, `uploaded_datetime`, `duration`, `source`), `queries`, `model_runs` |
| Model output | `incidents` (type, start/end timestamps, duration, description, severity 1-5, confidence), `reports`, `entities`, `instruments`, `assets` |
| Human ground truth | `gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets` |
| Eval matches | `entity_matches`, `instrument_matches`, `asset_matches` |
| Review + product | `review_status` (status, verified/edited by+at), `notifications`, `severity_eval_log` |

`verified_by`/`edited_by`/`rater` are freeform text (who typed their name in), not foreign keys to a user table - per the Overview doc's standing facts (§6). Skip a migration framework (Alembic etc.) - capstone-scale schema, `CREATE TABLE IF NOT EXISTS` run once on startup (`MetaData.create_all(checkfirst=True)` in `get_db()`) is enough.

DB access from the console is sync SQLAlchemy Core through `db.py`'s `IncidentDB` (matches Streamlit's per-script-rerun model); connection string is `INCIDENT_DB_DSN`, unset means a visible "database not configured" state, no offline mode. New file: `services/agent/src/vss_agents/utils/incident_db.py` - small async helper (`asyncpg` or SQLAlchemy-async) for CRUD against these tables.
Modify: `services/agent/pyproject.toml` (add `asyncpg`), `dev-profile-incident/.env` (add `INCIDENT_DB_DSN=postgresql://...`).
Note: the stack already runs its own internal Postgres (`centralizedb`, VIOS's metadata store) - do not repurpose it, its schema is VIOS-owned.
**Verify live:** `asyncpg`/SQLAlchemy connects through Hyperdrive with the right `sslmode`; keep the app-side connection pool small since Hyperdrive already pools (`IncidentDB.from_dsn` uses pool_size=2, max_overflow=3).
**Confirmed:** verified all four `DuckDBIncidentsManager` claims directly against `incidents.py` - read-only bulk S3-JSON cache, no single-record write API, not wired into any profile's `config.yml`, per-process singleton. Also confirmed: `services/agent/pyproject.toml` has zero Postgres client dependencies today (no `asyncpg`/`psycopg`/`sqlalchemy`), and no existing tool or API route in `services/agent` does async DB I/O or holds a connection pool - `incident_db.py` will be the *first* async-Postgres pattern in this package, with no in-repo precedent to model it on. Write it defensively (explicit pool sizing, explicit error handling) rather than assuming "it's just SQLAlchemy, it'll be fine."

---

## 2. R2 as the canonical video store
Per the Overview doc's standing facts (§6), R2 is the permanent video store on both ends of the pipeline — not an archive tier:
- **Inbound (source videos) — corrected target.** `dev-profile-base` has **no NvStreamer service at all** — it's only defined per-profile (search/lvs/alerts), which is part of why reusing search's tag was the right call, not just for the compose-tag superset. The canonical `CLIP_STORAGE_PATH` var in `deploy/docker/services/vios/vst.env:26` is a red herring for us: verified it's never referenced anywhere in the NvStreamer service we actually get. The real NvStreamer instance under `bp_developer_search_2d` is defined locally in `dev-profile-search/video-analytics-2d-app/compose.yml` (service `nvstreamer-2d-fusion`), and its watched directory is hardcoded in its own profile-local config: `nv_streamer_directory_path: "/tmp/nv_streamer/videos"` in `.../nvstreamer/configs/vst-config.json` (which, once copied into `dev-profile-incident/`, is already "our own folder" — safe to edit freely). **Also confirmed:** that path isn't bind-mounted to the host at all today — only `vst_data` (the metadata DB working dir) is. So this needs two changes, not just a mount: (1) add a host volume mount for `/tmp/nv_streamer/videos` (and/or `vst-storage.json`'s `video_path`) in our copy of the `nvstreamer-2d-fusion` service definition, (2) mount the R2 bucket onto that new host path via `rclone mount <r2-remote>:<bucket> <host-path>` (or `rclone sync` — see verify note below).
  **Verify live:** confirm the watcher works against a FUSE-mounted filesystem — if it relies on inotify rather than polling, prefer `rclone sync` into a real local directory over a live FUSE mount.
- **Outbound (VIOS recordings, if RTSP sources are also used):** `deploy/docker/services/vios/configs/vst_config.json` (`enable_cloud_storage: true`, `cloud_storage_type: "minio"`, plus R2 endpoint/keys/bucket) — confirmed gating in `services/vios/src/framework/media/media_pipelines/gstmux.cpp` (reads `enable_cloud_storage`/`cloud_storage_type`) selects `MinioCloudManager` via `cloud_manager_factory.cpp`, which speaks the S3 protocol R2 also speaks. Note this is the *canonical* VIOS config (separate from the profile-local NvStreamer config above) — it governs the `streamprocessing-ms`/`vst-ingress` RTSP-recording path, not file uploads.
  **Verify live:** `MinioCloudManager` uses the vendored `minio-cpp` SDK, not the AWS SDK — R2 commonly expects `region=auto` and this code's region handling looks inconsistent; do a real smoke test (record a clip, confirm it lands in and is retrievable from a test R2 bucket) before relying on it.
  Single-profile note: since there's now one `dev-profile-incident` deployment rather than two, this file is edited once — the earlier "shared between base and search" conflict this caveat used to describe no longer applies.

Local VIOS disk (`VST_VIDEO_STORAGE_PATH`) is now just a working cache once R2 holds the canonical copy — its aging/storage-cap policy can stay as-is; it no longer governs "permanent retention," which resolves the historical-retention requirement by construction.

---

## 3. New frontend app — `services/incident-console` (name is a placeholder, easy to rename), Python + Streamlit

**Capability → Streamlit component mapping** (confirms the fit before committing):

| Capability | Streamlit mechanism |
|---|---|
| Upload | `st.file_uploader` → calls vss-agent's own profile-agnostic `/api/v1/videos` upload contract, not raw VIOS (see §5) |
| Catalog + search/filter | `st.dataframe` + text/select filters over a direct SQL query |
| Edit metadata / edit report | `st.data_editor` or a `st.form` of field widgets per record |
| Prompt templates + reasoning toggle | `st.selectbox` (examples) + `st.checkbox` |
| Pipeline trigger + progress | `st.button` → HTTP call; `st.status()` context manager for stage-by-stage progress |
| Verify | `st.button` → direct DB update |
| Notifications | queried on every rerun; `st.toast()` for in-session alerts, optional `streamlit-autorefresh` component for near-live polling without manual reload |
| Jump-to-timestamp | `st.video(url, start_time=seconds)` — native support, confirmed |
| Dashboard | `st.plotly_chart`/`st.bar_chart` + `st.multiselect` filters + `.sort_values()` |
| Human eval | `st.slider` + `st.form` writing to `severity_eval_log` |

**Honest gap:** no true push notifications — only `st.toast()` (transient, single-session) plus rerun-triggered polling. Not a Streamlit-specific weakness: a from-scratch React app needs the same polling infrastructure unless you build real websockets, which is disproportionate effort for the underlying requirement ("don't miss a high-severity incident" — a polled badge satisfies that as long as the current spec doesn't demand something stronger; check it).

**Data access — direct Postgres, not a REST CRUD layer.** Since this app and `services/agent` are both Python hitting the same Postgres (via Hyperdrive, §1), Streamlit talks to Postgres **directly** (SQLAlchemy or `psycopg2`, sync — matches Streamlit's per-script-rerun execution model) for every read and plain write: catalog browsing, metadata edits, report edits/verify, notifications, dashboard aggregates, and eval-log writes. This removes most of the REST API originally planned — see §4, now reduced to just the two things that genuinely need `vss-agent`'s LLM/tool-calling.

Deployed as `dev-profile-incident/incident-console/compose.yml` — inside our own profile directory, not the shared `deploy/docker/services/` tree (same reasoning as `dev-profile-search`'s own `kibana-init-container-search`: this is profile-exclusive, not reusable NVIDIA infrastructure). `streamlit run app.py`, fronted by HAProxy alongside the existing NVIDIA UI (container name `vss-agent-ui`, Compose service key `vss-ui` — same service, two names depending on context; stays running unmodified, on-demand only, if the team still wants raw VSS chat/search for demos).

**Local dev is never Docker for this app** (see your mode's Implementation doc §2, "New incident-console app locally" for the full setup) — the VM deploy is the only place `incident-console/Dockerfile` gets used, and it should use `uv sync --frozen --no-dev`, matching `services/agent/docker/Dockerfile`'s own pattern, not `pip install -r requirements.txt`:
```dockerfile
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/
WORKDIR /app
COPY pyproject.toml uv.lock .
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
```

---

## 4. Minimal AI-trigger API on vss-agent
Two new endpoints — everything else is direct Postgres access per §3, since only these two need the LLM/agent tool-calling `services/agent` owns:
- `POST /api/v1/incidents/{id}/analyze` — new file `services/agent/src/vss_agents/api/incident_analyze.py` — triggers the one-click report-generation pipeline, internally calling `incident_report_gen` (§6). Streamlit polls `review_status`/`incidents` directly in Postgres for progress (via rerun/autorefresh) rather than needing a streaming response from this endpoint.
- `POST /api/v1/search` — new file `services/agent/src/vss_agents/api/search_query.py` (named to avoid colliding with `tools/search.py`, the underlying NAT function it calls into — NAT is `nvidia-nat`, the agent-toolkit framework `services/agent` is built on, not network address translation) — triggers VSS's existing `search_agent`/`embed_search` (search profile only, natural-language search capability), returning ranked results with relevance scores. Confirmed nothing resembling this already exists (`video_search_ingest.py` is upload-side only) — no duplication risk.

**Corrected file shape:** verified against `services/agent/src/vss_agents/api/rtsp_ingest.py`'s actual pattern — don't write these inline into `custom_fastapi_worker.py`. Each is its own module exposing `create_X_router(config) -> APIRouter` + `register_X_routes(app: FastAPI, config: Any) -> None` (which does `app.include_router(...)`), following NVIDIA's own documented extension convention (`services/agent/AGENTS.md`: "Tools subclass `FunctionBaseConfig`... Each tool has a `register.py` entry point"). `custom_fastapi_worker.py`'s `_register_streaming_routes` then gets exactly two added lines (an import + a call) per endpoint — this is the sanctioned, additive way to extend this codebase (confirmed: adding a route/tool module + a register.py entry is not flagged as sensitive in `AGENTS.md`'s "Ask first" / "Never" lists), not a separate installable plugin package.

**Flag — genuinely new territory:** every existing custom route module in `services/agent/src/vss_agents/api/` (`rtsp_ingest.py`, `video_ingest.py`, `video_delete.py`, `video_search_ingest.py`) only accepts `app` and `config` — none of them touch the `builder: WorkflowBuilder` that `add_routes` receives, and none invoke the agent's own tool-calling/reasoning loop; they all talk directly to VST/RTVI over plain HTTP. Wiring a plain FastAPI route to actually call `report_agent`/`search_agent` via `builder.get_tool(...)` has zero precedent in this codebase. `builder` is available and the mechanism is plausible, but treat this as an early spike/smoke-test, not an assumed-safe extension of an existing pattern.

Both sit alongside, not in place of, the existing chat/websocket endpoints.

---

## 5. Feature Implementation

### Data & Dataset

**Upload a new video**
**Corrected:** don't call VIOS's raw storage API directly — `services/agent/src/vss_agents/api/video_ingest.py` already implements a "profile-agnostic" upload contract (its own docstring's term) built exactly for this: `POST /api/v1/videos` (agent resolves and returns the VST upload URL) → chunked upload to that URL → `POST /api/v1/videos/{sensor_id}/complete` (triggers timeline lookup, storage URL resolution, and *optional* RT-CV register / embedding generation — each step self-skips if its backing service isn't configured). Streamlit's `st.file_uploader` should call this agent contract, then upsert the `videos` row (`IncidentDB.upsert_video()`; catalog status derives from `review_status`, `"unanalyzed"` when no incident exists yet) via a direct Postgres write. This also means the MVP1→MVP2 transition for uploads is already handled for us: the same call self-skips the embedding/RT-CV steps in MVP1 and picks them up automatically once MVP2's stack is running — no code change needed on our side at the boundary. Validation: surface VIOS's own rejection for unsupported containers (`vst_config.json`'s `nv_streamer_media_container_supported: ["mp4","mkv"]`) as the frontend error, rather than re-validating separately.

**Searchable video catalog**
`st.dataframe` over `IncidentDB.list_videos_with_counts()` (filename-substring/status filter, per-video report counts), backed by a direct `SELECT ... FROM videos` plus a join onto `incidents`/`review_status` for the derived status. Available from MVP1, no MVP2 dependency (distinct from the semantic/NL search capability below, which does need MVP2).

**Historical retention**
Satisfied by §1/§2 above (R2 + Postgres as canonical, permanent stores) — no separate archival workstream needed. Deletion becomes `IncidentDB.delete_incident()` / `delete_video()` (cascades to evidence, matches, review rows); "authorized user" gating is unenforced given the Overview doc's standing facts (§6) — flag this explicitly if it matters for grading criteria.

**Manual metadata correction**
`st.form` (location/camera source fields) issuing a direct `UPDATE videos SET ... , metadata_edited_by=..., metadata_edited_at=now()`. Reports generated after the edit must read live from `videos` rather than a cached copy — an explicit check to make when building `incident_report_gen` (see Incident classification below), not automatic by default.

### AI & Video Intelligence

**Natural-language search** — requires **MVP2's search stack** (RT-Embed — the video-embedding-generation service in NVIDIA's search pipeline — plus Elasticsearch), not active during MVP1. Wraps VSS's existing `search`/`search_agent`/`embed_search` functions (already built into the codebase, just not yet wired into `dev-profile-incident/vss-agent/configs/config.yml` at MVP1) behind the new `POST /api/v1/search` endpoint (§4) rather than the chat UI — Streamlit's search box calls it directly. Confidence scores: Elasticsearch's relevance score is already returned per hit — surface it directly.

**Analysis prompt + reasoning toggle**
Prompt templates: static list in Streamlit (`st.selectbox`), no backend change. Reasoning toggle: Nemotron-family models typically expose extended reasoning via a system-prompt flag — **unverified against whichever model is actually deployed; confirm its supported parameters before building the toggle** (under remote mode, confirm via the model probe described in your Implementation doc's §1). If supported, thread it through as an extra field on `/analyze`.

**Detailed event description**
Already `video_report_gen`'s core output, wrapped by `incident_report_gen` (see Incident classification below) — no separate work. Chronological ordering falls out of VSS's existing timestamped dense-captioning. Failure handling: wrap `/analyze` in try/except, return a structured error rather than a blank report. **Under remote mode specifically**, this matters more than it would locally, given the concurrent-request-ceiling hang risk flagged in your Implementation doc's §1: don't let a hung upstream call silently wedge the whole pipeline with no timeout.

**Key persons identification**
New file `services/agent/src/vss_agents/data_models/incident_report.py` — defines the `IncidentReport` Pydantic schema, field-named to match `db.py` (`type`, `severity_level`, `confidence_score`, `start_timestamp`/`end_timestamp`; persons live in the `entities` table). Add the persons extraction via `llm.with_structured_output` (same pattern already used in `services/agent/src/vss_agents/agents/postprocessing/validators/llm_based_rule_validator.py:131` and `services/agent/src/vss_agents/evaluators/report_evaluator/field_evaluators/llm_judge.py:246`). "States this rather than fabricating" is prompt engineering + an empty-list-is-valid schema, not new infra.

**Incident classification**
Add `type`, `severity_level` (1–5), `confidence_score` (0–1) to `IncidentReport`. Proposed default taxonomy (edit freely, and not confirmed against any spec — check it): robbery, burglary, vandalism, assault/fighting, trespassing, suspicious behavior, weapon presence, other — drawn from the problem statement's own examples. Low-confidence flagging is a UI threshold on `confidence_score`, no backend change.

Build `incident_report_gen` (`services/agent/src/vss_agents/tools/incident_report_gen.py`, new) as a thin wrapper around the existing `video_report_gen` tool, not a reimplementation — confirmed the base profile's `report_agent` (the pattern to copy into the new `config.yml`) runs "Mode 3 (Video/uploaded)" via `video_report_gen.py`. Call `video_report_gen` internally (`builder.get_tool(...)`), feed its `content` field (confirmed present at the time of writing, `video_report_gen.py:592` — re-verify the line number if this file has changed) into the schema extraction above, persist via §1's `incident_db.py`, return a `video_report_gen`-output-compatible object plus `structured_report: IncidentReport`. Wrap persistence in try/except (fail-soft — no existing in-repo precedent for this specific pattern was found on inspection; this is a design recommendation, not a copy of existing code) so a DB outage never breaks report generation. Preserves the existing `vss_report_{sensor_id}_{timestamp}.md` filename convention automatically. Register in `services/agent/src/vss_agents/tools/register.py` (a plain import-list append — see §4's "corrected file shape" note, same convention); wire into `dev-profile-incident/vss-agent/configs/config.yml` (`functions.report_agent.video_report_tool: incident_report_gen`) — per your Implementation doc's §1 correction, this `report_agent` block is copied in from `dev-profile-base`'s config as the MVP1 baseline (search's config has no `report_agent` to strip down); MVP2 only *adds* `search`/`search_agent`/`embed_search` blocks to it, never touches this part again.

**Incident start-time detection**
Add an LLM pass inside `incident_report_gen` that scans the same chunk-level timestamped captions `video_report_gen` already consumes, and returns the timestamp of the first chunk where the described incident actually begins — populating `start_timestamp`/`end_timestamp`. Falls back to `0:00` with no confident timestamp when not confidently identifiable. Built on existing timestamped-chunk infrastructure, not new video processing.

### Workflow & Automation

**One-click full pipeline**
`POST /api/v1/incidents/{id}/analyze` (§4) — internally chains ingestion-status check → (embedding-indexing wait, only meaningful once MVP2's embedding pipeline is running — no-op during MVP1) → `incident_report_gen`, per the Overview doc's standing facts (§6). Progress visibility: since Streamlit talks to Postgres directly, it doesn't need a streaming response from this endpoint at all — `st.status()` wraps a rerun/polling loop reading `review_status` (joined to `incidents`) directly from Postgres as the pipeline advances — halting gracefully and surfacing the failure. On failure at any stage, the endpoint records the failure state in Postgres, which Streamlit then displays. **Under remote mode**, given the concurrent-request-ceiling risk flagged in your Implementation doc's §1, set an explicit timeout on the upstream LLM/VLM calls inside this chain — without one, a saturated remote endpoint can hang the pipeline indefinitely rather than surfacing as `failed`.

**Auto-populate structured report**
Exactly what `incident_report_gen`'s `IncidentReport` schema (Incident classification / start-time detection above) already produces — confirm its fields cover whatever the current report-card spec needs (`type`, `location`, `time range`, `description`, `severity`, `confidence` — all present as designed, mapped onto `db.py`'s `type`/`severity_level`/`confidence_score`/timestamps).

**Status transitions**
`review_status.status` defaults `'unreviewed'` on `insert_incident`. Streamlit's "Verify" button calls `IncidentDB.set_review_status()` (persists the transition plus `verified_by`/`verified_at`, raises a `notifications` row when severity >= threshold) — no AI involved, so no need to route through `vss-agent`. Dashboard queries (below) filter `status='verified'` only, so unreviewed reports don't appear in manager-facing analytics — check this against whatever the current spec says about that boundary.

**High-severity alerts**
In the same verify-button handler (plain DB write, no agent call needed): if `severity >= 4`, insert a `notifications` row. **This threshold (4) is a proposed default, not sourced from any spec — confirm the actual cutoff before building.** Streamlit queries `notifications` on every rerun, using `st.toast()` for in-session alerts and `streamlit-autorefresh` for near-live polling (see §3's honest gap note); group notifications created within a short time window (e.g. same 5-minute bucket, also a proposed default) at query/render time rather than building a separate queue/worker.

### Frontend & User Experience

All new Streamlit work against Postgres directly (§3) — no further backend design needed beyond the capabilities above:
- **Search/filter** → direct `SELECT ... FROM incidents` joined to `videos`/`review_status` (type/status/keyword; see `IncidentDB._incident_view_rows`)
- **Jump-to-timestamp** → `st.video(url, start_time=incidents.start_timestamp)`; when the timestamp is not confidently identified, show an "unconfirmed" badge and default to 0:00 (the start-time-detection fallback above)
- **Edit/verify UI** → `IncidentDB.update_incident()` for field edits + `set_review_status()` for verify, which stamps `edited_by`/`edited_at`
- **Dashboard (filters + insights)** — all read from a direct aggregate query over `incidents` (counts by type/time, top recurring type per time-bucket for the "insights" text), rendered with `st.plotly_chart`/`st.bar_chart`. Insights sentences can start as a templated string over the aggregate results — no new ML needed unless the team wants it more sophisticated later.

### Evaluation & Testing (product-facing)

**Human-vs-AI severity validation**
New small Streamlit flow: `st.slider` to rate a sample of already-generated reports' severity independently, `st.form` submit writes directly to `severity_eval_log`. Agreement rate = matching rows / total rows, via a simple aggregate query; flag rows where `abs(ai_severity - human_severity) > threshold` (**threshold value not sourced from any spec — pick and confirm one, e.g. 1 or 2 on the 1–5 scale, before building**). Lightweight addition to the frontend — distinct from, and simpler than, the engineering-level evaluation harness below (which the team's original ask also covered, separate from this product-facing check).

---

## 6. Engineering/Technical Evaluation (supports the evaluation capability, not itself a user story)

Carried over from the team's original ask for a Python/notebook-based eval harness — distinct from the lightweight in-product agreement check (§5, human-vs-AI severity validation):

- **Report-quality scoring:** a real `nat eval`-based harness exists (`services/agent/src/vss_agents/evaluators/report_evaluator/`), wired up today only in `dev-profile-base/eval/`'s example config. `nat eval` itself is invoked with an explicit `--config_file` flag and `report_evaluator.eval_metrics_config_path` is `${ENV_VAR}`-driven — confirmed portable, no hardcoded profile paths. **But:** verified `dev-profile-search`'s `config.yml` has no `eval:` section at all (no `report_evaluator`/`trajectory_evaluator`/`qa_evaluator` blocks) — same root cause as the `report_agent` gap noted in your Implementation doc's §1, search's config was never built to run or evaluate report generation. So this isn't just "copy `report_eval_metrics.yaml` into a new `dev-profile-incident/eval/` directory" — the entire `eval:` block (~130 lines: `report_evaluator` + `trajectory_evaluator` + `qa_evaluator`) needs to be copied from `dev-profile-base`'s `config.yml` into `dev-profile-incident`'s `config.yml` first, then `report_eval_metrics.yaml` written against `IncidentReport`'s actual fields (from Incident classification / start-time detection, §5). Usable from MVP1 onward once that block is in place (report generation exists from MVP1). **Under remote mode:** running the eval harness fires many LLM-judge calls in sequence/parallel — be mindful of the same concurrent-request ceiling flagged in your Implementation doc's §1 if running eval at any real scale against the free hosted tier.
- **Retrieval precision/recall/F1:** nothing in the repo computes ranked-IR metrics today (the existing `f1` metric is token-overlap-on-text, unrelated). Build a standalone notebook (not hooked into `nat eval`) querying Elasticsearch directly (`network_mode: host`, `http://${HOST_IP}:9200`, index `mdx-embed-filtered-*` — confirmed real and in active use, not invented: `dev-profile-search/.env:338` sets `ELASTIC_SEARCH_INDEX=mdx-embed-filtered-2025-01-01`, and both `services/agent/src/vss_agents/tools/embed_search.py:617` and `attribute_search.py:77` reference the same wildcard pattern) or the deployed search API, against a hand-curated set of 10–30 queries with labeled relevant clip/video IDs — only exercisable once MVP2's search stack (and the natural-language search capability) is live.

---

## 7. Resulting Directory Tree

Scoped to everything this plan touches — the rest of the repo is untouched. `[NEW]` = file/dir we create; `[MOD]` = existing NVIDIA file with a small, additive edit. All filenames below are confirmed (not placeholders) except the Streamlit `pages/` breakdown, which is illustrative — exact page split is an implementation-time call, not a plan-level decision. Two lines below are deployment-mode-dependent — marked inline; see your Implementation doc's §1 for which applies.

```
vss/
├── deploy/docker/developer-profiles/
│   ├── compose.yml                                    [MOD] +1 line: include dev-profile-incident/compose.yml
│   │
│   ├── dev-profile-incident/                           [NEW] — everything below is ours (your Implementation doc, §1)
│   │   ├── .env                                        (copied from dev-profile-search/.env, BP_PROFILE kept)
│   │   ├── generated.env.<local|remote>                 (gitignored working copy, mode-specific — your Implementation doc, §2)
│   │   ├── compose.yml                                  (includes ./incident-console/compose.yml only —
│   │   │                                                  not search's kibana-init block, we don't use Kibana)
│   │   │
│   │   ├── vss-agent/configs/
│   │   │   ├── config.yml                               (built from base's report_agent/video_report_gen +
│   │   │   │                                              workflow for MVP1; search's functions + extended
│   │   │   │                                              subagent_names appended for MVP2; full eval: block
│   │   │   │                                              copied from base — §6; under remote mode, carries
│   │   │   │                                              over base's local openai_vlm base_url patch — see
│   │   │   │                                              remote Implementation doc §1 for its status)
│   │   │   └── config_rag.yml                           (remote mode only — same openai_vlm base_url patch)
│   │   │
│   │   ├── incident-console/                            [NEW] — the Streamlit app, profile-exclusive (§3)
│   │   │   ├── compose.yml                              (streamlit run app.py, tagged bp_developer_search_2d —
│   │   │   │                                              used for the VM deploy only, never local dev)
│   │   │   ├── Dockerfile                                (uv sync --frozen --no-dev, VM deploy only)
│   │   │   ├── pyproject.toml                            (uv-managed package — local dev is `uv run
│   │   │   ├── uv.lock                                    streamlit run app.py`, no Docker, your Implementation doc §2)
│   │   │   ├── app.py                                   (entry point / nav)
│   │   │   ├── mock_llm_server.py                        [NEW] tiny FastAPI/Uvicorn stub implementing
│   │   │   │                                              POST /v1/chat/completions with canned
│   │   │   │                                              IncidentReport-shaped output — local-dev-only,
│   │   │   │                                              avoids real GPU/NIM/API-quota use during iteration,
│   │   │   │                                              never deployed to the VM (your Implementation doc §2)
│   │   │   └── pages/                                   (illustrative split — catalog, report review,
│   │   │       ├── 1_catalog.py                          dashboard, human-eval — one per major screen
│   │   │       ├── 2_report_review.py                    from the Capability → Streamlit mapping, §3)
│   │   │       ├── 3_dashboard.py
│   │   │       └── 4_human_eval.py
│   │   │
│   │   ├── video-analytics-2d-app/                      (copied from dev-profile-search — needed for MVP2's
│   │   │   ├── nvstreamer/configs/
│   │   │   │   ├── vst-config.json                      [MOD from search's copy] add cloud/host-mount wiring
│   │   │   │   └── vst-storage.json                       for R2 (§2 — nv_streamer_directory_path target)
│   │   │   ├── deepstream/...                             search embedding pipeline — RT-CV, fusion_search)
│   │   │   └── vss-search-analytics/configs/...
│   │   │
│   │   └── eval/                                        [NEW] (§6)
│   │       └── report_eval_metrics.yaml                  (written against IncidentReport's fields)
│   │
│   └── dev-profile-search/                               (untouched — NVIDIA's own reference profile)
│
├── deploy/docker/services/nim/
│   └── nemotron-3-nano/
│       └── hw-OTHER.env                                 [MOD] local mode only — not present/needed under
│                                                                remote mode (your Implementation doc §1).
│                                                                Populated with NIM_KVCACHE_PERCENT/
│                                                                NIM_GPU_MEM_FRACTION sizing borrowed
│                                                                from L40S's dedicated-mode values;
│                                                                flagged incomplete, confirm before relying on it
│
└── services/agent/
    ├── pyproject.toml                                   [MOD] +asyncpg dependency (§1)
    │
    └── src/vss_agents/
        ├── tools/
        │   ├── incident_report_gen.py                    [NEW] wraps video_report_gen + structured
        │   │                                                    extraction (§5, Incident classification)
        │   └── register.py                               [MOD] +2 lines (import + __all__ entry)
        │
        ├── api/
        │   ├── incident_analyze.py                        [NEW] create_incident_analyze_router() +
        │   │                                                     register_incident_analyze_routes()
        │   │                                                     → POST /api/v1/incidents/{id}/analyze (§4)
        │   ├── search_query.py                             [NEW] same shape → POST /api/v1/search (§4)
        │   ├── register.py                                [MOD] +2 lines (import both new modules)
        │   └── custom_fastapi_worker.py                    [MOD] +2 lines per endpoint in
        │                                                          _register_streaming_routes (§4)
        │
        ├── data_models/
        │   └── incident_report.py                          [NEW] IncidentReport pydantic schema
        │                                                          (type, severity_level,
        │                                                           confidence_score, start/end
        │                                                           timestamps, §5, Key
        │                                                           persons identification)
        │
        └── utils/
            └── incident_db.py                              [NEW] async Postgres/Hyperdrive CRUD helper
                                                                    (first async-DB pattern in this
                                                                     package — no in-repo precedent, §1)
```

Not shown: external, non-repo resources (the Postgres server behind Hyperdrive, the R2 bucket) since they're cloud infrastructure, not files in this tree.

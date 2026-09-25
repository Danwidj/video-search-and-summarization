# Incident Profile Status

> **As of 2026-09-25**
>
> This is a volatile snapshot document capturing the current operational state, delivery milestones, known issues, and environment configuration. It is intended to be rewritten as reality evolves, not monotonically appended.

---

## 1. Milestone Status: Done vs. Outstanding

Current delivery status verified against the codebase:

| Component / Feature | Current State | Verifiable Source Files |
|---|---|---|
| **incident-console-v2 (Next.js)** | **Done** | `incident-console-v2/` (App Router UI, chunked VST upload, R2 direct fallback, report workspace, review flow, notification banner, eval form) |
| **vlm-gateway Proxy** | **Done** | `vlm-gateway/app.py`, `vlm-gateway/README.md` (FastAPI proxy on port 8600 holding upstream API credentials) |
| **mock-backend (Zero-GPU)** | **Done** | `mock-backend/base_profile_mock/` (port 7777, mock VST upload, mock stream registration, mock incident analysis) |
| **Agent /analyze Route & Tool** | **Done** | `services/agent/src/vss_agents/api/incident_analyze.py`, `services/agent/src/vss_agents/tools/incident_report_gen.py` |
| **Native VM Services Architecture** | **Done** | `.scripts/native-services.sh`, `.scripts/prune-native-images.sh` (`vss-agent` runs natively on `kwanz-ws` for 2s fast restarts; relinked editable to `services/agent/` with Brev inference) |
| **PostgREST Agent Persistence** | **Done** | `services/agent/src/vss_agents/utils/incident_db.py`, `supabase/migrations/20260917141225_insert_incident_function.sql`, `supabase/migrations/20260925031000_schema_defaults_and_precision.sql` |
| **Database Defaults & Precision Fix** | **Done (Live)** | `supabase/migrations/20260925031000_schema_defaults_and_precision.sql` applied to live Supabase DB on 2026-09-25: server-side UTC defaults on 9 timestamp columns, `review_status.status` default `'unreviewed'`, `notifications.acknowledged` default `FALSE`, and `insert_incident` updated to `p_confidence_score DOUBLE PRECISION`. PostgREST writers (`incident-console/db_postgrest.py`, `eval/db_postgrest.py`) updated to use `/rpc/insert_incident`. Agent extraction validation failure now surfaces HTTP 422/504 instead of persisting default reports. |
| **Cloudflare R2 Integration** | **Done** | `incident-console-v2/lib/r2/config.ts`, `incident-console-v2/app/api/uploads/r2/route.ts`, `incident-console/r2_videos.py` |
| **Tier 1 Ground-Truth Evaluation** | **Done** | `incident-console/eval_gt.py`, `incident-console/matching.py`, `incident-console-v2/components/advanced-report-tools.tsx` |
| **Unified Launcher (`start.sh`)** | **Done** | `start.sh`, `.scripts/tunnel.sh`, `.scripts/resolve-ssh-target.sh` (supports `--mode local` and `--mode vm` with non-interactive SSH resolution, preflight check, and auto self-heal) |
| **Analysis Contract Unification** | **Done** | `incident-console-v2/lib/analysis/schema.ts`, `incident-console-v2/lib/analysis/prompt.ts`, `incident-console-v2/lib/analysis/incident-report-contract.json`, `services/agent/src/vss_agents/data_models/incident_report.py` (Unified contract across gateway and agent modes onto agent snake_case schema and agent extraction prompt; legacy camelCase read-compatibility retained) |
| **Live VM & Brev Verification** | **Done (Live)** | Verified live via `./start.sh --mode vm` with `~/Desktop/test2.mp4` against Brev Switchyard; Agent and Gateway modes both produce valid non-empty snake_case reports; fixed HITL `NotImplementedError` and short-duration filter empty-report bugs in `services/agent` |
| **Multi-Subagent Search Config** | **Outstanding (MVP2)** | `deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` multi-subagent routing (`report_agent` + `search_agent`) planned; not yet wired together |
| **Natural Language Search Route** | **Outstanding (MVP2)** | `POST /api/v1/incidents/search` on `vss-agent` and UI search box not yet implemented |
| **Full RT-CV + RT-Embed Indexing** | **Outstanding (MVP2)** | DeepStream perception and vector embedding pipeline integration with Elasticsearch under live incident load |
| **Retrieval Benchmark Framework** | **Outstanding (MVP2)** | Precision/Recall/F1 benchmark suite for search queries |

---

## 2. Known Issues & Technical Debt

The following anomalies are currently present in the codebase and represent intentional compromises or pending work:

1. **Two Independent Writers & Agent-Mode Double-Write:**
   Both `incident-console-v2` (`incident-console-v2/app/api/analysis/route.ts`) and the native `vss-agent` (`services/agent/src/vss_agents/tools/incident_report_gen.py` via `services/agent/src/vss_agents/utils/incident_db.py`) possess full write logic to Supabase PostgREST tables. In Gateway Mode, the Next.js API route writes all tables directly. In Agent Mode, the agent persists records (`incidents`, `entities`, `instruments`, `assets`), while the console subsequently updates `model_runs` (setting `notes` to serialized native snake_case JSON and `model_name = 'vss-agent'`), restores the video R2 key, and inserts `reports`. Both modes now share the identical unified `snake_case` contract. Consolidation into the agent ("Option B") is planned but not started.
2. **Full Report JSON Serialized into `model_runs.notes`:**
   Instead of normalizing full VLM output or adding a dedicated `JSONB` column, `incident-console-v2` serializes the entire report dictionary (including raw and normalized VLM responses) as a JSON string stored within the SQL `TEXT` column `model_runs.notes`. Report display and sharing rely on reading and re-parsing this field.
3. **`videos.filepath` Overwritten by Agent with VST URL:**
   In `services/agent/src/vss_agents/tools/incident_report_gen.py` (line 392), after completing analysis, the agent calls `await db.upsert_video(incident_id, filepath=report_result.video_url, source=sensor_id)`. Because `video_url` points to the internal VST stream URL (`http://10.131.1.5:10000/...`), this call overwrites the permanent Cloudflare R2 object key stored in `videos.filepath`.
   *Active Workaround:* `incident-console-v2`'s `analyzeViaAgent` in `incident-console-v2/app/api/analysis/route.ts` explicitly re-saves the original R2 filepath after the agent completes: `await saveVideo(db, { videoId, filepath: input.filepath, sensorId: input.sensorId, uploadedAt: generatedAt })`.
4. **Mock-Backend Hash-Picked `anomaly/<category>` Uploads:**
   `mock-backend/base_profile_mock/.../routers/vst_storage.py` writes uploaded files to `anomaly/<category>/<original filename>` using `_CATEGORIES[sha256(incident_id)[0] % 5]`. This category assignment is pseudo-random rather than content-derived, resulting in test files (e.g. `AnimalN_xN.mp4`) polluting dataset fixture folders like `anomaly/fighting/` or `anomaly/road_accidents/`.
5. **Legacy Database Tables Remaining in Live Schema:**
   Four legacy tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`) remain in the live Supabase database from a pre-v1 integer-report-id schema. No current codebase references them, but they consume table namespace.
6. **RLS Disabled on Public Tables:**
   Row Level Security is currently disabled across public schema tables, and default Supabase grants permit full DML to `anon` and `authenticated` roles. Backend code exclusively uses the service role key server-side, but restricting `anon` access remains a pending hardening step.

---

## 3. Follow-Ups & Out-of-Scope Items

The following items were identified during schema validation and are deferred to future tasks:

1. **Analysis Schema Unification (Completed 2026-09-25):**
   Unified the analysis schema and prompt across both Gateway Mode and Agent Mode on the native `snake_case` contract defined by `IncidentReport` (see [`.docs/analysis-schema.md`](analysis-schema.md) and [`.docs/decisions.md`](decisions.md)). Relational columns for `title`, `severity_reason`, `timeline`, `uncertainties`, `location` await Option B migration.
2. **Legacy Tables Cleanup:**
   Creating a migration to safely archive or drop the four legacy tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`) once verified that no third-party scripts depend on them.
3. **RLS Policy Implementation:**
   Enabling Row Level Security on all public tables and revoking public/anon DML permissions to enforce service-role-only writes.
4. **Writer Consolidation (Option B):**
   Refactoring analysis persistence so all database writes flow through a single authority (the agent service) rather than dual writers in `incident-console-v2` and `vss-agent`.

---

## 4. Live VM Configuration Snapshot (`kwanz-ws`)

*Verified live read-only over SSH via `.scripts/resolve-ssh-target.sh` on 2026-09-25 01:43:45+08:00 (2026-09-24T17:43:45Z).*

Active configuration inspected in `/srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote`:

| Setting | Live Value on `kwanz-ws` | Notes |
|---|---|---|
| `VSS_APPS_DIR` | `/srv/rise-up/vss/deploy/docker` | Points to docker deployment directory |
| `VSS_DATA_DIR` | `/srv/rise-up/vss-apps-data` | Persistent container volume mounts on host |
| `HOST_IP` | `10.131.1.5` | VM internal network interface IP |
| `EXTERNAL_IP` | `localhost` | Embedded URL host for tunneled browser access |
| `VSS_AGENT_CONFIG_FILE` | `./deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` | Base profile config providing report-generation |
| `REPORT_REFERENCE_BASE_DIR` | `/tmp` | Required by agent evaluation config schema |
| `STREAM_PROCESSOR_HTTP_PORT` | `10000` | Streamprocessing HTTP port (ingress on :30888 proxies /vst/api/v1 and /vst/storage here) |
| `LLM_NAME` | `nvidia/nemotron-3-ultra` | Brev Switchyard model for LLM router and eval judge |
| `VLM_NAME` | `nvidia/cosmos-3-super-reasoner` | Brev Switchyard model for video understanding |
| `LLM_BASE_URL` | `https://switchyard-13doh4lsz.brevlab.com` | Brev inference endpoint (no trailing `/v1`) |
| `VLM_BASE_URL` | `https://switchyard-13doh4lsz.brevlab.com` | Brev inference endpoint (no trailing `/v1`) |
| `LLM_MODEL_TYPE` | `openai` | Required client type for Brev compatibility |
| `VLM_MODEL_TYPE` | `openai` | Required client type for Brev compatibility |
| `OPENAI_API_KEY` | *(Set)* | Brev Switchyard API Key |
| `NVIDIA_API_KEY` | *(Set)* | NGC inference API Key |
| `NGC_CLI_API_KEY` | *(Set)* | NGC container registry authentication key |
| `INCIDENT_SUPABASE_URL` | *(Set)* | Supabase PostgREST endpoint |
| `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | *(Set)* | Supabase Service Role Key |

> [!NOTE]
> On 2026-09-25, the VM `vss-agent` venv was relinked editable to the repository checkout (`services/agent`) with public dependencies (`supabase`, `opencv-python-headless`, `setuptools`). The live agent process was restarted and is actively connected to Brev Switchyard for LLM (`nvidia/nemotron-3-ultra`), VLM (`nvidia/cosmos-3-super-reasoner`), and eval judge inference.

---

## 5. Live Verification Log: Two-Flows End-to-End Test (2026-09-25)

Comprehensive end-to-end verification of `dev-profile-incident` across both analysis modes (**VM / Agent Mode** on `kwanz-ws` and **Local / Gateway Mode** with `mock-backend` + `vlm-gateway`), verifying the unified snake_case analysis contract, distinct model run generation on re-analysis, review status transitions, and storage integrity using `~/Desktop/test2.mp4` (2.3 MB, 5.3s clip):

### 5.1 Verification Checklist & Results

| # | Verification Item | Mode / Scope | Result | Details |
|---|---|---|---|---|
| 1 | **Appliance Stack & Agent Startup** | VM (`kwanz-ws`) | **PASS** | `docker compose -p mdx ps` confirmed 9 appliances up and healthy (`streamprocessing-ms`, `nvstreamer-2d-fusion`, `vst-ingress`, `centralizedb`, `vss-haproxy-ingress`, `redis`, `phoenix`, `kafka`). `vss-agent` restarted on current `main` (`dc878d985`) via `.scripts/native-services.sh` and healthy on port 8000 (`{"value":{"isAlive":true}}`). No `sdr-controller` running. |
| 2 | **Laptop Launcher: VM Mode** | VM (`./start.sh --mode vm`) | **PASS** | SSH preflight passed; backend appliances detected running; SSH tunnel opened (forwarding 8000, 7777, 30081, 30082); console dev server ready on `:3200`. `GET /api/health` returned HTTP 200 `ready`. |
| 3 | **Video Ingestion (VM Mode)** | VM (`test2.mp4`) | **PASS** | `POST /api/uploads` -> VST chunked upload to `:7777` (`sensorId: 18d62a4d-9698-4407-a877-63f74803d134`) -> direct R2 upload via `/api/uploads/r2` (`uploads/18d62a4d-9698-4407-a877-63f74803d134/bf704656-3b88-435b-aaa1-b0c18bd1c73f.mp4`) -> finalized via `POST /api/uploads/complete`. |
| 4 | **Agent Mode Analysis** | VM (`ANALYSIS_MODE=agent`) | **PASS** | `POST /api/analysis` invoked native `vss-agent` on `kwanz-ws` using Brev Switchyard models (`nvidia/nemotron-3-ultra` + `nvidia/cosmos-3-super-reasoner`). Latency: 32s. Valid `IncidentReport` returned: `videoId=v03e884e1dfba65ab953`, `modelRunId=m5b613baff9759dca358`. |
| 5 | **Storage Integrity (VM Mode)** | VM | **PASS** | `videos.filepath` contains R2 key (`uploads/...`), not overwritten by internal VST URL. Rows persisted to `videos`, `model_runs`, `incidents`, `reports`, `entities`, `assets`. |
| 6 | **Re-Analysis (VM Mode)** | VM | **PASS** | Triggered second `POST /api/analysis` on same video. Generated a distinct model run ID (`modelRunId=m0929a3a7bd056d6f247`, `reportId=r747e3d6f8c1a6d671e4`). Both runs remain accessible via `GET /api/reports/v03e884e1dfba65ab953?run=<runId>`. |
| 7 | **Review Workflow (VM Mode)** | VM | **PASS** | `PATCH /api/reports/v03e884e1dfba65ab953/review` transitioned `unreviewed` -> `verified` (`reviewedBy: daniel`). |
| 8 | **Tunnel Teardown & Port Check** | Laptop | **PASS** | VM mode stopped; trap cleanup closed SSH tunnel. Verified local ports 7777, 8000, 3200, 8600 completely released with zero collisions prior to local mode. |
| 9 | **Laptop Launcher: Local Mode** | Local (`./start.sh --mode local`) | **PASS** | Mock backend started on `:7777`, `vlm-gateway` started on `:8600`, console started on `:3200`. Health endpoints on all three services returned healthy (`{"value":{"isAlive":true}}`, `{"status":"ok"}`, `{"status":"ready"}`). |
| 10 | **Video Ingestion (Local Mode)** | Local (`test2.mp4`) | **PASS** | `POST /api/uploads` -> chunked upload to mock VST on `:7777` (`sensorId: sensor-30c7994e0ae95304`, R2 key: `anomaly/road_accidents/test2.mp4`) -> finalized via `POST /api/uploads/complete`. |
| 11 | **Gateway Mode Analysis** | Local (`ANALYSIS_MODE=gateway`) | **PASS** | `POST /api/analysis` called `vlm-gateway` on `:8600` proxying Brev Switchyard (`nvidia/cosmos-3-nano-reasoner`). Latency: 9s. Valid `IncidentReport` returned: `videoId=v2b6a3a3813585476b01`, `modelRunId=m6868a8b2e7d0aea7650`. |
| 12 | **Storage Integrity (Local Mode)** | Local | **PASS** | `videos.filepath` confirmed holding R2 key (`anomaly/road_accidents/test2.mp4`). Rows persisted to `videos`, `model_runs`, `incidents`, `reports`, `entities`, `instruments`, `assets`. |
| 13 | **Re-Analysis (Local Mode)** | Local | **PASS** | Triggered second `POST /api/analysis` on same video. Generated a distinct model run ID (`modelRunId=m907febd09dfb9185af0`, `reportId=rf8821a989f4733f4e25`). Both runs remain accessible via `GET /api/reports/v2b6a3a3813585476b01?run=<runId>`. |
| 14 | **Review Workflow (Local Mode)** | Local | **PASS** | `PATCH /api/reports/v2b6a3a3813585476b01/review` transitioned `unreviewed` -> `verified` (`reviewedBy: daniel`). |
| 15 | **Cross-Flow Consistency** | Both Flows | **PASS** | Both modes produce the identical unified snake_case schema (`title`, `incident_type`, `severity`, `severity_reason`, `confidence`, `duration_seconds`, `timeline`, `persons`, `instruments`, `assets`, `uncertainties`, `location`). Contract parity confirmed across Pydantic model, JSON contract, and Zod parser. |

### 5.2 Excerpts from Live Verification

#### Agent Mode Live Report Excerpt (`v03e884e1dfba65ab953`, `m5b613baff9759dca358`)
- **Model:** `vss-agent` (`nvidia/nemotron-3-ultra` + `nvidia/cosmos-3-super-reasoner` via Brev Switchyard)
- **Title:** "Monkey enters living room, knocks over vase and plays on furniture"
- **Incident Type:** `animal` (Severity: 1, Confidence: 0.95, Duration: 5s)
- **Severity Reason:** "Minor property damage (spilled vase) with no human presence, injuries, or structural damage observed. The monkey's behavior was playful rather than aggressive."
- **Timeline:** 5 items spanning [0.3s-1.4s], [1.4s-2.5s], [2.5s-3.6s], [3.6s-4.7s], [5.0s-5.3s]
- **Persons / Entities:** `[{"description": "Monkey with dark fur and lighter face, agile and playful movements", "actions": "Knocked over vase of sunflowers; jumped between floor, coffee table, and sectional sofa; explored room energetically"}]`
- **Assets:** `Vase of sunflowers` (knocked over), `Sunflowers and greenery` (scattered), `Coffee table` (climbed), `Beige sectional sofa` (climbed)
- **Uncertainties:** "How the monkey entered the residence is not shown", "Whether the monkey caused any damage beyond the spilled vase", "The monkey's origin (pet, escapee, wild) is unknown"
- **Location:** "Residential living room (camera location unspecified)"

#### Gateway Mode Live Report Excerpt (`v2b6a3a3813585476b01`, `m6868a8b2e7d0aea7650`)
- **Model:** `nvidia/cosmos-3-nano-reasoner` (via `vlm-gateway` :8600)
- **Title:** "Cat knocks over vase of sunflowers, scattering flowers and glass on living room floor"
- **Incident Type:** `animal` (Severity: 3, Confidence: 1.0, Duration: 0s)
- **Severity Reason:** "Cat knocks over a vase, causing broken glass and scattered flowers, creating a safety hazard and property damage"
- **Timeline:** 3 items spanning [0.0s-0.3s], [0.3s-2.6s], [2.6s-5.0s]
- **Instruments:** `Vase of sunflowers` (threat level 3), `Coffee table` (threat level 2)
- **Assets:** `Sunflowers` (scattered), `Broken glass` (hazardous), `Living room furniture` (unaffected)
- **Location:** "Indoor living room with large windows and a balcony view"

### 5.3 Bugs Found & Fixed During Implementation
1. **HITL `NotImplementedError` on REST API Endpoint:**
   - *Symptom:* `POST /api/v1/incidents/{id}/analyze` crashed with HTTP 500: `NotImplementedError: No human prompt callback was registered. Unable to handle requested prompt.`
   - *Cause:* `config.yml` enables `hitl_enabled: true`. When called non-interactively via the REST API or console, no callback is registered with NAT's `user_input_manager`.
   - *Fix:* The `/analyze` route passes an internal `skip_hitl=True` through `incident_report_gen` to `video_report_gen`, which then uses the configured VLM prompt with no HITL prompt. Interactive callers still prompt and still raise the missing-callback error. The LVS tools are not on the incident path and are unchanged.
2. **Short-Duration Event Filter Discarding All Events on Short Clips:**
   - *Symptom:* VLM correctly detected monkey activity across 5 consecutive segments, but report extraction returned `"Empty Video Analysis Report - No Incident Detected"`.
   - *Cause:* `_filter_short_duration_from_markdown(min_duration_seconds=2.0)` dropped every segment because `test2.mp4` chunk durations were ~1.1s each (< 2.0s). This stripped all events from the markdown summary passed to the extraction LLM.
   - *Fix:* In `video_report_gen.py`, filter every chunk first; if that would remove 100% of timestamped events across the whole report, fall back to the unfiltered chunks so short clips are preserved. Added unit tests in `test_video_report_gen.py`.


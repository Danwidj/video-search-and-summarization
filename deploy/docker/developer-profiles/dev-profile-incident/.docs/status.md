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
4. **`sdr-controller` Container in Restart Loop:**
   On `kwanz-ws`, the `sdr-controller` Docker container is observed repeatedly exiting and restarting (`Restarting (1)`). It does not block core VIOS video ingestion or agent analysis flows, but produces continuous container restart churn in `docker ps`.
5. **Mock-Backend Hash-Picked `anomaly/<category>` Uploads:**
   `mock-backend/base_profile_mock/.../routers/vst_storage.py` writes uploaded files to `anomaly/<category>/<original filename>` using `_CATEGORIES[sha256(incident_id)[0] % 5]`. This category assignment is pseudo-random rather than content-derived, resulting in test files (e.g. `AnimalN_xN.mp4`) polluting dataset fixture folders like `anomaly/fighting/` or `anomaly/road_accidents/`.
6. **Legacy Database Tables Remaining in Live Schema:**
   Four legacy tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`) remain in the live Supabase database from a pre-v1 integer-report-id schema. No current codebase references them, but they consume table namespace.
7. **RLS Disabled on Public Tables:**
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
> On 2026-09-25, the VM `vss-agent` venv was relinked editable to the repository checkout (`services/agent`) with public dependencies (`supabase`, `opencv-python-headless`, `setuptools`). The live agent process (pid 3721448) was restarted and is actively connected to Brev Switchyard for LLM (`nvidia/nemotron-3-ultra`), VLM (`nvidia/cosmos-3-super-reasoner`), and eval judge inference.

# Incident Profile Decision Log

Chronological log of architectural, technical, and tooling decisions for the Incident Search & Reporting profile (`dev-profile-incident`), newest first. Each entry captures the decision, rationale and constraints, alternatives considered and rejected, and traceable links.

---

### 2026-09-25: Move vss-agent remote LLM and VLM to Brev endpoint (Nemotron 3 Ultra + Cosmos 3 Super Reasoner)
- **Decision:** Switch `vss-agent` remote LLM and VLM from NGC's hosted free tier (`integrate.api.nvidia.com`) to the Brev Switchyard endpoint (`https://switchyard-13doh4lsz.brevlab.com`) with `LLM_NAME=nvidia/nemotron-3-ultra` and `VLM_NAME=nvidia/cosmos-3-super-reasoner` (captain: "the most capable models").
- **Why:** NGC free tier caps at 16 concurrent requests and report generation hangs under load; Brev key provides higher capacity. Config-only switch via LangChain `_type: openai` client (avoids upstream `verify_ssl` HTTP 400 bug in `_type: nim`). Probes on 2026-09-25 passed tool calling (`bind_tools`, 1.89s) and `json_schema` structured output (0.95s) on `nemotron-3-ultra`, and base64 MP4 `video_url` inlining across 5s, 60s, and 60s 1080p (~6MB) clips on `cosmos-3-super-reasoner` without payload rejection or `<think>` tag leakage. Fallback models `nemotron-3-super-120b-a12b` and `nemotron-3-nano-omni` frames also passed.
- **Alternatives rejected:** Cosmos for both LLM and VLM (rejected: cosmos models reject tool calling on Brev with HTTP 400, breaking `/chat`); VLM-only on Brev with LLM on NGC (rejected: both `openai_*` blocks share `OPENAI_API_KEY`, splitting endpoints requires code/config changes to `config.yml`).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`.docs/architecture.md`](architecture.md); [`.docs/incident-profile-operations.md`](incident-profile-operations.md). *(Internal scout and probe reports summarized in place; no API keys included).*

### 2026-09-25: Switch agent evaluation judge (`eval_llm_judge`) to OpenAI client type on Brev
- **Decision:** Change `eval_llm_judge` in `vss-agent` config from `_type: nim` to `_type: openai`, following `LLM_BASE_URL` onto the Brev endpoint using the shared `OPENAI_API_KEY`.
- **Why:** Captain directed using the same Brev endpoint for evaluation rather than NGC. The judge runs only under `nat eval`, never during live `nat serve`.
- **Alternatives rejected:** Retaining `_type: nim` against NGC (rejected: requires maintaining separate `NVIDIA_API_KEY` configuration and risks upstream `verify_ssl` HTTP 400 bugs).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); commit [`5ec2b0e56`](https://github.com/Danwidj/video-search-and-summarization/commit/5ec2b0e56); [`.docs/incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-25: Retire local GPU NIM deployment for LLM and VLM
- **Decision:** Officially retire on-prem GPU NIM container deployment (`dev-profile-incident` local LLM/VLM) and move implementation documentation to `.docs/archive/`.
- **Why:** Remote hosted inference was judged robust enough by the captain; no separate robustness verification was run.
- **Alternatives rejected:** Maintaining dual local-NIM and remote deployment paths (rejected: high operational overhead, complex GPU sizing, and VM VRAM limits).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`.docs/archive/incident-plan-implementation-local.md`](archive/incident-plan-implementation-local.md).

### 2026-09-25: Standardize reference incident report schema on agent snake_case
- **Decision:** Adopt the native `vss-agent` Pydantic model (`IncidentReport` in `services/agent`) with `snake_case` field names as the reference format in `.docs/analysis-schema.md`.
- **Why:** `vss-agent` is the long-term owner of the incident analysis and report lifecycle; aligning console-v2 code is deferred to avoid regressions.
- **Alternatives rejected:** Standardizing on `incident-console-v2`'s `camelCase` schema (rejected: agent is blueprint core; changing agent model causes unnecessary churn in upstream-aligned backend).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`.docs/analysis-schema.md`](analysis-schema.md); [`services/agent/src/vss_agents/data_models/incident_report.py`](file:///Users/danielwidjaja/.config/treehouse/pool/.treehouse/video-search-and-summarization-85c4f2/3/video-search-and-summarization/services/agent/src/vss_agents/data_models/incident_report.py).

### 2026-09-25: Restructure documentation into `.docs/` suite with standing update rule
- **Decision:** Restructure profile documentation into modular files under `.docs/` (`action-plan.md`, `architecture.md`, `data.md`, `analysis-schema.md`, `incident-profile-operations.md`, `archive/`) and establish a standing docs rule in `AGENTS.md`.
- **Why:** Monolithic and legacy plan documents drifted from the live codebase; requiring doc updates in the same PR treats stale documentation as a defect.
- **Alternatives rejected:** Keeping legacy plans at the profile root or documenting ad-hoc across commit messages (rejected: high risk of outdated information and agent disorientation).
- **Links:** [PR #93](https://github.com/Danwidj/video-search-and-summarization/pull/93); [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`AGENTS.md`](file:///Users/danielwidjaja/.config/treehouse/pool/.treehouse/video-search-and-summarization-85c4f2/3/video-search-and-summarization/AGENTS.md).

### 2026-09-25: Make incident-console-v2 analysis schema tolerant and lenient
- **Decision:** Update `incident-console-v2`'s `incidentAnalysisSchema` with Zod transforms to provide safe defaults, clamp numeric ranges, map text severity levels, and passthrough unknown fields.
- **Why:** Raw VLM outputs exhibit structural and type variations (e.g. text severity strings, missing fields, out-of-range confidence); strict validation crashed the UI on analysis responses.
- **Alternatives rejected:** Strict validation throwing on unexpected VLM outputs (rejected: degraded reviewer UX and dropped analysis payloads).
- **Links:** [PR #92](https://github.com/Danwidj/video-search-and-summarization/pull/92); commit [`88204849e`](https://github.com/Danwidj/video-search-and-summarization/commit/88204849e); [`incident-console-v2/lib/analysis/schema.ts`](../incident-console-v2/lib/analysis/schema.ts).

### 2026-09-24: Adopt dual analysis architecture ("Option A") in incident-console-v2 and start.sh
- **Decision:** Support two analysis modes via `start.sh --mode local|vm`: Gateway Mode (`ANALYSIS_MODE=gateway` via local `vlm-gateway`) and Agent Mode (`ANALYSIS_MODE=agent` via native `vss-agent`). In Agent Mode, the agent writes core tables (`incidents`, `entities`, `instruments`, `assets`) while console-v2 writes `reports` and serialized JSON in `model_runs.notes` ("Option A").
- **Why:** Enables fast zero-GPU local frontend testing while preserving full blueprint integration on `kwanz-ws`. Migration to "Option B" (agent owns all machine persistence, unified migrations under `supabase/migrations`) is planned but not started.
- **Alternatives rejected:** Mandating full VM backend for all local UI work (rejected: slows frontend development); immediate migration to Option B (rejected: risky to current delivery milestones).
- **Links:** [PR #88](https://github.com/Danwidj/video-search-and-summarization/pull/88); [PR #89](https://github.com/Danwidj/video-search-and-summarization/pull/89); [PR #90](https://github.com/Danwidj/video-search-and-summarization/pull/90); [`.docs/architecture.md`](architecture.md); [`.docs/data.md`](data.md).

### 2026-09-24: Retire Streamlit incident-console (v1) in favor of Next.js incident-console-v2
- **Decision:** Drop the Streamlit-based `incident-console` from `start.sh` and active development; `incident-console-v2` becomes the sole supported UI.
- **Why:** Reason not recorded - ask captain.
- **Alternatives rejected:** Maintaining Streamlit v1 in parallel with Next.js v2 in `start.sh` (rejected: unnecessary complexity and dual frontend maintenance burden).
- **Links:** [PR #80](https://github.com/Danwidj/video-search-and-summarization/pull/80); commit [`8fd8267ca`](https://github.com/Danwidj/video-search-and-summarization/commit/8fd8267ca); [`start.sh`](../start.sh).

### 2026-09-24: Fall back to direct R2 upload on real VST chunk uploads
- **Decision:** In `incident-console-v2`, when chunked video upload through VST omits a durable R2 storage key (`filePath`), fall back to uploading directly to R2 via server-side route `/api/uploads/r2`.
- **Why:** Real VST/NvStreamer returns empty `filePath` in chunk responses (only mock-backend simulated it); analysis flows require a durable R2 object key.
- **Alternatives rejected:** Modifying proprietary VST/NvStreamer binaries or requiring `vss-agent` changes (rejected: upstream closed binary appliance).
- **Links:** [PR #81](https://github.com/Danwidj/video-search-and-summarization/pull/81); commit [`7e9fb29f9`](https://github.com/Danwidj/video-search-and-summarization/commit/7e9fb29f9); [`incident-console-v2/app/api/uploads/r2/route.ts`](../incident-console-v2/app/api/uploads/r2/route.ts).

### 2026-09-24: Build standalone P1/RP1 evaluation pipeline separately from `nat eval`
- **Decision:** Implement dedicated P1 (structured extraction) and RP1 (report generation) benchmark suite under `eval/` rather than using `vss-agent`'s built-in `nat eval`.
- **Why:** The two evaluate different capabilities: `eval/` benchmarks per-field extraction against tabular ground truth using Hungarian matching, while `nat eval` tests conversational trajectory/QA. Specific choice of separate pipeline: Reason not recorded - ask HengZhengKai.
- **Alternatives rejected:** Adapting `nat eval` for tabular extraction metrics (rejected: lacks Hungarian matching and multi-attribute scoring).
- **Links:** [PR #83](https://github.com/Danwidj/video-search-and-summarization/pull/83); [PR #84](https://github.com/Danwidj/video-search-and-summarization/pull/84); [PR #86](https://github.com/Danwidj/video-search-and-summarization/pull/86); [`eval/`](../eval/).

### 2026-09-23: Dual database engine split (autocommit read engine + transactional write engine)
- **Decision:** Split `IncidentDB` in `incident-console/db.py` into a transactional engine for writes (`self.engine.begin()`) and a separate `AUTOCOMMIT` engine for reads (`self.read_engine.connect()`).
- **Why:** Over psycopg2, default read connections paid pre-ping, `BEGIN`, and `ROLLBACK` round trips (4 RTTs per statement); dedicated `AUTOCOMMIT` read pool cuts wire overhead to 1 RTT per query.
- **Alternatives rejected:** Global autocommit (rejected: breaks atomicity on multi-statement writes); per-checkout autocommit (rejected: still incurs 2 round trips).
- **Links:** [PR #78](https://github.com/Danwidj/video-search-and-summarization/pull/78); commit [`3f395e877`](https://github.com/Danwidj/video-search-and-summarization/commit/3f395e877); [`incident-console/db_connection.py`](../incident-console/db_connection.py).

### 2026-09-23: Batch and cache Dashboard evidence queries
- **Decision:** Replace per-incident evidence queries in `incident-console` with `IncidentDB.list_evidence_batch` executing 3 statements on the read engine, cached via `st.cache_data` (30s TTL).
- **Why:** Iterating queries per incident in Streamlit cost ~440 server round trips per rerun (~14s at 30ms latency); batching by `(incident_id, model_run_id)` pairs eliminates the loop overhead.
- **Alternatives rejected:** Batching on `incident_id` alone (rejected: inadvertently mixes evidence across different model runs).
- **Links:** [PR #76](https://github.com/Danwidj/video-search-and-summarization/pull/76); commit [`fdbe44781`](https://github.com/Danwidj/video-search-and-summarization/commit/fdbe44781); [`incident-console/dashboard_data.py`](../incident-console/dashboard_data.py).

### 2026-09-23: Lazy loading of video previews in Report Review
- **Decision:** Load incident video previews in `pages/2_Report_Review.py` only upon clicking "Load preview", scoped to an `st.fragment` using `st.session_state`.
- **Why:** Streamlit unconditionally mounts and fetches media inside collapsed `st.expander` or unselected `st.tabs`, causing 72 simultaneous network fetches on page render.
- **Alternatives rejected:** Relying on collapsed expanders or unselected tabs for lazy loading (rejected: verified in browser network panel that Streamlit fetches eagerly).
- **Links:** [PR #77](https://github.com/Danwidj/video-search-and-summarization/pull/77); commit [`fd584f8ca`](https://github.com/Danwidj/video-search-and-summarization/commit/fd584f8ca); [`incident-console/pages/2_Report_Review.py`](../incident-console/pages/2_Report_Review.py).

### 2026-09-21: Native service execution for vss-agent and analytics on kwanz-ws
- **Decision:** Run `vss-agent`, `video-analytics-api`, and `behavior-analytics` as native host processes on `kwanz-ws` managed by `.scripts/native-services.sh`, leaving VIOS/VST media and databases in Docker.
- **Why:** Application services undergo rapid development; native execution provides ~2-second process restarts instead of minutes-long Docker container rebuilds. Media engines and storage remain containerized.
- **Alternatives rejected:** Full Docker Compose deployment for all services (rejected: excessive build times and developer iteration friction).
- **Links:** [PR #70](https://github.com/Danwidj/video-search-and-summarization/pull/70); commit [`6bc80f2da`](https://github.com/Danwidj/video-search-and-summarization/commit/6bc80f2da); [`.docs/incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-17: Agent database access via Supabase PostgREST and insert_incident RPC
- **Decision:** Agent accesses Supabase via PostgREST HTTPS client (`incident_db.py` via `supabase-py` `AsyncClient`), utilizing an RPC stored procedure `insert_incident` for atomic upserts and review resets. Console/scripts retain direct Postgres (`db.py`).
- **Why:** Campus network firewall on `kwanz-ws` employs Deep Packet Inspection (DPI) that silently drops outbound raw Postgres traffic on port 5432, breaking `asyncpg`. HTTPS port 443 is unrestricted. PostgREST lacks client-held transactions, requiring server-side RPC for atomic multi-table writes.
- **Alternatives rejected:** Direct `asyncpg`/Postgres driver on `kwanz-ws` (rejected: dropped by campus DPI); SSH tunneling raw port 5432 (rejected: brittle and requires persistent tunnel infrastructure).
- **Links:** [PR #53](https://github.com/Danwidj/video-search-and-summarization/pull/53); [PR #54](https://github.com/Danwidj/video-search-and-summarization/pull/54); [PR #57](https://github.com/Danwidj/video-search-and-summarization/pull/57); [`.docs/data.md`](data.md); [`services/agent/src/vss_agents/utils/incident_db.py`](file:///Users/danielwidjaja/.config/treehouse/pool/.treehouse/video-search-and-summarization-85c4f2/3/video-search-and-summarization/services/agent/src/vss_agents/utils/incident_db.py).

### 2026-09-06: Remote (hosted) LLM/VLM chosen over local GPU NIM deployment
- **Decision:** Configure `dev-profile-incident` to use remote hosted LLM/VLM inference endpoints (`LLM_MODE=remote`, `VLM_MODE=remote`) rather than local GPU NIM containers on `kwanz-ws`.
- **Why:** GPU cost/benefit analysis: running local NIMs consumes an entire 48GB GPU solely for model weights, risking VRAM starvation for VIOS streaming. Hosted endpoints free GPU 1 entirely and keep GPU 0 dedicated to video decode and streaming.
- **Alternatives rejected:** Local NIM deployment across both GPUs (rejected: VRAM saturation, complex hardware profile sizing, and inability to run multi-stream VIOS processing).
- **Links:** [`.docs/archive/incident-plan-implementation-remote.md`](archive/incident-plan-implementation-remote.md) §1; [`.docs/architecture.md`](architecture.md).

### 2026-09-06: MVP1 / MVP2 scope partitioning
- **Decision:** Partition project deliverables into MVP1 (ingestion, automated extraction, human review UI, ground-truth evaluation) and MVP2 (real-time perception RT-CV/RT-Embed, Elasticsearch vector storage, multi-subagent routing, natural language search).
- **Why:** Establishes a verified end-to-end incident analysis baseline before introducing multi-subagent routing and multi-modal vector search. Reason for specific milestone cut: Reason not recorded - ask captain.
- **Alternatives rejected:** Monolithic single-phase delivery implementing search and reporting concurrently (rejected: high integration risk and interdependency bottlenecks).
- **Links:** [`.docs/action-plan.md`](action-plan.md); [`.docs/archive/incident-plan-implementation-shared.md`](archive/incident-plan-implementation-shared.md).

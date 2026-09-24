# Incident Profile Decision Log

Chronological log of architectural, technical, and tooling decisions for the Incident Search & Reporting profile (`dev-profile-incident`), newest first. Each entry captures the date, decision, why (evidence and constraints), alternatives rejected, and traceable links (PR, commit, or doc).

---

### 2026-09-25: Move vss-agent remote LLM and VLM to Brev endpoint (Nemotron 3 Ultra + Cosmos 3 Super Reasoner)
- **Decision:** Switch `vss-agent` remote LLM and VLM from NGC's hosted free tier (`integrate.api.nvidia.com`) to the Brev Switchyard endpoint (`https://switchyard-13doh4lsz.brevlab.com`) with `LLM_NAME=nvidia/nemotron-3-ultra` and `VLM_NAME=nvidia/cosmos-3-super-reasoner` (captain chose "the most capable models").
- **Why:** NGC free tier caps at 16 concurrent requests and report generation hangs on it; Brev key provides higher capacity. Config-only switch via LangChain `_type: openai` client (avoids upstream `verify_ssl` HTTP 400 bug in `_type: nim`). Probes on 2026-09-25 passed tool calling (`bind_tools`, 1.89s) and `json_schema` structured output (0.95s) on `nemotron-3-ultra`, and base64 MP4 `video_url` inlining across 5s, 60s, and 60s 1080p (~6MB) clips on `cosmos-3-super-reasoner` without payload rejection or `<think>` tag leakage. Fallback models `nemotron-3-super-120b-a12b` and `nemotron-3-nano-omni` frames also passed.
- **Alternatives rejected:** Cosmos for both LLM and VLM (rejected: cosmos models reject tool calling on Brev with HTTP 400, breaking `/chat`); VLM-only on Brev with LLM on NGC (rejected: both `openai_*` blocks share `OPENAI_API_KEY`, splitting endpoints requires code/config changes to `config.yml`).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`.docs/architecture.md`](architecture.md); [`.docs/incident-profile-operations.md`](incident-profile-operations.md). *(Internal scout and probe reports summarized in place; no API keys included).*

### 2026-09-25: Switch agent evaluation judge (`eval_llm_judge`) to OpenAI client type on Brev
- **Decision:** Change `eval_llm_judge` in `vss-agent` config from `_type: nim` to `_type: openai`, following `LLM_BASE_URL` onto the Brev endpoint using the shared `OPENAI_API_KEY`.
- **Why:** Captain directed using the same Brev endpoint for evaluation rather than NGC. The judge runs only under `nat eval`, never during `nat serve`.
- **Alternatives rejected:** Keeping judge on NGC pinned to `integrate.api.nvidia.com` (captain directed using the same Brev endpoint, not NGC).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); commit [`5ec2b0e56`](https://github.com/Danwidj/video-search-and-summarization/commit/5ec2b0e56); [`.docs/incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-25: Retire local GPU NIM deployment for LLM and VLM
- **Decision:** Officially retire on-prem GPU NIM container deployment (`dev-profile-incident` local LLM/VLM) and move implementation documentation to `.docs/archive/`.
- **Why:** Remote hosted inference was judged robust enough by the captain; no separate robustness verification was run.
- **Alternatives rejected:** None considered.
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`.docs/archive/incident-plan-implementation-local.md`](archive/incident-plan-implementation-local.md).

### 2026-09-25: Standardize reference incident report schema on agent snake_case
- **Decision:** Adopt the native `vss-agent` Pydantic model (`IncidentReport` in `services/agent`) with `snake_case` field names as the reference format in `.docs/analysis-schema.md`.
- **Why:** The agent is the long-term owner of the report; code alignment for the console is deferred.
- **Alternatives rejected:** Console `camelCase` schema (rejected because agent is the long-term owner of the report).
- **Links:** [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`.docs/analysis-schema.md`](analysis-schema.md); [`services/agent/src/vss_agents/data_models/incident_report.py`](../../../../services/agent/src/vss_agents/data_models/incident_report.py).

### 2026-09-25: Restructure documentation into `.docs/` suite with standing update rule
- **Decision:** Restructure profile documentation into modular files under `.docs/` (`action-plan.md`, `architecture.md`, `data.md`, `analysis-schema.md`, `incident-profile-operations.md`, `archive/`) and establish a standing docs rule in `AGENTS.md`.
- **Why:** Monolithic and legacy plan documents drifted out of date; standing rule in `AGENTS.md` treats stale documentation as a defect and requires updating affected docs in the same PR.
- **Alternatives rejected:** None considered.
- **Links:** [PR #93](https://github.com/Danwidj/video-search-and-summarization/pull/93); [PR #94](https://github.com/Danwidj/video-search-and-summarization/pull/94); [`AGENTS.md`](../../../../AGENTS.md).

### 2026-09-25: Make incident-console-v2 analysis schema tolerant and lenient
- **Decision:** Update `incident-console-v2`'s `incidentAnalysisSchema` with Zod transforms to provide safe defaults, clamp numeric ranges, map text severity levels, and passthrough unknown fields instead of throwing validation errors.
- **Why:** Variations in VLM output or future prompt adjustments crashed the UI with validation errors; lenient defaults and Zod transforms avoid UI crashes.
- **Alternatives rejected:** None considered.
- **Links:** [PR #92](https://github.com/Danwidj/video-search-and-summarization/pull/92); commit [`88204849e`](https://github.com/Danwidj/video-search-and-summarization/commit/88204849e); [`incident-console-v2/lib/analysis/schema.ts`](../incident-console-v2/lib/analysis/schema.ts).

### 2026-09-24: Adopt dual analysis architecture ("Option A") in incident-console-v2 and start.sh
- **Decision:** Support two analysis modes via `start.sh --mode local|vm`: Gateway Mode (`ANALYSIS_MODE=gateway` via local `vlm-gateway`) and Agent Mode (`ANALYSIS_MODE=agent` via native `vss-agent`). In Agent Mode, the agent writes incident rows (`incidents`, `entities`, `instruments`, `assets`) while console-v2 writes `reports` and serialized JSON in `model_runs.notes` ("Option A").
- **Why:** Enables fast zero-GPU local frontend testing while preserving full blueprint integration on `kwanz-ws`.
- **Alternatives rejected:** "Option B" (agent owns all machine output, schema moved into supabase/migrations) is planned, not started.
- **Links:** [PR #88](https://github.com/Danwidj/video-search-and-summarization/pull/88); [PR #89](https://github.com/Danwidj/video-search-and-summarization/pull/89); [PR #90](https://github.com/Danwidj/video-search-and-summarization/pull/90); [`.docs/architecture.md`](architecture.md); [`.docs/data.md`](data.md).

### 2026-09-24: Retire Streamlit incident-console (v1) in favor of Next.js incident-console-v2
- **Decision:** Drop the Streamlit-based `incident-console` from `start.sh` and active development on 2026-09-24; `incident-console-v2` becomes the sole UI.
- **Why:** Slow UI loading, and the UI looked bad; Next.js is better for development (captain, 2026-09-25).
- **Alternatives rejected:** None considered.
- **Links:** [PR #80](https://github.com/Danwidj/video-search-and-summarization/pull/80); commit [`8fd8267ca`](https://github.com/Danwidj/video-search-and-summarization/commit/8fd8267ca); [`start.sh`](../start.sh).

### 2026-09-24: Fall back to direct R2 upload on real VST chunk uploads
- **Decision:** In `incident-console-v2`, when chunked video upload through VST omits a durable R2 storage key (`filePath`), fall back to uploading directly to R2 via server-side route `/api/uploads/r2`.
- **Why:** Real VST/NvStreamer chunk response never includes a durable R2 object key (`filePath`) — only `mock-backend` faked that field — and analysis flows hard-require that key.
- **Alternatives rejected:** None considered.
- **Links:** [PR #81](https://github.com/Danwidj/video-search-and-summarization/pull/81); commit [`7e9fb29f9`](https://github.com/Danwidj/video-search-and-summarization/commit/7e9fb29f9); [`incident-console-v2/app/api/uploads/r2/route.ts`](../incident-console-v2/app/api/uploads/r2/route.ts).

### 2026-09-24: Build standalone P1/RP1 evaluation pipeline separately from `nat eval`
- **Decision:** Implement dedicated P1 (structured extraction) and RP1 (report generation) benchmark suite under `eval/` rather than using `vss-agent`'s built-in `nat eval`.
- **Why:** The two measure different things: `eval/` evaluates per-field extraction accuracy against tabular ground truth, while `nat eval` tests conversational chat trajectory and QA. Why a separate pipeline was chosen: Reason not recorded - ask HengZhengKai.
- **Alternatives rejected:** Reason not recorded - ask HengZhengKai.
- **Links:** [PR #83](https://github.com/Danwidj/video-search-and-summarization/pull/83); [PR #84](https://github.com/Danwidj/video-search-and-summarization/pull/84); [PR #86](https://github.com/Danwidj/video-search-and-summarization/pull/86); [`eval/`](../eval/).

### 2026-09-23: Dual database engine split (autocommit read engine + transactional write engine)
- **Decision:** Split `IncidentDB` in `incident-console/db.py` into a transactional engine for writes (`self.engine.begin()`) and a separate `AUTOCOMMIT` engine for reads (`self.read_engine.connect()`).
- **Why:** The database is remote; default read connections paid four round trips per query (pre-ping, `BEGIN`, statement, `ROLLBACK`). Dedicated `AUTOCOMMIT` read pool cuts wire overhead to 1 RTT per query.
- **Alternatives rejected:** Global AUTOCOMMIT (rejected: not atomic on writes); switching isolation level per checkout on a shared pool (rejected: costs two round trips per read due to SQLAlchemy reset on pool return sending `SET`).
- **Links:** [PR #78](https://github.com/Danwidj/video-search-and-summarization/pull/78); commit [`3f395e877`](https://github.com/Danwidj/video-search-and-summarization/commit/3f395e877); [`incident-console/db_connection.py`](../incident-console/db_connection.py).

### 2026-09-23: Batch and cache Dashboard evidence queries
- **Decision:** Replace per-incident evidence queries in `incident-console` with `IncidentDB.list_evidence_batch` executing 3 statements on the read engine, cached via `st.cache_data` (30s TTL).
- **Why:** Iterating queries per incident in Streamlit cost ~440 server round trips per rerun (~14s at 30ms latency); batching by `(incident_id, model_run_id)` pairs eliminates the loop overhead.
- **Alternatives rejected:** Batching on `incident_id` alone (rejected: inadvertently mixes evidence across different model runs).
- **Links:** [PR #76](https://github.com/Danwidj/video-search-and-summarization/pull/76); commit [`fdbe44781`](https://github.com/Danwidj/video-search-and-summarization/commit/fdbe44781); [`incident-console/dashboard_data.py`](../incident-console/dashboard_data.py).

### 2026-09-23: Lazy loading of video previews in Report Review
- **Decision:** Load incident video previews in `pages/2_Report_Review.py` only upon clicking "Load preview", scoped to an `st.fragment` using `st.session_state`.
- **Why:** Streamlit mounts and executes whatever a run renders even inside a collapsed `st.expander` or unselected `st.tabs` tab, visually hiding content without deferring network fetches.
- **Alternatives rejected:** Visually hiding content in collapsed expanders or unselected tabs (rejected: does not defer fetching in Streamlit).
- **Links:** [PR #77](https://github.com/Danwidj/video-search-and-summarization/pull/77); commit [`fd584f8ca`](https://github.com/Danwidj/video-search-and-summarization/commit/fd584f8ca); [`incident-console/pages/2_Report_Review.py`](../incident-console/pages/2_Report_Review.py).

### 2026-09-21: Native service execution for vss-agent and analytics on kwanz-ws
- **Decision:** Run `vss-agent`, `video-analytics-api`, and `behavior-analytics` as native host processes on `kwanz-ws` managed by `.scripts/native-services.sh`, leaving VIOS/VST media and databases in Docker.
- **Why:** Fast-iterating application services run as native processes directly on `kwanz-ws` so a code change is a ~2s process restart instead of a container rebuild; media/appliance infra stays in Docker. Captain wants services native as much as possible (captain, 2026-09-25).
- **Alternatives rejected:** Docker for everything - rejected (slow rebuild per code change). Running VIOS/VST media engines, DeepStream perception, and core infra (Postgres, Redis, Kafka, Elasticsearch, Phoenix, HAProxy) natively - rejected: an investigation classified them infeasible or no-benefit natively because they depend on proprietary CUDA/GStreamer/DeepStream/Triton container toolchains or are heavy JVM appliances, while vss-agent, video-analytics-api and behavior-analytics are high-feasibility native. All services already use host networking, so native processes reach the Docker ones on localhost.
- **Links:** [PR #70](https://github.com/Danwidj/video-search-and-summarization/pull/70); commit [`6bc80f2da`](https://github.com/Danwidj/video-search-and-summarization/commit/6bc80f2da); [`.docs/incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-17: Agent database access via Supabase PostgREST and insert_incident RPC
- **Decision:** Agent accesses Supabase via PostgREST HTTPS client (`incident_db.py` via `supabase-py` `AsyncClient`), utilizing the stored procedure `insert_incident` Postgres RPC for atomic upserts and review status resets. Console and local tools retain direct Postgres (`db.py`).
- **Why:** The campus network firewall on `kwanz-ws` silently drops outbound port 5432 regardless of destination, breaking raw Postgres drivers like `asyncpg`. HTTPS port 443 works. PostgREST lacks client-held transactions, so atomic delete-then-insert plus review reset requires the `insert_incident` RPC function.
- **Alternatives rejected:** Direct-Postgres / `asyncpg` on `kwanz-ws` (fails because campus firewall drops outbound port 5432). No other alternatives were considered.
- **Links:** [PR #53](https://github.com/Danwidj/video-search-and-summarization/pull/53); [PR #54](https://github.com/Danwidj/video-search-and-summarization/pull/54); [PR #57](https://github.com/Danwidj/video-search-and-summarization/pull/57); [`.docs/data.md`](data.md); [`services/agent/src/vss_agents/utils/incident_db.py`](../../../../services/agent/src/vss_agents/utils/incident_db.py).

### 2026-09-06: Remote (hosted) LLM/VLM chosen over local GPU NIM deployment
- **Decision:** Configure `dev-profile-incident` to use remote hosted LLM/VLM inference endpoints (`LLM_MODE=remote`, `VLM_MODE=remote`) rather than local GPU NIM containers on `kwanz-ws`.
- **Why:** GPU cost/benefit: "running them locally would consume an entire GPU for no reason once a free-tier hosted option exists." Offloading inference frees GPU 1 entirely and keeps GPU 0 dedicated to VIOS video streaming.
- **Alternatives rejected:** Running LLM/VLM locally as NIM containers (rejected: consumes an entire GPU for no reason once a free hosted option exists).
- **Links:** [`.docs/archive/incident-plan-implementation-remote.md`](archive/incident-plan-implementation-remote.md) §1; [`.docs/architecture.md`](architecture.md).

### 2026-09-06: MVP1 / MVP2 scope partitioning
- **Decision:** Partition project deliverables into MVP1 (ingestion, automated extraction, human review UI, ground-truth evaluation) and MVP2 (real-time perception RT-CV/RT-Embed, Elasticsearch vector storage, multi-subagent routing, natural language search).
- **Why:** Scope entirely determined by deadline: MVP1 is due for the mid-term, MVP2 for finals (captain, 2026-09-25).
- **Alternatives rejected:** None considered.
- **Links:** [`.docs/action-plan.md`](action-plan.md); [`.docs/archive/incident-plan-implementation-shared.md`](archive/incident-plan-implementation-shared.md).

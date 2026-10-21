# Incident Search & Reporting Capstone — Architecture

This document describes the system architecture, component topology, deployment mechanics, and
runtime interaction sequences for `dev-profile-incident`.

---

## 1. System Context Architecture

The system spans three runtime tiers:
1. **Developer Laptop:** Hosts the modern frontend (`incident-console-v2`), local API proxies (`vlm-gateway`),
   and base mocks (`mock-backend`).
2. **Shared GPU Workstation (`kwanz-ws` VM):** Runs the heavy video ingestion appliance (VIOS/NvStreamer),
   infrastructure services in Docker, and the fast-iterating AI agent (`vss-agent`) as a native process.
3. **Cloud & External Services:** Cloudflare R2 for durable video storage, Supabase for relational data via
   HTTPS PostgREST, and hosted LLM/VLM inference endpoints (NGC and Brev).

### System Context Diagram

```mermaid
flowchart TB
    subgraph Laptop["Developer Laptop"]
        UI["incident-console-v2<br/>(Next.js App Router, Port 3200)"]
        Gateway["vlm-gateway<br/>(FastAPI Proxy, Port 8600)"]
        Mock["mock-backend<br/>(FastAPI Base Mock, Port 7777)"]
    end

    subgraph Tunnel["SSH Port Forwarding Tunnel"]
        FwdAgent["localhost:8000 -> VM:8000"]
        FwdHAProxy["localhost:7777 -> VM:7777"]
        FwdNIM["localhost:30081/30082 -> VM:30081/30082<br/>(Unused in Brev mode)"]
    end

    subgraph VM["kwanz-ws Shared Workstation"]
        subgraph VMNative["Native Processes (High Feasibility / Fast Restart)"]
            Agent["vss-agent<br/>(NAT Framework, Port 8000)"]
            VideoAnalytics["video-analytics-api<br/>(Optional, Port 8081)"]
            BehaviorAnalytics["behavior-analytics<br/>(Optional, no HTTP port; Kafka consumer)"]
        end

        subgraph VMDocker["Docker Appliances (Proprietary Toolchains / JVM / Infra)"]
            HAProxy["vss-haproxy-ingress<br/>(Port 7777)"]
            VIOSIngress["vss-vios-ingress<br/>(nginx, Port 30888)"]
            StreamProcessing["vss-vios-streamprocessing<br/>(VST storage API, Port 10000; GPU 0)"]
            VIOSSensor["vss-vios-sensor<br/>(Port 30000; GPU 0)"]
            NvStreamer["vss-vios-nvstreamer<br/>(RTSP streamer, Port 31000; GPU 0)"]
            VIOSPostgres["vss-vios-postgres<br/>(Internal DB, Unix socket only)"]
            Redis["redis<br/>(State Cache)"]
            Phoenix["phoenix<br/>(Telemetry, Port 6006)"]
            Kafka["kafka<br/>(Analytics Bus, always started by start.sh)"]
            Elasticsearch["elasticsearch<br/>(Search Index, Optional)"]
            RTVICV["vss-rtvi-cv<br/>(DeepStream Perception, Port 9000, GPU 0, MVP2)"]
            RTVIEmbed["vss-rtvi-embed<br/>(Triton Embeddings, Port 8017, GPU 0, unused in MVP2)"]
        end
    end

    subgraph External["Cloud & Hosted Services"]
        R2[("Cloudflare R2<br/>(Video & Evidence Store)")]
        Supabase[("Supabase Postgres<br/>(HTTPS PostgREST & RPC)")]
        Brev["Brev Lab Switchyard API<br/>(https://switchyard-13doh4lsz.brevlab.com)"]
    end

    %% Laptop connections
    UI -->|Local Mode Inference| Gateway
    UI -->|Local Mode Upload| Mock
    UI -->|VM Mode HTTP /analyze| FwdAgent
    UI -->|VM Mode Video Upload| FwdHAProxy
    UI -->|Direct Upload Fallback & Presigned URLs| R2
    UI -->|REST /rpc/insert_incident| Supabase
    UI -->|/rpc/save_human_report_edit, /rpc/set_review_status| Supabase

    %% Gateway Upstream
    Gateway -->|Bearer Token Auth| Brev

    %% Tunnel Connections
    FwdAgent --> Agent
    FwdHAProxy --> HAProxy

    %% VM Internal Routing
    HAProxy --> VIOSIngress
    VIOSIngress --> StreamProcessing
    VIOSIngress --> VIOSSensor
    Agent -->|Fetch Video Bytes| VIOSIngress
    Agent -->|OpenAI Protocol Inference| Brev
    Agent -->|HTTPS PostgREST & RPC| Supabase
```

### Component Reference Table

| Component | Host | Port | Runtime Type | Primary Source / Owner File | Responsibility |
|---|---|---|---|---|---|
| `incident-console-v2` | Laptop | 3200 | Node.js (Next.js 15 App Router) | `incident-console-v2/` | Primary user interface: video upload, review workflow, eval form, report display |
| `vlm-gateway` | Laptop (or VM) | 8600 | Python (FastAPI / Uvicorn) | `vlm-gateway/app.py` | Holds Brev upstream credential server-side; exposes `/v1/chat/completions` for local mode |
| `mock-backend` | Laptop | 7777 | Python (FastAPI / Uvicorn) | `mock-backend/base_profile_mock/` | Zero-GPU local mock simulating VST upload, streaming, base profile responses, search, and chat |
| `vss-agent` | `kwanz-ws` | 8000 | Python (Native `nat serve`) | `services/agent/` | Core VSS agent: incident analysis, search, and chat workflows (`/api/v1/incidents/{id}/analyze`, `POST /api/v1/incidents/search`, `POST /api/v1/incidents/chat`), tool calling, report persistence; remote inference via Brev |
| `video-analytics-api` | `kwanz-ws` | 8081 | Node.js (Native) | `services/analytics/video-analytics-api/` | Optional MVP2 video analytics ingestion and query layer (`ENABLE_ANALYTICS=true`) |
| `behavior-analytics` | `kwanz-ws` | none (8080 is a HAProxy/label placeholder) | Python (Native) | `services/analytics/behavior-analytics/` | Optional MVP2 behavior perception pipeline (`ENABLE_ANALYTICS=true`) |
| `vss-haproxy-ingress` | `kwanz-ws` | 7777 | Docker container | `deploy/docker/services/infra/haproxy/` | Public reverse proxy on :7777: /api,/chat → vss-agent :8000; /vst,/storage → vss-vios-ingress :30888; /phoenix → :6006; optional analytics/kibana backends |
| `vss-vios-streamprocessing`| `kwanz-ws` | 10000 | Docker container (GPU 0) | `deploy/docker/services/vios/` | VST storage/upload + replay API (receives chunked uploads via the ingress) |
| `vss-vios-nvstreamer` | `kwanz-ws` | 31000 | Docker container (GPU 0) | `deploy/docker/developer-profiles/dev-profile-alerts/compose.yml` | NvStreamer RTSP file streamer (not in the upload path; not routed by ingress/HAProxy) |
| `vss-vios-ingress` | `kwanz-ws` | 30888 | Docker container | `deploy/docker/services/vios/` (foundational) | Nginx VST ingress: /vst/api/v1/sensor → sensor-ms :30000; other /vst/api/v1 and /vst/storage → streamprocessing :10000 |
| `vss-vios-sensor` | `kwanz-ws` | 30000 | Docker (GPU 0) | `deploy/docker/services/vios/initiator/` | VST sensor-ms (sensor registration; /vst/api/v1/sensor via ingress) |
| `vss-vios-postgres` | `kwanz-ws` | none (Unix socket only) | Docker container | `deploy/docker/services/vios/` | VIOS internal database for camera sensors and stream registrations |
| `vss-rtvi-cv` | `kwanz-ws` | 9000 | Docker container (GPU 0) | `deploy/docker/services/rtvi/` | DeepStream perception container for real-time video analytics (MVP2) |
| `vss-rtvi-embed` | `kwanz-ws` | 8017 (→8000) | Docker container (GPU 0, bridged; unused in MVP2) | `deploy/docker/services/rtvi/` | Triton inference server for real-time video embeddings (unused in MVP2; text embeddings and VLM are remote) |
| `redis` | `kwanz-ws` | 6379 (int) | Docker container | Stock compose infra | Message broker and caching layer |
| `phoenix` | `kwanz-ws` | 6006 (int) | Docker container (bridged mdx_default) | Stock compose infra | LLM/VLM telemetry, trace logging, and performance monitoring |
| `kafka` | `kwanz-ws` | 9092 | Docker container | Stock compose infra | Heavy event bus for analytics (always started by start.sh) |
| `elasticsearch` | `kwanz-ws` | Internal | Docker container | Stock compose infra | JVM search index appliance (optional, only with `ENABLE_ANALYTICS=true`) |
| `Supabase` | Cloud | 443 (HTTPS) | Managed PostgREST / Postgres | `supabase/migrations/` (finals); `supabase/midterm/` (frozen record) | Relational store for reports, incidents, evidence, reviews, and ground truth. One project per phase: see [Two Supabase projects](#two-supabase-projects-one-per-phase) |
| `Cloudflare R2` | Cloud | 443 (HTTPS) | S3-Compatible Object Store | `incident-console-v2/lib/r2/` | Canonical persistent object storage for video clips and screenshots |
| `Brev Switchyard` | Cloud | 443 (HTTPS) | Remote Switchyard Proxy | Upstream endpoint | Hosted VLM/LLM inference used by both `vss-agent` (VM) and `vlm-gateway` (laptop) |

### Native vs. Docker Service Split Policy

**Policy Rule:** Run a service natively whenever feasible.

Services are split based on feasibility:
- **Native Processes (High Feasibility):** `vss-agent` (Python/uv), `video-analytics-api` (Node.js), and `behavior-analytics` (Python). Running natively eliminates Docker image rebuilds on code changes (~2s process restart vs multi-minute container build).
- **Docker Appliances (Infeasible Natively):** Media engines and perception services (`vss-vios-streamprocessing`, `vss-vios-nvstreamer`, `vss-vios-ingress`, `vss-vios-sensor`, `vss-vios-postgres`, `vss-rtvi-cv`, `vss-rtvi-embed`). These depend on proprietary CUDA, GStreamer, DeepStream, or Triton container toolchains; host installation is infeasible.
- **Docker Appliances (No Benefit / JVM):** Infrastructure appliances (`redis`, `kafka`, `elasticsearch`, `phoenix`, `vss-haproxy-ingress`). Standard prebuilt containers or heavy JVM runtimes where native execution provides no development benefit.
- **Networking:** Nearly all containers use host networking (`network_mode: host`); exceptions are `phoenix` (bridge `mdx_default`, published 6006:6006) and `vss-rtvi-embed` (published `${RTVI_EMBED_PORT}`=8017→8000). Native processes reach all of them on `localhost`.

---

## 2. Deployment & Connectivity

The one-command entry point for setting up and launching the system is `start.sh` (`./start.sh --mode local` or `./start.sh --mode vm`), executed directly from developer laptops. It automates backend checks, self-healing service deployment, port tunneling, and UI initialization.

```mermaid
flowchart TD
    Start["./start.sh --mode local|vm"] --> CheckMode{Mode?}

    %% Local Mode Path
    CheckMode -->|local| StartMock["Start mock-backend (127.0.0.1:7777)"]
    StartMock --> StartGateway["Start vlm-gateway (127.0.0.1:8600)"]
    StartGateway --> LocalInit["Export INCIDENT_AGENT_BASE_URL=http://127.0.0.1:7777,<br/>VLM_GATEWAY_URL=http://127.0.0.1:8600,<br/>ANALYSIS_MODE=gateway"]
    LocalInit --> RunV2Local["Launch incident-console-v2 (Port 3200)"]

    %% VM Mode Path
    CheckMode -->|vm| Preflight["SSH Preflight & IP Detection<br/>(.scripts/vm-preflight.sh)"]
    Preflight --> CheckSSH["Check VM State via SSH<br/>(docker compose ps & native-services.sh status)"]
    CheckSSH --> StateDecision{Deploy State?}
    
    StateDecision -->|Nothing Running| FreshDeploy["Deploy Docker Appliances over SSH (.scripts/vm-ensure-docker.sh)<br/>Start Native Services via native-services.sh"]
    StateDecision -->|Partial State| SelfHeal["Self-Heal: Start only missing Docker & Native services"]
    StateDecision -->|All Running| Ready["Backend Ready"]
    
    FreshDeploy --> OpenTunnel
    SelfHeal --> OpenTunnel
    Ready --> OpenTunnel

    OpenTunnel["Open backgrounded SSH tunnel (inline in start.sh; same forwards as .scripts/tunnel.sh)<br/>8000, 7777, 30081, 30082<br/>then wait for localhost:8000/health"] --> CheckConsole{--no-console?}
    CheckConsole -->|yes| Hold["Hold tunnel open (wait)"]
    CheckConsole -->|no| VMInit["Export INCIDENT_AGENT_BASE_URL=http://localhost:8000,<br/>ANALYSIS_MODE=agent"]
    VMInit --> RunV2VM["Launch incident-console-v2 (Port 3200)"]
```

### SSH Tunnel Port Forwards

When running in VM mode, `start.sh` opens a backgrounded SSH tunnel (the standalone equivalent is `.scripts/tunnel.sh`) forwarding the following
ports from `localhost` to `kwanz-ws` (`<vm-ip>`, detected dynamically via `ip -4 route get 1.1.1.1`, fallback `10.131.1.5`, currently `10.132.56.251`):

| Local Port | Remote Destination | Target Service | Usage |
|---|---|---|---|
| `8000` | `127.0.0.1:8000` (loopback) | Native `vss-agent` | Agent REST API (`/health`, `POST /api/v1/incidents/{id}/analyze`, `POST /api/v1/incidents/search`) |
| `7777` | `<vm-ip>:7777` | `vss-haproxy-ingress` | VIOS/NvStreamer chunked upload and video storage API |
| `30081` | `<vm-ip>:30081` | LLM NIM Endpoint | Unused in remote (Brev) mode — nothing listens on the VM; only meaningful if a local LLM NIM is deployed |
| `30082` | `<vm-ip>:30082` | VLM NIM Endpoint | Unused in remote (Brev) mode — nothing listens on the VM; only meaningful if a local VLM NIM is deployed |

### Two Supabase projects (one per phase)

| Project | Role | Schema | Access |
|---|---|---|---|
| **Finals** (new project, same organisation and region as midterm) | The live database every service uses | [`supabase/migrations/`](../supabase/README.md): the finals baseline, then later finals migrations | `service_role` (PostgREST) and `postgres` (direct DSN) only; RLS on everything; the public key reaches nothing |
| **Midterm** (`rfevukimyftzbxlehwel`) | Frozen record of the midterm phase | [`supabase/midterm/`](../supabase/midterm/README.md) (archive; never pushed) | Read-only after the freeze: `service_role` reads and runs the read RPCs, every write fails, direct-DSN sessions are read-only, `anon` is locked out |

Finals is built from the baseline and filled once from midterm by `supabase/copy/copy_midterm_to_finals.py` (one-way; [`../supabase/README.md`](../supabase/README.md)). **R2 is shared:** both projects name the same bucket and keys, so no object is copied and no R2 setting changes. A delete in finals removes R2 objects that the midterm record still names; that is accepted for a record.

What points at the database, and how it switches at the cutover:

| Where | Settings | Read by | How it switches |
|---|---|---|---|
| `dev-profile-incident/.env.local` on each laptop (symlinked into `incident-console/`, `incident-console-v2/`, `vlm-gateway/`, `mock-backend/`) | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`, `INCIDENT_DB_DSN` | Console, eval, mock backend in local mode, the copy and parity scripts | Each teammate sets the 3 finals values |
| `.env.local` copies in other worktrees | same | Console or eval started from those worktrees | `.githooks/setup-worktree.sh` never overwrites an existing copy, so old worktrees keep midterm values: refresh or delete them. The freeze makes a stale one fail loudly |
| `generated.env.remote` on `kwanz-ws` | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | Native `vss-agent` (search, chat, standalone persistence); the evidence loader (`scripts/backfill_official_timestamps.py`); `.scripts/native-services.sh` | Back up, set the two finals values, restart `vss-agent` ("ask first"; [`incident-operate-vm`](../skills/incident-operate-vm/SKILL.md)) |
| `deploy/docker/services/agent/compose.yml` | `INCIDENT_SUPABASE_*` passthrough | The Docker `vss-agent` (not used; the native one owns :8000) | Nothing |
| `eval/` | `INCIDENT_DB_DSN` or `INCIDENT_SUPABASE_*` from the same `.env.local` | P1/RP1 batch, ground-truth ingest | Same `.env.local`; `init_schema()` is a no-op on finals (every table exists) |

The agent only **warns** when it cannot record a search query, so an agent still pointed at midterm keeps answering searches and silently loses the query logs: check that `queries` grows on finals after the switch. The cutover steps, checklist and rollback are in the [`incident-manage-database`](../skills/incident-manage-database/SKILL.md) skill.

---

## 3. Remote LLM/VLM Deployment Facts (Brev Switchyard & Remote Inference)

The VM deployment runs LLM, VLM, and evaluation judge inference against Brev Switchyard (`https://switchyard-13doh4lsz.brevlab.com`). There are no local NIM inference containers on `kwanz-ws`.

Live values are in [`status.md`](status.md); the full procedure for editing `generated.env.remote` is in [`incident-profile-operations.md`](incident-profile-operations.md).

### Inference Rules & Requirements

1. **Client Type Rule:** Use `_type: openai` for remote inference models, **never** `_type: nim`. The `nim_langchain` client leaks proprietary parameters (such as `verify_ssl`) into the HTTP JSON request body, which triggers HTTP 400 Bad Request errors on standard OpenAI-compatible endpoints.
2. **Model Selection Rules:**
   - **LLM (`nvidia/nemotron-3-ultra`):** Must support OpenAI tool calling (`bind_tools`) for `top_agent` and `json_schema` structured output for incident reporting. Also serves as `eval_llm_judge`.
   - **VLM (`nvidia/cosmos-3-super-reasoner`):** Must support base64 MP4 `video_url` inlining (`data:video/mp4;base64,...`) and frame-by-frame JPEG extraction.
3. **URL Format Rule:** Set `*_BASE_URL` without a trailing `/v1` (`https://switchyard-13doh4lsz.brevlab.com`). Agent and LangChain client instantiations append `/v1` automatically.
4. **Authentication Rule:** Set `OPENAI_API_KEY` to the Brev Switchyard key; it is shared across LLM, VLM, and `eval_llm_judge`.
5. **GPU Device Allocation:** All VSS services and Docker appliances (`nvstreamer`, `streamprocessing-ms`, `sensor-ms`, `vss-rtvi-cv`, and `vss-rtvi-embed`) are pinned strictly to GPU 0 (`device_ids=['0']`, `NVIDIA_VISIBLE_DEVICES=0`, `CUDA_VISIBLE_DEVICES=0`, `RT_CV_DEVICE_ID=0`, `RT_EMBED_DEVICE_ID=0`, `RTVI_EMBED_NVIDIA_VISIBLE_DEVICES=0`), leaving GPU 1 completely untouched for co-tenant training workloads on `kwanz-ws`. `vss-rtvi-embed` is pinned to GPU 0 for safety but is not used in MVP2 (MVP2 uses remote `nvidia/llama-nemotron-embed-vl-1b-v2` text embeddings and remote Brev VLM). No local LLM/VLM NIM uses either GPU in remote mode.

---

## 4. Runtime Interaction Sequences

### Console middle layer (ports and adapters)

`incident-console-v2` reaches Supabase through a hexagonal middle layer ([`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md)):

```
components/*.tsx --fetch /api--> app/api/**/route.ts --> lib/application/* (multi-step use cases)
                                         |                       |
                                         +-----> lib/ports/* <---+   (domain types + port interfaces)
                                                      ^
                                     lib/adapters/supabase/* (getDbAdapters, mappers) --> lib/postgrest/client.ts --> PostgREST
```

- Routes depend on ports only and get adapters from `getDbAdapters()` / `getDbHealth()` (`lib/adapters/supabase/index.ts`). Only the adapters know table names, filters, RPC argument names and snake_case columns. The adapters and `lib/adapters/supabase/mappers/` map rows and RPC JSON field by field into camelCase domain types (one run's report rows, the report library, the dashboard) and database refusals into `StoreRejection`.
- Report detail, review status changes and delete go through `lib/application/reports.ts` (`getReport`, `changeReviewStatus`, `deleteReport`); R2 signing and deletion are passed in as functions. A run's report is read from the `effective_incidents/entities/instruments/assets` views (the reviewer version when the run has one, else the AI's), and a review change is one `set_review_status` call. A refusal by `set_review_status` or `save_human_report_edit` (for example verifying a legacy AI report that must be edited first) becomes a `StoreRejection`, which the route returns as 422 with the database's reason. Health, the dashboard, the report library, the videos list, official selection and edit call a port directly; the report library route signs thumbnails itself.
- `EvidenceSearchRepository` is defined for MVP2 search; its planned adapter calls the vss-agent's `POST /api/v1/incidents/search`.
- Not yet behind the ports (listed in §7 of [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md#7-deferred-in-this-round)): ground truth, analysis saving and run history (`/api/analysis`, `/api/videos/[videoId]/runs`, `lib/analysis/*`).

### Report library pagination and deferred report loading

```mermaid
sequenceDiagram
    actor User as Reviewer
    participant UI as /reports
    participant API as Next.js /api/reports
    participant DB as Supabase RPC
    participant R2 as Cloudflare R2

    User->>UI: Open library or change metadata/evidence filter
    UI->>API: GET summaries (page size 6; entity/instrument/asset terms)
    API->>DB: list_incident_report_summaries(...) (IncidentRepository.listReports)
    DB-->>API: 6 summaries + total count
    API->>R2: Sign up to 6 derived thumbnail keys
    API-->>UI: Metadata + small thumbnail URLs (no video URL)
    UI-->>User: Lazy screenshot images or skeleton fallback
    User->>UI: Open one report
    UI->>API: GET /api/reports/videoId?run=modelRunId
    API->>DB: Read selected report graph (IncidentRepository.getRunReport)
    API->>R2: Create selected object's signed URL
    API-->>UI: Full report + playback URL
```

Date inputs are directly editable: entering either boundary activates the custom range automatically. Preset
selection clears stale custom boundaries, and the date/time row has an explicit reset that clears both date and
time constraints. The API forwards inclusive day boundaries, optional time-of-day bounds, and the viewer's detected timezone to the summary RPC.

### Dashboard analytics and cross-filtering

`GET /api/dashboard` calls the service-role-only `get_incident_dashboard` RPC through `DashboardRepository.getDashboard`. It counts **official incidents only**: one per video, through the video's explicitly selected official report (D6).
- Videos with reports but no official one ("awaiting official report"), videos without any report, and all uploaded videos are counted separately, all time, and link to the matching `/videos` lists.
- Evidence statistics are canonical entity types plus normalised instrument and asset names, counted per distinct incident.
- Model coverage counts every analysis attempt in the period by outcome.
- Every other number links to `/reports?scope=official&...` with the same period and filters, using `match=exact` for instrument and asset names, so the reports total equals the clicked number. The URL is the reports page's filter state.
- The period window is computed in the browser after mount and sent as zoneless UTC; the API reads it as UTC.
- The heatmap and weekday/hour cross-filters use the viewer's local time: `GET /api/dashboard` forwards the browser's detected `timezone` (e.g. `America/New_York`) to `p_timezone`, which groups and filters `generated_datetime` in that zone. `/reports` detects the same zone itself, so drill-down links carry no timezone and the totals still match.

### Structured (Class A) report editing

`Edit report` opens a side-by-side editor: the original model output read-only on the left, and the structured fields on the right.
- **Editable:** incident type, start/end seconds, summary, severity level, and entities, instruments (with holder and threat level) and assets. IDs are renumbered by position; each item sends the AI item it came from as `source_id` (null for an item the reviewer added), so a delete or reorder never relinks it to the AI item that now has its number.
- **Model-generated, never editable:** title, severity rationale, location, timeline and uncertainties.
- **Provenance:** never editable.

`PATCH /api/reports/[videoId]/edit` rejects Class B/C keys (400), validates the edit against the contract's own sub-schemas and ID/holder/window rules (422), then calls `save_human_report_edit`. In one transaction that function saves the run's reviewer version (`human_reports` and its items; created on the first edit, `revision` +1 per save) and stamps `review_status.edited_by/edited_at`; an edit of a verified report sends it back to `under review` and clears the verifier. It never touches the AI rows or `model_runs.notes`. The console calls it directly, not the `apply_structured_report_edit` shim the finals database keeps for older consoles.

`PATCH /api/reports/[videoId]/review` calls `set_review_status`, one transaction that never writes `edited_by/edited_at` (they mean the last content edit). Verifying a report with no reviewer version first copies the AI report into one, so every verified report has a reviewer version.

The report then shows "Reviewer-edited after generation", "Model assessed N/5; reviewer set M/5" beside the model severity rationale, and the model's original window beside a reviewer-set one.

### Run history, re-analysis and official report

- **Video history.** A video is the parent of its analyses. `GET /api/videos/[videoId]/runs` builds the history from two sources:
  - runs with an incident for the video;
  - incident-less attempt records whose notes explicitly name the video: failed attempts, and runs whose report was deleted.

  Each entry shows model, time, outcome, failure reasons or repair operations, and any additional instruction. Its type and severity come from `effective_incidents`, so a reviewer's edit shows there as on the report page. Failed attempts are never reports.
- **Re-analysis.** `POST /api/videos/[videoId]/runs {model, additionalInstruction?}` re-analyses the stored R2 object:
  - the same canonical request, strict validation and ID-only recovery as an upload;
  - always a new run;
  - it never writes the `videos` row (the upload time is kept);
  - it never selects the official report.
- **Official report.** `PUT/DELETE /api/videos/[videoId]/official` calls `select_official_report` / `clear_official_report`, used from the report page and the video history.
- **Where it appears:** pages `/videos`, `/videos/[id]` and `/videos/[id]/ground-truth`. The report page's analysis card combines re-analysis with a compact history.

### Sequence A: Upload, Analysis & Reporting in Gateway Mode (`ANALYSIS_MODE=gateway`)

*Zero-GPU local development flow using `vlm-gateway` and Cloudflare R2, on `incident-contract-v3`.*

```mermaid
sequenceDiagram
    autonumber
    actor User as Reviewer (Browser)
    participant UI as incident-console-v2 (Next.js)
    participant VST as VST / NvStreamer (Mock 7777)
    participant R2 as Cloudflare R2 Bucket
    participant Gateway as vlm-gateway (Port 8600)
    participant Brev as Brev Switchyard API
    participant DB as Supabase PostgREST & RPC

    User->>UI: Choose a model (allowlist from contracts/inference.json), then a video
    UI->>VST: POST /api/v1/videos, chunked upload, complete (via /api/uploads*)
    alt Chunk response lacks a valid R2 key (real VST)
        UI->>R2: PutObject + HeadObject via /api/uploads/r2
    else Mock backend returns its durable R2 key
        VST->>R2: PutObject (uploads/<sensorId>/<uuid><ext>)
    end
    UI->>UI: POST /api/analysis {sensorId, filepath, filename, model}
    UI->>R2: HeadObject (object must exist and be nonempty)
    UI->>DB: Insert videos row if absent (upload lifecycle; never updated later)
    UI->>UI: Sign R2 GET URL; build P1 request = eval P1 (video, canonical prompt, strict response_format, 16384 tokens, 64 frames)
    UI->>Gateway: POST /v1/chat/completions (per-model timeout)
    Gateway->>Brev: Forward with Bearer auth (VLM_GATEWAY_TIMEOUT_SECONDS)
    Brev->>R2: GET video via presigned URL
    Brev-->>Gateway: Completion
    Gateway-->>UI: Completion
    UI->>UI: Strict parse + schema + cross-field rules; id-normalization-v1 only if every violation is ID-only, then re-validate
    alt valid_first_pass / valid_after_structural_repair
        UI->>DB: model_runs (immutable notes: request, raw response, validation, repair, report)
        UI->>DB: /rpc/insert_incident, entities (E#), instruments (I#, holder), assets (A#), reports
        UI->>DB: Read back and verify
        UI-->>User: Redirect to /reports/[videoId]?run=[modelRunId]
    else contract_failed / request_failed
        UI->>DB: model_runs attempt record only (no incident/report/review/evidence rows)
        UI-->>User: 422 / 502 / 504 with the reason; the attempt appears in the video's history
    end
```

---

### Sequence B: Upload, Analysis & Reporting in Agent Mode (`ANALYSIS_MODE=agent`)

*Full blueprint integration connecting laptop UI to native `vss-agent` on `kwanz-ws`.*

```mermaid
sequenceDiagram
    autonumber
    actor User as Reviewer (Browser)
    participant UI as incident-console-v2 (Next.js)
    participant Tunnel as SSH Tunnel (:7777 / :8000)
    participant VIOS as HAProxy :7777 → vss-vios-ingress :30888 → VST streamprocessing :10000
    participant R2 as Cloudflare R2 Bucket
    participant Agent as vss-agent (:8000)
    participant Brev as Brev Switchyard API
    participant DB as Supabase PostgREST & RPC

    User->>UI: Select and upload video clip
    UI->>UI: POST /api/uploads
    UI->>Tunnel: POST localhost:8000/api/v1/videos (INCIDENT_AGENT_BASE_URL)
    Tunnel->>Agent: Forward /api/v1/videos
    Agent-->>UI: upload url (http://localhost:7777/vst/api/v1/storage/file)

    UI->>Tunnel: Single-request chunked upload to localhost:7777
    Tunnel->>VIOS: Forward chunked upload (mediaFile, filename, nvstreamer-* headers)
    VIOS-->>UI: Sensor registration (sensorId)

    %% R2 Fallback
    UI->>UI: POST /api/uploads/r2
    UI->>R2: PutObject (uploads/<sensorId>/<uuid><ext>)
    R2-->>UI: Durable R2 object key
    UI->>R2: HeadObject (exact uploaded byte length required)

    UI->>Tunnel: POST localhost:8000/api/v1/videos/{sensorId}/complete
    Tunnel->>Agent: Forward complete (fetches timeline & storage URL)

    UI->>UI: Trigger POST /api/analysis
    UI->>R2: HeadObject (object must exist and be nonempty)
    UI->>DB: Upsert videos (id, filepath=R2 key, source=sensorId)
    UI->>UI: Sign 1-hour R2 GET URL locally

    UI->>Tunnel: POST localhost:8000/api/v1/incidents/[id]/analyze {model_run_id, video_url, skip_rp1: true}
    Tunnel->>Agent: Forward analyze request

    Agent->>Brev: P1 (video URL first, contract prompt, strict response_format) - same call as gateway mode
    Brev->>R2: GET video via presigned URL
    Brev-->>Agent: Schema-constrained JSON
    Agent->>Agent: Strict parse under core-scored-v1 (+ id-normalization-v1), derive duration; core violation -> 422 with raw_output
    Note over Agent,Brev: skip_rp1 - no RP1 call, like gateway mode (standalone calls run RP1)
    Note over Agent,DB: With model_run_id the agent writes nothing - the console records the run

    Agent-->>Tunnel: Return {report, report_text, model, contract_version, raw_output, finish_reason}
    Tunnel-->>UI: Forward agent response

    UI->>UI: Strict parse + schema + cross-field rules under policy core-scored-v1; id-normalization-v1 only if needed
    alt valid_first_pass / valid_after_structural_repair
        UI->>DB: model_runs (immutable notes: request, raw response, validation, repair, report)
        UI->>DB: /rpc/insert_incident, entities (E#), instruments (I#, holder), assets (A#), reports
        UI->>DB: Read back and verify
        UI-->>User: Redirect to /reports/[videoId]?run=[modelRunId]
    else contract_failed / request_failed
        UI->>DB: model_runs attempt record only (no incident/report/review/evidence rows)
        UI-->>User: 422 / 502 / 504 with the reason; the attempt appears in the video's history
    end
```

---

### Sequence C: Natural Language Video Search & Conversational Chat (MVP2)

*Authoritative specification, sequence, and data flow: [`mvp2/README.md`](mvp2/README.md) and [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/).*

> [!NOTE]
> MVP2 shifted from real-time perception/Elasticsearch indexing to a hybrid pipeline combining VLM extraction (`incident-contract-v3`), object cropping through a detector port (today the remote VLM; local open-vocabulary detectors are evaluated in [`mvp2/eval.md`](mvp2/eval.md)), Supabase `pgvector` (`evidence_crops`), conversational Q&A (`chat-contract-v1`), and an always-on VLM critic (`query_results`). See [`mvp2/README.md`](mvp2/README.md) for the authoritative architecture and end-to-end data flow.

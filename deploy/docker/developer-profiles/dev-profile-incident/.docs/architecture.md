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
            StreamProcessing["vss-vios-streamprocessing<br/>(VST storage API, Port 10000; all GPUs visible)"]
            VIOSSensor["vss-vios-sensor<br/>(Port 30000)"]
            NvStreamer["vss-vios-nvstreamer<br/>(RTSP streamer, Port 31000; GPU 0)"]
            VIOSPostgres["vss-vios-postgres<br/>(Internal DB, Unix socket only)"]
            Redis["redis<br/>(State Cache)"]
            Phoenix["phoenix<br/>(Telemetry, Port 6006)"]
            Kafka["kafka<br/>(Analytics Bus, always started by start.sh)"]
            Elasticsearch["elasticsearch<br/>(Search Index, Optional)"]
            RTVICV["vss-rtvi-cv<br/>(DeepStream Perception, Port 9000, MVP2)"]
            RTVIEmbed["vss-rtvi-embed<br/>(Triton Embeddings, Port 8017, GPU 1, MVP2)"]
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
| `mock-backend` | Laptop | 7777 | Python (FastAPI / Uvicorn) | `mock-backend/base_profile_mock/` | Zero-GPU local mock simulating VST upload, streaming, and base profile responses |
| `vss-agent` | `kwanz-ws` | 8000 | Python (Native `nat serve`) | `services/agent/` | Core VSS agent: incident analysis workflow, tool calling, report persistence; remote inference via Brev |
| `video-analytics-api` | `kwanz-ws` | 8081 | Node.js (Native) | `services/analytics/video-analytics-api/` | Optional MVP2 video analytics ingestion and query layer (`ENABLE_ANALYTICS=true`) |
| `behavior-analytics` | `kwanz-ws` | none (8080 is a HAProxy/label placeholder) | Python (Native) | `services/analytics/behavior-analytics/` | Optional MVP2 behavior perception pipeline (`ENABLE_ANALYTICS=true`) |
| `vss-haproxy-ingress` | `kwanz-ws` | 7777 | Docker container | `deploy/docker/services/infra/haproxy/` | Public reverse proxy on :7777: /api,/chat → vss-agent :8000; /vst,/storage → vss-vios-ingress :30888; /phoenix → :6006; optional analytics/kibana backends |
| `vss-vios-streamprocessing`| `kwanz-ws` | 10000 | Docker container (nvidia runtime, all GPUs) | `deploy/docker/services/vios/` | VST storage/upload + replay API (receives chunked uploads via the ingress) |
| `vss-vios-nvstreamer` | `kwanz-ws` | 31000 | Docker container (GPU 0) | `deploy/docker/developer-profiles/dev-profile-alerts/compose.yml` | NvStreamer RTSP file streamer (not in the upload path; not routed by ingress/HAProxy) |
| `vss-vios-ingress` | `kwanz-ws` | 30888 | Docker container | `deploy/docker/services/vios/` (foundational) | Nginx VST ingress: /vst/api/v1/sensor → sensor-ms :30000; other /vst/api/v1 and /vst/storage → streamprocessing :10000 |
| `vss-vios-sensor` | `kwanz-ws` | 30000 | Docker (nvidia runtime) | `deploy/docker/services/vios/initiator/` | VST sensor-ms (sensor registration; /vst/api/v1/sensor via ingress) |
| `vss-vios-postgres` | `kwanz-ws` | none (Unix socket only) | Docker container | `deploy/docker/services/vios/` | VIOS internal database for camera sensors and stream registrations |
| `vss-rtvi-cv` | `kwanz-ws` | 9000 | Docker container (GPU 0) | `deploy/docker/services/rtvi/` | DeepStream perception container for real-time video analytics (MVP2) |
| `vss-rtvi-embed` | `kwanz-ws` | 8017 (→8000) | Docker container (GPU 1, bridged) | `deploy/docker/services/rtvi/` | Triton inference server for real-time video embeddings (MVP2) |
| `redis` | `kwanz-ws` | 6379 (int) | Docker container | Stock compose infra | Message broker and caching layer |
| `phoenix` | `kwanz-ws` | 6006 (int) | Docker container (bridged mdx_default) | Stock compose infra | LLM/VLM telemetry, trace logging, and performance monitoring |
| `kafka` | `kwanz-ws` | 9092 | Docker container | Stock compose infra | Heavy event bus for analytics (always started by start.sh) |
| `elasticsearch` | `kwanz-ws` | Internal | Docker container | Stock compose infra | JVM search index appliance (optional, only with `ENABLE_ANALYTICS=true`) |
| `Supabase` | Cloud | 443 (HTTPS) | Managed PostgREST / Postgres | `supabase/migrations/` | Relational store for reports, incidents, evidence, reviews, and ground truth |
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
    CheckMode -->|vm| CheckSSH["Check VM State via SSH<br/>(docker compose ps & native-services.sh status)"]
    CheckSSH --> StateDecision{Deploy State?}
    
    StateDecision -->|Nothing Running| FreshDeploy["Deploy Docker Appliances over SSH<br/>Start Native Services via native-services.sh"]
    StateDecision -->|Partial State| SelfHeal["Self-Heal: Start only missing Docker & Native services"]
    StateDecision -->|All Running| Ready["Backend Ready"]
    
    FreshDeploy --> OpenTunnel
    SelfHeal --> OpenTunnel
    Ready --> OpenTunnel

    OpenTunnel["Open backgrounded SSH tunnel (inline in start.sh; same forwards as .scripts/tunnel.sh)<br/>8000, 7777, 30081, 30082<br/>then wait for localhost:8000/health"] --> VMInit["Export INCIDENT_AGENT_BASE_URL=http://localhost:8000,<br/>ANALYSIS_MODE=agent"]
    VMInit --> RunV2VM["Launch incident-console-v2 (Port 3200)"]
```

### SSH Tunnel Port Forwards

When running in VM mode, `start.sh` opens a backgrounded SSH tunnel (the standalone equivalent is `.scripts/tunnel.sh`) forwarding the following
ports from `localhost` to `kwanz-ws` (`10.131.1.5`):

| Local Port | Remote Destination | Target Service | Usage |
|---|---|---|---|
| `8000` | `10.131.1.5:8000` | Native `vss-agent` | Agent REST API (`/health`, `POST /api/v1/incidents/{id}/analyze`) |
| `7777` | `10.131.1.5:7777` | `vss-haproxy-ingress` | VIOS/NvStreamer chunked upload and video storage API |
| `30081` | `10.131.1.5:30081` | LLM NIM Endpoint | Unused in remote (Brev) mode — nothing listens on the VM; only meaningful if a local LLM NIM is deployed |
| `30082` | `10.131.1.5:30082` | VLM NIM Endpoint | Unused in remote (Brev) mode — nothing listens on the VM; only meaningful if a local VLM NIM is deployed |

---

## 3. Remote LLM/VLM Deployment Facts (Brev Switchyard & Remote Inference)

The VM deployment runs LLM, VLM, and evaluation judge inference against Brev Switchyard (`https://switchyard-13doh4lsz.brevlab.com`),
eliminating the need for local NIM inference containers on `kwanz-ws` and avoiding NGC hosted endpoint rate-limits.

### Configuration Variables (`generated.env.remote`)

```dotenv
LLM_MODE=remote
VLM_MODE=remote
LLM_MODEL_TYPE=openai
VLM_MODEL_TYPE=openai
LLM_NAME=nvidia/nemotron-3-ultra
VLM_NAME=nvidia/cosmos-3-super-reasoner
LLM_NAME_SLUG=none
VLM_NAME_SLUG=none
LLM_BASE_URL=https://switchyard-13doh4lsz.brevlab.com
VLM_BASE_URL=https://switchyard-13doh4lsz.brevlab.com
LLM_ENDPOINT_URL=https://switchyard-13doh4lsz.brevlab.com
VLM_ENDPOINT_URL=https://switchyard-13doh4lsz.brevlab.com
OPENAI_API_KEY=<brev-switchyard-api-key>
```

### Inference Rules & Requirements

1. **Client Type Rule:** Use `_type: openai` for remote inference models, **never** `_type: nim`. The `nim_langchain` client leaks proprietary parameters (such as `verify_ssl`) into the HTTP JSON request body, which triggers HTTP 400 Bad Request errors on standard OpenAI-compatible endpoints.
2. **Model Selection Rules:**
   - **LLM (`nvidia/nemotron-3-ultra`):** Must support OpenAI tool calling (`bind_tools`) for `top_agent` and `json_schema` structured output for incident reporting. Also serves as `eval_llm_judge`.
   - **VLM (`nvidia/cosmos-3-super-reasoner`):** Must support base64 MP4 `video_url` inlining (`data:video/mp4;base64,...`) and frame-by-frame JPEG extraction.
3. **URL Format Rule:** Set `*_BASE_URL` without a trailing `/v1` (`https://switchyard-13doh4lsz.brevlab.com`). Agent and LangChain client instantiations append `/v1` automatically.
4. **Authentication Rule:** Set `OPENAI_API_KEY` to the Brev Switchyard key; it is shared across LLM, VLM, and `eval_llm_judge`.
5. **GPU Device Allocation:** nvstreamer is pinned to GPU 0 and streamprocessing/sensor see all GPUs (nvidia runtime). For MVP2, RT-CV uses GPU 0 (`RT_CV_DEVICE_ID=0`) and RT-Embed uses GPU 1 (`RT_EMBED_DEVICE_ID=1`). No local LLM/VLM NIM uses either GPU in remote mode.

---

## 4. Runtime Interaction Sequences

### Report library pagination and deferred report loading

```mermaid
sequenceDiagram
    actor User as Reviewer
    participant UI as /reports
    participant API as Next.js /api/reports
    participant DB as Supabase RPC
    participant R2 as Cloudflare R2

    User->>UI: Open library or change page/filter
    UI->>API: GET summaries (page size 6)
    API->>DB: list_incident_report_summaries(...)
    DB-->>API: 6 summaries + total count
    API->>R2: Sign up to 6 derived thumbnail keys
    API-->>UI: Metadata + small thumbnail URLs (no video URL)
    UI-->>User: Lazy screenshot images or skeleton fallback
    User->>UI: Open one report
    UI->>API: GET /api/reports/videoId?run=modelRunId
    API->>DB: Read selected report graph
    API->>R2: Create selected object's signed URL
    API-->>UI: Full report + playback URL
```

### Sequence A: Upload, Analysis & Reporting in Gateway Mode (`ANALYSIS_MODE=gateway`)

*Zero-GPU local development flow using `vlm-gateway` and Cloudflare R2.*

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

    User->>UI: Select and upload video clip
    UI->>UI: POST /api/uploads
    UI->>VST: POST /api/v1/videos (via INCIDENT_AGENT_BASE_URL)
    VST-->>UI: upload url (.../vst/api/v1/storage/file)
    UI->>VST: Single-request chunked upload (mediaFile, filename, nvstreamer-* headers)
    VST-->>UI: Chunk response (sensorId, filePath)
    
    alt Chunk response lacks a valid R2 key (real VST)
        UI->>UI: Call Next.js POST /api/uploads/r2
        UI->>R2: PutObject (uploads/<sensorId>/<uuid><ext>)
        R2-->>UI: Stored object key
        UI->>R2: HeadObject (exact uploaded byte length required)
    else Mock backend returns its durable R2 key
        VST->>R2: PutObject (uploads/<sensorId>/<uuid><ext>)
    end

    UI->>UI: Capture and resize one local video frame
    UI->>R2: PUT thumbnail via /api/uploads/thumbnail

    UI->>VST: POST /api/uploads/complete → /api/v1/videos/{sensorId}/complete

    UI->>UI: Trigger POST /api/analysis
    UI->>R2: HeadObject (object must exist and be nonempty)
    UI->>UI: Sign 1-hour R2 GET URL locally (no R2 call)
    
    UI->>Gateway: POST /v1/chat/completions (Prompt + Video URL)
    Gateway->>Brev: Forward with Bearer Auth Header
    Brev->>R2: GET video via presigned URL
    Brev-->>Gateway: VLM Completion (JSON / text)
    Gateway-->>UI: Raw Completion

    UI->>UI: Validate & parse with incidentAnalysisSchema (Zod)

    opt parse/schema validation fails
        UI->>Gateway: Retry repair prompt with raw content
        Gateway->>Brev: Forward repair request
        Brev-->>Gateway: Corrected JSON response
        Gateway-->>UI: Raw repaired completion
        UI->>UI: Re-validate & parse repaired JSON with schema
    end
    
    %% Persistence
    UI->>DB: Upsert videos (id, filepath=R2 key, source=sensorId)
    UI->>DB: Upsert model_runs (id, notes=full JSON report)
    UI->>DB: Call /rpc/insert_incident (atomic delete/insert + reset review_status)
    UI->>DB: Upsert entities, instruments, assets
    UI->>DB: Upsert reports (id, incident_id, model_run_id)
    UI->>DB: Read back videos, model_runs, incidents, reports
    Note over UI,DB: Success requires all four rows and videos.filepath == submitted R2 key

    UI-->>User: Render Incident Report & redirect to /reports/[id]
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

    UI->>Tunnel: POST localhost:8000/api/v1/incidents/[id]/analyze
    Tunnel->>Agent: Forward analyze request (model_run_id)

    Agent->>DB: GET videos (resolve sensor_id from videos.source)
    Agent->>VIOS: Fetch video from VST_INTERNAL_URL (http://10.131.1.5:30888, vss-vios-ingress → streamprocessing :10000)
    VIOS-->>Agent: Video stream bytes
    
    Agent->>Brev: VLM & LLM Inference (nemotron-3-ultra / cosmos-3-super)
    Brev-->>Agent: Structured output
    
    Agent->>Agent: Parse into IncidentReport (Pydantic, LLM structured output)
    Agent->>DB: Upsert videos (filepath = VST URL — overwritten later by UI)
    Agent->>DB: Upsert model_runs (agent model_name)
    Agent->>DB: Call /rpc/insert_incident (atomic delete/insert + reset review_status)
    Agent->>DB: Delete+insert entities, instruments, assets (best-effort, failures only logged)

    Agent-->>Tunnel: Return IncidentReport JSON
    Tunnel-->>UI: Forward agent response

    UI->>UI: Parse & validate snake_case agent response directly with incidentAnalysisSchema (Zod)
    UI->>DB: Upsert model_runs (id, notes=full JSON report)
    UI->>DB: Re-upsert videos (RESTORING durable R2 filepath!)
    UI->>DB: Upsert reports (id, incident_id, model_run_id)
    UI->>DB: Read back videos, model_runs, incidents, reports
    Note over UI,DB: Success requires all four rows and videos.filepath == submitted R2 key

    UI-->>User: Render Incident Report & redirect to /reports/[id]
```

---

### Sequence C: Natural Language Video Search (Planned MVP2)

*Multi-subagent search workflow querying indexed Elasticsearch video embeddings.*

> [!NOTE]
> The search route `/api/v1/incidents/search` and the UI `/search` view are planned for MVP2. In `dev-profile-search`, search components (`search_agent`, `embed_search`, `attribute_search`, and `/api/v1/embed_search`) exist, but the VM incident profile currently loads `dev-profile-base`'s configuration which does not register them.

```mermaid
sequenceDiagram
    autonumber
    actor User as Investigator (Browser)
    participant UI as incident-console-v2 (/search)
    participant Tunnel as SSH Tunnel (:8000)
    participant Agent as vss-agent (Workflow Router)
    participant SearchSub as search_agent / embed_search
    participant ES as Elasticsearch (Vector Index)
    participant R2 as Cloudflare R2 Store

    %% Background Ingestion Phase (continuous)
    Note over Agent,ES: Background: RT-CV & RT-Embed index video frames into ES via Kafka

    %% Search Query Phase
    User->>UI: Enter query: "Person in black hoodie forcing back door"
    UI->>Tunnel: POST localhost:8000/api/v1/incidents/search
    Tunnel->>Agent: Forward search query
    
    Agent->>Agent: Route via config.yml prompt to search_agent
    Agent->>SearchSub: Dispatch text query
    
    SearchSub->>SearchSub: Generate query embedding
    SearchSub->>ES: Vector kNN + BM25 attribute search
    ES-->>SearchSub: Ranked matching video segments (sensorId, timestamps, scores)
    
    SearchSub->>Agent: Synthesize search results with temporal windows
    Agent-->>Tunnel: Return ranked results array
    Tunnel-->>UI: Forward search response

    UI->>R2: Request presigned playback URLs for matching intervals
    R2-->>UI: Presigned video URLs
    UI-->>User: Display interactive video results with timestamp seek
```

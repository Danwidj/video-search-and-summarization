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
        FwdNIM["localhost:30081/30082 -> VM:30081/30082"]
    end

    subgraph VM["kwanz-ws Shared Workstation"]
        subgraph VMNative["Native Processes (Fast Restart)"]
            Agent["vss-agent<br/>(NAT Framework, Port 8000)"]
            VideoAnalytics["video-analytics-api<br/>(Optional, Port 8081)"]
            BehaviorAnalytics["behavior-analytics<br/>(Optional, Port 8080)"]
        end

        subgraph VMDocker["Docker Appliances (compose.yml)"]
            HAProxy["vss-haproxy-ingress<br/>(Port 7777)"]
            VIOSIngress["vss-vios-ingress<br/>(Port 10000)"]
            StreamProcessing["vss-vios-streamprocessing<br/>(GPU 0)"]
            NvStreamer["vss-vios-nvstreamer<br/>(GPU 0)"]
            VIOSPostgres["vss-vios-postgres<br/>(Internal DB)"]
            Redis["redis<br/>(State Cache)"]
            Phoenix["phoenix<br/>(Telemetry)"]
            Kafka["kafka<br/>(Analytics Bus, Optional)"]
            Elasticsearch["elasticsearch<br/>(Search Index, Optional)"]
        end
    end

    subgraph External["Cloud & Hosted Services"]
        R2[("Cloudflare R2<br/>(Video & Evidence Store)")]
        Supabase[("Supabase Postgres<br/>(HTTPS PostgREST & RPC)")]
        NGC["NVIDIA NGC Hosted API<br/>(https://integrate.api.nvidia.com)"]
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
    VIOSIngress --> NvStreamer
    Agent -->|Fetch Video Bytes| VIOSIngress
    Agent -->|OpenAI Protocol Inference| NGC
    Agent -->|HTTPS PostgREST & RPC| Supabase
```

### Component Reference Table

| Component | Host | Port | Runtime Type | Primary Source / Owner File | Responsibility |
|---|---|---|---|---|---|
| `incident-console-v2` | Laptop | 3200 | Node.js (Next.js 14 App Router) | `incident-console-v2/` | Primary user interface: video upload, review workflow, eval form, report display |
| `vlm-gateway` | Laptop (or VM) | 8600 | Python (FastAPI / Uvicorn) | `vlm-gateway/app.py` | Holds Brev upstream credential server-side; exposes `/v1/chat/completions` for local mode |
| `mock-backend` | Laptop | 7777 | Python (FastAPI / Uvicorn) | `mock-backend/base_profile_mock/` | Zero-GPU local mock simulating VST upload, streaming, and base profile responses |
| `vss-agent` | `kwanz-ws` | 8000 | Python (Native `nat serve`) | `services/agent/` | Core VSS agent: incident analysis workflow, prompt execution, tool calling, report persistence |
| `video-analytics-api` | `kwanz-ws` | 8081 | Node.js (Native) | `services/analytics/` | Optional MVP2 video analytics ingestion and query layer (`ENABLE_ANALYTICS=true`) |
| `behavior-analytics` | `kwanz-ws` | 8080 | Python (Native) | `services/analytics/` | Optional MVP2 behavior perception pipeline (`ENABLE_ANALYTICS=true`) |
| `vss-haproxy-ingress` | `kwanz-ws` | 7777 | Docker container | `services/ingress/` | Gateway reverse proxy exposing VIOS, NvStreamer, and storage endpoints |
| `vss-vios-streamprocessing`| `kwanz-ws` | Internal | Docker container (GPU 0) | `services/vios/streamprocessing/` | Core video decode, encode, and frame processing engine |
| `vss-vios-nvstreamer` | `kwanz-ws` | Internal | Docker container (GPU 0) | `services/vios/nvstreamer/` | Video file ingestion and RTSP/WebRTC chunked stream publisher |
| `vss-vios-ingress` | `kwanz-ws` | 10000 | Docker container | `services/vios/ingress/` | Nginx reverse proxy routing internal storage and streaming API calls |
| `vss-vios-postgres` | `kwanz-ws` | 5432 (int) | Docker container | `services/vios/postgres/` | VIOS internal database for camera sensors and stream registrations |
| `redis` | `kwanz-ws` | 6379 (int) | Docker container | Stock compose infra | Message broker and caching layer |
| `phoenix` | `kwanz-ws` | 6006 (int) | Docker container | Stock compose infra | LLM/VLM telemetry, trace logging, and performance monitoring |
| `Supabase` | Cloud | 443 (HTTPS) | Managed PostgREST / Postgres | `supabase/migrations/` | Relational store for reports, incidents, evidence, reviews, and ground truth |
| `Cloudflare R2` | Cloud | 443 (HTTPS) | S3-Compatible Object Store | `incident-console-v2/lib/r2/` | Canonical persistent object storage for video clips and screenshots |
| `NGC Hosted API` | Cloud | 443 (HTTPS) | Remote NVIDIA NIM Service | Upstream endpoint | Hosted VLM/LLM inference used by `vss-agent` on the VM |
| `Brev Switchyard` | Cloud | 443 (HTTPS) | Remote Switchyard Proxy | Upstream endpoint | Hosted VLM/LLM inference used by `vlm-gateway` for local laptop analysis |

---

## 2. Deployment & Connectivity

The laptop-to-VM development loop is driven by the unified entrypoint script `start.sh`.

```mermaid
flowchart TD
    Start["./start.sh --mode local|vm"] --> CheckMode{Mode?}

    %% Local Mode Path
    CheckMode -->|local| LocalInit["Export ANALYSIS_MODE=gateway"]
    LocalInit --> StartMock["Start mock-backend (127.0.0.1:7777)"]
    StartMock --> StartGateway["Start vlm-gateway (127.0.0.1:8600)"]
    StartGateway --> RunV2Local["Launch incident-console-v2 (Port 3200)"]

    %% VM Mode Path
    CheckMode -->|vm| VMInit["Export ANALYSIS_MODE=agent"]
    VMInit --> CheckSSH["Check VM State via SSH<br/>(docker compose ps & native-services.sh status)"]
    CheckSSH --> StateDecision{Deploy State?}
    
    StateDecision -->|Nothing Running| FreshDeploy["Deploy Docker Appliances over SSH<br/>Start Native Services via native-services.sh"]
    StateDecision -->|Partial State| SelfHeal["Self-Heal: Start only missing Docker & Native services"]
    StateDecision -->|All Running| Ready["Backend Ready"]
    
    FreshDeploy --> OpenTunnel
    SelfHeal --> OpenTunnel
    Ready --> OpenTunnel

    OpenTunnel["Open SSH Tunnel (.scripts/tunnel.sh)<br/>8000, 7777, 30081, 30082"] --> RunV2VM["Launch incident-console-v2 (Port 3200)"]
```

### SSH Tunnel Port Forwards

When running in VM mode, `.scripts/tunnel.sh` establishes an SSH tunnel forwarding the following
ports from `localhost` to `kwanz-ws` (`10.131.1.5`):

| Local Port | Remote Destination | Target Service | Usage |
|---|---|---|---|
| `8000` | `10.131.1.5:8000` | Native `vss-agent` | Agent REST API (`/health`, `POST /api/v1/incidents/{id}/analyze`) |
| `7777` | `10.131.1.5:7777` | `vss-haproxy-ingress` | VIOS/NvStreamer chunked upload and video storage API |
| `30081` | `10.131.1.5:30081` | LLM NIM Endpoint | Tunneled LLM inference (when running local NIM or tunneled proxy) |
| `30082` | `10.131.1.5:30082` | VLM NIM Endpoint | Tunneled VLM inference (when running local NIM or tunneled proxy) |

---

## 3. Remote LLM/VLM Deployment Facts (NGC Hosted)

The VM deployment runs LLM and VLM inference against NVIDIA's hosted NGC endpoints, eliminating the
need for local NIM inference containers on `kwanz-ws`.

### Configuration Variables (`generated.env.remote`)

```dotenv
LLM_MODE=remote
VLM_MODE=remote
LLM_MODEL_TYPE=openai
VLM_MODEL_TYPE=openai
LLM_NAME_SLUG=none
VLM_NAME_SLUG=none
LLM_BASE_URL=https://integrate.api.nvidia.com
VLM_BASE_URL=https://integrate.api.nvidia.com
LLM_ENDPOINT_URL=https://integrate.api.nvidia.com
VLM_ENDPOINT_URL=https://integrate.api.nvidia.com
NVIDIA_API_KEY=<your-ngc-api-key>
OPENAI_API_KEY=<same-key-as-nvidia-api-key>
```

### Critical Operational Facts & Gotchas

1. **Authentication Quirk (`OPENAI_API_KEY`):**
   Upstream LangChain integration components in the agent read `OPENAI_API_KEY` rather than `NVIDIA_API_KEY`
   for authorization headers, even when hitting NVIDIA's hosted endpoint (`https://integrate.api.nvidia.com`).
   Setting only `NVIDIA_API_KEY` results in silent HTTP 401 Unauthorized errors. Both variables must be set
   to the same NGC API key.
2. **Missing `base_url` in `openai_vlm` Patch:**
   Upstream blueprint configurations omit `base_url` from the `openai_vlm` block in `config.yml` and
   `config_rag.yml`. Without adding `base_url: ${VLM_BASE_URL}/v1`, VLM requests silently default to the
   public OpenAI endpoint (`api.openai.com`), causing authentication failures.
3. **Live Model Probing:**
   NVIDIA NGC free-tier models frequently change availability or deprecate without notice (`410 Gone`), and
   inclusion in catalog listings does not guarantee account entitlement (`404 Function not found for account`).
   Before deployment, run `scripts/probe_remote_models.sh`. Currently,
   `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` is confirmed operational for both LLM and VLM roles on the
   free tier.
4. **16-Concurrent Request Free-Tier Cap:**
   NVIDIA's hosted free tier enforces a strict limit of 16 concurrent requests. High-framerate video processing
   saturating this ceiling causes pipeline calls to loop or hang indefinitely rather than degrading gracefully.
   Limiting `max_frames` in agent configuration mitigates request bursts.
5. **GPU Device Allocation under Remote Mode:**
   With LLM/VLM inference offloaded to the cloud, local GPU requirements on `kwanz-ws` drop dramatically:
   - **GPU 0:** Dedicated to video infrastructure (`vss-vios-nvstreamer` and `vss-vios-streamprocessing`).
     In MVP2, `vss-rtvi-cv` and `vss-rtvi-embed` will also default to GPU 0.
   - **GPU 1:** Completely idle and unallocated. Free for other team research or optional isolation of
     `vss-rtvi-embed` if GPU 0 experiences SM contention during heavy ingestion.

---

## 4. Runtime Interaction Sequences

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
    UI->>VST: Chunked upload (mediaFile, filename)
    VST-->>UI: Chunk response (sensorId, filePath)
    
    alt Missing durable R2 key (real VST case)
        UI->>UI: Call Next.js POST /api/uploads/r2
        UI->>R2: PutObject (uploads/<sensorId>/<uuid>.mp4)
        R2-->>UI: Stored object key
    end

    UI->>UI: Trigger POST /api/analysis
    UI->>R2: Generate 1-hour presigned GET URL
    R2-->>UI: Signed video URL
    
    UI->>Gateway: POST /v1/chat/completions (Prompt + Video URL)
    Gateway->>Brev: Forward with Bearer Auth Header
    Brev-->>Gateway: VLM Completion (JSON / text)
    Gateway-->>UI: Raw Completion

    opt Invalid JSON structure
        UI->>Gateway: Retry repair prompt with raw content
        Gateway->>Brev: Forward repair request
        Brev-->>Gateway: Corrected JSON response
        Gateway-->>UI: Sanitized JSON
    end

    UI->>UI: Validate & parse with incidentAnalysisSchema (Zod)
    
    %% Persistence
    UI->>DB: Upsert videos (id, filepath=R2 key, source=sensorId)
    UI->>DB: Upsert model_runs (id, notes=full JSON report)
    UI->>DB: Call /rpc/insert_incident (atomic delete/insert + reset review_status)
    UI->>DB: Upsert entities, instruments, assets
    UI->>DB: Upsert reports (id, incident_id, model_run_id)

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
    participant VIOS as VIOS / NvStreamer (:7777)
    participant R2 as Cloudflare R2 Bucket
    participant Agent as vss-agent (:8000)
    participant NGC as NVIDIA NGC Hosted API
    participant DB as Supabase PostgREST & RPC

    User->>UI: Select and upload video clip
    UI->>Tunnel: Chunked upload to localhost:7777
    Tunnel->>VIOS: Forward chunked upload
    VIOS-->>UI: Sensor registration (sensorId)

    %% R2 Fallback
    UI->>UI: POST /api/uploads/r2
    UI->>R2: PutObject (uploads/<sensorId>/<uuid>.mp4)
    R2-->>UI: Durable R2 object key

    UI->>UI: Trigger POST /api/analysis
    UI->>DB: Upsert videos (id, filepath=R2 key, source=sensorId)

    UI->>Tunnel: POST localhost:8000/api/v1/incidents/[id]/analyze
    Tunnel->>Agent: Forward analyze request (model_run_id)

    Agent->>VIOS: Fetch video bytes from internal URL (10.131.1.5:10000)
    VIOS-->>Agent: Video stream bytes
    
    Agent->>NGC: VLM & LLM Inference (nemotron-3-nano-omni)
    NGC-->>Agent: Structured output
    
    Agent->>Agent: Parse into IncidentReport (Pydantic)
    Agent->>DB: Call /rpc/insert_incident (atomic delete/insert)
    Agent->>DB: Upsert entities, instruments, assets
    Agent->>DB: Upsert videos (WARNING: overwrites filepath with VST URL!)

    Agent-->>Tunnel: Return IncidentReport JSON
    Tunnel-->>UI: Forward agent response

    UI->>UI: Translate snake_case agent response (analyzeViaAgent)
    UI->>DB: Upsert model_runs (id, notes=full JSON report)
    UI->>DB: Re-upsert videos (RESTORING durable R2 filepath!)
    UI->>DB: Upsert reports (id, incident_id, model_run_id)

    UI-->>User: Render Incident Report & redirect to /reports/[id]
```

---

### Sequence C: Natural Language Video Search (Planned MVP2)

*Multi-subagent search workflow querying indexed Elasticsearch video embeddings.*

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

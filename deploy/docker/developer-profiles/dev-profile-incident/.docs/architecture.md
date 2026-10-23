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
            VIOSSensor["vss-vios-sensor<br/>(Port 30000; GPU 0, not started by start.sh)"]
            NvStreamer["vss-vios-nvstreamer<br/>(RTSP streamer, Port 31000; GPU 0)"]
            VIOSPostgres["vss-vios-postgres<br/>(Internal DB, Unix socket only)"]
            Redis["redis<br/>(State Cache)"]
            Phoenix["phoenix<br/>(Telemetry, Port 6006)"]
            Kafka["kafka<br/>(Analytics Bus, always started by start.sh)"]
            Elasticsearch["elasticsearch<br/>(Search Index, Optional)"]
        end
    end

    subgraph External["Cloud & Hosted Services"]
        R2[("Cloudflare R2<br/>(Video & Evidence Store)")]
        Supabase[("Supabase Postgres<br/>(HTTPS PostgREST & RPC)")]
        Brev["Brev Lab Switchyard API<br/>(https://switchyard-13doh4lsz.brevlab.com)"]
    end

    %% Laptop connections
    UI -->|Mock Mode Inference| Gateway
    UI -->|Mock Mode Upload| Mock
    UI -->|VM Mode HTTP /analyze| FwdAgent
    UI -->|VM Mode Video Upload| FwdHAProxy
    UI -->|Direct Upload Fallback & Presigned URLs| R2
    UI -->|REST report_revisions insert| Supabase
<<<<<<< HEAD
    UI -->|/rpc/save_human_revision, /rpc/set_official_revision| Supabase
=======
    UI -->|/rpc/save_human_revision, set_official_revision| Supabase
>>>>>>> origin/main

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
| `incident-console-v2` | Laptop | 3200 | Node.js (Next.js 15 App Router) | `incident-console-v2/` | Primary user interface: video upload, report versions (edit, History, restore, official), report display |
| `vlm-gateway` | Laptop (or VM) | 8600 | Python (FastAPI / Uvicorn) | `vlm-gateway/app.py` | Holds Brev upstream credential server-side; exposes `/v1/chat/completions` for mock mode |
| `mock-backend` | Laptop | 7777 | Python (FastAPI / Uvicorn) | `mock-backend/base_profile_mock/` | Zero-GPU local mock simulating VST upload, streaming, base profile responses, search, and chat |
| `vss-agent` | `kwanz-ws` | 8000 | Python (Native `nat serve`) | `services/agent/` | Core VSS agent: incident analysis, search, and chat workflows (`/api/v1/incidents/{id}/analyze`, `POST /api/v1/incidents/search`, `POST /api/v1/incidents/chat`), tool calling, report persistence; remote inference via Brev |
| `video-analytics-api` | `kwanz-ws` | 8081 | Node.js (Native) | `services/analytics/video-analytics-api/` | Optional MVP2 video analytics ingestion and query layer (`ENABLE_ANALYTICS=true`) |
| `behavior-analytics` | `kwanz-ws` | none (8080 is a HAProxy/label placeholder) | Python (Native) | `services/analytics/behavior-analytics/` | Optional MVP2 behavior perception pipeline (`ENABLE_ANALYTICS=true`) |
| `vss-haproxy-ingress` | `kwanz-ws` | 7777 | Docker container | `deploy/docker/services/infra/haproxy/` | Public reverse proxy on :7777: /api,/chat → vss-agent :8000; /vst,/storage → vss-vios-ingress :30888; /phoenix → :6006; optional analytics/kibana backends |
| `vss-vios-streamprocessing`| `kwanz-ws` | 10000 | Docker container (GPU 0) | `deploy/docker/services/vios/` | VST storage/upload + replay API (receives chunked uploads via the ingress) |
| `vss-vios-nvstreamer` | `kwanz-ws` | 31000 | Docker container (GPU 0) | `deploy/docker/developer-profiles/dev-profile-alerts/compose.yml` | NvStreamer RTSP file streamer (not in the upload path; not routed by ingress/HAProxy) |
| `vss-vios-ingress` | `kwanz-ws` | 30888 | Docker container | `deploy/docker/services/vios/` (foundational) | Nginx VST ingress: /vst/api/v1/sensor → sensor-ms :30000; other /vst/api/v1 and /vst/storage → streamprocessing :10000 |
| `vss-vios-sensor` | `kwanz-ws` | 30000 | Docker container (GPU 0) | `deploy/docker/services/vios/initiator/` | VST sensor registration service (`sensor-ms`; pinned to GPU 0 in `compose.override.yml`, but not started by `start.sh`) |
| `vss-vios-postgres` | `kwanz-ws` | none (Unix socket only) | Docker container | `deploy/docker/services/vios/` | VIOS internal database for camera sensors and stream registrations |
| `perception-2d-fusion` (`vss-rtvi-cv`) | `kwanz-ws` | 9000 | Docker container (GPU 0) | `deploy/docker/developer-profiles/dev-profile-search/video-analytics-2d-app/compose.yml` | Stock DeepStream perception service (pinned to GPU 0 in `compose.override.yml`, but not started by `start.sh` and not used in MVP2) |
| `rtvi-embed` (`vss-rtvi-embed`) | `kwanz-ws` | 8017 (→8000) | Docker container (GPU 0, bridged) | `deploy/docker/services/rtvi/rtvi-embed/` | Stock Triton inference server for video embeddings (pinned to GPU 0 in `compose.override.yml`, but not started by `start.sh` and unused in MVP2; text embeddings and VLM are remote) |
| `redis` | `kwanz-ws` | 6379 (int) | Docker container | Stock compose infra | Message broker and caching layer |
| `phoenix` | `kwanz-ws` | 6006 (int) | Docker container (bridged mdx_default) | Stock compose infra | LLM/VLM telemetry, trace logging, and performance monitoring |
| `kafka` | `kwanz-ws` | 9092 | Docker container | Stock compose infra | Heavy event bus for analytics (always started by start.sh) |
| `elasticsearch` | `kwanz-ws` | Internal | Docker container | Stock compose infra | JVM search index appliance (optional, only with `ENABLE_ANALYTICS=true`) |
| `Supabase` | Cloud | 443 (HTTPS) | Managed PostgREST / Postgres | `supabase/migrations/` (finals, including the versioned-report schema and functions); `supabase/midterm/` (frozen record) | Store for videos, runs, versioned report revisions, evidence crops and search history. One project per phase: see [Two Supabase projects](#two-supabase-projects-one-per-phase) |
| `Cloudflare R2` | Cloud | 443 (HTTPS) | S3-Compatible Object Store | `incident-console-v2/lib/r2/` | Canonical persistent object storage for video clips and screenshots |
| `Brev Switchyard` | Cloud | 443 (HTTPS) | Remote Switchyard Proxy | Upstream endpoint | Hosted VLM/LLM inference used by both `vss-agent` (VM) and `vlm-gateway` (laptop) |

### Native vs. Docker Service Split Policy

**Policy Rule:** Run a service natively whenever feasible.

Services are split based on feasibility:
- **Native Processes (High Feasibility):** `vss-agent` (Python/uv), `video-analytics-api` (Node.js), and `behavior-analytics` (Python). Running natively eliminates Docker image rebuilds on code changes (~2s process restart vs multi-minute container build).
- **Docker Appliances (Infeasible Natively):** Media engines and storage appliances (`vss-vios-streamprocessing`, `vss-vios-nvstreamer`, `vss-vios-ingress`, `vss-vios-postgres`). These depend on proprietary CUDA and GStreamer container toolchains; host installation is infeasible. Stock perception and embedding appliances (`perception-2d-fusion` / `vss-rtvi-cv`, `rtvi-embed` / `vss-rtvi-embed`, `sensor-ms` / `vss-vios-sensor`) are containerized and pinned to GPU 0 in `compose.override.yml`, but are not started by `start.sh`.
- **Docker Appliances (No Benefit / JVM):** Infrastructure appliances (`redis`, `kafka`, `elasticsearch`, `phoenix`, `vss-haproxy-ingress`). Standard prebuilt containers or heavy JVM runtimes where native execution provides no development benefit.
- **Networking:** Nearly all containers use host networking (`network_mode: host`); exceptions are `phoenix` (bridge `mdx_default`, published 6006:6006) and `vss-rtvi-embed` (if started; published `${RTVI_EMBED_PORT}`=8017→8000). Native processes reach all of them on `localhost`.

---

## 2. Deployment & Connectivity

The one-command entry point for setting up and launching the system is `start.sh` (`./start.sh --mode mock` or `./start.sh --mode vm`; `--mode local` is a deprecated alias for `mock`), executed directly from developer laptops. It automates backend checks, self-healing service deployment, port tunneling, and UI initialization.

```mermaid
flowchart TD
    Start["./start.sh --mode mock|vm"] --> CheckMode{Mode?}

    %% Mock Mode Path
    CheckMode -->|mock|  StartMock["Start mock-backend (127.0.0.1:7777)"]
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

    OpenTunnel["Open backgrounded SSH tunnel (inline in start.sh; same forwards as .scripts/tunnel.sh)<br/>8000, 7777<br/>then wait for localhost:8000/health and localhost:7777/storage"] --> CheckConsole{--no-console?}
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

### Two Supabase projects (one per phase)

| Project | Role | Schema | Access |
|---|---|---|---|
| **Finals** (new project, same organisation and region as midterm) | The live database every service uses | [`supabase/migrations/`](../supabase/README.md): the finals baseline, then the versioned-report schema and its functions, then later finals migrations | `service_role` (PostgREST) and `postgres` (direct DSN) only; RLS on everything; the public key reaches nothing |
| **Midterm** (`rfevukimyftzbxlehwel`) | Frozen record of the midterm phase | [`supabase/midterm/`](../supabase/midterm/README.md) (archive; never pushed) | Read-only after the freeze: `service_role` reads and runs the read RPCs, every write fails, direct-DSN sessions are read-only, `anon` is locked out |

Finals is built from the baseline and filled once from midterm by `supabase/copy/copy_midterm_to_finals.py` (one-way; [`../supabase/README.md`](../supabase/README.md)). The versioned-report schema and its functions (`save_human_revision`, `set_official_revision`, the rewritten search/library/dashboard functions) are applied on top through `supabase/migrations/`. **R2 is shared:** both projects name the same bucket and keys, so no object is copied and no R2 setting changes. A delete in finals removes R2 objects that the midterm record still names; that is accepted for a record.

What points at the database, and how it switches at the cutover:

| Where | Settings | Read by | How it switches |
|---|---|---|---|
| `dev-profile-incident/.env.local` on each laptop (symlinked into `incident-console-v2/`, `vlm-gateway/`, `mock-backend/`) | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`, `INCIDENT_DB_DSN` | Console, eval, mock backend in local mode, the copy and parity scripts | Each teammate sets the 3 finals values |
| `.env.local` copies in other worktrees | same | Console or eval started from those worktrees | `.githooks/setup-worktree.sh` never overwrites an existing copy, so old worktrees keep midterm values: refresh or delete them. The freeze makes a stale one fail loudly |
| `generated.env.remote` on `kwanz-ws` | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | Native `vss-agent` (search, chat, AI revision insert, evidence embeddings); `.scripts/native-services.sh` | Back up, set the two finals values, restart `vss-agent` ("ask first"; [`incident-operate-vm`](../skills/incident-operate-vm/SKILL.md)) |
| `deploy/docker/services/agent/compose.yml` | `INCIDENT_SUPABASE_*` passthrough | The Docker `vss-agent` (not used; the native one owns :8000) | Nothing |
| `eval/` | `INCIDENT_DB_DSN` or `INCIDENT_SUPABASE_*` from the same `.env.local` | P1/RP1 batch (outside this change) | Same `.env.local`; eval's storage is outside this change |

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
5. **GPU Device Allocation:** The active incident stack started by `start.sh` runs on GPU 0 alone (`streamprocessing-ms`, `nvstreamer-2d-fusion`, and native processes via `CUDA_VISIBLE_DEVICES=0` / `NVIDIA_VISIBLE_DEVICES=0`), leaving GPU 1 completely untouched for co-tenant training workloads on `kwanz-ws`. All other GPU-capable Docker services in the profile (`sensor-ms`, `perception-2d-fusion`, and `rtvi-embed`) are pinned strictly to GPU 0 in `compose.override.yml` (`device_ids=['0']`, `NVIDIA_VISIBLE_DEVICES=0`, `CUDA_VISIBLE_DEVICES=0`, `RT_CV_DEVICE_ID=0`, `RT_EMBED_DEVICE_ID=0`, `RTVI_EMBED_NVIDIA_VISIBLE_DEVICES=0`) for safety if ever launched, but `start.sh` never starts them. Neither `perception-2d-fusion` nor `rtvi-embed` is used in MVP2 (MVP2 uses remote `nvidia/llama-nemotron-embed-vl-1b-v2` text embeddings and remote Brev VLM). No local LLM/VLM NIM uses either GPU in remote mode.

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
<<<<<<< HEAD
- Report detail, History, Save, Restore, official marking and delete go through `lib/application/reports.ts` (`getReport`, `listRevisions`, `saveHumanEdit`, `restoreRevision`, `setOfficialRevision`, `deleteVideoAndReports`); R2 signing and deletion, and the agent's embedding call, are passed in as functions. A report is read from one `report_revisions` row (`?revision=<id>`, else the official one, else the newest). A refusal by `save_human_revision` or `set_official_revision` becomes a `StoreRejection`, which the route returns as 422 with the database's reason. Health, the dashboard, the report library, the videos list and the History list call a port directly; the report library route signs thumbnails itself.
=======
- Report detail, review status changes and delete go through `lib/application/reports.ts` (`getReport`, `changeReviewStatus`, `deleteReport`); R2 signing and deletion are passed in as functions. A run's report is read from the revision model (the reviewer version when the run has one, else the AI's latest `report_revisions` row), and a review change invokes the revision write functions. See `.docs/data.md` for the current schema. Health, the dashboard, the report library, the videos list, official selection and edit call a port directly; the report library route signs thumbnails itself.
>>>>>>> origin/main
- `EvidenceSearchRepository` is defined for MVP2 search; its planned adapter calls the vss-agent's `POST /api/v1/incidents/search`.
- Analysis saving (`lib/analysis/persistence.ts`) writes `model_runs` and the AI revision through the same `PostgrestClient`; see §7 of [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md#7-deferred-in-this-round) for what is still outside the ports.

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
    UI->>API: GET /api/reports/videoId?revision=revisionId
    API->>DB: Read one report_revisions row (IncidentRepository.getReport)
    API->>R2: Create selected object's signed URL
    API-->>UI: Full report + playback URL
```

Date inputs are directly editable: entering either boundary activates the custom range automatically. Preset
selection clears stale custom boundaries, and the date/time row has an explicit reset that clears both date and
time constraints. The API forwards inclusive day boundaries, optional time-of-day bounds, and the viewer's detected timezone to the summary RPC.

### Dashboard analytics and cross-filtering

`GET /api/dashboard` calls the service-role-only `get_incident_dashboard` RPC through `DashboardRepository.getDashboard`. It counts **official versions only**: one per video, through `videos.official_revision_id`.
- Videos with revisions but no official one ("awaiting official report"), videos without any report, and all uploaded videos are counted separately, all time, and link to the matching `/videos` lists.
- Evidence statistics are canonical entity types plus normalised instrument and asset names, counted per distinct incident.
- Model coverage counts every analysis attempt in the period by outcome.
- Every other number links to `/reports?scope=official&...` with the same period and filters, using `match=exact` for instrument and asset names, so the reports total equals the clicked number. The URL is the reports page's filter state.
- The period window is computed in the browser after mount and sent as zoneless UTC; the API reads it as UTC.
- The heatmap and weekday/hour cross-filters use the viewer's local time: `GET /api/dashboard` forwards the browser's detected `timezone` (e.g. `America/New_York`) to `p_timezone`, which groups and filters `generated_datetime` in that zone. `/reports` detects the same zone itself, so drill-down links carry no timezone and the totals still match.

### Report versions: editing, History and restore

`Edit report` opens a side-by-side editor: the original model output read-only on the left, and the structured fields on the right. The page's **History** lists every revision of the incident (kind, author, time, note), newest first; opening one loads it into the editor.
- **Editable:** incident type, start/end seconds, summary, severity level, and entities, instruments (with holder and threat level) and assets, including each item's description and detail and its image. IDs are renumbered by position; each item sends the item it came from as `source_id` (null for an added item) so its evidence follows it through a delete or reorder.
- **Model-generated, never editable:** title, severity rationale, location, timeline and uncertainties (copied unchanged into the new revision).
- **Provenance:** never editable.
- **Unsaved edits** exist only in the form. A refresh reloads the stored revision. There is no draft.

<<<<<<< HEAD
`PATCH /api/reports/[videoId]/edit {parentId, editedBy, edit, note?}` rejects Class B/C keys (400), validates the edit against the contract's own sub-schemas and ID/holder/window rules (422), builds the new payload and evidence (`humanRevisionContent`) and calls `save_human_revision`, which appends a `human` revision whose parent is the revision that was opened. `POST /api/reports/[videoId]/restore {revisionId, restoredBy}` does the same with the content of an earlier revision. `GET /api/reports/[videoId]/revisions` is the History list. `POST /api/reports/[videoId]/evidence-image` uploads a replacement image to a new R2 key `evidence/<videoId>/<uuid>/<itemId>.jpg` (never overwriting or deleting) and returns the key for the edit to use. No route changes a revision, `model_runs.notes` or an existing R2 object, and there is no verify step.

The report shows "Reviewer-edited after generation", "Model assessed N/5; reviewer set M/5" beside the model severity rationale, and the model's original window beside a reviewer-set one.
=======
`PATCH /api/reports/[videoId]/edit` rejects Class B/C keys (400), validates the edit against the contract's own sub-schemas and ID/holder/window rules (422), then calls `save_human_revision`. In one transaction that function saves the run's reviewer version (`report_revisions` human revision, revision No. max + 1, inheriting the parent's `model_run_id`) and stamps `review_status.edited_by/edited_at`; an edit of a verified report sends it back to `under review` and clears the verifier. It never touches the AI rows or `model_runs.notes`. The console calls it directly, not the `apply_structured_report_edit` shim the finals database keeps for older consoles.

`PATCH /api/reports/[videoId]/review` calls `the revision-based review transition`, one transaction that never writes `edited_by/edited_at` (they mean the last content edit). Verifying a report with no reviewer version first copies the AI report into one, so every verified report has a reviewer version.
>>>>>>> origin/main

### Run history, re-generation and the official version

- **Video history.** A video is the parent of its analyses. `GET /api/videos/[videoId]/runs` builds the history from two sources:
  - runs with an AI revision for the video;
  - revision-less attempt records whose notes explicitly name the video: failed attempts.

  Each entry shows model, time, outcome, failure reasons or repair operations, the reviewer prompt, and whether its revision is the official one. Failed attempts are never reports.
- **Re-generation.** `POST /api/videos/[videoId]/runs {model, additionalInstruction?}` re-analyses the stored R2 object (the console's "reviewer prompt" box is `additionalInstruction`):
  - the same canonical request, strict validation and ID-only recovery as an upload;
  - always a new run and a new AI revision, which starts from the model's output (earlier edits are not carried across);
  - it never writes the `videos` row (the upload time is kept);
<<<<<<< HEAD
  - it never changes the official version.
- **Official version.** `PUT /api/videos/[videoId]/official {revisionId}` and `DELETE` call `setOfficialRevision`: for a mark, the console asks the agent for the revision's evidence embeddings (`POST /api/v1/incidents/evidence-embeddings`) and passes them to `set_official_revision`, which sets `videos.official_revision_id` and rebuilds the incident's `evidence_crops`; for a clear it passes none and the rows go. If the agent is unreachable the mark fails and nothing changes. Used from the report page and the video history.
- **Where it appears:** pages `/videos` and `/videos/[id]`. The report page's analysis card combines re-generation with a compact history.
=======
  - it never selects the official report.
- **Official report.** `PUT/DELETE /api/videos/[videoId]/official` calls `set_official_revision`, used from the report page and the video history.
- **Where it appears:** pages `/videos` and `/videos/[id]`. The report page's analysis card combines re-analysis with a compact history.
>>>>>>> origin/main

### Sequence A: Upload, Analysis & Reporting in Gateway Mode (`ANALYSIS_MODE=gateway`)

*Zero-GPU local development flow using `vlm-gateway` and Cloudflare R2, on `incident-contract-v4`.*

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
<<<<<<< HEAD
        UI->>DB: report_revisions (kind ai: payload, evidence, facets)
=======
        UI->>DB: /rpc/report_revisions_insert, entities (E#), instruments (I#, holder), assets (A#), reports
>>>>>>> origin/main
        UI->>DB: Read back and verify
        UI-->>User: Redirect to /reports/[videoId]?revision=[revisionId]
    else contract_failed / request_failed
        UI->>DB: model_runs attempt record only (no revision)
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
    Note over Agent,DB: The agent inserts the AI revision and returns revision_id; the console records the run

    Agent-->>Tunnel: Return {report, report_text, model, contract_version, raw_output, finish_reason, revision_id}
    Tunnel-->>UI: Forward agent response

    UI->>UI: Strict parse + schema + cross-field rules under policy core-scored-v1; id-normalization-v1 only if needed
    alt valid_first_pass / valid_after_structural_repair
        UI->>DB: model_runs (immutable notes: request, raw response, validation, repair, report)
<<<<<<< HEAD
        UI->>DB: report_revisions (kind ai: payload, evidence, facets)
=======
        UI->>DB: /rpc/report_revisions_insert, entities (E#), instruments (I#, holder), assets (A#), reports
>>>>>>> origin/main
        UI->>DB: Read back and verify
        UI-->>User: Redirect to /reports/[videoId]?revision=[revisionId]
    else contract_failed / request_failed
        UI->>DB: model_runs attempt record only (no revision)
        UI-->>User: 422 / 502 / 504 with the reason; the attempt appears in the video's history
    end
```

---

### Sequence C: Natural Language Video Search & Conversational Chat (MVP2)

*Authoritative specification, sequence, and data flow: [`mvp2/README.md`](mvp2/README.md) and [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/).*

> [!NOTE]
> MVP2 shifted from real-time perception/Elasticsearch indexing to a hybrid pipeline combining VLM extraction (`incident-contract-v4`), object cropping through a detector port (today the remote VLM; local open-vocabulary detectors are evaluated in [`mvp2/eval.md`](mvp2/eval.md)), Supabase `pgvector` (`evidence_crops`), conversational Q&A (`chat-contract-v1`), and an always-on VLM critic (`query_results`). See [`mvp2/README.md`](mvp2/README.md) for the authoritative architecture and end-to-end data flow.

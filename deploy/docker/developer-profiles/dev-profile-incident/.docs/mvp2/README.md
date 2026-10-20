# MVP2: Natural-Language Evidence Search with Object Crops

**Profile:** `dev-profile-incident`
**Target:** Zero-GPU local workstation and `kwanz-ws` (2x NVIDIA RTX A6000 48 GB)
**Status:** Planning (contracts and schema defined, VM backend steps in progress)

---

## 1. Executive Summary

MVP2 adds **natural-language evidence search with object crops** to the incident search and reporting capstone. A reviewer uploads a video clip, a VLM extracts a structured incident report (incident-contract-v3), and the system enables searching across all stored incidents using natural language queries. Each search result returns the matching evidence item (entity/instrument/asset) with its **timestamp** and a **cropped object image** (bounding box from a separate open-vocabulary detector stage).

The MVP2 end-goal user-facing outcome is: **A reviewer types a natural-language query (e.g. "crowbar used in ATM burglary") and receives ranked evidence items, each showing the incident timestamp, description, and a tightly cropped JPEG of the object from the exact video frame.**

---

## 2. End-to-End Architecture & Data Flow

```
Surveillance Video
       |
       V (VLM P1 Extraction, incident-contract-v3)
       |
   Structured Report
       |  - incident type/title/description + severity, start_timestamp, end_timestamp
       |  - entities [{entity_id, type, description, timestamp_seconds, label}]
       |  - instruments [{instrument_id, name, threat_level, holder_entity_id, timestamp_seconds, label}]
       |  - assets [{asset_id, name, description, timestamp_seconds, label}]
       |  - timestamp_seconds + label per item (not bounding boxes)
       |
       V (Crop Pipeline Service)
       |
Keyframe @ timestamp_seconds  ──────────────────▶  Open-Vocabulary Detector (Grounding DINO / OWLv2)
       |                                                   |
       |   Bounding box [ymin,xmin,ymax,xmax] normalised 0-1000
       V                                                   V
 Cropped JPEG (evidence image)                        High-precision box
       |                                                   |
       V                                                   V
  R2: evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg  Supabase evidence_crops table
                                                 (embedding vector(1024), timestamp_seconds, bounding_box)
       |
       | (Text Embedding Model generates vector(1024) from item description)
       V
Search & Retrieval
       |
 POST /api/v1/incidents/search (vss-agent Search Route, search-contract-v1)
       |   - Input: natural-language query text + filters
       |   - Backend generates query text embedding vector(1024)
       V
 search_evidence_items RPC (Supabase Postgres, service_role only)
       |   - pgvector cosine distance over evidence_crops.embedding <=> query_embedding
       |   - Filters: item_type, incident_type, severity, min_similarity
       |   - Returns candidates with similarity_score, image URL, timestamp_seconds, bounding_box
       |
       V (Critic Always On)
       |
  VLM Critic evaluates every candidate hit against the user query using the cropped screenshot
       and item description. Outputs confirmed/rejected with objective rationale.
       |
       V (Result Persistence)
       |
  Both retrieval ranking and critic verdicts persisted into query_results table
       |
       V (Console Display)
       |
  Ranked results returned to incident-console-v2: each result shows
  - Incident type and description
  - Timestamp (hh:mm:ss)
  - Cropped object image with bounding box label
  - Critic verdict (confirmed/rejected)
  - Rank and similarity score

```

### Key Data Flow Details

1. **VLM P1 Extraction** (incident-contract-v3): The VLM returns `timestamp_seconds` and a short searchable **label** for each entity/instrument/asset. **Bounding boxes are NOT requested** from the VLM (0% well-framed in pilot). The incident report schema uses `timestamp_seconds` (INT) and descriptive text per item, whilst `start_timestamp` and `end_timestamp` define incident-level temporal boundaries.

2. **Crop Pipeline**: When an incident report is generated, a lightweight CPU utility extracts the video frame at `timestamp_seconds`, then an open-vocabulary detector (Grounding DINO or OWLv2) runs on the single frame with the item name as prompt. The detector produces a tight bounding box (with 5% padding). The cropped JPEG is uploaded to Cloudflare R2 and the metadata (`timestamp_seconds`, `bounding_box`, `image` R2 key, `item_name`, `item_description`) is stored in the `evidence_crops` table. A text embedding model generates the pgvector embedding from the item description/text.

3. **evidence_crops table** (new, unified):
   - Consolidates entities, instruments, and assets into one table
   - Columns: `incident_id, model_run_id, item_type, item_id, item_name, description, timestamp_seconds, bounding_box INTEGER[4], image (R2 key), embedding vector(1024)`
   - HNSW index on `embedding` for cosine distance search
   - RLS: `service_role` only

4. **Search Route & Database RPC**:
   - Frontend calls REST route `POST /api/v1/incidents/search` (`search-contract-v1`) with natural-language query text and optional filters.
   - The backend service generates `query_embedding` and executes the `search_evidence_items` RPC (Supabase Postgres, restricted to `service_role`).
   - The RPC takes `p_query_embedding`, `top_k`, `min_similarity`, and applies filters (`item_type`, `incident_type`, `severity_level`, `min_similarity`).
   - Queries pgvector HNSW over `evidence_crops.embedding <=> p_query_embedding`.
   - Joins with `videos` (via `selected_model_run_id`) and `incidents` to return candidate metadata.
   - **Critic Always On**: After retrieval, the VLM Critic evaluates each candidate hit against the original user query using the cropped screenshot and item description. Both ranking and critic verdicts are persisted into `query_results` before returning results.
   - In `incident-console-v2`, search goes through the `EvidenceSearchRepository` port, whose planned adapter calls this route ([console spec §3.1](console-hexagonal-architecture.md#libportssearchts-mvp2-extension-port)).

5. **Query Results** (new table):
   - Records: `query_id`, `rank`, `similarity_score`, `critic_verdict` (confirmed/rejected/unverified), `critic_rationale`
   - Enables audit trails and critic feedback loops

6. **Chat Endpoint**: Follow-up conversational queries against the same search infrastructure. The chat REST endpoint receives conversational history, generates query embeddings, and invokes the `search_evidence_items` RPC with the resolved query context.

---

## 3. Shared Contracts & Workstream Consumption

| Contract / Schema | Description | Consumed By |
|---|---|---|
| **incident-contract-v3** (`contracts/incident_report.schema.json`) | Report schema: `incident{type, title, start_timestamp, end_timestamp, description, severity_level, severity_reason, confidence_score, location}`, `entities[]`, `instruments[]`, `assets[]`, `timeline[]`, `uncertainties[]`. Key fields: `timestamp_seconds` (INT, per item: entities, instruments, assets; `start_timestamp` and `end_timestamp` per incident), `entity type {human, animal, unknown}`, `instrument threat_level 1-5`, `asset name/description`. **Does NOT include bounding boxes.** | VM backend (vss-agent P1 extraction), eval PR 119, console gateway mode |
| **evidence_crops** (new Supabase table) | Unified table: `(incident_id, model_run_id, item_type, item_id, item_name, description, timestamp_seconds, bounding_box INTEGER[4], image R2 key, embedding vector(1024))`. HNSW index on embedding. RLS service_role-only. | search route, chat endpoint, evidence loader (migration delivered in PR 134) |
| **query_results** (new Supabase table) | Records: `id, query_id, incident_id, model_run_id, item_type, item_id, rank, similarity_score, critic_verdict, critic_rationale, retrieved_at`. | PR 119 (eval), search route, critic audit |
| **search-contract-v1** (REST endpoint) | `POST /api/v1/incidents/search`. Parameters: `query` (natural-language string), `top_k`, `min_similarity`, `item_types[]`, `incident_types[]`, `min_severity`, `max_severity`. Returns ranked results with incident metadata, item fields, similarity score, image URL, timestamp, and critic verdict. | PR 118 (frontend search), PR 119 (eval) |
| **search_evidence_items** (Database RPC) | Supabase Postgres function. Parameters: `p_query_embedding vector(1024)`, `top_k`, `min_similarity`, `item_types[]`, `incident_types[]`, `min_severity`, `max_severity`. Returns matching candidate table. RLS/Permissions: `service_role` only. | VM backend search route, PR 119 (retrieval benchmarks) |
| **chat-contract-v1** (REST endpoint) | `POST /api/v1/incidents/chat`. Parameters: `session_id` (optional), `messages[]` (`{role: "user" | "assistant", content}`), `context` (`{scope: "global" | "incident", incident_id, evidence_crop_ids}`). Returns assistant response with grounded evidence citations (`incident_id`, `item_id`, `item_type`, `timestamp_seconds`, `crop_image_url`). | PR 118 (frontend chat) |
| **incident-contract-v3 taxonomy** | Retained from contract-v2: `road accident`, `burglary`, `explosion`, `assault`, `animal attack`. `entity type {human, animal, unknown}`. `instrument threat_level 1-5`. Item IDs: sequential `E1..`, `I1..`, `A1..`. | All workstreams |

---

## 4. Workstream Dependencies & Order

The PR workstreams and the VM backend steps form a chain of dependencies. Each waits for the previous step's contract/schema to be finalised.

### VM Backend Steps (built separately, outside this repo):

| Step | Deliverable | Depends On | Status |
|---|---|---|---|
| **Step 1** | `incident-contract-v3` schema, `vss-agent` native P1 extraction, Brev Switchyard integration | - | Delivered |
| **Step 2** | Mock backend with search-profile superset mock (port 7778) | Step 1 | Delivered |
| **Step 3** | Crop service: detector port, `CropEvidenceService` on keyframes, JPEG quality 85, 5% padding, R2 canonical key layout, `EvidenceStore` port | Step 2 | Delivered (`services/agent/src/vss_agents/utils/crop_evidence.py`) |
| **Step 4** | `POST /api/v1/incidents/search` REST route in `vss-agent` with always-on critic (configurable delay spacing via `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS`, default 1.0s, 0 disables), query persistence, and hexagonal `SearchStore` port (`InMemorySearchStore` and `SupabaseSearchStore` calling `search_evidence_items` RPC with Cloudflare R2 presigned crop URL resolution) | Step 3 | Delivered (`services/agent/src/vss_agents/api/incident_search.py`) |
| **Step 5** | Chat endpoint `POST /api/v1/incidents/chat` (resolving history context against search infrastructure) | Step 4 | Delivered (`services/agent/src/vss_agents/api/incident_chat.py`, `chat-contract-v1`) |
| **Step 6** | `start.sh` bringing search up (always on, no --search flag) | Step 5 | Delivered (`start.sh` brings up search route unconditionally in both VM and local modes with always-on critic and persisted ranking/verdicts) |

### PR Workstreams (in this repo, building docs + UI/code):

| PR | Focus | Depends On | Blocks |
|---|---|---|---|
| **PR 118** (frontend) | Search box, results display, chat endpoint, theming | VM backend Step 4 (search REST route), Step 5 (chat REST route) | Cannot display search results or chat without REST API routes |
| **PR 119** (eval) | System vs one-shot baseline, retrieval benchmarks, critic verdicts | VM backend Step 3 (evidence_crops with embeddings), Step 4 (search RPC / REST route) | Cannot run retrieval benchmarks without embeddings and search RPC |
| **PR 120** (console middle layer) | Hexagonal ports and adapters in `incident-console-v2` (`lib/ports/`, `lib/adapters/supabase/`, `lib/application/`); evidence search port shaped on search-contract-v1 | VM backend Step 4 (search REST route) for the search adapter | Console search needs the port's agent adapter |
| **PR 126** (data & search layer) | Live RLS & RPC lockdown, connection & VM persistence verification (the `evidence_crops` / `query_results` / `search_evidence_items` migration was delivered in PR 134) | VM backend Step 1 (contract-v3), Step 2 (mock backend) | Cannot verify the live schema without the contract and mock backend |

**Order of operations:**
1. VM backend Step 1: `incident-contract-v3` lands → database migration work can start (migration delivered in PR 134)
2. VM backend Step 2: Mock backend with search-profile mock → the migration is validated locally
3. VM backend Step 3: Crop service + `evidence_crops` table → PR 119 can embed and test retrieval
4. VM backend Step 4: `search_evidence_items` RPC and search REST route → PR 118 can implement search UI; PR 119 evaluates critic verdicts
5. VM backend Step 5: Chat REST endpoint → PR 118 implements chat
6. VM backend Step 6: `start.sh` search up → the PR workstreams integrate end-to-end

---

## 5. Shared Conventions, Environments & Definitions

The PR task docs assume the following conventions and environment setup. This section makes them explicit.

### Environment

- **Zero-GPU local development:** `mock-backend/base_profile_mock/` (port 7777) provides a full mock of vss-agent API + VST + inference behind one FastAPI process. `mock-backend/search_profile_mock/` (port 7778) adds search-profile mock for MVP2 prep. `vlm-gateway/` (port 8600) holds the Brev key server-side.
- **GPU-backed VM:** `kwanz-ws` with 2x NVIDIA RTX A6000 48 GB. `start.sh --mode vm` launches native `vss-agent` on port 8000. Docker appliances (HAProxy, VIOS, Redis, Kafka, Elasticsearch) run in compose.
- **Secrets:** Server-side only. `VLM_GATEWAY_API_KEY` owned by gateway, not browser (`NEXT_PUBLIC_` never used for credentials). `/api/health` returns booleans only.

### Conventions

- **Item ID formats:** Sequential `E1..`, `I1..`, `A1..` (contract-v2). Enforced by `id-normalization-v1` repair.
- **Timestamp format:** Integer seconds (`timestamp_seconds INT`) at the application and contract boundary for evidence items (entities, instruments, assets); incident temporal boundaries use `start_timestamp` and `end_timestamp`. DB stores `VARCHAR(32)` for legacy compatibility (`M:SS` clock strings), but contract and app layer use integer seconds.
- **Taxonomy:** `incident-contract-v2` taxonomy retained: `road accident`, `burglary`, `explosion`, `assault`, `animal attack`. Entity type: `human`, `animal`, `unknown`. Instrument `threat_level` 1-5.
- **RLS and RPC lockdown:** New MVP2 tables (`evidence_crops`, `query_results`) enable RLS; privileges revoked from `anon`/`authenticated`; granted to `service_role` only. RPC execution permissions restricted to `service_role` via `REVOKE EXECUTE ON FUNCTION search_evidence_items FROM anon, authenticated; GRANT EXECUTE ON FUNCTION search_evidence_items TO service_role;`.
- **pgvector:** Supabase Postgres `vector` extension enabled. HNSW index `m=16, ef_construction=64` on `evidence_crops.embedding` for cosine distance (`<=>`).
- **Critic always on:** Every search candidate is evaluated by the VLM critic; both ranking and verdict are persisted. No opt-in `--search` flag; search starts automatically with `start.sh`.
- **R2 key layout:** `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg` (e.g. `evidence/Explosion001/MR001/entities/E1.jpg`).
- **Search parameters:**
  - REST route: `query` (natural-language string), `top_k DEFAULT 10`, `min_similarity DEFAULT 0.0`, `hide_rejected DEFAULT true`, `item_types[]`, `incident_types[]`, `min_severity`, `max_severity`.
  - Database RPC: `p_query_embedding vector(1024)`, `top_k DEFAULT 10`, `min_similarity DEFAULT 0.2`, `item_types[]`, `incident_types[]`, `min_severity`, `max_severity`.

### Definitions (for PR task doc consistency)

- **Evidence crop:** A targeted object image (JPEG) extracted from a video frame at `timestamp_seconds`, cropped by an open-vocabulary detector's bounding box, stored in R2 with metadata in `evidence_crops`.
- **Critic verdict:** `confirmed` (VLM confirms the crop matches the user query), `rejected` (VLM says it does not), or `unverified` (critic evaluation failure or fallback), with an objective rationale string.
- **Query result:** A ranked search hit from `search_evidence_items`, including similarity_score, critic_verdict, and image URL.
- **One-shot baseline:** A retrieval run that scores results using only the initial query embedding, without critic re-evaluation. System baseline uses the full pipeline (critic always on).
- **Natural-language evidence search:** The user types a query (e.g. "crowbar"), the system retrieves matching evidence items across all stored incidents, each with timestamp and cropped object image.

---

## 6. Per-Workstream Context

### PR 118 - Frontend (search, chat, theming)

**File:** `.docs/mvp2/frontend.md` (to be created by PR assignee)

> [!IMPORTANT]
> **TODO [PR 118]: Frontend Console Search UI & Interactive Intelligence**
> - **Missing:** Implementation of `/search` route, natural-language query input with filter chips, search hit cards rendering crop image with threat and critic badges, jump-to-clip video scrubber integration, user relevance feedback persisting to `query_results`, evidence timeline with crop drawer on report page, saved searches drawer, theme token loader for dynamic styling, and conversational Q&A chat panel.
> - **Owner:** PR 118 (`docs(dev-profile-incident): MVP2 frontend (search, chat, theming) workstream tasks`)
> - **Stand-in Placeholder:** `incident-console-v2/app/search/page.tsx` rendering mock results via `search-contract-v1` against `mock-backend` on port 7778; `components/chat-drawer.tsx` connecting to mock chat route.

**What PR 118 needs from this overview:**
- The `POST /api/v1/incidents/search` REST contract (query text, filter parameters, return shape, critic verdict format)
- The `POST /api/v1/incidents/chat` REST contract (conversation history context + query)
- The evidence crop display format: cropped JPEG with bounding box label and critic verdict
- The theming conventions (how confirmed/rejected results are styled)
- Dependency on VM backend Steps 4 and 5 (search REST route and chat REST endpoint must be live)
- Zero-GPU local development: use `mock-backend/search_profile_mock` (port 7778) and `vlm-gateway` for mock inference
- The `query_results` table structure for displaying critic rationale and audit trails

**Key interfaces:**
- `POST /api/v1/incidents/search` with natural-language query text from the frontend
- Display ranked results with image, timestamp, critic verdict (critic calls staggered with default 1.0s delay via `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` to prevent upstream 429 rate limits)
- `POST /api/v1/incidents/chat` sends conversation history and follow-up query text to the chat route

### PR 119 - Eval (system vs one-shot baseline, retrieval)

**File:** `.docs/mvp2/eval.md` (to be created by PR assignee)

> [!IMPORTANT]
> **TODO [PR 119]: System-Level Benchmarking & Retrieval Suite**
> - **Missing:** System-level evaluation framework comparing one-shot VLM prompt baseline against the full VSS pipeline, independent non-circular benchmark queries dataset (50+ queries), retrieval benchmark suite (`eval/scripts/eval_retrieval.py` measuring P@K, R@K, MRR, F1), always-on critic utility ablation study, open-vocabulary detector comparative framing evaluation (Grounding DINO, OWLv2, Florence-2), and embedding model comparison.
> - **Owner:** PR 119 (`docs(dev-profile-incident): MVP2 eval (system vs one-shot baseline, retrieval) workstream tasks`)
> - **Stand-in Placeholder:** `eval/eval_data/retrieval_benchmark_sample.json` query set; `eval/scripts/eval_retrieval.py` reporting mock metrics (`P@5=0.80, R@5=0.75, MRR=0.85`).

**What PR 119 needs from this overview:**
- The `evidence_crops` table schema (especially `embedding vector(1024)`, `timestamp_seconds`, `bounding_box`) for embedding generation and HNSW indexing
- The `query_results` table structure (rank, similarity_score, critic_verdict, critic_rationale) for evaluating critic impact
- The `search_evidence_items` RPC and search REST route contracts for running retrieval benchmarks
- The difference between **one-shot baseline** (retrieval only, no critic) and **system baseline** (retrieval + critic always on)
- Taxonomy and item type filters (`item_type IN ('entity','instrument','asset')`, `incident_types`)
- Mock backend: `mock-backend/search_profile_mock` (port 7778) for local eval runs without GPU
- VM backend Steps 3 and 4 must be live: crop service producing embeddings, and search RPC with pgvector

**Key metrics for eval:**
- Precision@k, Recall@k with critic verdicts aggregated
- Critic accuracy: % of hits confirmed by the VLM critic
- One-shot vs system baseline delta (critic rejection rate, ranking shift)

### PR 120 - incident-console-v2 Middle Layer

**File:** [`.docs/mvp2/console-hexagonal-architecture.md`](console-hexagonal-architecture.md)

Hexagonal ports and adapters between the console's API routes and Supabase (no database migrations). Console evidence search goes through `EvidenceSearchRepository`, shaped on search-contract-v1; its planned adapter calls the vss-agent's `POST /api/v1/incidents/search` ([`../vm-api-contracts.md`](../vm-api-contracts.md)), and the adapter and a console search route come later.

### PR 126 - Data and Search Layer

**File:** `.docs/mvp2/db-migration.md` (on the PR 126 branch, https://github.com/Danwidj/video-search-and-summarization/pull/126)

> [!IMPORTANT]
> **TODO [PR 126]: MVP2 Data and Search Layer**
> - **Missing:** Live Supabase RLS lockdown migration verification (`20261016000000`), standalone crop embedding generator, batch re-analysis ingestion loader, and Cloudflare R2 evidence crop storage management. The MVP2 migration `20261016120000_mvp2_evidence_search_and_crops.sql` (`evidence_crops`, `query_results`, `search_evidence_items`) is already delivered and applied.
> - **Owner:** PR 126 (`docs(dev-profile-incident): MVP2 database migration and search layer workstream tasks`)
> - **Stand-in Placeholder:** Table definitions in §2 and the migration checklist below; the console never queries these tables (it searches through the vss-agent route).

The DDL, RLS and RPC items below are delivered and applied (`supabase/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`, PR 134); PR 126 keeps the live verification.

**What PR 126 needs from this overview:**
- The complete `evidence_crops` migration DDL (table definition, HNSW index, RLS lockdown)
- The `query_results` migration DDL (table definition, indexes)
- The `search_evidence_items` RPC migration (PG function definition with pgvector parameters)
- RLS policy: `ENABLE ROW LEVEL SECURITY`, `REVOKE ALL FROM anon, authenticated`, `GRANT ALL TO service_role`
- RPC execution permission lockdown: `REVOKE EXECUTE ON FUNCTION search_evidence_items FROM anon, authenticated; GRANT EXECUTE ON FUNCTION search_evidence_items TO service_role;`
- pgvector extension: `CREATE EXTENSION IF NOT EXISTS vector;`
- Connection verification, and verifying VM `vss-agent` persists reports to Supabase end to end (hexagonal decoupling of `incident-console-v2` is PR 120)
- The `start.sh` launcher: search is always on (no `--search` flag), starts in <5 seconds because it uses Supabase pgvector and Brev Switchyard for critic inference (this launcher change belongs to VM backend Step 6 `start.sh` search task, not to PR 126's scope)
- Dependency on VM backend Step 1 (`incident-contract-v3`) and Step 2 (mock backend)

**Migration checklist** (steps 1-8 delivered in PR 134):
1. `CREATE EXTENSION IF NOT EXISTS vector;`
2. Create `evidence_crops` table with all columns, PRIMARY KEY, FOREIGN KEY, HNSW index
3. Create `query_results` table with all columns, PRIMARY KEY, two secondary indexes
4. `ALTER TABLE evidence_crops ENABLE ROW LEVEL SECURITY;`
5. `REVOKE ALL ON evidence_crops FROM anon, authenticated; GRANT ALL ON evidence_crops TO service_role;`
6. Same RLS policies for `query_results`
7. Create or replace `search_evidence_items` RPC function
8. Lock down RPC execution permissions: `REVOKE EXECUTE ON FUNCTION search_evidence_items FROM anon, authenticated; GRANT EXECUTE ON FUNCTION search_evidence_items TO service_role;`
9. Verify `start.sh --mode local` launches search in <5 seconds

---

## 7. Still-Not-Final (Planned, Not Final) & Master TODO Index

The following specifications are planned, not final, pending completion of the open workstreams and the MVP2 contracts branch (`fm/vss-mvp2-contracts`):

> [!IMPORTANT]
> **TODO [Contracts / PR 119]: Bounding Box Format & Detector Framing**
> - **Missing:** Final detector model selection (Grounding DINO vs OWLv2 vs Florence-2) and exact bounding box coordinate constraints in schema.
> - **Owner:** Contracts branch `fm/vss-mvp2-contracts` and PR 119
> - **Stand-in Placeholder:** `[ymin, xmin, ymax, xmax]` normalised integers 0–1000 with 5% margin padding.

> [!IMPORTANT]
> **TODO [Contracts / PR 119]: Critic Model Specification & Verification Prompt**
> - **Missing:** Final critic model selection (`nvidia/cosmos-3-nano-reasoner` or alternate) and strict structured chat completion prompt.
> - **Owner:** Contracts branch `fm/vss-mvp2-contracts` and PR 119
> - **Stand-in Placeholder:** Structured output schema returning `{verdict: "confirmed" | "rejected", rationale: string}`.

> [!IMPORTANT]
> **TODO [PR 126 / PR 119]: Embedding Model & Vector Dimension**
> - **Missing:** Benchmark selection between NVIDIA NeMo NIM, OpenAI text-embedding-3, and MiniLM.
> - **Owner:** PR 126 and PR 119
> - **Stand-in Placeholder:** `vector(1024)` column definition on `evidence_crops.embedding`. The agent embeds evidence and queries itself; the console never embeds.

> [!IMPORTANT]
> **TODO [PR 119]: Search RPC Parameter Tuning**
> - **Missing:** Calibrated default thresholds for `min_similarity` and `top_k`.
> - **Owner:** PR 119 (tuning); the RPC is delivered in `20261016120000_mvp2_evidence_search_and_crops.sql`
> - **Stand-in Placeholder:** `top_k DEFAULT 10`; the REST route sends `min_similarity DEFAULT 0.0` (the RPC keeps its own 0.2 default, unused by the route).

> [!NOTE]
> **COMPLETED [Contracts / Chat Endpoint]: Conversational Q&A Schema (`chat-contract-v1`) & Backend Endpoint**
> - **Delivered:** JSON schemas defining multi-turn message history and grounded assistant responses with citations for `POST /api/v1/incidents/chat` under `contracts/chat-contract-v1/`.
> - **Endpoints:** Native endpoint implemented in `vss-agent` (`services/agent/src/vss_agents/api/incident_chat.py`) with hexagonal `SearchClient` port and in-memory adapter; mock endpoint in `mock-backend/base_profile_mock` (port 7777).

> [!IMPORTANT]
> **TODO [Contracts / PR 126]: Item Type Filter Enum Alignment**
> - **Missing:** Finalization of item category enum in `search-contract-v1` and database RPC.
> - **Owner:** Contracts branch `fm/vss-mvp2-contracts` and PR 126
> - **Stand-in Placeholder:** Enum values `'entity'`, `'instrument'`, `'asset'`.

> [!NOTE]
> **COMPLETED [fm/vss-mvp2-backfill-timestamps]: Targeted Timestamp Backfill Pass & Production Evidence Loader**
> - **Delivered:** `scripts/backfill_official_timestamps.py` with bounded concurrency, batch sizing, idempotent resumability, and per-item failure isolation.
> - **Production Adapters:** `LiveCropClient` (remote VLM detector + R2 upload), `RemoteTextEmbedderAdapter` (NVIDIA-hosted `nvidia/llama-nemotron-embed-vl-1b-v2` embeddings at 1024 dimensions), and `LiveEvidenceStore` (`SupabaseEvidenceStore` upserting into `evidence_crops`). In-memory fakes retained for unit tests and `--dry-run`.

---

### Master Workstream TODO Index

| Item | Missing Component | Owning Workstream | Stand-in Placeholder |
|---|---|---|---|
| 1 | Search Route, UI & Hit Cards | PR 118 | `/search` mock route & cards |
| 2 | Evidence Timeline & Crop Gallery | PR 118 | Scrubber markers at `timestamp_seconds` |
| 3 | Conversational Q&A Chat | Chat Endpoint / PR 118 | `chat-contract-v1`, native `vss-agent` chat endpoint & mock |
| 4 | External Style Guide Theming | PR 118 | JSON tokens to CSS variables fallback |
| 5 | Baseline vs Full System Benchmark | PR 119 | One-shot VLM baseline evaluation harness |
| 6 | Retrieval Benchmark Suite (50+ queries) | PR 119 | `eval/scripts/eval_retrieval.py` |
| 7 | Always-On Critic Ablation Study | PR 119 | Precision vs latency false-positive report |
| 8 | Open-Vocab Detector Evaluation | PR 119 | Grounding DINO vs OWLv2 vs Florence-2 report (detector port & CropEvidenceService implemented in services/agent) |
| 9 | Embedding Model Comparison | PR 119 / PR 126 | NeMo vs OpenAI vs MiniLM benchmark |
| 10 | Live DB RLS Lockdown Verification | PR 126 | Verification test suite on migration `20261016000000` |
| 11 | `evidence_crops` & `query_results` Migration | PR 134 | Delivered (`supabase/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`; applied to live Supabase) |
| 12 | `search_evidence_items` Database RPC | PR 134 | Delivered (`supabase/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`; applied to live Supabase) |
| 13 | Crop Embedding Generator & Ingestion | Backfill | Delivered via `scripts/backfill_official_timestamps.py` |
| 14 | Console Middle Layer (ports and adapters) | PR 120 | `incident-console-v2/lib/ports/`, `lib/adapters/supabase/` |
| 15 | `search-contract-v1` REST Schemas | `fm/vss-mvp2-contracts` | `search_request.schema.json` & `search_response.schema.json` |
| 16 | Mock Search Backend (port 7778) | `fm/vss-mvp2-contracts` | Search mock routers in `mock-backend/search_profile_mock` |
| 17 | Targeted Timestamp Backfill Script | `fm/vss-mvp2-backfill-timestamps` | `scripts/backfill_official_timestamps.py` script & test suite |

---

## Appendix: MVP2 Plan Genealogy

- **Original MVP2 plan** (`vss-mvp2-plan-v2/report.md`): Proposed VLM bounding boxes via `incident-contract-v3`. Boxes were 0% well-framed in the box-accuracy pilot.
- **Amended plan** (after box-accuracy pilot `/Users/danielwidjaja/workspace/firstmate/data/vss-box-pilot/report.md`): VLM bounding boxes rejected (0% well-framed). Timestamps over 95% accurate. Architecture shifted to **Hybrid: VLM timestamp + open-vocabulary detector for boxes** (Option c). `incident-contract-v3` adds only `timestamp_seconds` + short searchable label per item; boxes come from a separate detector stage stored with the crops.
- **This doc** (MVP2 overview): Reflects the amended plan's end goal and architecture.

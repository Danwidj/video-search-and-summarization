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
       |  - incident type/title/description + severity
       |  - timestamp_seconds (per incident)
       |  - entities [{entity_id, type, description}]
       |  - instruments [{instrument_id, name, threat_level, holder_entity_id}]
       |  - assets [{asset_id, name, description}]
       |  - timestamp_seconds + label per item (not bounding boxes)
       |
       V (Crop Pipeline Service)
       |
Keyframe @ timestamp_seconds  ──────────────────▶  Open-Vocabulary Detector (Grounding DINO / OWLv2)
       |                                                   |
       |   Bounding box [ymin,xmin,ymax,xmax] normalized 0-1000
       V                                                   V
 Cropped JPEG (evidence image)                        High-precision box
       |                                                   |
       V                                                   V
  R2: evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg  Supabase evidence_crops table
                                                 (embedding vector(1024), timestamp_seconds, bounding_box)

       V (Search RPC)
       |
 POST /api/v1/incidents/search  ──────────────────────▶  vss-agent search_evidence_items RPC
       |   - query text embedding
       |   - pgvector cosine distance over evidence_crops.embedding
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

1. **VLM P1 Extraction** (incident-contract-v3): The VLM returns `timestamp_seconds` and a short searchable **label** for each entity/instrument/asset. **Bounding boxes are NOT requested** from the VLM (0% well-framed in pilot). The incident report schema uses `timestamp_seconds` (INT) and descriptive text only.

2. **Crop Pipeline**: When an incident report is generated, a lightweight CPU utility extracts the video frame at `timestamp_seconds`, then an open-vocabulary detector (Grounding DINO or OWLv2) runs on the single frame with the item name as prompt. The detector produces a tight bounding box (with 5% padding). The cropped JPEG is uploaded to Cloudflare R2 and the metadata (`timestamp_seconds`, `bounding_box`, `image` R2 key, `item_name`, `item_description`) is stored in the `evidence_crops` table. The detector also generates a pgvector embedding from the item description/text.

3. **evidence_crops table** (new, unified):
   - Consolidates entities, instruments, and assets into one table
   - Columns: `incident_id, model_run_id, item_type, item_id, item_name, description, timestamp_seconds, bounding_box INTEGER[4], image (R2 key), embedding vector(1024)`
   - HNSW index on `embedding` for cosine distance search
   - RLS: `service_role` only

4. **Search RPC** (`search_evidence_items`):
   - Takes a query text embedding, `top_k`, `min_similarity`
   - Queries pgvector HNSW over `evidence_crops.embedding <=> p_query_embedding`
   - Applies filters: `item_type`, `incident_type`, `severity_level`, `min_similarity`
   - Joins with `videos` (via `selected_model_run_id`) and `incidents` to return metadata
   - **Critic Always On**: After retrieval, the VLM Critic evaluates each candidate hit against the original user query using the cropped screenshot and item description. Both ranking and critic verdicts are persisted into `query_results` before returning results.

5. **Query Results** (new table):
   - Records: `query_id`, `rank`, `similarity_score`, `critic_verdict` (confirmed/rejected/unverified), `critic_rationale`
   - Enables audit trails and critic feedback loops

6. **Chat Endpoint**: Follow-up conversational queries against the same search infrastructure, using the same `search_evidence_items` RPC with conversation history context.

---

## 3. Shared Contracts & Workstream Consumption

| Contract / Schema | Description | Consumed By |
|---|---|---|
| **incident-contract-v3** (`contracts/incident_report.schema.json`) | Report schema: `incident{type, title, start_timestamp, end_timestamp, description, severity_level, severity_reason, confidence_score, location}`, `entities[]`, `instruments[]`, `assets[]`, `timeline[]`, `uncertainties[]`. Key fields: `timestamp_seconds` (INT, per incident), `entity type {human, animal, unknown}`, `instrument threat_level 1-5`, `asset name/description`. **Does NOT include bounding boxes.** | VM backend (vss-agent P1 extraction), eval PR 119, console gateway mode |
| **evidence_crops** (new Supabase table) | Unified table: `(incident_id, model_run_id, item_type, item_id, item_name, description, timestamp_seconds, bounding_box INTEGER[4], image R2 key, embedding vector(1024))`. HNSW index on embedding. RLS service_role-only. | PR 120 (data migration), search route, chat endpoint |
| **query_results** (new Supabase table) | Records: `id, query_id, incident_id, model_run_id, item_type, item_id, rank, similarity_score, critic_verdict, critic_rationale, retrieved_at`. | PR 119 (eval), search route, critic audit |
| **search_evidence_items RPC** | `POST /api/v1/incidents/search`. Parameters: query_embedding, top_k, min_similarity, item_types[], incident_types[], min_severity, max_severity. Returns table with incident metadata + item fields + similarity_score + image + timestamp_seconds + bounding_box. Critic verdict persisted to `query_results`. | PR 118 (frontend search), PR 119 (eval), chat endpoint |
| **Chat endpoint contract** | Same `search_evidence_items` RPC with conversation history context parameter. Returns ranked results with critic verdicts and cropped images. | PR 118 (frontend chat) |
| **incident-contract-v3 taxonomy** | Retained from contract-v2: `road accident`, `burglary`, `explosion`, `assault`, `animal attack`. `entity type {human, animal, unknown}`. `instrument threat_level 1-5`. Item IDs: sequential `E1..`, `I1..`, `A1..`. | All workstreams |

---

## 4. Workstream Dependencies & Order

The three PR workstreams and the VM backend steps form a chain of dependencies. Each waits for the previous step's contract/schema to be finalized.

### VM Backend Steps (built separately, outside this repo):

| Step | Deliverable | Depends On |
|---|---|---|
| **Step 1** (in progress) | `incident-contract-v3` schema, `vss-agent` native P1 extraction, Brev Switchyard integration | — |
| **Step 2** | Mock backend with search-profile superset mock (port 7778) | Step 1 |
| **Step 3** | Crop service: open-vocabulary detector (Grounding DINO/OWLv2) on extracted keyframes, R2 upload, `evidence_crops` metadata population | Step 2 |
| **Step 4** | `search_evidence_items` RPC with pgvector HNSW, critic always-on, `query_results` persistence | Step 3 |
| **Step 5** | Chat endpoint (same RPC with history context) | Step 4 |
| **Step 6** | `start.sh` bringing search up (always on, no --search flag) | Step 5 |

### PR Workstreams (in this repo, building docs + UI/code):

| PR | Focus | Depends On | Blocks |
|---|---|---|---|
| **PR 118** (frontend) | Search box, results display, chat endpoint, theming | VM backend Step 4 (search RPC), Step 5 (chat contract) | Cannot display search results or chat without RPC contract |
| **PR 119** (eval) | System vs one-shot baseline, retrieval benchmarks, critic verdicts | VM backend Step 3 (evidence_crops with embeddings), Step 4 (search RPC) | Cannot run retrieval benchmarks without embeddings and search RPC |
| **PR 120** (data & search layer, zero-VM) | `evidence_crops` migration, pgvector setup, RLS lockdown, `start.sh` zero-VM compatibility | VM backend Step 1 (contract-v3), Step 2 (mock backend) | Cannot migrate schema or run search without the contract and mock backend |

**Order of operations:**
1. VM backend Step 1: `incident-contract-v3` lands → PR 120 can start data/migration work
2. VM backend Step 2: Mock backend with search-profile mock → PR 120 validates migration locally
3. VM backend Step 3: Crop service + `evidence_crops` table → PR 119 can embed and test retrieval
4. VM backend Step 4: `search_evidence_items` RPC → PR 118 can implement search UI; PR 119 evaluates critic verdicts
5. VM backend Step 5: Chat endpoint → PR 118 implements chat
6. VM backend Step 6: `start.sh` search up → All three PRs integrate end-to-end

---

## 5. Shared Conventions, Environments & Definitions

The three PR task docs assume the following conventions and environment setup. This section makes them explicit.

### Environment

- **Zero-GPU local development:** `mock-backend/base_profile_mock/` (port 7777) provides a full mock of vss-agent API + VST + inference behind one FastAPI process. `mock-backend/search_profile_mock/` (port 7778) adds search-profile mock for MVP2 prep. `vlm-gateway/` (port 8600) holds the Brev key server-side.
- **GPU-backed VM:** `kwanz-ws` with 2x NVIDIA RTX A6000 48 GB. `start.sh --mode vm` launches native `vss-agent` on port 8000. Docker appliances (HAProxy, VIOS, Redis, Kafka, Elasticsearch) run in compose.
- **Secrets:** Server-side only. `VLM_GATEWAY_API_KEY` owned by gateway, not browser (`NEXT_PUBLIC_` never used for credentials). `/api/health` returns booleans only.

### Conventions

- **Item ID formats:** Sequential `E1..`, `I1..`, `A1..` (contract-v2). Enforced by `id-normalization-v1` repair.
- **Timestamp format:** Integer seconds (`timestamp_seconds INT`) at the application and contract boundary. DB stores `VARCHAR(32)` for legacy compatibility (`M:SS` clock strings), but contract and app layer use integer seconds.
- **Taxonomy:** `incident-contract-v2` taxonomy retained: `road accident`, `burglary`, `explosion`, `assault`, `animal attack`. Entity type: `human`, `animal`, `unknown`. Instrument `threat_level` 1-5.
- **RLS lockdown:** New MVP2 tables (`evidence_crops`, `query_results`) enable RLS; privileges revoked from `anon`/`authenticated`; granted to `service_role` only. RPC execution permissions restricted to `service_role`.
- **pgvector:** Supabase Postgres `vector` extension enabled. HNSW index `m=16, ef_construction=64` on `evidence_crops.embedding` for cosine distance (`<=>`).
- **Critic always on:** Every search candidate is evaluated by the VLM critic; both ranking and verdict are persisted. No opt-in `--search` flag; search starts automatically with `start.sh`.
- **R2 key layout:** `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg` (e.g. `evidence/Explosion001/MR001/entities/E1.jpg`).
- **Search RPC parameters:** `query_embedding vector(1024)`, `top_k DEFAULT 10`, `min_similarity DEFAULT 0.2`, `item_types[]`, `incident_types[]`, `min_severity`, `max_severity`.

### Definitions (for PR task doc consistency)

- **Evidence crop:** A targeted object image (JPEG) extracted from a video frame at `timestamp_seconds`, cropped by an open-vocabulary detector's bounding box, stored in R2 with metadata in `evidence_crops`.
- **Critic verdict:** `confirmed` (VLM confirms the crop matches the user query) or `rejected` (VLM says it does not), with an objective rationale string.
- **Query result:** A ranked search hit from `search_evidence_items`, including similarity_score, critic_verdict, and image URL.
- **One-shot baseline:** A retrieval run that scores results using only the initial query embedding, without critic re-evaluation. System baseline uses the full pipeline (critic always on).
- **Natural-language evidence search:** The user types a query (e.g. "crowbar"), the system retrieves matching evidence items across all stored incidents, each with timestamp and cropped object image.

---

## 6. Per-Workstream Context

### PR 118 — Frontend (search, chat, theming)

**File:** `.docs/mvp2/frontend.md` (to be created by PR assignee)

**What PR 118 needs from this overview:**
- The `search_evidence_items` RPC contract (parameters, return shape, critic verdict format)
- The chat endpoint contract (same RPC with conversation history context)
- The evidence crop display format: cropped JPEG with bounding box label and critic verdict
- The theming conventions (how confirmed/rejected results are styled)
- Dependency on VM backend Steps 4 and 5 (search RPC and chat endpoint must be live)
- Zero-GPU local development: use `mock-backend/search_profile_mock` (port 7778) and `vlm-gateway` for mock inference
- The `query_results` table structure for displaying critic rationale and audit trails

**Key interfaces:**
- `POST /api/v1/incidents/search` from the frontend
- Display ranked results with image, timestamp, critic verdict
- Chat follow-up sends conversation history to the same search RPC

### PR 119 — Eval (system vs one-shot baseline, retrieval)

**File:** `.docs/mvp2/eval.md` (to be created by PR assignee)

**What PR 119 needs from this overview:**
- The `evidence_crops` table schema (especially `embedding vector(1024)`, `timestamp_seconds`, `bounding_box`) for embedding generation and HNSW indexing
- The `query_results` table structure (rank, similarity_score, critic_verdict, critic_rationale) for evaluating critic impact
- The `search_evidence_items` RPC contract for running retrieval benchmarks
- The difference between **one-shot baseline** (retrieval only, no critic) and **system baseline** (retrieval + critic always on)
- Taxonomy and item type filters (`item_type IN ('entity','instrument','asset')`, `incident_types`)
- Mock backend: `mock-backend/search_profile_mock` (port 7778) for local eval runs without GPU
- VM backend Steps 3 and 4 must be live: crop service producing embeddings, and search RPC with pgvector

**Key metrics for eval:**
- Precision@k, Recall@k with critic verdicts aggregated
- Critic accuracy: % of hits confirmed by the VLM critic
- One-shot vs system baseline delta (critic rejection rate, ranking shift)

### PR 120 — Data and Search Layer, Zero-VM

**File:** `.docs/mvp2/db-migration.md` (to be created by PR assignee)

**What PR 120 needs from this overview:**
- The complete `evidence_crops` migration DDL (table definition, HNSW index, RLS lockdown)
- The `query_results` migration DDL (table definition, indexes)
- The `search_evidence_items` RPC migration (PG function definition with pgvector parameters)
- RLS policy: `ENABLE ROW LEVEL SECURITY`, `REVOKE ALL FROM anon, authenticated`, `GRANT ALL TO service_role`
- pgvector extension: `CREATE EXTENSION IF NOT EXISTS vector;`
- Zero-VM compatibility: migration must run against `mock-backend` Postgres-compatible setup, no GPU requirements
- The `start.sh` zero-VM launcher: search is always on (no `--search` flag), starts in <5 seconds because it uses Supabase pgvector and Brev Switchyard for critic inference
- Dependency on VM backend Step 1 (`incident-contract-v3`) and Step 2 (mock backend)

**Migration checklist:**
1. `CREATE EXTENSION IF NOT EXISTS vector;`
2. Create `evidence_crops` table with all columns, PRIMARY KEY, FOREIGN KEY, HNSW index
3. Create `query_results` table with all columns, PRIMARY KEY, two secondary indexes
4. `ALTER TABLE evidence_crops ENABLE ROW LEVEL SECURITY;`
5. `REVOKE ALL ON evidence_crops FROM anon, authenticated; GRANT ALL ON evidence_crops TO service_role;`
6. Same RLS policies for `query_results`
7. Create or replace `search_evidence_items` RPC function
8. Verify `start.sh --mode local` launches search in <5 seconds

---

## 7. Still-Not-Final (Planned, Not Final)

Mark the following as planned, not final, since the VM backend contracts are still being built:

- **Bounding box format** in `evidence_crops.bounding_box`: `[ymin, xmin, ymax, xmax]` normalized integers 0-1000. *Source: incident-contract-v3 decision after box-accuracy pilot; open-vocabulary detector stage.*
- **Critic model and endpoint**: Which VLM critic model (`nvidia/cosmos-3-nano-reasoner` etc.) and the exact `/v1/chat/completions` prompt format. *These are VM backend decisions.*
- **pgvector dimension**: `vector(1024)` dimension. *Confirmed by current schema, but may change with model switch.*
- **RPC parameter defaults**: `top_k DEFAULT 10`, `min_similarity DEFAULT 0.2`. *May be tuned after eval PR 119 runs benchmarks.*
- **Chat endpoint conversation history format**: Exact JSON shape for passing conversation context to `search_evidence_items`. *To be defined by VM backend Step 5.*
- **Item type filter values**: `'entity'`, `'instrument'`, `'asset'`. *Match contract-v2 enum; may be expanded.*

These are marked `planned` not `final` so that this doc does not contradict the contracts when they land.

---

## Appendix: MVP2 Plan Genealogy

- **Original MVP2 plan** (`vss-mvp2-plan-v2/report.md`): Proposed VLM bounding boxes via `incident-contract-v3`. Boxes were 0% well-framed in the box-accuracy pilot.
- **Amended plan** (after box-accuracy pilot `/Users/danielwidjaja/workspace/firstmate/data/vss-box-pilot/report.md`): VLM bounding boxes rejected (0% well-framed). Timestamps over 95% accurate. Architecture shifted to **Hybrid: VLM timestamp + open-vocabulary detector for boxes** (Option c). `incident-contract-v3` adds only `timestamp_seconds` + short searchable label; boxes come from a separate detector stage stored with the crops.
- **This doc** (MVP2 overview): Reflects the amended plan's end goal and architecture.
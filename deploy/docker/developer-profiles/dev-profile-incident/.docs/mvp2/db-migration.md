# Workstream Task: MVP2 Database Migration (Evidence Crops & Query Results)

- **Assignee / Role:** Database Engineer
- **Status:** Ready for implementation (build on this PR branch)
- **Workstream Scope:** Supabase schema migration, pgvector extension, table schemas with RLS lockdown, RPC functions, and SQLAlchemy Core mirroring in `incident-console/db.py`.

---

## 1. Goal

Implement the database schema and storage foundation for MVP2 natural-language evidence search with object crops. This workstream delivers the migration script creating the `evidence_crops` and `query_results` tables in Supabase PostgreSQL, enables the `vector` extension, configures Row-Level Security (RLS) under the strict lockdown policy (revoking access from `anon`/`authenticated` and granting exclusively to `service_role`), provisions the `search_evidence_items` RPC, and mirrors the schema in `incident-console/db.py`.

---

## 2. Dependencies and Constraints

### Upstream Dependencies (In Progress / External)
1. **Database Lockdown Migration (PR #116):**
   - Migration `supabase/migrations/20261016000000_enable_rls_and_lockdown_anon.sql` from [PR #116](https://github.com/Danwidj/video-search-and-summarization/pull/116).
   - This MVP2 migration **must build on top of PR #116**.
   - Under PR #116's lockdown policy, all public tables enable RLS and default-deny access for `anon` and `authenticated`.
   - Any new functions must explicitly execute `REVOKE ALL ON FUNCTION ... FROM PUBLIC, anon, authenticated` and `GRANT EXECUTE ... TO service_role`.
2. **Search API Contract (`contracts/search-contract-v1/`):**
   - Owned by the Captain; defines the search request/response schema.
   - Specifically shapes the data fields joined and returned by `search_evidence_items` RPC.
3. **Report Contract Bump (`incident-contract-v3`):**
   - Owned by the Captain; adds per-item `timestamp_seconds` and a short label for a detector stage.
   - Note: Per pilot findings, bounding boxes do not come from the VLM report; they are produced by a downstream open-vocabulary detector stage and stored alongside crops in `evidence_crops`.

### Scope Boundaries (What NOT to Touch)
- **No Contract Files:** Do not edit or create files in `contracts/`.
- **No VM or Agent Implementation:** Do not implement `vss-agent` search routes or background tasks (`services/agent/`).
- **No Cropping Service:** Do not implement frame extraction or image cropping logic.
- **No Frontend Console Changes:** Do not touch `incident-console-v2/` UI components or routes.
- **No Live DB Execution Without Approval:** Per repository rules, dry-run first and ask before applying migrations to the shared live Supabase instance.
- **Do Not Touch Legacy Pre-v1 Tables:** Do not drop or alter `incident_reports`, `incident_entities`, `incident_instruments`, or `incident_assets`.
- **Do Not Alter Existing Evidence Tables:** Do not modify `entities`, `instruments`, or `assets` columns. All crop, bbox, and embedding data is consolidated into the dedicated `evidence_crops` table.

---

## 3. Tasks / Checklist

- [ ] Enable `vector` PostgreSQL extension via `CREATE EXTENSION IF NOT EXISTS vector;` in a new Supabase migration.
- [ ] Create `evidence_crops` table mapping `(incident_id, model_run_id, item_type, item_id)` with temporal anchor, detector bounding box, R2 image key, and vector embedding column.
- [ ] Create HNSW vector index on `evidence_crops(embedding vector_cosine_ops)` with `(m = 16, ef_construction = 64)` and composite lookup index on `(incident_id, model_run_id)`.
- [ ] Create `query_results` table for recording item-level search hits, ranks, similarity scores, and critic audit trail.
- [ ] Create indexes on `query_results (query_id, rank)` and `query_results (incident_id, model_run_id, item_type, item_id)`.
- [ ] Enable Row-Level Security (RLS) on both `evidence_crops` and `query_results`.
- [ ] Revoke all permissions on `evidence_crops` and `query_results` from `anon` and `authenticated`; grant all permissions strictly to `service_role`.
- [ ] Create `search_evidence_items` RPC function restricted to `service_role` that performs cosine similarity search over official reports (`videos.selected_model_run_id = incidents.model_run_id`).
- [ ] Explicitly revoke execute privileges on `search_evidence_items` from `PUBLIC`, `anon`, and `authenticated`, granting execute strictly to `service_role`.
- [ ] Mirror `evidence_crops` and `query_results` table schemas in `incident-console/db.py` using SQLAlchemy Core definitions.
- [ ] Document the new tables, RPC function, and R2 image key layout in `.docs/data.md` and `.docs/decisions.md`.

---

## 4. Technical Specifications & Interfaces

### 4.1 Findings from Spatial Grounding Pilot
A box-accuracy pilot across 166 evaluated items established that VLMs cannot reliably predict spatial bounding boxes (0.0% well-framed, 99.4% degenerate or complete misses). However, temporal grounding is highly accurate (>95% of predicted timestamps land on the exact frame showing the item).
- Consequently, `incident-contract-v3` adds only `timestamp_seconds` and item labels.
- The spatial bounding box `bounding_box INT[4]` (normalized `[ymin, xmin, ymax, xmax]` in range 0–1000) is generated by a separate open-vocabulary detector stage (e.g. Grounding DINO / OWLv2) on the extracted frame and persisted directly in `evidence_crops`.

### 4.2 Supabase Schema Migration Details
Location: `deploy/docker/developer-profiles/dev-profile-incident/supabase/migrations/<timestamp>_mvp2_evidence_search_and_crops.sql`

#### `evidence_crops` Table
Consolidates crops across all evidence item types (`entity`, `instrument`, `asset`):
- `incident_id VARCHAR(20) NOT NULL`
- `model_run_id VARCHAR(20) NOT NULL`
- `item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset'))`
- `item_id VARCHAR(20) NOT NULL` (sequential IDs: `E1..`, `I1..`, `A1..`)
- `item_name VARCHAR(256) NOT NULL`
- `description TEXT NOT NULL`
- `threat_level INTEGER` (nullable; 1–5 for instruments)
- `holder_entity_id VARCHAR(20)` (nullable; holder reference)
- `timestamp_seconds INTEGER NOT NULL`
- `bounding_box INTEGER[4] NOT NULL` (from detector stage: `[ymin, xmin, ymax, xmax]` normalized 0–1000)
- `image VARCHAR(1024) NOT NULL` (R2 key: `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg`)
- `embedding vector(<DIM>)` (semantic text embedding; dimension depends on model decision)
- `created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc')`
- **Primary Key:** `(incident_id, model_run_id, item_type, item_id)`
- **Foreign Key:** `(incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE`

#### `query_results` Table
Records multi-item search rankings and critic audit verdicts per query:
- `id VARCHAR(36) PRIMARY KEY` (UUID or string ID)
- `query_id VARCHAR(20) NOT NULL REFERENCES queries(id) ON DELETE CASCADE`
- `incident_id VARCHAR(20) NOT NULL`
- `model_run_id VARCHAR(20) NOT NULL`
- `item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset'))`
- `item_id VARCHAR(20) NOT NULL`
- `rank INTEGER NOT NULL`
- `similarity_score DOUBLE PRECISION NOT NULL`
- `critic_verdict VARCHAR(16) NOT NULL CHECK (critic_verdict IN ('confirmed', 'rejected', 'unverified'))`
- `critic_rationale TEXT`
- `retrieved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc')`
- **Foreign Key:** `(incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE`

#### `search_evidence_items` RPC
- Signature:
  - `p_query_embedding vector(<DIM>)`
  - `p_top_k INTEGER DEFAULT 10`
  - `p_min_similarity DOUBLE PRECISION DEFAULT 0.2`
  - `p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset']`
  - `p_incident_types TEXT[] DEFAULT NULL`
  - `p_min_severity INTEGER DEFAULT NULL`
  - `p_max_severity INTEGER DEFAULT NULL`
- Behavior:
  - Must join `evidence_crops` with `videos` and `incidents`.
  - Must scope strictly to official reports: `v.id = ec.incident_id AND v.selected_model_run_id = ec.model_run_id` and `inc.incident_id = ec.incident_id AND inc.model_run_id = ec.model_run_id`.
  - Computes similarity score as `(1.0 - (ec.embedding <=> p_query_embedding))`.
  - Orders by `ec.embedding <=> p_query_embedding ASC` with `LIMIT p_top_k`.
  - Execution permissions: `SECURITY INVOKER`, `STABLE`, revoked from `PUBLIC, anon, authenticated`, granted exclusively to `service_role`.

### 4.3 SQLAlchemy Core Schema Mirroring
File: `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py`
- Add `evidence_crops` and `query_results` table definitions to `metadata`.
- Match data types, foreign keys, and cascading rules. Note: pgvector column in SQLAlchemy can use `pgvector.sqlalchemy.Vector` or fallback to custom/array representation if client does not load the vector package.

---

## 5. Open Questions & Decisions

1. **Embedding Model Selection & Vector Dimension (`<DIM>`):**
   - The choice of text embedding model is currently an open Captain decision:
     - **Option A (Recommended):** NVIDIA NeMo Retriever NIM (`nvidia/llama-3.2-nv-embedqa-1b-v2`) via Brev/NGC (1024 dimensions).
     - **Option B:** OpenAI `text-embedding-3-small` (1536 dimensions).
     - **Option C:** Local CPU sentence-transformers (`all-MiniLM-L6-v2`, 384 dimensions).
   - *Action for Assignee:* Confirm the final embedding model with the Captain before hardcoding the `vector(<DIM>)` length in the migration DDL and HNSW index.
2. **PR #116 Merge Status:**
   - Verify that PR #116 is merged or base this migration timestamp after `20261016000000` to maintain clean migration sequencing.

---

## 6. Definition of Done

- [ ] Supabase migration SQL file is created under `deploy/docker/developer-profiles/dev-profile-incident/supabase/migrations/` and passes SQL syntax verification.
- [ ] Migration applies cleanly in a transaction, sets up RLS and privileges as specified, and notifies PostgREST schema cache reload.
- [ ] SQLAlchemy Core definitions in `incident-console/db.py` are updated and pass Python linting/type checks.
- [ ] Documentation updates to `.docs/data.md` and `.docs/decisions.md` are included.
- [ ] Live migration dry-run plan is prepared for execution approval.

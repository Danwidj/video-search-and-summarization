# Workstream Task: MVP2 Data and Search Layer (Zero-VM Architecture)

- **Assignee / Role:** Database & Search Engineer
- **Status:** Ready for implementation (build on this PR branch)
- **Workstream Scope:** Extended data and search layer operating entirely without VM access — applying the merged RLS lockdown migration to live Supabase, comprehensive RLS test verification, Supabase MVP2 schema migration (`evidence_crops` and `query_results`), HNSW vector index tuning, hybrid search RPC, embedding evaluation and generation pipeline, re-analysis output ingestion loader, Cloudflare R2 evidence crop storage management, and a new typed data module `incident-console-v2/lib/db/` for the new MVP2 tables.

---

## 1. Goal

Build and deliver the complete, self-contained data and search layer for MVP2 natural-language evidence search with object crops. This workstream delivers everything required to store, embed, ingest, index, secure, and retrieve multi-modal evidence items without touching or requiring the GPU virtual machine (`kwanz-ws`).

All components in this workstream run locally on macOS or directly against remote managed services (Supabase PostgreSQL, Cloudflare R2, and remote embedding APIs).

---

## 2. Dependencies, Ownership, and Constraints

### Ownership Boundary
- **Database Engineer Owns:**
  - `supabase/` (migrations, RLS policies, indexing, search RPC `search_evidence_items`).
  - `incident-console-v2/lib/db/`: a new, dedicated typed data access module providing helper functions for the new MVP2 tables (e.g. `saveFeedback`, `getQueryHistory`, `getEvidenceCrops`).
- **Frontend Engineer Owns:**
  - `incident-console-v2/` page routes (`app/`), UI components (`components/`), and theme styling. Frontend reads and writes the new MVP2 tables exclusively through `incident-console-v2/lib/db/` functions.
- **Existing Codebase Rule:**
  - Existing API routes (`app/api/*/route.ts`) and existing Supabase client code in `incident-console-v2/` are **not** refactored. The new `lib/db/` module is strictly for the new MVP2 tables and features.
  - Retired `incident-console/` (v1) and `incident-console/db.py` are obsolete and out of scope; do not update or mirror schemas to v1.

### Upstream Dependencies
1. **Database Lockdown Migration (PR #116):**
   - Migration file `supabase/migrations/20261016000000_enable_rls_and_lockdown_anon.sql` is merged into `main` but **not yet applied to the live database**.
   - Applying this lockdown migration to live Supabase and verifying it with automated tests is the **FIRST task** of this workstream.
   - All public tables default to deny access for `anon` and `authenticated`.
   - All new functions must explicitly execute `REVOKE ALL ON FUNCTION ... FROM PUBLIC, anon, authenticated` and `GRANT EXECUTE ... TO service_role`.
2. **Search Contract (`contracts/search-contract-v1/`):**
   - Owned by the Captain. Defines query input filters (`incident_types`, `min_severity`, `max_severity`, `item_types`), ranking requirements, and output schemas.
3. **Re-Analysis Output Format (from Captain):**
   - The Captain executes batch re-analysis on the VM.
   - The Captain delivers structured output JSON containing validated `incident-contract-v3` reports (`timestamp_seconds`, detector bounding boxes, and crop images).
   - This workstream ingests that output via a standalone loader into Supabase and R2.
4. **Embedding Model Selection (measured with Eval Workstream):**
   - Evaluated against benchmark queries alongside the eval engineer.

### Operating Constraints (Zero-VM Requirement)
- **No VM Access Required:** Everything in this workstream runs locally or directly against Supabase and R2 APIs. No SSH to `kwanz-ws`, no Docker Compose on VM, and no GPU dependencies.
- **Scope Boundaries (What NOT to Touch):**
  - Do NOT implement VM inference pipelines or `vss-agent` routes on the VM.
  - Do NOT run video re-analysis (owned by the Captain).
  - Do NOT edit Next.js frontend UI pages or visual components in `incident-console-v2/` (owned by Frontend engineer).
  - Do NOT edit or bump shared contract files in `contracts/` (owned by Captain).
  - Do NOT drop or alter legacy pre-v1 tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`).
  - Do NOT mutate existing relational tables `entities`, `instruments`, or `assets` (all MVP2 crops, boxes, and embeddings live in `evidence_crops`).
  - Do NOT edit or mirror schemas to `incident-console/` (v1 is obsolete).

---

## 3. Workstream Areas & Task Checklist

### Area 1: Live RLS Lockdown Application & Verification (FIRST TASK)
- [ ] Apply merged RLS lockdown migration `supabase/migrations/20261016000000_enable_rls_and_lockdown_anon.sql` to the live Supabase database instance.
- [ ] Run RLS verification test suite proving:
  - `anon` and `authenticated` roles are blocked from direct table access and RPC execution across all schemas.
  - `incident-console-v2` continues to function normally using `SUPABASE_SERVICE_ROLE_KEY`.
  - `vss-agent` continues to ingest and read data using service-role credentials.
  - Evaluation workflows (`eval/`) continue to read ground truth and reports without permission errors.
  - Mock backend (`mock-backend/base_profile_mock/`) operations remain unaffected.

### Area 2: Supabase MVP2 Schema, RLS, and Search RPC
- [ ] Create Supabase migration `supabase/migrations/<timestamp>_mvp2_data_and_search_layer.sql` enabling the `vector` extension (`CREATE EXTENSION IF NOT EXISTS vector;`).
- [ ] Create unified `evidence_crops` table mapping `(incident_id, model_run_id, item_type, item_id)` with temporal anchors, detector bounding boxes, R2 image keys, item descriptions, and pgvector embeddings.
- [ ] Create `query_results` table for recording item-level search hits, ranks, similarity scores, and critic audit trail.
- [ ] Enable Row-Level Security (RLS) on both `evidence_crops` and `query_results`.
- [ ] Revoke all permissions on `evidence_crops` and `query_results` from `anon` and `authenticated`; grant all permissions strictly to `service_role`.

### Area 3: Typed Data Module for MVP2 Tables (`incident-console-v2/lib/db/`)
- [ ] Create `incident-console-v2/lib/db/` module providing typed data access functions for the new MVP2 tables using the service-role client.
- [ ] Implement `saveFeedback({ resultId, queryId, feedback, notes })` to persist relevance feedback into `query_results`.
- [ ] Implement `getQueryHistory({ limit })` to retrieve historical search queries and results from `queries` / `query_results`.
- [ ] Implement `getEvidenceCrops({ incidentId, modelRunId })` to fetch all evidence crops for an incident.
- [ ] Keep existing API routes intact without refactoring existing database code.

### Area 4: Hybrid Search Engine & Ranking Tuning
- [ ] Implement `search_evidence_items` RPC function in PostgreSQL supporting hybrid search:
  - Vector cosine similarity via pgvector `<=>` operator.
  - Full-text keyword search via PostgreSQL `tsvector` / `tsquery` over item name and description.
  - Combined hybrid scoring formula: `alpha * vector_similarity + (1 - alpha) * keyword_rank`.
  - Relational filtering by `incident_types`, severity range (`min_severity` to `max_severity`), and `item_types`.
  - Strict scoping to official reports: `videos.selected_model_run_id = incidents.model_run_id`.
- [ ] Revoke execute on `search_evidence_items` from `PUBLIC, anon, authenticated`; grant execute strictly to `service_role`.
- [ ] Tune ranking weights (`alpha`) and similarity thresholds against retrieval benchmark queries in coordination with the eval engineer.

### Area 5: Embedding Pipeline & Benchmark Selection
- [ ] Benchmark candidate embedding models using evidence texts (names + descriptions + threat levels):
  - Option A: NVIDIA NeMo Retriever NIM (`nvidia/llama-3.2-nv-embedqa-1b-v2`, 1024 dims).
  - Option B: OpenAI `text-embedding-3-small` (1536 dims).
  - Option C: Local CPU sentence-transformers (`all-MiniLM-L6-v2`, 384 dims).
- [ ] Document empirical trade-offs (retrieval quality, dimension size, latency, cost) and select final model.
- [ ] Implement standalone embedding utility script to generate and batch-upload embeddings into `evidence_crops.embedding`.

### Area 6: Ingestion Loader for Re-Analysis Output
- [ ] Define standardized ingestion payload format matching Captain's re-analysis output.
- [ ] Implement idempotent ingestion loader script (`scripts/ingest_reanalysis_output.py`):
  - Parses re-analysis output batches.
  - Inserts/updates `evidence_crops` rows with detector bounding boxes, timestamps, and metadata.
  - Generates text embeddings for newly ingested items.
  - Validates foreign keys against parent `incidents` and `videos`.

### Area 7: Cloudflare R2 Evidence Crop Storage Management
- [ ] Establish canonical R2 object key layout:
  `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg` (where collection is `entities`, `instruments`, or `assets`).
- [ ] Implement helper module for generating time-limited presigned GET URLs for frontend console viewing.
- [ ] Implement orphan cleanup utility to purge R2 crop objects when parent incidents or model runs are deleted.
- [ ] Validate direct S3/R2 client compatibility with standard credentials (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`).

### Area 8: Security Testing, Performance & Index Tuning
- [ ] Build automated RLS test suite:
  - Verify `anon` role is rejected (HTTP 401/403 or 0 rows) across direct PostgREST table queries and RPC endpoints.
  - Verify `authenticated` role is denied access.
  - Verify `service_role` has full read/write access and bypasses RLS.
- [ ] Benchmark HNSW index parameters (`m`, `ef_construction`, `ef_search`) on pgvector for target dataset size.
- [ ] Test query execution plans (`EXPLAIN ANALYZE`) on `search_evidence_items` to ensure index scans rather than sequential scans.

---

## 4. Technical Specifications & Reference Schemas

### 4.1 Schema DDL Specification

```sql
-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Unified evidence_crops table
CREATE TABLE IF NOT EXISTS evidence_crops (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset')),
    item_id VARCHAR(20) NOT NULL,
    item_name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    threat_level INTEGER, -- Nullable for entities/assets, 1-5 for instruments
    holder_entity_id VARCHAR(20), -- Nullable, for instruments held by an entity
    timestamp_seconds INTEGER NOT NULL,
    bounding_box INTEGER[4] NOT NULL, -- [ymin, xmin, ymax, xmax] normalized 0-1000 from detector
    image VARCHAR(1024) NOT NULL, -- R2 key: evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg
    embedding vector(1024), -- Dimension tuned to chosen embedding model
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(item_name, '') || ' ' || coalesce(description, ''))
    ) STORED,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (incident_id, model_run_id, item_type, item_id),
    FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- Indexing
CREATE INDEX IF NOT EXISTS evidence_crops_embedding_hnsw_idx 
    ON evidence_crops USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS evidence_crops_fts_idx 
    ON evidence_crops USING gin (search_vector);

CREATE INDEX IF NOT EXISTS evidence_crops_lookup_idx 
    ON evidence_crops (incident_id, model_run_id);

-- 3. Dedicated query_results table
CREATE TABLE IF NOT EXISTS query_results (
    id VARCHAR(36) PRIMARY KEY,
    query_id VARCHAR(20) NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset')),
    item_id VARCHAR(20) NOT NULL,
    rank INTEGER NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    critic_verdict VARCHAR(16) NOT NULL CHECK (critic_verdict IN ('confirmed', 'rejected', 'unverified')),
    critic_rationale TEXT,
    retrieved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS query_results_query_rank_idx ON query_results (query_id, rank);

-- 4. RLS Policy Lockdown
ALTER TABLE evidence_crops ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_results ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON evidence_crops FROM anon, authenticated;
REVOKE ALL ON query_results FROM anon, authenticated;

GRANT ALL ON evidence_crops TO service_role;
GRANT ALL ON query_results TO service_role;
```

### 4.2 Hybrid Search Function Specification

```sql
CREATE OR REPLACE FUNCTION search_evidence_items(
    p_query_embedding vector(1024),
    p_query_text TEXT DEFAULT NULL,
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
    p_alpha DOUBLE PRECISION DEFAULT 0.7, -- Weight for vector similarity vs text rank
    p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset'],
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INTEGER DEFAULT NULL,
    p_max_severity INTEGER DEFAULT NULL
)
RETURNS TABLE (
    incident_id VARCHAR(20),
    model_run_id VARCHAR(20),
    video_filepath VARCHAR(1024),
    incident_type VARCHAR(32),
    severity_level INTEGER,
    incident_description TEXT,
    incident_start_timestamp VARCHAR(32),
    incident_end_timestamp VARCHAR(32),
    item_type VARCHAR(16),
    item_id VARCHAR(20),
    item_name VARCHAR(256),
    item_description TEXT,
    threat_level INTEGER,
    holder_entity_id VARCHAR(20),
    image VARCHAR(1024),
    timestamp_seconds INTEGER,
    bounding_box INTEGER[4],
    similarity_score DOUBLE PRECISION
)
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ec.incident_id,
        ec.model_run_id,
        v.filepath AS video_filepath,
        inc.type AS incident_type,
        inc.severity_level,
        inc.description AS incident_description,
        inc.start_timestamp AS incident_start_timestamp,
        inc.end_timestamp AS incident_end_timestamp,
        ec.item_type,
        ec.item_id,
        ec.item_name,
        ec.description AS item_description,
        ec.threat_level,
        ec.holder_entity_id,
        ec.image,
        ec.timestamp_seconds,
        ec.bounding_box,
        (
            CASE 
                WHEN p_query_text IS NOT NULL AND ec.search_vector @@ plainto_tsquery('english', p_query_text)
                THEN (p_alpha * (1.0 - (ec.embedding <=> p_query_embedding))) + 
                     ((1.0 - p_alpha) * ts_rank_cd(ec.search_vector, plainto_tsquery('english', p_query_text)))
                ELSE (1.0 - (ec.embedding <=> p_query_embedding))
            END
        ) AS similarity_score
    FROM evidence_crops ec
    JOIN videos v ON v.id = ec.incident_id AND v.selected_model_run_id = ec.model_run_id
    JOIN incidents inc ON inc.incident_id = ec.incident_id AND inc.model_run_id = ec.model_run_id
    WHERE ec.item_type = ANY(p_item_types)
      AND ec.embedding IS NOT NULL
      AND (1.0 - (ec.embedding <=> p_query_embedding)) >= p_min_similarity
      AND (p_incident_types IS NULL OR inc.type = ANY(p_incident_types))
      AND (p_min_severity IS NULL OR inc.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR inc.severity_level <= p_max_severity)
    ORDER BY similarity_score DESC
    LIMIT p_top_k;
END;
$$;

REVOKE ALL ON FUNCTION search_evidence_items FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION search_evidence_items TO service_role;
```

---

## 5. Definition of Done

- [ ] Merged RLS lockdown migration applied to live Supabase and automated test suite passes: `anon` and `authenticated` roles receive HTTP 401/403 or empty responses; `service_role` executes queries and RPCs without error; console, vss-agent, eval, and mock operate cleanly.
- [ ] Supabase MVP2 migration applied and validated on a local/test PostgreSQL instance with pgvector.
- [ ] Dedicated typed data module `incident-console-v2/lib/db/` created for new MVP2 tables (`saveFeedback`, `getQueryHistory`, `getEvidenceCrops`) without refactoring existing database code.
- [ ] Hybrid search RPC produces accurate rankings across combined vector and text queries.
- [ ] Embedding generation script processes evidence items and populates pgvector embeddings.
- [ ] Re-analysis ingestion loader successfully loads batch output into `evidence_crops` and matches official report IDs.
- [ ] R2 helper generates working presigned URLs and cleanup logic correctly identifies orphaned crop keys.
- [ ] Documentation updated in `.docs/data.md` and `.docs/decisions.md`.


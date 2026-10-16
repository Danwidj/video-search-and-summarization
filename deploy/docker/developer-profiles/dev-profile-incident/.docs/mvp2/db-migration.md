# Workstream Task: MVP2 Database Migration & Search Layer

- **Assignee / Role:** Database & Search Engineer
- **Status:** Ready for implementation (build on this PR branch)
- **Workstream Scope:** Complete delivery of the MVP2 database and search infrastructure — applying the merged RLS lockdown migration to live Supabase, executing the Supabase MVP2 schema migration (`evidence_crops` and `query_results`), conducting programmatic connection and RLS verification, validating end-to-end VM `vss-agent` to Supabase report persistence on `kwanz-ws`, tuning HNSW vector indexes, implementing the hybrid search RPC function (`search_evidence_items`), building the embedding evaluation and generation pipeline, creating the re-analysis batch ingestion loader, and managing Cloudflare R2 evidence crop storage.

---

## 1. Goal

Deliver the complete, robust database and search layer for MVP2 natural-language evidence search with object crops. This workstream delivers schema migrations, RLS security lockdown, vector search capabilities, and operational verification across both local and VM environments.

Key objectives:
1. **Deploy MVP2 Schema & Security:** Apply the pending RLS lockdown migration and create new MVP2 schema objects (`evidence_crops`, `query_results`, `search_evidence_items` RPC) locked down strictly to `service_role`.
2. **Verify Connection & RLS Security:** Prove programmatically that the console adapter reaches Supabase via `service_role`, `anon` and `authenticated` roles remain blocked, and new MVP2 tables are reachable. Record concrete evidence in the PR.
3. **Verify VM `vss-agent` Persistence End to End:** Verify that `vss-agent` running on the `kwanz-ws` GPU VM successfully generates and persists incident reports to live Supabase PostgREST over the campus firewall.
4. **Implement Hybrid Search & Ingestion Pipeline:** Implement the hybrid search RPC function, benchmark embedding models, build the ingestion loader for Option B backfill JSON Lines output, and establish Cloudflare R2 evidence crop storage handling.

---

## 2. Dependencies, Ownership, and Constraints

### Ownership Boundary
- **Database / Backend Engineer Owns (This PR):**
  - `supabase/` (migrations, RLS policies, indexing, search RPC `search_evidence_items`).
  - Supabase PostgREST adapter implementation for new MVP2 tables (`evidence_crops`, `query_results`) satisfying `EvidenceSearchRepository`.
  - Connection verification scripts and evidence collection.
  - VM verification of `vss-agent` to Supabase report persistence on `kwanz-ws`.
  - Ingestion loader script (`scripts/ingest_reanalysis_output.py`), R2 storage helpers, and embedding generation utilities.
- **Frontend Engineer Owns (PR #120):**
  - Hexagonal architecture refactor in `incident-console-v2`: domain ports (`lib/ports/`), route refactoring (`app/api/*`), UI presentation components (`components/`).

### Codebase Boundaries & Rules
- **Hexagonal Architecture Alignment:**
  - Database access for MVP2 tables plugs into hexagonal architecture via the `EvidenceSearchRepository` port (`incident-console-v2/lib/ports/search.ts`) and `SupabaseEvidenceSearchAdapter` (`incident-console-v2/lib/adapters/supabase/search.ts`).
- **Legacy Codebase Boundary:**
  - Retired `incident-console/` (v1) and `incident-console/db.py` are obsolete and out of scope; do not update or mirror schemas to v1.
  - Do NOT mutate existing relational tables `entities`, `instruments`, or `assets` (all MVP2 crops, boxes, and embeddings live in `evidence_crops`).
  - Do NOT drop or alter legacy pre-v1 tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`) without separate approval.

### Option B Scope: Official Report Backfill & Evidence Ingestion
The captain selected Option B for the MVP2 timestamp pass and evidence crop workflow:
- **Preserve Official Reports:** Official reports in `incidents` and `model_runs` are kept as they are; they carry human review, triage decisions, and edits that must not be overwritten or regenerated.
- **Targeted VLM Pass:** The VLM returns only per-item `timestamp_seconds` and a short detector label for existing items.
- **Detector Crops via Crop Service:** Detector bounding boxes and cropped images are produced by the crop service rather than report generation.
- **Database Loader Responsibility:** The database loader script (`scripts/ingest_reanalysis_output.py`, owned by this workstream) reads the backfill output and populates `evidence_crops` with temporal anchors, bounding boxes, R2 image keys, and embeddings.
- **Strict Scope to Official Reports:** Ingestion is scoped strictly to official reports (`videos.selected_model_run_id IS NOT NULL`).
- **Input Format (JSON Lines):** The backfill process writes item records as JSON Lines to its `--output-file`. The loader must consume this format.
  - *TODO:* Confirm exact JSON Lines record schema with the backfill PR (`fm/vss-mvp2-backfill-timestamps`).

### VM Access, Environment & Operating Rules
- **VM Access is Established:**
  - The GPU VM host is `kwanz-ws`, accessible via SSH over Zheng's tailnet.
  - Mutations inside the VM repository checkout are performed by whoever has VM access running the exact commands specified in this document.
  - The assignee must confirm they have VM access before starting VM verification; if not, ask the captain.
- **Campus Firewall & Network Constraint:**
  - Direct PostgreSQL connections on port 5432 from `kwanz-ws` are blocked by campus deep-packet-inspection (DPI) firewalls.
  - `vss-agent` persists strictly via HTTPS PostgREST (port 443) using `services/agent/src/vss_agents/utils/incident_db.py` configured with `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`.
- **Strict Non-Destructive Operating Rules on VM:**
  - **NEVER** run `docker compose down -v` or `dev-profile.sh down` on `kwanz-ws`.
  - If a service restart is needed, use `docker compose -p mdx stop <service>` and `docker compose -p mdx start <service>` only.

---

## 3. Workstream Areas & Task Checklist

### Area 1: Live RLS Lockdown & Supabase MVP2 Schema Migration
- [ ] Apply merged RLS lockdown migration `supabase/migrations/20261016000000_enable_rls_and_lockdown_anon.sql` to the live Supabase database instance.
- [ ] Create Supabase migration `supabase/migrations/<timestamp>_mvp2_data_and_search_layer.sql` enabling the `vector` extension (`CREATE EXTENSION IF NOT EXISTS vector;`).
- [ ] Create unified `evidence_crops` table mapping `(incident_id, model_run_id, item_type, item_id)` with temporal anchors, detector bounding boxes, R2 image keys, item descriptions, and pgvector embeddings.
- [ ] Create `query_results` table for recording item-level search hits, ranks, similarity scores, and critic audit trail.
- [ ] Enable Row-Level Security (RLS) on both `evidence_crops` and `query_results`.
- [ ] Revoke all permissions on `evidence_crops` and `query_results` from `anon` and `authenticated`; grant all permissions strictly to `service_role`.
- [ ] Implement `SupabaseEvidenceSearchAdapter` to query `evidence_crops` and `query_results` using the service-role client.

### Area 2: Connection & Security Verification
- [ ] Verify console adapters reach Supabase cleanly through the `service_role` path:
  - Test health check endpoint (`/api/health`).
  - Query dashboard analytics, videos, and incident reports via the service-role client.
- [ ] Verify RLS lockdown holds across all roles on both existing tables and new MVP2 tables:
  - `anon` key requests to `evidence_crops` and `query_results` return HTTP 401/403 or 0 rows.
  - `authenticated` key requests return HTTP 401/403 or 0 rows.
  - `service_role` key retains full read/write access.
- [ ] Verify new MVP2 tables (`evidence_crops`, `query_results`) and RPC functions are queryable via `service_role`.
- [ ] Record verification evidence (commands executed, HTTP status codes, output snippets) into the PR description or comment.

### Area 3: VM `vss-agent` End-to-End Supabase Verification
- [ ] Confirm VM access to `kwanz-ws` over Zheng's tailnet (ask captain if access is not configured).
- [ ] Inspect VM environment variables and verify `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` are active in `vss-agent` container.
- [ ] Trigger an incident analysis run on `kwanz-ws` (or execute test analysis via `incident_db.py`).
- [ ] Verify the generated incident report lands end to end in live Supabase:
  - Confirm row inserted in `incidents`, `model_runs`, `videos`, and evidence tables (`entities`, `instruments`, `assets`).
  - Confirm `insert_incident` RPC executed successfully without permission errors.
- [ ] Observe non-destructive rules: do NOT execute `docker compose down -v` or `dev-profile.sh down`; use `docker compose -p mdx stop/start` only if container restart is required.
- [ ] Record verification evidence in the PR description or comment.

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

### Area 6: Ingestion Loader for Backfill Output (Option B)
- [ ] Define standardized JSON Lines ingestion schema matching the backfill script's `--output-file` (TODO: confirm exact record schema with backfill PR).
- [ ] Implement idempotent ingestion loader script (`scripts/ingest_reanalysis_output.py`):
  - Streams and parses JSON Lines records from backfill `--output-file`.
  - Validates that records correspond to official reports (`videos.selected_model_run_id IS NOT NULL`).
  - Inserts/updates `evidence_crops` rows with detector bounding boxes, timestamps, and metadata.
  - Generates text embeddings for newly ingested items.
  - Validates foreign keys against parent `incidents` and `videos`.

### Area 7: Cloudflare R2 Evidence Crop Storage Management
- [ ] Establish canonical R2 object key layout:
  `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg` (where collection is `entities`, `instruments`, or `assets`).
- [ ] Implement helper module for generating time-limited presigned GET URLs for frontend console viewing.
- [ ] Implement orphan cleanup utility to purge R2 crop objects when parent incidents or model runs are deleted.
- [ ] Validate direct S3/R2 client compatibility with standard credentials (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`).

### Area 8: Performance, HNSW Index Tuning & Verification
- [ ] Benchmark HNSW index parameters (`m`, `ef_construction`, `ef_search`) on pgvector for target dataset size.
- [ ] Test query execution plans (`EXPLAIN ANALYZE`) on `search_evidence_items` to ensure index scans rather than sequential scans.

---

## 4. Technical Specifications & Architecture Details

### 4.1 Schema DDL Specification

```sql
-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Evidence Crops Table (Unified items with crops, boxes, and embeddings)
CREATE TABLE IF NOT EXISTS evidence_crops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    model_run_id TEXT NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset')),
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    description TEXT NOT NULL,
    threat_level INTEGER CHECK (threat_level BETWEEN 1 AND 5),
    holder_entity_id TEXT,
    timestamp_seconds INTEGER NOT NULL,
    bounding_box JSONB NOT NULL,
    image_r2_key TEXT NOT NULL,
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_evidence_crop UNIQUE (incident_id, model_run_id, item_type, item_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_crops_incident_run ON evidence_crops (incident_id, model_run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_crops_item_type ON evidence_crops (item_type);
CREATE INDEX IF NOT EXISTS idx_evidence_crops_fts ON evidence_crops USING gin(to_tsvector('english', item_name || ' ' || description));
CREATE INDEX IF NOT EXISTS idx_evidence_crops_embedding_hnsw ON evidence_crops USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- 3. Query Results Table (Audit trail & evaluation)
CREATE TABLE IF NOT EXISTS query_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id UUID NOT NULL,
    query_text TEXT NOT NULL,
    query_embedding vector(1024),
    evidence_crop_id UUID NOT NULL REFERENCES evidence_crops(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    similarity_score FLOAT NOT NULL,
    critic_verdict TEXT CHECK (critic_verdict IN ('relevant', 'irrelevant', 'ambiguous')),
    critic_reason TEXT,
    user_feedback TEXT CHECK (user_feedback IN ('helpful', 'unhelpful')),
    user_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_results_query_id ON query_results (query_id);
CREATE INDEX IF NOT EXISTS idx_query_results_evidence_crop_id ON query_results (evidence_crop_id);

-- 4. Enable RLS and Restrict to service_role
ALTER TABLE evidence_crops ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_results ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON evidence_crops FROM PUBLIC, anon, authenticated;
REVOKE ALL ON query_results FROM PUBLIC, anon, authenticated;

GRANT ALL ON evidence_crops TO service_role;
GRANT ALL ON query_results TO service_role;
```

---

### 4.2 Hybrid Search Function Specification

```sql
CREATE OR REPLACE FUNCTION search_evidence_items(
    p_query_embedding vector(1024),
    p_query_text TEXT DEFAULT NULL,
    p_top_k INT DEFAULT 10,
    p_min_similarity FLOAT DEFAULT 0.0,
    p_alpha FLOAT DEFAULT 0.7,
    p_item_types TEXT[] DEFAULT NULL,
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INT DEFAULT NULL,
    p_max_severity INT DEFAULT NULL
)
RETURNS TABLE (
    evidence_crop_id UUID,
    incident_id UUID,
    video_id TEXT,
    model_run_id TEXT,
    item_type TEXT,
    item_id TEXT,
    item_name TEXT,
    description TEXT,
    threat_level INT,
    timestamp_seconds INT,
    bounding_box JSONB,
    image_r2_key TEXT,
    similarity_score FLOAT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    WITH scored_items AS (
        SELECT
            ec.id AS evidence_crop_id,
            ec.incident_id,
            v.id AS video_id,
            ec.model_run_id,
            ec.item_type,
            ec.item_id,
            ec.item_name,
            ec.description,
            ec.threat_level,
            ec.timestamp_seconds,
            ec.bounding_box,
            ec.image_r2_key,
            (
                p_alpha * (1.0 - (ec.embedding <=> p_query_embedding)) +
                (1.0 - p_alpha) * COALESCE(ts_rank_cd(to_tsvector('english', ec.item_name || ' ' || ec.description), plainto_tsquery('english', COALESCE(p_query_text, ''))), 0.0)
            ) AS combined_score
        FROM evidence_crops ec
        JOIN incidents inc ON inc.id = ec.incident_id
        JOIN videos v ON v.id = inc.video_id
        WHERE v.selected_model_run_id = inc.model_run_id
          AND (p_item_types IS NULL OR ec.item_type = ANY(p_item_types))
          AND (p_incident_types IS NULL OR inc.incident_type = ANY(p_incident_types))
          AND (p_min_severity IS NULL OR inc.severity_level >= p_min_severity)
          AND (p_max_severity IS NULL OR inc.severity_level <= p_max_severity)
    )
    SELECT
        si.evidence_crop_id,
        si.incident_id,
        si.video_id,
        si.model_run_id,
        si.item_type,
        si.item_id,
        si.item_name,
        si.description,
        si.threat_level,
        si.timestamp_seconds,
        si.bounding_box,
        si.image_r2_key,
        si.combined_score AS similarity_score
    FROM scored_items si
    WHERE si.combined_score >= p_min_similarity
    ORDER BY si.combined_score DESC
    LIMIT p_top_k;
END;
$$;

REVOKE ALL ON FUNCTION search_evidence_items FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION search_evidence_items TO service_role;
```

---

### 4.3 Connection & Security Verification Protocol

To verify that the database layer is operational, secure, and correctly configured:

1. **Console Adapter Service-Role Access:**
   Execute a request via the console's health and data endpoints or node verification script:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3200/api/health
   # Expected output: 200
   ```
2. **RLS Lockdown Verification (Anon & Authenticated Blocked):**
   Query PostgREST directly using the anonymous key:
   ```bash
   curl -s -i "${SUPABASE_URL}/rest/v1/evidence_crops?select=item_id&limit=1" \
     -H "apikey: ${SUPABASE_ANON_KEY}" \
     -H "Authorization: Bearer ${SUPABASE_ANON_KEY}"
   # Expected output: HTTP 401/403 or empty array []
   ```
3. **Service-Role Table & RPC Reachability:**
   Query PostgREST directly using the service-role key:
   ```bash
   curl -s -i "${SUPABASE_URL}/rest/v1/evidence_crops?select=item_id&limit=1" \
     -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
     -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}"
   # Expected output: HTTP 200 OK
   ```
4. **Recording Evidence in PR:**
   - Execute the verification script or above curl commands.
   - Paste the exact command invocations, HTTP status codes, and JSON response snippets into a comment or dedicated section in the PR.

---

### 4.4 VM `vss-agent` End-to-End Persistence Verification

1. **Accessing the VM:**
   - Connect to `kwanz-ws` over Zheng's tailnet:
     ```bash
     ssh <user>@kwanz-ws
     ```
   - Confirm access. If access is not available, ask the captain.
2. **Checking Environment Configuration:**
   - Verify `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` are populated in the agent configuration.
3. **Triggering Report Persistence:**
   - Run a test video analysis through `vss-agent` or trigger an incident persistence test:
     ```bash
     # Non-destructive command inside VM repository
     docker compose -p mdx exec vss-agent python -m vss_agents.utils.incident_db
     ```
   - Confirm that the report row lands in Supabase `incidents`, `model_runs`, `videos`, and evidence tables.
4. **Operating Rules on VM:**
   - Non-destructive commands only: do **NOT** run `docker compose down -v` or `dev-profile.sh down`.
   - If containers need to restart, use `docker compose -p mdx stop vss-agent && docker compose -p mdx start vss-agent`.
5. **Recording Evidence in PR:**
   - Include VM execution log snippet showing successful persistence without network or RLS errors in the PR.

---

## 5. Definition of Done

- [ ] Merged RLS lockdown migration applied to live Supabase and automated test suite passes: `anon` and `authenticated` roles receive HTTP 401/403 or empty responses; `service_role` executes queries and RPCs without error; console, vss-agent, eval, and mock operate cleanly.
- [ ] Supabase MVP2 migration applied and validated on a PostgreSQL instance with pgvector (`evidence_crops`, `query_results`).
- [ ] Connection and security verification completed: service-role reachability verified, anon/authenticated lockdown verified, and verification evidence recorded in the PR.
- [ ] VM `vss-agent` report persistence verified end to end on `kwanz-ws` without port 5432 errors or RLS rejections, and evidence recorded in the PR.
- [ ] Hybrid search RPC produces accurate rankings across combined vector and text queries.
- [ ] Embedding generation script processes evidence items and populates pgvector embeddings.
- [ ] Ingestion loader successfully loads Option B JSON Lines backfill output into `evidence_crops`, scoped strictly to official reports (`videos.selected_model_run_id IS NOT NULL`).
- [ ] R2 helper generates working presigned URLs and cleanup logic correctly identifies orphaned crop keys.
- [ ] Documentation updated in `.docs/data.md` and `.docs/decisions.md`.

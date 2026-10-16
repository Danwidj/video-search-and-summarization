# Workstream Task: MVP2 Data and Search Layer

- **Assignee / Role:** Database & Search Engineer
- **Status:** Ready for implementation (build on this PR branch)
- **Workstream Scope:** Complete delivery of the MVP2 data and search layer — decoupling `incident-console-v2` via hexagonal architecture (ports and adapters), applying the merged RLS lockdown migration to live Supabase, Supabase MVP2 schema migration (`evidence_crops` and `query_results`), connection and RLS verification, end-to-end VM `vss-agent` to Supabase reporting verification, HNSW vector index tuning, hybrid search RPC, embedding evaluation and generation pipeline, re-analysis output ingestion loader, and Cloudflare R2 evidence crop storage management.

---

## 1. Goal

Deliver the complete, robust data and search layer for MVP2 natural-language evidence search with object crops. This workstream delivers clean architectural decoupling of the console, end-to-end database persistence, vector search capabilities, and operational verification across both local and VM environments.

Key objectives:
1. **Decouple Console UI from Database Access:** Refactor `incident-console-v2` to follow hexagonal architecture (ports and adapters), isolating Next.js UI routes from database transport details and establishing ports for MVP2 tables.
2. **Deploy MVP2 Schema & Security:** Apply the pending RLS lockdown migration and create new MVP2 schema objects (`evidence_crops`, `query_results`, `search_evidence_items` RPC) locked down strictly to `service_role`.
3. **Verify Connection & RLS Security:** Prove programmatically that console adapters reach Supabase via `service_role`, `anon` and `authenticated` roles remain blocked, and new MVP2 tables are reachable. Record concrete evidence in the PR.
4. **Verify VM `vss-agent` Persistence End to End:** Verify that `vss-agent` running on the `kwanz-ws` GPU VM successfully generates and persists incident reports to live Supabase PostgREST over the campus firewall.
5. **Implement Hybrid Search & Ingestion Pipeline:** Implement the hybrid search RPC function, benchmark embedding models, build the ingestion loader for Captain's re-analysis output batches, and establish Cloudflare R2 evidence crop storage handling.

---

## 2. Dependencies, Ownership, and Constraints

### Ownership Boundary
- **Database / Backend Engineer Owns:**
  - `supabase/` (migrations, RLS policies, indexing, search RPC `search_evidence_items`).
  - `incident-console-v2/lib/ports/`: domain port interfaces defining all data operations required by the console UI and API routes.
  - `incident-console-v2/lib/adapters/supabase/`: concrete Supabase PostgREST adapter implementations satisfying the domain ports, including adapters for the new MVP2 tables (`evidence_crops`, `query_results`).
  - Connection verification scripts and evidence collection.
  - VM verification of `vss-agent` to Supabase report persistence on `kwanz-ws`.
  - Ingestion loader script (`scripts/ingest_reanalysis_output.py`), R2 storage helpers, and embedding generation utilities.
- **Frontend Engineer Owns:**
  - `incident-console-v2/` page routes (`app/`), UI presentation components (`components/`), and theme styling. Frontend components and API routes consume data exclusively through the domain ports.

### Hexagonal Architecture & Codebase Rules
- **Hexagonal Decoupling (Ports & Adapters):**
  - Database access is fully decoupled from the UI. Next.js route handlers (`app/api/*/route.ts`) and components depend strictly on domain ports (`lib/ports/`).
  - Low-level PostgREST queries, URL parameter constructions (`select=...`, `in.(...)`, `like.*...*`), table names, and direct `PostgrestClient` instantiations move out of API route handlers into concrete adapters under `lib/adapters/supabase/`.
  - The new MVP2 tables (`evidence_crops`, `query_results`) plug directly into this architecture via a dedicated `EvidenceSearchRepository` port and `SupabaseEvidenceSearchAdapter`.
- **Legacy Codebase Boundary:**
  - Retired `incident-console/` (v1) and `incident-console/db.py` are obsolete and out of scope; do not update or mirror schemas to v1.
  - Do NOT mutate existing relational tables `entities`, `instruments`, or `assets` (all MVP2 crops, boxes, and embeddings live in `evidence_crops`).
  - Do NOT drop or alter legacy pre-v1 tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`) without separate approval.

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

### Area 1: Live RLS Lockdown Application (Prerequisite Baseline)
- [ ] Apply merged RLS lockdown migration `supabase/migrations/20261016000000_enable_rls_and_lockdown_anon.sql` to the live Supabase database instance.
- [ ] Run RLS verification test suite proving:
  - `anon` and `authenticated` roles are blocked from direct table access and RPC execution across all schemas.
  - `incident-console-v2` continues to function normally using `SUPABASE_SERVICE_ROLE_KEY`.
  - `vss-agent` continues to ingest and read data using service-role credentials.
  - Evaluation workflows (`eval/`) continue to read ground truth and reports without permission errors.
  - Mock backend (`mock-backend/base_profile_mock/`) operations remain unaffected.

### Area 2: Hexagonal Decoupling for `incident-console-v2` (Ports & Adapters)
- [ ] Define domain ports in `incident-console-v2/lib/ports/`:
  - `IncidentRepository` (`lib/ports/incidents.ts`): get incident details, list report summaries, update review status, edit report drafts, delete incident records.
  - `DashboardRepository` (`lib/ports/dashboard.ts`): fetch aggregate dashboard metrics and analytics.
  - `VideoRepository` (`lib/ports/videos.ts`): list videos, fetch video details, update official report selection, record uploaded videos.
  - `EvidenceSearchRepository` (`lib/ports/search.ts`): search evidence items, fetch evidence crops, save user feedback, retrieve query history.
  - `HealthRepository` (`lib/ports/health.ts`): check database connectivity and latency.
- [ ] Implement Supabase PostgREST adapters in `incident-console-v2/lib/adapters/supabase/`:
  - `SupabaseIncidentAdapter` (implements `IncidentRepository`).
  - `SupabaseDashboardAdapter` (implements `DashboardRepository`).
  - `SupabaseVideoAdapter` (implements `VideoRepository`).
  - `SupabaseEvidenceSearchAdapter` (implements `EvidenceSearchRepository`).
  - `SupabaseHealthAdapter` (implements `HealthRepository`).
  - Provide an adapter factory / dependency injection provider (`lib/adapters/supabase/index.ts`).
- [ ] Refactor API route handlers in `app/api/*` to use domain ports via the adapter factory instead of directly constructing PostgREST queries or instantiating `PostgrestClient`.
- [ ] Ensure existing unit tests pass and add unit tests verifying adapters correctly satisfy port interfaces.

### Area 3: Supabase MVP2 Schema & RLS Migration
- [ ] Create Supabase migration `supabase/migrations/<timestamp>_mvp2_data_and_search_layer.sql` enabling the `vector` extension (`CREATE EXTENSION IF NOT EXISTS vector;`).
- [ ] Create unified `evidence_crops` table mapping `(incident_id, model_run_id, item_type, item_id)` with temporal anchors, detector bounding boxes, R2 image keys, item descriptions, and pgvector embeddings.
- [ ] Create `query_results` table for recording item-level search hits, ranks, similarity scores, and critic audit trail.
- [ ] Enable Row-Level Security (RLS) on both `evidence_crops` and `query_results`.
- [ ] Revoke all permissions on `evidence_crops` and `query_results` from `anon` and `authenticated`; grant all permissions strictly to `service_role`.
- [ ] Wire `SupabaseEvidenceSearchAdapter` to query `evidence_crops` and `query_results` using the service-role client.

### Area 4: Connection & Security Verification
- [ ] Verify console adapters reach Supabase cleanly through the `service_role` path:
  - Test health check endpoint (`/api/health`).
  - Query dashboard analytics, videos, and incident reports via the new adapters.
- [ ] Verify RLS lockdown holds across all roles on both existing tables and new MVP2 tables:
  - `anon` key requests to `evidence_crops` and `query_results` return HTTP 401/403 or 0 rows.
  - `authenticated` key requests return HTTP 401/403 or 0 rows.
  - `service_role` key retains full read/write access.
- [ ] Verify new MVP2 tables (`evidence_crops`, `query_results`) and RPC functions are queryable via `service_role`.
- [ ] Record verification evidence (commands executed, HTTP status codes, output snippets) into PR 120 description or comment.

### Area 5: VM `vss-agent` End-to-End Supabase Verification
- [ ] Confirm VM access to `kwanz-ws` over Zheng's tailnet (ask captain if access is not configured).
- [ ] Inspect VM environment variables and verify `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` are active in `vss-agent` container.
- [ ] Trigger an incident analysis run on `kwanz-ws` (or execute test analysis via `incident_db.py`).
- [ ] Verify the generated incident report lands end to end in live Supabase:
  - Confirm row inserted in `incidents`, `model_runs`, `videos`, and evidence tables (`entities`, `instruments`, `assets`).
  - Confirm `insert_incident` RPC executed successfully without permission errors.
- [ ] Observe non-destructive rules: do NOT execute `docker compose down -v` or `dev-profile.sh down`; use `docker compose -p mdx stop/start` only if container restart is required.
- [ ] Record verification evidence in PR 120.

### Area 6: Hybrid Search Engine & Ranking Tuning
- [ ] Implement `search_evidence_items` RPC function in PostgreSQL supporting hybrid search:
  - Vector cosine similarity via pgvector `<=>` operator.
  - Full-text keyword search via PostgreSQL `tsvector` / `tsquery` over item name and description.
  - Combined hybrid scoring formula: `alpha * vector_similarity + (1 - alpha) * keyword_rank`.
  - Relational filtering by `incident_types`, severity range (`min_severity` to `max_severity`), and `item_types`.
  - Strict scoping to official reports: `videos.selected_model_run_id = incidents.model_run_id`.
- [ ] Revoke execute on `search_evidence_items` from `PUBLIC, anon, authenticated`; grant execute strictly to `service_role`.
- [ ] Tune ranking weights (`alpha`) and similarity thresholds against retrieval benchmark queries in coordination with the eval engineer.

### Area 7: Embedding Pipeline & Benchmark Selection
- [ ] Benchmark candidate embedding models using evidence texts (names + descriptions + threat levels):
  - Option A: NVIDIA NeMo Retriever NIM (`nvidia/llama-3.2-nv-embedqa-1b-v2`, 1024 dims).
  - Option B: OpenAI `text-embedding-3-small` (1536 dims).
  - Option C: Local CPU sentence-transformers (`all-MiniLM-L6-v2`, 384 dims).
- [ ] Document empirical trade-offs (retrieval quality, dimension size, latency, cost) and select final model.
- [ ] Implement standalone embedding utility script to generate and batch-upload embeddings into `evidence_crops.embedding`.

### Area 8: Ingestion Loader for Re-Analysis Output
- [ ] Define standardized ingestion payload format matching Captain's re-analysis output.
- [ ] Implement idempotent ingestion loader script (`scripts/ingest_reanalysis_output.py`):
  - Parses re-analysis output batches.
  - Inserts/updates `evidence_crops` rows with detector bounding boxes, timestamps, and metadata.
  - Generates text embeddings for newly ingested items.
  - Validates foreign keys against parent `incidents` and `videos`.

### Area 9: Cloudflare R2 Evidence Crop Storage Management
- [ ] Establish canonical R2 object key layout:
  `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg` (where collection is `entities`, `instruments`, or `assets`).
- [ ] Implement helper module for generating time-limited presigned GET URLs for frontend console viewing.
- [ ] Implement orphan cleanup utility to purge R2 crop objects when parent incidents or model runs are deleted.
- [ ] Validate direct S3/R2 client compatibility with standard credentials (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`).

### Area 10: Performance, HNSW Index Tuning & Verification
- [ ] Benchmark HNSW index parameters (`m`, `ef_construction`, `ef_search`) on pgvector for target dataset size.
- [ ] Test query execution plans (`EXPLAIN ANALYZE`) on `search_evidence_items` to ensure index scans rather than sequential scans.

---

## 4. Technical Specifications & Architecture Details

### 4.1 Hexagonal Architecture (Ports and Adapters)

```
incident-console-v2/
  lib/
    ports/                        # Core application domain interfaces
      incidents.ts                # IncidentRepository (reports, reviews, edits, deletes)
      dashboard.ts                # DashboardRepository (metrics, heatmaps, trends)
      videos.ts                   # VideoRepository (video listings, official selections)
      search.ts                   # EvidenceSearchRepository (MVP2 search, crops, feedback)
      health.ts                   # HealthRepository (database liveness)
      index.ts                    # Barrel exports
    adapters/                     # Secondary adapters (infrastructure implementations)
      supabase/                   # Supabase PostgREST adapter implementation
        incidents.ts              # SupabaseIncidentAdapter implements IncidentRepository
        dashboard.ts              # SupabaseDashboardAdapter implements DashboardRepository
        videos.ts                 # SupabaseVideoAdapter implements VideoRepository
        search.ts                 # SupabaseEvidenceSearchAdapter implements EvidenceSearchRepository
        health.ts                 # SupabaseHealthAdapter implements HealthRepository
        client.ts                 # PostgrestClient wrapper and service configuration
        index.ts                  # Factory functions (e.g. getDbAdapters())
```

#### Port Interface Example (`lib/ports/search.ts`)
```typescript
export interface EvidenceCropItem {
  incidentId: string;
  modelRunId: string;
  itemType: 'entity' | 'instrument' | 'asset';
  itemId: string;
  itemName: string;
  description: string;
  threatLevel: number | null;
  holderEntityId: string | null;
  timestampSeconds: number;
  boundingBox: [number, number, number, number];
  image: string;
  similarityScore?: number;
}

export interface SearchEvidenceParams {
  queryEmbedding: number[];
  queryText?: string;
  topK?: number;
  minSimilarity?: number;
  alpha?: number;
  itemTypes?: Array<'entity' | 'instrument' | 'asset'>;
  incidentTypes?: string[];
  minSeverity?: number;
  maxSeverity?: number;
}

export interface EvidenceSearchRepository {
  searchEvidenceItems(params: SearchEvidenceParams): Promise<EvidenceCropItem[]>;
  getEvidenceCrops(incidentId: string, modelRunId: string): Promise<EvidenceCropItem[]>;
  saveFeedback(params: { resultId: string; queryId: string; feedback: string; notes?: string }): Promise<void>;
  getQueryHistory(params: { limit?: number }): Promise<Array<Record<string, unknown>>>;
}
```

#### What Moves Out of UI / Route Code
1. Direct calls to `new PostgrestClient(...)` are eliminated from `app/api/*`.
2. URL query string assembly (`select=...`, `in.(...)`, `order=...`) moves inside `lib/adapters/supabase/`.
3. Route handlers obtain typed port instances via factory functions (e.g., `getEvidenceSearchRepository()`), invoke interface methods, and return typed responses.

---

### 4.2 Schema DDL Specification

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

---

### 4.3 Hybrid Search Function Specification

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

### 4.4 Connection & Security Verification Protocol

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
   - Paste the exact command invocations, HTTP status codes, and JSON response snippets into a comment or dedicated section in PR 120.

---

### 4.5 VM `vss-agent` End-to-End Persistence Verification

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
   - Include VM execution log snippet showing successful persistence without network or RLS errors in PR 120.

---

## 5. Definition of Done

- [ ] Merged RLS lockdown migration applied to live Supabase and automated test suite passes: `anon` and `authenticated` roles receive HTTP 401/403 or empty responses; `service_role` executes queries and RPCs without error; console, vss-agent, eval, and mock operate cleanly.
- [ ] Hexagonal architecture implemented in `incident-console-v2`: domain ports defined under `lib/ports/`, Supabase PostgREST adapters implemented under `lib/adapters/supabase/`, and API routes refactored to depend on ports.
- [ ] Supabase MVP2 migration applied and validated on a PostgreSQL instance with pgvector (`evidence_crops`, `query_results`).
- [ ] Connection and security verification completed: service-role reachability verified, anon/authenticated lockdown verified, and verification evidence recorded in PR 120.
- [ ] VM `vss-agent` report persistence verified end to end on `kwanz-ws` without port 5432 errors or RLS rejections, and evidence recorded in PR 120.
- [ ] Hybrid search RPC produces accurate rankings across combined vector and text queries.
- [ ] Embedding generation script processes evidence items and populates pgvector embeddings.
- [ ] Re-analysis ingestion loader successfully loads batch output into `evidence_crops` and matches official report IDs.
- [ ] R2 helper generates working presigned URLs and cleanup logic correctly identifies orphaned crop keys.
- [ ] Documentation updated in `.docs/data.md` and `.docs/decisions.md`.

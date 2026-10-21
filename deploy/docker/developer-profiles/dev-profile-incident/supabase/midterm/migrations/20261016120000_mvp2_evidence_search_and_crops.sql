-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Migration: 20261016120000_mvp2_evidence_search_and_crops.sql
-- Description: Adds pgvector semantic search, unified evidence_crops table,
--              query_results table, and search RPC with strict RLS lockdown.

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create unified evidence_crops table for MVP2 crops and semantic embeddings
--    (Cleaner than altering entities/instruments/assets, consolidating search & vectors)
CREATE TABLE IF NOT EXISTS public.evidence_crops (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset')),
    item_id VARCHAR(20) NOT NULL,
    item_name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    threat_level INTEGER, -- Nullable for entities/assets, 1-5 for instruments
    holder_entity_id VARCHAR(20), -- Nullable, for instruments held by an entity
    timestamp_seconds INTEGER NOT NULL,
    bounding_box INTEGER[4] NOT NULL, -- [ymin, xmin, ymax, xmax] normalized 0-1000
    image VARCHAR(1024) NOT NULL, -- R2 key: evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg
    embedding vector(1024), -- Semantic text embedding for search by meaning (1024 dimensions)
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (incident_id, model_run_id, item_type, item_id),
    FOREIGN KEY (incident_id, model_run_id) REFERENCES public.incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- HNSW index for cosine distance (<=>) retrieval
CREATE INDEX IF NOT EXISTS evidence_crops_embedding_hnsw_idx 
    ON public.evidence_crops USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS evidence_crops_lookup_idx 
    ON public.evidence_crops (incident_id, model_run_id);

-- 3. Create query_results table for multi-item retrieval logging & critic audit
CREATE TABLE IF NOT EXISTS public.query_results (
    id VARCHAR(36) PRIMARY KEY, -- UUID or 'qr_' + 16 hex
    query_id VARCHAR(20) NOT NULL REFERENCES public.queries(id) ON DELETE CASCADE,
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    item_type VARCHAR(16) NOT NULL CHECK (item_type IN ('entity', 'instrument', 'asset')),
    item_id VARCHAR(20) NOT NULL,
    rank INTEGER NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    critic_verdict VARCHAR(16) NOT NULL CHECK (critic_verdict IN ('confirmed', 'rejected', 'unverified')),
    critic_rationale TEXT,
    retrieved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    FOREIGN KEY (incident_id, model_run_id) REFERENCES public.incidents(incident_id, model_run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS query_results_query_rank_idx ON public.query_results (query_id, rank);
CREATE INDEX IF NOT EXISTS query_results_incident_item_idx ON public.query_results (incident_id, model_run_id, item_type, item_id);

-- 4. Row-Level Security (RLS) Lockdown on New MVP2 Tables
--    (Compliant with Captain Decision 2026-10-16 and RLS lockdown policy)
ALTER TABLE public.evidence_crops ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.query_results ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.evidence_crops FROM anon, authenticated;
REVOKE ALL ON public.query_results FROM anon, authenticated;

GRANT ALL ON public.evidence_crops TO service_role;
GRANT ALL ON public.query_results TO service_role;

-- 5. Atomic Search RPC over official reports with incident join
CREATE OR REPLACE FUNCTION public.search_evidence_items(
    p_query_embedding vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
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
SET search_path = public, extensions
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
        (1.0 - (ec.embedding <=> p_query_embedding)) AS similarity_score
    FROM public.evidence_crops ec
    JOIN public.videos v ON v.id = ec.incident_id AND v.selected_model_run_id = ec.model_run_id
    JOIN public.incidents inc ON inc.incident_id = ec.incident_id AND inc.model_run_id = ec.model_run_id
    WHERE (p_item_types IS NULL OR ec.item_type = ANY(p_item_types))
      AND ec.embedding IS NOT NULL
      AND (1.0 - (ec.embedding <=> p_query_embedding)) >= p_min_similarity
      AND (p_incident_types IS NULL OR inc.type = ANY(p_incident_types))
      AND (p_min_severity IS NULL OR inc.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR inc.severity_level <= p_max_severity)
    ORDER BY ec.embedding <=> p_query_embedding ASC
    LIMIT p_top_k;
END;
$$;

-- Secure the Search RPC function
REVOKE ALL ON FUNCTION public.search_evidence_items FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_evidence_items TO service_role;

-- 6. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';

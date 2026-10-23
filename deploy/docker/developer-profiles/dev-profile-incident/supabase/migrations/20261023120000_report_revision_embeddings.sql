-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Incident-level vector search: one embedding per saved report revision.
--
-- The agent embeds the report summary (incident title and description) before it inserts an AI
-- revision and stores the vector in the same row. The column is NULL when the embedding endpoint
-- is unavailable, and for every human revision, since save_human_revision (a SQL function) does
-- not compute one. report_revisions is append-only, so a vector can only be set at insert time.
--
-- Safe on the live database, which already has the revision schema: the column and index use
-- IF NOT EXISTS, and the function is CREATE OR REPLACE.

BEGIN;

-- 1. embedding column and HNSW cosine index ------------------------------------------------------
-- The append-only trigger covers UPDATE and DELETE only, so ADD COLUMN is allowed.
ALTER TABLE public.report_revisions ADD COLUMN IF NOT EXISTS embedding extensions.vector(1024);

CREATE INDEX IF NOT EXISTS report_revisions_embedding_hnsw_idx ON public.report_revisions
    USING hnsw (embedding extensions.vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- 2. search_report_revisions ---------------------------------------------------------------------
-- Cosine search over every revision that has a vector (AI revisions, and human ones only if they
-- ever get one). Returns one row per revision, so a video can appear more than once; the caller
-- decides how to group. Title and description come from the payload, facets from the columns.
CREATE OR REPLACE FUNCTION public.search_report_revisions(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.0
)
RETURNS TABLE (
    revision_id BIGINT,
    video_id VARCHAR(20),
    revision_no INTEGER,
    kind VARCHAR(8),
    model_run_id VARCHAR(20),
    title TEXT,
    description TEXT,
    incident_type VARCHAR(64),
    severity_level INTEGER,
    start_seconds INTEGER,
    end_seconds INTEGER,
    similarity_score DOUBLE PRECISION
)
LANGUAGE plpgsql SECURITY INVOKER STABLE SET search_path = ''
AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.id,
        r.video_id,
        r.revision_no,
        r.kind,
        r.model_run_id,
        r.payload #>> '{incident,title}',
        r.payload #>> '{incident,description}',
        r.incident_type,
        r.severity_level,
        r.start_seconds,
        r.end_seconds,
        (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION
    FROM public.report_revisions AS r
    WHERE r.embedding IS NOT NULL
      AND (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity
    ORDER BY r.embedding OPERATOR(extensions.<=>) p_query_embedding ASC
    LIMIT p_top_k;
END;
$$;

-- 3. Security ------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION
    public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
TO service_role;

-- PostgREST caches function signatures; reload so the new one is callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

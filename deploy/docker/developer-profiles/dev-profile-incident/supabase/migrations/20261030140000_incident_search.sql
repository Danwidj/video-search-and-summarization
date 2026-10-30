-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Incident-level search for mvp3 (P3.2).
--
-- Defines search_evidence_items and search_report_revisions on the incident schema. Both were dropped
-- by the earlier mvp3 migrations (the core migration dropped the evidence search, the revisions
-- migration dropped the report search); this file creates them again and replaces nothing else.
--
-- Searchable revision: an incident is searched through one revision, the official one when it has one,
-- otherwise its newest. It is worked out inline, so this migration does not depend on
-- searchable_revision_id (owned by the crops migration). Stale revisions are never returned.
--
--   * search_evidence_items ranks the evidence_crops of each incident's searchable revision. Every hit
--     names the incident and the source video (video_id, video_filepath). p_video_id limits the scan
--     to one source video, p_incident_id to one incident; both are applied before ranking, so the
--     top p_top_k all come from the scope. A NULL p_query_embedding lists the scoped crops in video
--     time order with similarity 0 (the agent passes NULL only together with a scope).
--   * search_report_revisions ranks one revision per incident (its searchable revision) and returns
--     the incident id and the real names of the videos the revision covers.
--
-- Type and severity filters are applied to the searchable revision's incident_type and severity_level.
-- Safe to run again: the old signatures are dropped first and the functions are created with OR REPLACE.

BEGIN;

DROP FUNCTION IF EXISTS public.search_evidence_items(
    extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, TEXT, BIGINT);
DROP FUNCTION IF EXISTS public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION);

CREATE OR REPLACE FUNCTION public.search_evidence_items(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
    p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset'],
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INTEGER DEFAULT NULL,
    p_max_severity INTEGER DEFAULT NULL,
    p_video_id TEXT DEFAULT NULL,
    p_incident_id BIGINT DEFAULT NULL
)
RETURNS TABLE (
    incident_id BIGINT,
    revision_id BIGINT,
    model_run_id TEXT,
    video_id TEXT,
    video_filepath VARCHAR(1024),
    incident_title TEXT,
    incident_type VARCHAR(64),
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
LANGUAGE plpgsql SECURITY INVOKER STABLE SET search_path = ''
AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.incident_id,
        r.id,
        r.model_run_id,
        ec.video_id,
        v.filepath,
        r.payload #>> '{overview,title}',
        r.incident_type,
        r.severity_level,
        r.payload #>> '{overview,description}',
        r.start_seconds::VARCHAR(32),
        r.end_seconds::VARCHAR(32),
        ec.item_type,
        ec.item_id,
        ec.item_name,
        ec.description,
        ec.threat_level,
        ec.holder_entity_id,
        ec.image,
        ec.timestamp_seconds,
        ec.bounding_box,
        CASE WHEN p_query_embedding IS NULL THEN 0.0
             ELSE (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION
        END
    FROM public.evidence_crops AS ec
    JOIN public.report_revisions AS r ON r.id = ec.revision_id
    JOIN public.incidents AS i ON i.id = r.incident_id
    JOIN public.videos AS v ON v.id = ec.video_id
    WHERE r.id = COALESCE(
              i.official_revision_id,
              (SELECT r2.id FROM public.report_revisions AS r2
               WHERE r2.incident_id = i.id ORDER BY r2.revision_no DESC LIMIT 1))
      AND (p_incident_id IS NULL OR r.incident_id = p_incident_id)
      AND (p_video_id IS NULL OR ec.video_id = p_video_id)
      AND (p_item_types IS NULL OR ec.item_type = ANY (p_item_types))
      AND (p_query_embedding IS NULL OR ec.embedding IS NOT NULL)
      AND (p_query_embedding IS NULL
           OR (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity)
      AND (p_incident_types IS NULL OR r.incident_type = ANY (p_incident_types))
      AND (p_min_severity IS NULL OR r.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR r.severity_level <= p_max_severity)
    ORDER BY ec.embedding OPERATOR(extensions.<=>) p_query_embedding ASC NULLS LAST,
             ec.timestamp_seconds ASC, ec.video_id ASC, ec.item_id ASC
    LIMIT p_top_k;
END;
$$;

CREATE OR REPLACE FUNCTION public.search_report_revisions(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.0
)
RETURNS TABLE (
    incident_id BIGINT,
    revision_id BIGINT,
    revision_no INTEGER,
    kind VARCHAR(8),
    model_run_id TEXT,
    video_names TEXT[],
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
        r.incident_id,
        r.id,
        r.revision_no,
        r.kind,
        r.model_run_id,
        r.video_names,
        r.payload #>> '{overview,title}',
        r.payload #>> '{overview,description}',
        r.incident_type,
        r.severity_level,
        r.start_seconds,
        r.end_seconds,
        (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION
    FROM public.report_revisions AS r
    JOIN public.incidents AS i ON i.id = r.incident_id
    WHERE r.id = COALESCE(
              i.official_revision_id,
              (SELECT r2.id FROM public.report_revisions AS r2
               WHERE r2.incident_id = i.id ORDER BY r2.revision_no DESC LIMIT 1))
      AND r.embedding IS NOT NULL
      AND (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity
    ORDER BY r.embedding OPERATOR(extensions.<=>) p_query_embedding ASC, r.incident_id ASC
    LIMIT p_top_k;
END;
$$;

REVOKE ALL ON FUNCTION
    public.search_evidence_items(
        extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, TEXT, BIGINT),
    public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.search_evidence_items(
        extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, TEXT, BIGINT),
    public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
TO service_role;

-- PostgREST caches function signatures; reload so the new ones are callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

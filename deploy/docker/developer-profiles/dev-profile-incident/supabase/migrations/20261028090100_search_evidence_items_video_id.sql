-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- search_evidence_items can be scoped to one video.
--
-- "See evidence" on a library card searches that one incident. A new last argument, p_video_id, limits
-- the scan to that video's searchable revision before ranking, so the top p_top_k are all from the
-- video (filtering the global top-k afterwards would drop them). NULL searches every video, as before.
--
-- p_query_embedding may now be NULL. That lists the scoped video's crops in video time order with
-- similarity 0, which is what the card shows before anything is typed. The agent only passes NULL
-- together with a p_video_id.
--
-- The old 7-argument function is dropped first: two overloads would make PostgREST calls ambiguous.
-- The agent sends p_video_id only for a scoped search, so an agent deployed before this migration
-- still serves unscoped searches. The file is safe to run again.

BEGIN;

DROP FUNCTION IF EXISTS public.search_evidence_items(
    extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER);

CREATE OR REPLACE FUNCTION public.search_evidence_items(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
    p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset'],
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INTEGER DEFAULT NULL,
    p_max_severity INTEGER DEFAULT NULL,
    p_video_id VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    incident_id VARCHAR(20),
    revision_id BIGINT,
    model_run_id VARCHAR(20),
    video_filepath VARCHAR(1024),
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
        r.video_id,
        r.id,
        r.model_run_id,
        v.filepath,
        r.incident_type,
        r.severity_level,
        r.payload #>> '{incident,description}',
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
    JOIN public.videos AS v ON v.id = r.video_id AND public.searchable_revision_id(v.id) = r.id
    WHERE (p_video_id IS NULL OR r.video_id = p_video_id)
      AND (p_item_types IS NULL OR ec.item_type = ANY (p_item_types))
      AND (p_query_embedding IS NULL OR ec.embedding IS NOT NULL)
      AND (p_query_embedding IS NULL
           OR (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity)
      AND (p_incident_types IS NULL OR r.incident_type = ANY (p_incident_types))
      AND (p_min_severity IS NULL OR r.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR r.severity_level <= p_max_severity)
    ORDER BY ec.embedding OPERATOR(extensions.<=>) p_query_embedding ASC NULLS LAST,
             ec.timestamp_seconds ASC, ec.item_id ASC
    LIMIT p_top_k;
END;
$$;

REVOKE ALL ON FUNCTION
    public.search_evidence_items(
        extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, VARCHAR)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.search_evidence_items(
        extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, VARCHAR)
TO service_role;

-- PostgREST caches function signatures; reload so the new one is callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

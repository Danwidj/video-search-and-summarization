-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Functions over the versioned report tables from 20261023000000_report_revisions_schema.sql.
--
-- save_human_revision and set_official_revision are the write path the console uses; the three
-- reader RPCs replace their relational-model versions. Every function is SECURITY INVOKER with an
-- empty search_path and is executable by service_role only. The file is safe to run again: every
-- function is created with OR REPLACE (the schema migration dropped the predecessors).

BEGIN;

-- 1. save_human_revision -------------------------------------------------------------------------
-- Append a kind='human' revision for a video. The parent is the revision the reviewer opened; the
-- new revision inherits its model_run_id (the run whose output it derives from). revision_no is
-- max+1 for the video, assigned while the video row is locked, so concurrent saves cannot take the
-- same number. A writer that does not lock the video (the agent) relies on the unique
-- (video_id, revision_no) key and retries. Facets are written from the caller's arguments.
--
-- Returns {revisionId, revisionNo, videoId, kind, parentId, modelRunId, createdBy, createdAt, note}.
CREATE OR REPLACE FUNCTION public.save_human_revision(
    p_video_id VARCHAR,
    p_parent_id BIGINT,
    p_created_by TEXT,
    p_note TEXT,
    p_payload JSONB,
    p_evidence JSONB,
    p_incident_type TEXT,
    p_severity_level INTEGER,
    p_start_seconds INTEGER,
    p_end_seconds INTEGER
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_parent public.report_revisions;
    v_by TEXT := btrim(COALESCE(p_created_by, ''));
    v_row public.report_revisions;
BEGIN
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Video not found: %', p_video_id USING ERRCODE = 'P0001';
    END IF;
    IF p_parent_id IS NULL THEN
        RAISE EXCEPTION 'A parent revision is required' USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_parent
    FROM public.report_revisions
    WHERE id = p_parent_id AND video_id = p_video_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Revision not found for this video: %', p_parent_id USING ERRCODE = 'P0001';
    END IF;
    IF v_by = '' OR length(v_by) > 256 THEN
        RAISE EXCEPTION 'A reviewer name of 1 to 256 characters is required' USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
        OR jsonb_typeof(p_payload -> 'incident') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'The report payload must be an object with an incident' USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(p_evidence) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The evidence must be a list' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.report_revisions (
        video_id, revision_no, kind, model_run_id, parent_id, payload, evidence,
        incident_type, severity_level, start_seconds, end_seconds, created_by, note
    )
    SELECT
        p_video_id,
        COALESCE(MAX(r.revision_no), 0) + 1,
        'human',
        v_parent.model_run_id,
        v_parent.id,
        p_payload,
        p_evidence,
        p_incident_type,
        p_severity_level,
        p_start_seconds,
        p_end_seconds,
        v_by,
        NULLIF(btrim(COALESCE(p_note, '')), '')
    FROM public.report_revisions AS r
    WHERE r.video_id = p_video_id
    RETURNING * INTO v_row;

    RETURN jsonb_build_object(
        'revisionId', v_row.id,
        'revisionNo', v_row.revision_no,
        'videoId', v_row.video_id,
        'kind', v_row.kind,
        'parentId', v_row.parent_id,
        'modelRunId', v_row.model_run_id,
        'createdBy', v_row.created_by,
        'createdAt', v_row.created_at,
        'note', v_row.note
    );
END;
$$;

-- 2. set_official_revision -----------------------------------------------------------------------
-- Point a video at one official revision (NULL clears it) and replace that video's evidence_crops
-- with p_crops in the same transaction. p_crops is the exact row list the console wants stored:
--   [{item_type, item_id, image, bounding_box, timestamp_seconds, item_name, description,
--     threat_level, holder_entity_id, embedding}, ...]
-- Entries without an image are skipped; a missing bounding box becomes the whole frame; a missing
-- timestamp becomes 0. An embedding, when present, is a 1024-number JSON array.
--
-- Returns {videoId, officialRevisionId, crops}.
CREATE OR REPLACE FUNCTION public.set_official_revision(
    p_video_id VARCHAR,
    p_revision_id BIGINT,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_crops INTEGER := 0;
BEGIN
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Video not found: %', p_video_id USING ERRCODE = 'P0001';
    END IF;
    IF p_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.report_revisions
        WHERE id = p_revision_id AND video_id = p_video_id
    ) THEN
        RAISE EXCEPTION 'Revision not found for this video: %', p_revision_id USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;

    DELETE FROM public.evidence_crops
    WHERE revision_id IN (SELECT id FROM public.report_revisions WHERE video_id = p_video_id);
    UPDATE public.videos SET official_revision_id = p_revision_id WHERE id = p_video_id;

    IF p_revision_id IS NOT NULL THEN
        INSERT INTO public.evidence_crops (
            revision_id, item_type, item_id, item_name, description, threat_level, holder_entity_id,
            timestamp_seconds, bounding_box, image, embedding
        )
        SELECT DISTINCT ON (e ->> 'item_type', e ->> 'item_id')
            p_revision_id,
            e ->> 'item_type',
            e ->> 'item_id',
            left(COALESCE(NULLIF(btrim(COALESCE(e ->> 'item_name', '')), ''), e ->> 'item_type', 'item'), 256),
            COALESCE(e ->> 'description', ''),
            CASE WHEN jsonb_typeof(e -> 'threat_level') = 'number'
                THEN (e ->> 'threat_level')::NUMERIC::INTEGER END,
            NULLIF(btrim(COALESCE(e ->> 'holder_entity_id', '')), ''),
            COALESCE(
                CASE WHEN jsonb_typeof(e -> 'timestamp_seconds') = 'number'
                    THEN (e ->> 'timestamp_seconds')::NUMERIC::INTEGER END,
                0),
            CASE WHEN jsonb_typeof(e -> 'bounding_box') = 'array'
                    AND jsonb_array_length(e -> 'bounding_box') = 4
                THEN ARRAY(SELECT box.value::INTEGER FROM jsonb_array_elements_text(e -> 'bounding_box') AS box(value))
                ELSE ARRAY[0, 0, 1000, 1000] END,
            e ->> 'image',
            CASE WHEN jsonb_typeof(e -> 'embedding') = 'array'
                THEN (e -> 'embedding')::TEXT::extensions.vector(1024) END
        FROM jsonb_array_elements(COALESCE(p_crops, '[]'::JSONB)) AS e
        WHERE jsonb_typeof(e) = 'object'
          AND e ->> 'item_type' IN ('entity', 'instrument', 'asset')
          AND COALESCE(btrim(e ->> 'item_id'), '') <> ''
          AND COALESCE(btrim(e ->> 'image'), '') <> ''
        ORDER BY e ->> 'item_type', e ->> 'item_id';
        GET DIAGNOSTICS v_crops = ROW_COUNT;
    END IF;

    RETURN jsonb_build_object(
        'videoId', p_video_id,
        'officialRevisionId', p_revision_id,
        'crops', v_crops
    );
END;
$$;

-- 3. search_evidence_items -----------------------------------------------------------------------
-- Same arguments as the relational-model version; searches evidence_crops, which exist only for
-- official revisions, and returns the revision they belong to. query_results stores revision_id.
CREATE OR REPLACE FUNCTION public.search_evidence_items(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
    p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset'],
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INTEGER DEFAULT NULL,
    p_max_severity INTEGER DEFAULT NULL
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
        (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION
    FROM public.evidence_crops AS ec
    JOIN public.report_revisions AS r ON r.id = ec.revision_id
    JOIN public.videos AS v ON v.id = r.video_id AND v.official_revision_id = r.id
    WHERE (p_item_types IS NULL OR ec.item_type = ANY (p_item_types))
      AND ec.embedding IS NOT NULL
      AND (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity
      AND (p_incident_types IS NULL OR r.incident_type = ANY (p_incident_types))
      AND (p_min_severity IS NULL OR r.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR r.severity_level <= p_max_severity)
    ORDER BY ec.embedding OPERATOR(extensions.<=>) p_query_embedding ASC
    LIMIT p_top_k;
END;
$$;

-- 4. list_incident_report_summaries ---------------------------------------------------------------
-- One card per incident. The card is the official revision when there is one, otherwise the newest
-- revision (so the library still lists reports awaiting selection). Facets come from the revision
-- columns, the rest from its payload. p_kind filters on the card's kind ('ai' or 'human').
CREATE OR REPLACE FUNCTION public.list_incident_report_summaries(
    p_page INTEGER DEFAULT 1,
    p_page_size INTEGER DEFAULT 6,
    p_search TEXT DEFAULT NULL::TEXT,
    p_type TEXT DEFAULT NULL::TEXT,
    p_severity TEXT DEFAULT NULL::TEXT,
    p_kind TEXT DEFAULT NULL::TEXT,
    p_generated_after TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_generated_before TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_time_from TIME WITHOUT TIME ZONE DEFAULT NULL::TIME WITHOUT TIME ZONE,
    p_time_to TIME WITHOUT TIME ZONE DEFAULT NULL::TIME WITHOUT TIME ZONE,
    p_entities TEXT[] DEFAULT NULL::TEXT[],
    p_instruments TEXT[] DEFAULT NULL::TEXT[],
    p_assets TEXT[] DEFAULT NULL::TEXT[],
    p_day_of_week INTEGER DEFAULT NULL::INTEGER,
    p_sort TEXT DEFAULT 'newest'::TEXT,
    p_scope TEXT DEFAULT 'all'::TEXT,
    p_entity_types TEXT[] DEFAULT NULL::TEXT[],
    p_evidence_match TEXT DEFAULT 'contains'::TEXT,
    p_timezone TEXT DEFAULT 'UTC'::TEXT
) RETURNS JSONB
LANGUAGE sql STABLE SET search_path = ''
AS $function$
WITH parameters AS (
    SELECT
        replace(replace(replace(p_search, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') AS escaped_search,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_entities) AS value) AS escaped_entities,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_instruments) AS value) AS escaped_instruments,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_assets) AS value) AS escaped_assets,
        ARRAY(SELECT public.normalized_name(value) FROM unnest(p_instruments) AS value) AS exact_instruments,
        ARRAY(SELECT public.normalized_name(value) FROM unnest(p_assets) AS value) AS exact_assets,
        ARRAY(SELECT public.canonical_entity_type(value) FROM unnest(p_entity_types) AS value) AS entity_types,
        public.canonical_incident_type(p_type) AS canonical_type,
        COALESCE(p_evidence_match, 'contains') = 'exact' AS exact_match,
        COALESCE(NULLIF(p_timezone, ''), 'UTC') AS target_tz
),
shown AS (
    -- Per video: the official revision, else the newest.
    SELECT DISTINCT ON (r.video_id) r.*, v.official_revision_id IS NOT NULL AS is_official,
        v.filepath, v.source, v.uploaded_datetime
    FROM public.report_revisions AS r
    JOIN public.videos AS v ON v.id = r.video_id
    WHERE v.official_revision_id IS NULL OR v.official_revision_id = r.id
    ORDER BY r.video_id, r.revision_no DESC
),
filtered AS (
    SELECT
        s.id AS revision_id, s.revision_no, s.video_id, s.model_run_id, s.kind, s.created_by, s.note,
        s.payload #>> '{incident,title}' AS stored_title,
        s.incident_type, s.payload #>> '{incident,description}' AS description, s.severity_level,
        CASE WHEN jsonb_typeof(s.payload #> '{incident,confidence_score}') = 'number'
            THEN (s.payload #>> '{incident,confidence_score}')::DOUBLE PRECISION END AS confidence_score,
        s.created_at AS generated_datetime, s.uploaded_datetime,
        regexp_replace(COALESCE(s.filepath, s.video_id), '^.*/', '') AS filename,
        mr.model_name, CASE WHEN mr.id IS NULL THEN NULL ELSE public.run_outcome(mr.notes) END AS outcome,
        s.is_official, s.filepath AS r2_key, s.source AS sensor_id,
        COALESCE(s.payload -> 'entities', '[]'::JSONB) AS entities,
        COALESCE(s.payload -> 'instruments', '[]'::JSONB) AS instruments,
        COALESCE(s.payload -> 'assets', '[]'::JSONB) AS assets
    FROM shown AS s
    LEFT JOIN public.model_runs AS mr ON mr.id = s.model_run_id
    CROSS JOIN parameters AS params
    WHERE (COALESCE(p_scope, 'all') <> 'official' OR s.is_official)
      AND (p_kind IS NULL OR s.kind = p_kind)
      AND (p_type IS NULL OR s.incident_type = params.canonical_type)
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'high' THEN s.severity_level >= 4
          WHEN 'medium' THEN s.severity_level = 3
          WHEN 'low' THEN s.severity_level <= 2
          ELSE s.severity_level = p_severity::INTEGER END)
      AND (p_generated_after IS NULL OR s.created_at >= p_generated_after)
      AND (p_generated_before IS NULL OR s.created_at <= p_generated_before)
      AND (p_time_from IS NULL OR (s.created_at AT TIME ZONE 'utc' AT TIME ZONE params.target_tz)::TIME >= p_time_from)
      AND (p_time_to IS NULL OR (s.created_at AT TIME ZONE 'utc' AT TIME ZONE params.target_tz)::TIME <= p_time_to)
      AND (p_day_of_week IS NULL OR EXTRACT(DOW FROM (s.created_at AT TIME ZONE 'utc' AT TIME ZONE params.target_tz))::INTEGER = p_day_of_week)
),
matched AS (
    SELECT f.* FROM filtered AS f CROSS JOIN parameters AS params
    WHERE (p_entity_types IS NULL OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(f.entities) e
          WHERE public.canonical_entity_type(e ->> 'type') = ANY (params.entity_types)
      ))
      AND (p_entities IS NULL OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(f.entities) e
          WHERE EXISTS (SELECT 1 FROM unnest(params.escaped_entities) term WHERE concat_ws(' ', e ->> 'type', e ->> 'description') ILIKE '%' || term || '%' ESCAPE E'\\')
      ))
      AND (p_instruments IS NULL OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(f.instruments) ins
          WHERE CASE WHEN params.exact_match
              THEN public.normalized_name(ins ->> 'name') = ANY (params.exact_instruments)
              ELSE EXISTS (SELECT 1 FROM unnest(params.escaped_instruments) term WHERE concat_ws(' ', ins ->> 'name', ins ->> 'description') ILIKE '%' || term || '%' ESCAPE E'\\')
          END
      ))
      AND (p_assets IS NULL OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(f.assets) a
          WHERE CASE WHEN params.exact_match
              THEN public.normalized_name(a ->> 'name') = ANY (params.exact_assets)
              ELSE EXISTS (SELECT 1 FROM unnest(params.escaped_assets) term WHERE concat_ws(' ', a ->> 'name', a ->> 'description') ILIKE '%' || term || '%' ESCAPE E'\\')
          END
      ))
      AND (params.escaped_search IS NULL
          OR concat_ws(' ', f.stored_title, f.incident_type, f.description, f.filename) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.entities) e WHERE concat_ws(' ', e ->> 'type', e ->> 'description') ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.instruments) ins WHERE concat_ws(' ', ins ->> 'name', ins ->> 'description') ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.assets) a WHERE concat_ws(' ', a ->> 'name', a ->> 'description') ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'))
),
ordered AS (
    SELECT * FROM matched
    ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, revision_id ASC
    LIMIT LEAST(GREATEST(p_page_size, 1), 1000)
    OFFSET (GREATEST(p_page, 1) - 1) * LEAST(GREATEST(p_page_size, 1), 1000)
),
incident_types AS (
    SELECT COALESCE(jsonb_agg(incident_type ORDER BY incident_type), '[]'::JSONB) AS values
    FROM (SELECT DISTINCT incident_type FROM shown WHERE incident_type IS NOT NULL) types
)
SELECT jsonb_build_object(
    'reports', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'revisionId', revision_id, 'revisionNo', revision_no, 'videoId', video_id, 'modelRunId', model_run_id,
        'kind', kind, 'createdBy', created_by, 'note', note,
        'title', COALESCE(NULLIF(stored_title, ''), COALESCE(NULLIF(initcap(incident_type), ''), 'Incident') || ' report'),
        'filename', filename, 'incident_type', COALESCE(incident_type, 'Unclassified'),
        'description', COALESCE(description, 'No summary was recorded.'),
        'severity', COALESCE(severity_level, 1), 'confidence', confidence_score,
        'generatedAt', generated_datetime, 'uploadedAt', uploaded_datetime,
        'model', COALESCE(model_name, 'Unknown model'),
        'outcome', outcome, 'isOfficial', is_official,
        'r2Key', r2_key, 'sensorId', sensor_id
    ) ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, revision_id ASC) FROM ordered), '[]'::JSONB),
    'totalItems', (SELECT count(*) FROM matched),
    'incidentTypes', (SELECT values FROM incident_types)
);
$function$;

-- 5. get_incident_dashboard ----------------------------------------------------------------------
-- Incident statistics from each video's official revision only (facet columns and payload); videos
-- are counted all time; model coverage counts analysis attempts by outcome (failed attempts from
-- model_runs, successful ones by their AI revision). 'revisions' splits official reports by kind.
CREATE OR REPLACE FUNCTION public.get_incident_dashboard(
    p_period_start TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_period_end TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_type TEXT DEFAULT NULL::TEXT,
    p_severity TEXT DEFAULT NULL::TEXT,
    p_day_of_week INTEGER DEFAULT NULL::INTEGER,
    p_hour INTEGER DEFAULT NULL::INTEGER,
    p_timezone TEXT DEFAULT 'UTC'::TEXT
) RETURNS JSONB
LANGUAGE sql STABLE SET search_path = ''
AS $function$
WITH target_tz AS (
    SELECT COALESCE(NULLIF(p_timezone, ''), 'UTC') AS tz
),
official_all AS (
    -- One incident per video: its official revision. Its time is when that revision was made.
    SELECT
        r.video_id AS incident_id, r.id AS revision_id, r.kind, r.created_at AS generated_datetime,
        r.incident_type, r.severity_level AS severity,
        CASE WHEN jsonb_typeof(r.payload #> '{incident,confidence_score}') = 'number'
            THEN (r.payload #>> '{incident,confidence_score}')::DOUBLE PRECISION END AS confidence,
        r.payload,
        EXTRACT(DOW FROM (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS day_of_week,
        EXTRACT(HOUR FROM (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS hour_of_day
    FROM public.videos AS v
    JOIN public.report_revisions AS r ON r.video_id = v.id AND r.id = v.official_revision_id
    CROSS JOIN target_tz
),
dimension_filtered AS (
    SELECT * FROM official_all
    WHERE (p_type IS NULL OR incident_type = public.canonical_incident_type(p_type))
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'low' THEN severity <= 2 WHEN 'medium' THEN severity = 3 WHEN 'high' THEN severity >= 4 ELSE FALSE END)
      AND (p_day_of_week IS NULL OR day_of_week = p_day_of_week)
      AND (p_hour IS NULL OR hour_of_day = p_hour)
),
filtered AS (
    SELECT * FROM dimension_filtered
    WHERE (p_period_start IS NULL OR generated_datetime >= p_period_start)
      AND (p_period_end IS NULL OR generated_datetime < p_period_end)
),
video_counts AS (
    SELECT
        COUNT(*)::INTEGER AS uploaded,
        COUNT(*) FILTER (WHERE v.official_revision_id IS NOT NULL)::INTEGER AS with_official,
        COUNT(*) FILTER (WHERE v.official_revision_id IS NULL AND EXISTS (SELECT 1 FROM public.report_revisions r WHERE r.video_id = v.id))::INTEGER AS awaiting_selection,
        COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM public.report_revisions r WHERE r.video_id = v.id))::INTEGER AS without_report
    -- All time, independent of the period, so these numbers match the /videos lists they link to.
    FROM public.videos AS v
),
date_bounds AS (
    SELECT
        COALESCE(p_period_start::DATE, MIN(generated_datetime)::DATE, CURRENT_DATE) AS first_day,
        COALESCE((p_period_end - INTERVAL '1 microsecond')::DATE, MAX(generated_datetime)::DATE, CURRENT_DATE) AS last_day
    FROM filtered
),
daily AS (
    SELECT day::DATE AS day, COUNT(f.incident_id)::INTEGER AS count
    FROM date_bounds
    CROSS JOIN LATERAL generate_series(first_day, last_day, INTERVAL '1 day') AS day
    LEFT JOIN filtered AS f ON f.generated_datetime::DATE = day::DATE
    GROUP BY day ORDER BY day
),
entity_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.canonical_entity_type(e ->> 'type') AS label
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'entities', '[]'::JSONB)) AS e
),
instrument_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(ins ->> 'name') AS label,
        CASE WHEN jsonb_typeof(ins -> 'threat_level') = 'number'
            THEN (ins ->> 'threat_level')::NUMERIC::INTEGER END AS threat_level
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'instruments', '[]'::JSONB)) AS ins
    WHERE public.normalized_name(ins ->> 'name') IS NOT NULL
),
asset_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(a ->> 'name') AS label
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'assets', '[]'::JSONB)) AS a
    WHERE public.normalized_name(a ->> 'name') IS NOT NULL
),
type_counts AS (
    SELECT incident_type, COUNT(*)::INTEGER AS count FROM filtered GROUP BY incident_type
),
type_details AS (
    SELECT jsonb_agg(jsonb_build_object(
        'type', COALESCE(tc.incident_type, 'Unclassified'),
        'count', tc.count,
        'severity', jsonb_build_object(
            'low', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity <= 2),
            'medium', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity = 3),
            'high', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity >= 4)),
        'entities', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM entity_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label LIMIT 3) ranked), '[]'::JSONB),
        'instruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM instrument_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label LIMIT 3) ranked), '[]'::JSONB),
        'assets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM asset_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label LIMIT 3) ranked), '[]'::JSONB)
    ) ORDER BY tc.count DESC, tc.incident_type) AS values
    FROM type_counts tc
),
ranked AS (
    SELECT 'entity' AS kind, label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM entity_rows GROUP BY label
    UNION ALL SELECT 'instrument', label, COUNT(DISTINCT incident_id)::INTEGER FROM instrument_rows GROUP BY label
    UNION ALL SELECT 'asset', label, COUNT(DISTINCT incident_id)::INTEGER FROM asset_rows GROUP BY label
),
threat_levels AS (
    SELECT threat_level AS level, COUNT(*)::INTEGER AS count FROM instrument_rows WHERE threat_level IS NOT NULL GROUP BY threat_level
),
attempts AS (
    -- Every recorded analysis attempt in the period, by outcome: failed attempts from model_runs,
    -- successful ones by their AI revision.
    SELECT mr.model_name, public.run_outcome(mr.notes) AS outcome
    FROM public.model_runs mr
    WHERE public.run_outcome(mr.notes) IN ('contract_failed', 'request_failed')
      AND (p_period_start IS NULL OR mr.run_datetime >= p_period_start)
      AND (p_period_end IS NULL OR mr.run_datetime < p_period_end)
    UNION ALL
    SELECT mr.model_name, public.run_outcome(mr.notes)
    FROM public.report_revisions r JOIN public.model_runs mr ON mr.id = r.model_run_id
    WHERE r.kind = 'ai'
      AND (p_period_start IS NULL OR r.created_at >= p_period_start)
      AND (p_period_end IS NULL OR r.created_at < p_period_end)
),
model_coverage AS (
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'model', model_name,
        'withReport', with_report, 'validFirstPass', valid_first_pass, 'repaired', repaired,
        'legacy', legacy, 'contractFailed', contract_failed, 'requestFailed', request_failed
    ) ORDER BY with_report DESC, model_name), '[]'::JSONB) AS values
    FROM (
        SELECT COALESCE(model_name, 'Unknown model') AS model_name,
            COUNT(*) FILTER (WHERE outcome NOT IN ('contract_failed', 'request_failed'))::INTEGER AS with_report,
            COUNT(*) FILTER (WHERE outcome = 'valid_first_pass')::INTEGER AS valid_first_pass,
            COUNT(*) FILTER (WHERE outcome = 'valid_after_structural_repair')::INTEGER AS repaired,
            COUNT(*) FILTER (WHERE outcome = 'legacy')::INTEGER AS legacy,
            COUNT(*) FILTER (WHERE outcome = 'contract_failed')::INTEGER AS contract_failed,
            COUNT(*) FILTER (WHERE outcome = 'request_failed')::INTEGER AS request_failed
        FROM attempts GROUP BY COALESCE(model_name, 'Unknown model')
    ) per_model
),
confidence_buckets AS (
    SELECT LEAST(9, GREATEST(0, FLOOR(confidence * 10)::INTEGER)) AS bucket, COUNT(*)::INTEGER AS count
    FROM filtered WHERE confidence IS NOT NULL GROUP BY 1
),
heatmap AS (
    SELECT day_of_week, hour_of_day, COUNT(*)::INTEGER AS count FROM filtered GROUP BY day_of_week, hour_of_day
),
previous AS (
    SELECT COUNT(*)::INTEGER AS total,
        COUNT(*) FILTER (WHERE kind = 'human')::INTEGER AS human,
        COUNT(*) FILTER (WHERE kind = 'ai')::INTEGER AS ai,
        COUNT(*) FILTER (WHERE severity >= 4)::INTEGER AS high
    FROM dimension_filtered
    WHERE p_period_start IS NOT NULL AND p_period_end IS NOT NULL
      AND generated_datetime >= p_period_start - (p_period_end - p_period_start)
      AND generated_datetime < p_period_start
)
SELECT jsonb_build_object(
    'total', (SELECT COUNT(*) FROM filtered),
    'videos', (SELECT jsonb_build_object('uploaded', uploaded, 'withOfficial', with_official, 'awaitingSelection', awaiting_selection, 'withoutReport', without_report) FROM video_counts),
    'previous', CASE WHEN p_period_start IS NULL OR p_period_end IS NULL THEN NULL ELSE (SELECT to_jsonb(previous) FROM previous) END,
    'averageConfidence', (SELECT AVG(confidence) FROM filtered WHERE confidence IS NOT NULL),
    'confidenceNotProvided', (SELECT COUNT(*) FROM filtered WHERE confidence IS NULL),
    'severity', (SELECT jsonb_build_object('low', COUNT(*) FILTER (WHERE severity <= 2), 'medium', COUNT(*) FILTER (WHERE severity = 3), 'high', COUNT(*) FILTER (WHERE severity >= 4)) FROM filtered),
    'revisions', (SELECT jsonb_build_object('ai', COUNT(*) FILTER (WHERE kind = 'ai'), 'human', COUNT(*) FILTER (WHERE kind = 'human')) FROM filtered),
    'types', COALESCE((SELECT values FROM type_details), '[]'::JSONB),
    'trend', COALESCE((SELECT jsonb_agg(jsonb_build_object('date', day, 'count', count) ORDER BY day) FROM daily), '[]'::JSONB),
    'heatmap', COALESCE((SELECT jsonb_agg(jsonb_build_object('day', day_of_week, 'hour', hour_of_day, 'count', count) ORDER BY day_of_week, hour_of_day) FROM heatmap), '[]'::JSONB),
    'confidence', COALESCE((SELECT jsonb_agg(jsonb_build_object('bucket', bucket, 'count', count) ORDER BY bucket) FROM confidence_buckets), '[]'::JSONB),
    'entityTypes', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM ranked WHERE kind = 'entity'), '[]'::JSONB),
    'topInstruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (SELECT * FROM ranked WHERE kind = 'instrument' ORDER BY count DESC, label LIMIT 8) top), '[]'::JSONB),
    'topAssets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (SELECT * FROM ranked WHERE kind = 'asset' ORDER BY count DESC, label LIMIT 8) top), '[]'::JSONB),
    'threatLevels', COALESCE((SELECT jsonb_agg(jsonb_build_object('level', level, 'count', count) ORDER BY level) FROM threat_levels), '[]'::JSONB),
    'modelCoverage', (SELECT values FROM model_coverage)
);
$function$;

-- 6. Security ------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION
    public.save_human_revision(VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER),
    public.set_official_revision(VARCHAR, BIGINT, JSONB),
    public.search_evidence_items(extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER),
    public.list_incident_report_summaries(
        INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
        TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT),
    public.get_incident_dashboard(
        TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.save_human_revision(VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER),
    public.set_official_revision(VARCHAR, BIGINT, JSONB),
    public.search_evidence_items(extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER),
    public.list_incident_report_summaries(
        INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
        TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT),
    public.get_incident_dashboard(
        TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT)
TO service_role;

-- PostgREST caches function signatures; reload so the new ones are callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

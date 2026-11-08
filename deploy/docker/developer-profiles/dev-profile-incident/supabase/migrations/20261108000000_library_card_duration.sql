-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Each library summary carries durationSeconds: the video's length as the analysis that produced the shown
-- revision read it (incidentConsoleV2.request.videoDurationSeconds in its model_runs.notes). The Library card
-- shows it as a badge. NULL when the run did not record a length, or the revision has no run.
-- The signature, defaults, sort and grants are unchanged from 20261107100000 (CREATE OR REPLACE). Safe to run twice.

BEGIN;

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
        v.official_since, v.filepath, v.source, v.uploaded_datetime
    FROM public.report_revisions AS r
    JOIN public.videos AS v ON v.id = r.video_id
    WHERE v.official_revision_id IS NULL OR v.official_revision_id = r.id
    ORDER BY r.video_id, r.revision_no DESC
),
filtered AS (
    SELECT
        s.id AS revision_id, s.revision_no, s.video_id, s.model_run_id, s.kind, s.created_by, s.note,
        s.payload #>> '{incident,title}' AS stored_title,
        CASE WHEN jsonb_typeof(public.try_parse_jsonb(mr.notes) #> '{incidentConsoleV2,request,videoDurationSeconds}') = 'number'
            THEN (public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,request,videoDurationSeconds}')::DOUBLE PRECISION END AS duration_seconds,
        s.incident_type, s.payload #>> '{incident,description}' AS description, s.severity_level,
        CASE WHEN jsonb_typeof(s.payload #> '{incident,confidence_score}') = 'number'
            THEN (s.payload #>> '{incident,confidence_score}')::DOUBLE PRECISION END AS confidence_score,
        s.created_at AS generated_datetime, s.uploaded_datetime,
        regexp_replace(COALESCE(s.filepath, s.video_id), '^.*/', '') AS filename,
        mr.model_name, CASE WHEN mr.id IS NULL THEN NULL ELSE public.run_outcome(mr.notes) END AS outcome,
        s.is_official, s.official_since, s.evidence, s.filepath AS r2_key, s.source AS sensor_id,
        COALESCE(s.payload -> 'entities', '[]'::JSONB) AS entities,
        COALESCE(s.payload -> 'instruments', '[]'::JSONB) AS instruments,
        COALESCE(s.payload -> 'assets', '[]'::JSONB) AS assets
    FROM shown AS s
    LEFT JOIN public.model_runs AS mr ON mr.id = s.model_run_id
    CROSS JOIN parameters AS params
    WHERE (COALESCE(p_scope, 'all') <> 'official' OR s.is_official)
      AND (COALESCE(p_scope, 'all') <> 'not_official' OR NOT s.is_official)
      AND (p_kind IS NULL OR s.kind = p_kind)
      AND (p_type IS NULL OR s.incident_type = params.canonical_type
          OR (params.canonical_type = 'unclassified' AND s.incident_type IS NULL))
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
    ORDER BY CASE WHEN p_sort = 'official-first' THEN is_official END DESC,
        CASE WHEN p_sort = 'official-first' THEN uploaded_datetime END ASC,
        CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
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
        'outcome', outcome, 'isOfficial', is_official, 'officialSince', official_since, 'durationSeconds', duration_seconds,
        'versionCount', (SELECT count(*) FROM public.report_revisions AS x WHERE x.video_id = ordered.video_id),
        'evidenceCount', (SELECT count(*) FROM jsonb_array_elements(ordered.evidence) AS ev WHERE public.evidence_image(ev) IS NOT NULL),
        'thumbnail', (SELECT public.evidence_image(ev) FROM jsonb_array_elements(ordered.evidence) WITH ORDINALITY AS t(ev, n)
            WHERE public.evidence_image(ev) IS NOT NULL ORDER BY n LIMIT 1),
        'r2Key', r2_key, 'sensorId', sensor_id
    ) ORDER BY CASE WHEN p_sort = 'official-first' THEN is_official END DESC,
        CASE WHEN p_sort = 'official-first' THEN uploaded_datetime END ASC,
        CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
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

NOTIFY pgrst, 'reload schema';

COMMIT;

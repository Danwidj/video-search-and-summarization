-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Library and dashboard summaries per incident for mvp3 (P3.1).
--
-- Rewrites the two functions the core migration dropped:
--   1. list_incident_report_summaries: one row per incident. The card shows the incident's official
--      revision, else its latest one. Each row carries the video count, the first video's name, key and
--      thumbnail key, and the revision's coverage (video_names) plus the computed gap against the
--      incident's current videos. An incident with no revision yet still gets a row (revisionId null).
--   2. get_incident_dashboard: counts incidents (statistics from official revisions only) and videos.
--
-- Facets (entities, instruments, assets) come from every camera report of the revision envelope;
-- title, description and confidence come from its overview. Arguments are unchanged.
-- Defines only these two functions; it assumes the tables of the core, per-incident revision and
-- analyses migrations and the baseline helpers (canonical_*, normalized_name, run_outcome).

BEGIN;

-- 1. list_incident_report_summaries ---------------------------------------------------------------
-- The first video is the earliest uploaded (ties by name). The thumbnail key is derived from its
-- logical R2 key as the console does (thumbnails/<key>.webp); null when the video has no key.
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
    -- Per incident: the official revision, else the newest (none when the incident has no revision yet).
    SELECT i.id AS incident_id, i.created_at AS incident_created_at,
        i.official_revision_id IS NOT NULL AS is_official, i.official_since,
        r.id AS revision_id, r.revision_no, r.model_run_id, r.kind, r.created_by, r.note, r.payload,
        r.incident_type, r.severity_level, r.created_at AS revision_created_at, r.evidence,
        COALESCE(r.video_names, '{}'::TEXT[]) AS covered_names
    FROM public.incidents AS i
    LEFT JOIN LATERAL (
        SELECT x.* FROM public.report_revisions AS x
        WHERE x.incident_id = i.id AND (i.official_revision_id IS NULL OR x.id = i.official_revision_id)
        ORDER BY x.revision_no DESC LIMIT 1
    ) AS r ON TRUE
),
enriched AS (
    SELECT s.*,
        (SELECT count(*) FROM public.videos AS v WHERE v.incident_id = s.incident_id)::INTEGER AS video_count,
        (SELECT count(*) FROM public.report_revisions AS x WHERE x.incident_id = s.incident_id)::INTEGER AS version_count,
        fv.id AS first_video_name, fv.filepath AS first_video_key, fv.source AS first_video_source,
        (SELECT min(v.uploaded_datetime) FROM public.videos AS v WHERE v.incident_id = s.incident_id) AS uploaded_datetime,
        ARRAY(SELECT v.id FROM public.videos AS v WHERE v.incident_id = s.incident_id
            AND NOT (v.id = ANY (s.covered_names)) ORDER BY v.id) AS missing_videos,
        ARRAY(SELECT n FROM unnest(s.covered_names) AS n WHERE NOT EXISTS (
            SELECT 1 FROM public.videos AS v WHERE v.incident_id = s.incident_id AND v.id = n)) AS removed_videos,
        CASE WHEN jsonb_typeof(s.payload -> 'cameras') = 'array' THEN s.payload -> 'cameras' ELSE '[]'::JSONB END AS cameras
    FROM shown AS s
    LEFT JOIN LATERAL (
        SELECT v.id, v.filepath, v.source FROM public.videos AS v
        WHERE v.incident_id = s.incident_id ORDER BY v.uploaded_datetime ASC NULLS LAST, v.id ASC LIMIT 1
    ) AS fv ON TRUE
),
filtered AS (
    SELECT
        e.incident_id, e.revision_id, e.revision_no, e.model_run_id, e.kind, e.created_by, e.note,
        e.payload #>> '{overview,title}' AS stored_title,
        e.incident_type, e.payload #>> '{overview,description}' AS description, e.severity_level,
        CASE WHEN jsonb_typeof(e.payload #> '{overview,confidence_score}') = 'number'
            THEN (e.payload #>> '{overview,confidence_score}')::DOUBLE PRECISION END AS confidence_score,
        COALESCE(e.revision_created_at, e.incident_created_at) AS generated_datetime, e.uploaded_datetime,
        e.first_video_name, e.first_video_key, e.first_video_source, e.video_count, e.version_count,
        e.covered_names, e.missing_videos, e.removed_videos,
        mr.model_name, CASE WHEN mr.id IS NULL THEN NULL ELSE public.run_outcome(mr.notes) END AS outcome,
        e.is_official, e.official_since,
        COALESCE((SELECT jsonb_agg(x) FROM jsonb_array_elements(e.cameras) AS c,
            jsonb_array_elements(CASE WHEN jsonb_typeof(c -> 'report' -> 'entities') = 'array' THEN c -> 'report' -> 'entities' ELSE '[]'::JSONB END) AS x), '[]'::JSONB) AS entities,
        COALESCE((SELECT jsonb_agg(x) FROM jsonb_array_elements(e.cameras) AS c,
            jsonb_array_elements(CASE WHEN jsonb_typeof(c -> 'report' -> 'instruments') = 'array' THEN c -> 'report' -> 'instruments' ELSE '[]'::JSONB END) AS x), '[]'::JSONB) AS instruments,
        COALESCE((SELECT jsonb_agg(x) FROM jsonb_array_elements(e.cameras) AS c,
            jsonb_array_elements(CASE WHEN jsonb_typeof(c -> 'report' -> 'assets') = 'array' THEN c -> 'report' -> 'assets' ELSE '[]'::JSONB END) AS x), '[]'::JSONB) AS assets,
        ARRAY(SELECT v.id FROM public.videos AS v WHERE v.incident_id = e.incident_id ORDER BY v.id) AS video_names
    FROM enriched AS e
    LEFT JOIN public.model_runs AS mr ON mr.id = e.model_run_id
    CROSS JOIN parameters AS params
    WHERE (COALESCE(p_scope, 'all') <> 'official' OR e.is_official)
      AND (p_kind IS NULL OR e.kind = p_kind)
      AND (p_type IS NULL OR e.incident_type = params.canonical_type)
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'high' THEN e.severity_level >= 4
          WHEN 'medium' THEN e.severity_level = 3
          WHEN 'low' THEN e.severity_level <= 2
          ELSE e.severity_level = p_severity::INTEGER END)
      AND (p_generated_after IS NULL OR COALESCE(e.revision_created_at, e.incident_created_at) >= p_generated_after)
      AND (p_generated_before IS NULL OR COALESCE(e.revision_created_at, e.incident_created_at) <= p_generated_before)
      AND (p_time_from IS NULL OR (COALESCE(e.revision_created_at, e.incident_created_at) AT TIME ZONE 'utc' AT TIME ZONE params.target_tz)::TIME >= p_time_from)
      AND (p_time_to IS NULL OR (COALESCE(e.revision_created_at, e.incident_created_at) AT TIME ZONE 'utc' AT TIME ZONE params.target_tz)::TIME <= p_time_to)
      AND (p_day_of_week IS NULL OR EXTRACT(DOW FROM (COALESCE(e.revision_created_at, e.incident_created_at) AT TIME ZONE 'utc' AT TIME ZONE params.target_tz))::INTEGER = p_day_of_week)
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
          OR concat_ws(' ', f.stored_title, f.incident_type, f.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          OR EXISTS (SELECT 1 FROM unnest(f.video_names) AS n WHERE n ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.entities) e WHERE concat_ws(' ', e ->> 'type', e ->> 'description') ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.instruments) ins WHERE concat_ws(' ', ins ->> 'name', ins ->> 'description') ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.assets) a WHERE concat_ws(' ', a ->> 'name', a ->> 'description') ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'))
),
ordered AS (
    SELECT * FROM matched
    ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC NULLS LAST,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC NULLS LAST,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, incident_id ASC
    LIMIT LEAST(GREATEST(p_page_size, 1), 1000)
    OFFSET (GREATEST(p_page, 1) - 1) * LEAST(GREATEST(p_page_size, 1), 1000)
),
incident_types AS (
    SELECT COALESCE(jsonb_agg(incident_type ORDER BY incident_type), '[]'::JSONB) AS values
    FROM (SELECT DISTINCT incident_type FROM shown WHERE incident_type IS NOT NULL) types
)
SELECT jsonb_build_object(
    'reports', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'incidentId', incident_id, 'revisionId', revision_id, 'revisionNo', revision_no, 'modelRunId', model_run_id,
        'kind', kind, 'createdBy', created_by, 'note', note,
        'title', COALESCE(NULLIF(stored_title, ''), COALESCE(NULLIF(initcap(incident_type), ''), 'Incident') || ' report'),
        'incident_type', COALESCE(incident_type, 'Unclassified'),
        'description', COALESCE(description, 'No summary was recorded.'),
        'severity', COALESCE(severity_level, 1), 'confidence', confidence_score,
        'generatedAt', generated_datetime, 'uploadedAt', uploaded_datetime,
        'model', COALESCE(model_name, 'Unknown model'),
        'outcome', outcome, 'isOfficial', is_official, 'officialSince', official_since,
        'versionCount', version_count, 'videoCount', video_count,
        'firstVideoName', first_video_name, 'firstVideoKey', first_video_key,
        'thumbnail', CASE WHEN first_video_key IS NULL THEN NULL ELSE 'thumbnails/' || first_video_key || '.webp' END,
        'sensorId', first_video_source,
        'coverage', to_jsonb(covered_names), 'missingVideos', to_jsonb(missing_videos),
        'removedVideos', to_jsonb(removed_videos)
    ) ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC NULLS LAST,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC NULLS LAST,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, incident_id ASC) FROM ordered), '[]'::JSONB),
    'totalItems', (SELECT count(*) FROM matched),
    'incidentTypes', (SELECT values FROM incident_types)
);
$function$;

-- 2. get_incident_dashboard ----------------------------------------------------------------------
-- Statistics come from each incident's official revision only (facet columns and envelope). 'incidents'
-- counts incidents all time (total, with an official revision, awaiting selection, without a report);
-- 'videos' counts uploaded videos all time. Model coverage counts analysis attempts by outcome (failed
-- attempts from model_runs, successful ones by their AI revision). 'revisions' splits official reports
-- by kind.
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
    -- One row per incident that has an official revision. Its time is when that revision was made.
    SELECT
        i.id AS incident_id, r.id AS revision_id, r.kind, r.created_at AS generated_datetime,
        r.incident_type, r.severity_level AS severity,
        CASE WHEN jsonb_typeof(r.payload #> '{overview,confidence_score}') = 'number'
            THEN (r.payload #>> '{overview,confidence_score}')::DOUBLE PRECISION END AS confidence,
        COALESCE((SELECT jsonb_agg(x) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.payload -> 'cameras') = 'array' THEN r.payload -> 'cameras' ELSE '[]'::JSONB END) AS c,
            jsonb_array_elements(CASE WHEN jsonb_typeof(c -> 'report' -> 'entities') = 'array' THEN c -> 'report' -> 'entities' ELSE '[]'::JSONB END) AS x), '[]'::JSONB) AS entities,
        COALESCE((SELECT jsonb_agg(x) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.payload -> 'cameras') = 'array' THEN r.payload -> 'cameras' ELSE '[]'::JSONB END) AS c,
            jsonb_array_elements(CASE WHEN jsonb_typeof(c -> 'report' -> 'instruments') = 'array' THEN c -> 'report' -> 'instruments' ELSE '[]'::JSONB END) AS x), '[]'::JSONB) AS instruments,
        COALESCE((SELECT jsonb_agg(x) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.payload -> 'cameras') = 'array' THEN r.payload -> 'cameras' ELSE '[]'::JSONB END) AS c,
            jsonb_array_elements(CASE WHEN jsonb_typeof(c -> 'report' -> 'assets') = 'array' THEN c -> 'report' -> 'assets' ELSE '[]'::JSONB END) AS x), '[]'::JSONB) AS assets,
        EXTRACT(DOW FROM (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS day_of_week,
        EXTRACT(HOUR FROM (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS hour_of_day
    FROM public.incidents AS i
    JOIN public.report_revisions AS r ON r.incident_id = i.id AND r.id = i.official_revision_id
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
incident_counts AS (
    -- All time, independent of the period.
    SELECT
        COUNT(*)::INTEGER AS total,
        COUNT(*) FILTER (WHERE i.official_revision_id IS NOT NULL)::INTEGER AS with_official,
        COUNT(*) FILTER (WHERE i.official_revision_id IS NULL AND EXISTS (SELECT 1 FROM public.report_revisions r WHERE r.incident_id = i.id))::INTEGER AS awaiting_selection,
        COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM public.report_revisions r WHERE r.incident_id = i.id))::INTEGER AS without_report
    FROM public.incidents AS i
),
video_counts AS (
    SELECT COUNT(*)::INTEGER AS uploaded FROM public.videos
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
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(f.entities) AS e
),
instrument_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(ins ->> 'name') AS label,
        CASE WHEN jsonb_typeof(ins -> 'threat_level') = 'number'
            THEN (ins ->> 'threat_level')::NUMERIC::INTEGER END AS threat_level
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(f.instruments) AS ins
    WHERE public.normalized_name(ins ->> 'name') IS NOT NULL
),
asset_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(a ->> 'name') AS label
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(f.assets) AS a
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
    'incidents', (SELECT jsonb_build_object('total', total, 'withOfficial', with_official, 'awaitingSelection', awaiting_selection, 'withoutReport', without_report) FROM incident_counts),
    'videos', (SELECT jsonb_build_object('uploaded', uploaded) FROM video_counts),
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

-- 3. Security ------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION
    public.list_incident_report_summaries(
        INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
        TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT),
    public.get_incident_dashboard(
        TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.list_incident_report_summaries(
        INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
        TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT),
    public.get_incident_dashboard(
        TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT)
TO service_role;

-- PostgREST caches function signatures; reload so the new ones are callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

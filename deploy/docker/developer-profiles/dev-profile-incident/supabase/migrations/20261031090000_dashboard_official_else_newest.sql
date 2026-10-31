-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- The dashboard counts every video that has a report, and says which are official.
--
-- get_incident_dashboard counted official revisions only, so with no official revision it showed
-- nothing. It now counts each video once through searchable_revision_id: the official revision,
-- else the newest, the rule the Library and search already use. Nothing is marked official:
-- videos.official_revision_id is only read, to report the split. The new fields are official and
-- notOfficial (at the top level, per trend day, per type, per top asset and per heatmap cell) and
-- severityByScope. Every existing field keeps its name. model_coverage is unchanged.
--
-- It gains p_scope ('all', 'official' or 'not_official', as in the Library), which narrows the
-- incident statistics and the previous-period comparison to one report status. The video counts
-- and model coverage are independent of it. That is a new argument, so the old signature is dropped.
--
-- Its trend days now use p_timezone, as the heatmap and the weekday and hour filters do.
--
-- list_incident_report_summaries gains p_scope 'not_official', so each half of the split opens a
-- Library list of the same size. Both functions now treat the 'Unclassified' label the dashboard
-- shows for a NULL incident_type as a NULL type, so that row's link opens its reports.
--
-- list_incident_report_summaries keeps its signature and grants. Safe to run twice.

BEGIN;

-- 1. list_incident_report_summaries -----------------------------------------------------------
-- One card per incident, as before; see 20261023000200_searchable_latest_revision.sql.
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
        'outcome', outcome, 'isOfficial', is_official, 'officialSince', official_since,
        'versionCount', (SELECT count(*) FROM public.report_revisions AS x WHERE x.video_id = ordered.video_id),
        'evidenceCount', (SELECT count(*) FROM jsonb_array_elements(ordered.evidence) AS ev WHERE public.evidence_image(ev) IS NOT NULL),
        'thumbnail', (SELECT public.evidence_image(ev) FROM jsonb_array_elements(ordered.evidence) WITH ORDINALITY AS t(ev, n)
            WHERE public.evidence_image(ev) IS NOT NULL ORDER BY n LIMIT 1),
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

-- 2. get_incident_dashboard -------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT);

-- Incident statistics from each video's official revision, else its newest; videos are counted all
-- time; model coverage counts analysis attempts by outcome (failed attempts from model_runs,
-- successful ones by their AI revision). 'revisions' splits the counted reports by kind.
CREATE OR REPLACE FUNCTION public.get_incident_dashboard(
    p_period_start TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_period_end TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_type TEXT DEFAULT NULL::TEXT,
    p_severity TEXT DEFAULT NULL::TEXT,
    p_day_of_week INTEGER DEFAULT NULL::INTEGER,
    p_hour INTEGER DEFAULT NULL::INTEGER,
    p_timezone TEXT DEFAULT 'UTC'::TEXT,
    p_scope TEXT DEFAULT 'all'::TEXT
) RETURNS JSONB
LANGUAGE sql STABLE SET search_path = ''
AS $function$
WITH target_tz AS (
    SELECT COALESCE(NULLIF(p_timezone, ''), 'UTC') AS tz
),
counted_all AS (
    -- One incident per video: its official revision, else its newest (the Library's rule, through
    -- searchable_revision_id). Its time is when that revision was made.
    SELECT
        r.video_id AS incident_id, r.id AS revision_id, r.kind, r.created_at AS generated_datetime,
        v.official_revision_id IS NOT NULL AS is_official,
        r.incident_type, r.severity_level AS severity,
        CASE WHEN jsonb_typeof(r.payload #> '{incident,confidence_score}') = 'number'
            THEN (r.payload #>> '{incident,confidence_score}')::DOUBLE PRECISION END AS confidence,
        r.payload,
        EXTRACT(DOW FROM (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS day_of_week,
        EXTRACT(HOUR FROM (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS hour_of_day,
        (r.created_at AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz)::DATE AS local_day
    FROM public.videos AS v
    JOIN public.report_revisions AS r ON r.video_id = v.id AND r.id = public.searchable_revision_id(v.id)
    CROSS JOIN target_tz
),
dimension_filtered AS (
    SELECT * FROM counted_all
    WHERE (p_type IS NULL OR incident_type = public.canonical_incident_type(p_type)
          OR (public.canonical_incident_type(p_type) = 'unclassified' AND incident_type IS NULL))
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'low' THEN severity <= 2 WHEN 'medium' THEN severity = 3 WHEN 'high' THEN severity >= 4 ELSE FALSE END)
      AND (p_day_of_week IS NULL OR day_of_week = p_day_of_week)
      AND (p_hour IS NULL OR hour_of_day = p_hour)
      AND (COALESCE(p_scope, 'all') <> 'official' OR is_official)
      AND (COALESCE(p_scope, 'all') <> 'not_official' OR NOT is_official)
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
    -- All time, independent of the period and the filters.
    FROM public.videos AS v
),
date_bounds AS (
    SELECT
        COALESCE((p_period_start AT TIME ZONE 'utc' AT TIME ZONE (SELECT tz FROM target_tz))::DATE, MIN(local_day), CURRENT_DATE) AS first_day,
        COALESCE(((p_period_end - INTERVAL '1 microsecond') AT TIME ZONE 'utc' AT TIME ZONE (SELECT tz FROM target_tz))::DATE, MAX(local_day), CURRENT_DATE) AS last_day
    FROM filtered
),
daily AS (
    SELECT day::DATE AS day, COUNT(f.incident_id)::INTEGER AS count,
        COUNT(f.incident_id) FILTER (WHERE f.is_official)::INTEGER AS official
    FROM date_bounds
    CROSS JOIN LATERAL generate_series(first_day, last_day, INTERVAL '1 day') AS day
    LEFT JOIN filtered AS f ON f.local_day = day::DATE
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
    SELECT DISTINCT f.incident_id, f.incident_type, f.is_official, public.normalized_name(a ->> 'name') AS label
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'assets', '[]'::JSONB)) AS a
    WHERE public.normalized_name(a ->> 'name') IS NOT NULL
),
type_counts AS (
    SELECT incident_type, COUNT(*)::INTEGER AS count, COUNT(*) FILTER (WHERE is_official)::INTEGER AS official
    FROM filtered GROUP BY incident_type
),
type_details AS (
    SELECT jsonb_agg(jsonb_build_object(
        'type', COALESCE(tc.incident_type, 'Unclassified'),
        'count', tc.count,
        'official', tc.official,
        'notOfficial', tc.count - tc.official,
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
    SELECT 'entity' AS kind, label, COUNT(DISTINCT incident_id)::INTEGER AS count, NULL::INTEGER AS official FROM entity_rows GROUP BY label
    UNION ALL SELECT 'instrument', label, COUNT(DISTINCT incident_id)::INTEGER, NULL FROM instrument_rows GROUP BY label
    UNION ALL SELECT 'asset', label, COUNT(DISTINCT incident_id)::INTEGER,
        COUNT(DISTINCT incident_id) FILTER (WHERE is_official)::INTEGER FROM asset_rows GROUP BY label
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
    SELECT day_of_week, hour_of_day, COUNT(*)::INTEGER AS count, COUNT(*) FILTER (WHERE is_official)::INTEGER AS official
    FROM filtered GROUP BY day_of_week, hour_of_day
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
    'official', (SELECT COUNT(*) FILTER (WHERE is_official) FROM filtered),
    'notOfficial', (SELECT COUNT(*) FILTER (WHERE NOT is_official) FROM filtered),
    'videos', (SELECT jsonb_build_object('uploaded', uploaded, 'withOfficial', with_official, 'awaitingSelection', awaiting_selection, 'withoutReport', without_report) FROM video_counts),
    'previous', CASE WHEN p_period_start IS NULL OR p_period_end IS NULL THEN NULL ELSE (SELECT to_jsonb(previous) FROM previous) END,
    'averageConfidence', (SELECT AVG(confidence) FROM filtered WHERE confidence IS NOT NULL),
    'confidenceNotProvided', (SELECT COUNT(*) FROM filtered WHERE confidence IS NULL),
    'severity', (SELECT jsonb_build_object('low', COUNT(*) FILTER (WHERE severity <= 2), 'medium', COUNT(*) FILTER (WHERE severity = 3), 'high', COUNT(*) FILTER (WHERE severity >= 4)) FROM filtered),
    'severityByScope', (SELECT jsonb_build_object(
        'official', jsonb_build_object('low', COUNT(*) FILTER (WHERE is_official AND severity <= 2), 'medium', COUNT(*) FILTER (WHERE is_official AND severity = 3), 'high', COUNT(*) FILTER (WHERE is_official AND severity >= 4)),
        'notOfficial', jsonb_build_object('low', COUNT(*) FILTER (WHERE NOT is_official AND severity <= 2), 'medium', COUNT(*) FILTER (WHERE NOT is_official AND severity = 3), 'high', COUNT(*) FILTER (WHERE NOT is_official AND severity >= 4))) FROM filtered),
    'revisions', (SELECT jsonb_build_object('ai', COUNT(*) FILTER (WHERE kind = 'ai'), 'human', COUNT(*) FILTER (WHERE kind = 'human')) FROM filtered),
    'types', COALESCE((SELECT values FROM type_details), '[]'::JSONB),
    'trend', COALESCE((SELECT jsonb_agg(jsonb_build_object('date', day, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY day) FROM daily), '[]'::JSONB),
    'heatmap', COALESCE((SELECT jsonb_agg(jsonb_build_object('day', day_of_week, 'hour', hour_of_day, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY day_of_week, hour_of_day) FROM heatmap), '[]'::JSONB),
    'confidence', COALESCE((SELECT jsonb_agg(jsonb_build_object('bucket', bucket, 'count', count) ORDER BY bucket) FROM confidence_buckets), '[]'::JSONB),
    'entityTypes', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM ranked WHERE kind = 'entity'), '[]'::JSONB),
    'topInstruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (SELECT * FROM ranked WHERE kind = 'instrument' ORDER BY count DESC, label LIMIT 8) top), '[]'::JSONB),
    'topAssets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY count DESC, label) FROM (SELECT * FROM ranked WHERE kind = 'asset' ORDER BY count DESC, label LIMIT 8) top), '[]'::JSONB),
    'threatLevels', COALESCE((SELECT jsonb_agg(jsonb_build_object('level', level, 'count', count) ORDER BY level) FROM threat_levels), '[]'::JSONB),
    'modelCoverage', (SELECT values FROM model_coverage)
);
$function$;

-- 3. Security ------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT, TEXT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT, TEXT)
TO service_role;

-- PostgREST caches function signatures; reload so the new results are served at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

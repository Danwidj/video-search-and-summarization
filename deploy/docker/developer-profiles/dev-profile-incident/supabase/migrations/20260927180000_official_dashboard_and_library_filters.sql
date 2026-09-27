-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Official-report dashboard semantics and exact library filters (plan phases 6-7).
--
-- 1. Value folding (display/query only; stored rows are never rewritten):
--    legacy incident types fighting -> assault, animal -> animal attack;
--    legacy entity type person -> human; instrument/asset names compared by a
--    normalised form (lower case, trimmed, single spaces).
-- 2. list_incident_report_summaries gains
--      p_scope          'all' (default, every successful report) | 'official'
--                       (only each video's explicitly selected official report)
--      p_entity_types   exact entity-type filter (canonical)
--      p_evidence_match 'contains' (default substring) | 'exact' (normalised
--                       instrument / asset name equality)
--    folds legacy types for filtering and display, and returns each report's
--    analysis outcome (from model_runs.notes) and whether it is official.
-- 3. get_incident_dashboard counts incidents from official reports only
--    (decision D6): one incident per video with an official report; videos
--    with reports but no official one are counted as awaiting selection and
--    never attributed to a category; uploaded videos are counted from videos
--    (all time, matching the video lists they link to).
--    Evidence statistics count distinct official incidents, so a dashboard
--    number equals the reports-page total for the same filters with
--    scope=official. Model coverage counts analysis attempts by outcome.
--
-- Signature changes need DROP + CREATE; no table or data change.

CREATE FUNCTION public.canonical_incident_type(p_type TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT CASE lower(btrim(p_type))
        WHEN 'fighting' THEN 'assault'
        WHEN 'animal' THEN 'animal attack'
        ELSE NULLIF(lower(btrim(p_type)), '')
    END;
$$;

CREATE FUNCTION public.canonical_entity_type(p_type TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT CASE lower(btrim(COALESCE(p_type, '')))
        WHEN '' THEN 'unknown'
        WHEN 'person' THEN 'human'
        ELSE lower(btrim(p_type))
    END;
$$;

CREATE FUNCTION public.normalized_name(p_name TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT NULLIF(regexp_replace(lower(btrim(COALESCE(p_name, ''))), '\s+', ' ', 'g'), '');
$$;

-- The analysis outcome recorded in model_runs.notes, as the console reads it
-- (lib/reports/run-notes.ts recordedOutcome).
CREATE FUNCTION public.run_outcome(p_notes TEXT) RETURNS TEXT
LANGUAGE sql STABLE SET search_path = ''
AS $$
    SELECT CASE
        WHEN parsed #>> '{incidentConsoleV2,contractVersion}' IS NULL THEN 'legacy'
        WHEN parsed #>> '{incidentConsoleV2,status}' IN ('valid_after_structural_repair', 'contract_failed', 'request_failed')
            THEN parsed #>> '{incidentConsoleV2,status}'
        ELSE 'valid_first_pass'
    END
    FROM (SELECT public.try_parse_jsonb(p_notes) AS parsed) AS notes;
$$;

REVOKE ALL ON FUNCTION public.canonical_incident_type(TEXT), public.canonical_entity_type(TEXT), public.normalized_name(TEXT), public.run_outcome(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.canonical_incident_type(TEXT), public.canonical_entity_type(TEXT), public.normalized_name(TEXT), public.run_outcome(TEXT) TO service_role;

DROP FUNCTION public.list_incident_report_summaries(
    INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT,
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
    TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE,
    TEXT[], TEXT[], TEXT[], INTEGER, TEXT
);

CREATE FUNCTION public.list_incident_report_summaries(
    p_page INTEGER DEFAULT 1,
    p_page_size INTEGER DEFAULT 6,
    p_search TEXT DEFAULT NULL,
    p_type TEXT DEFAULT NULL,
    p_severity TEXT DEFAULT NULL,
    p_status TEXT DEFAULT NULL,
    p_generated_after TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_generated_before TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_time_from TIME WITHOUT TIME ZONE DEFAULT NULL,
    p_time_to TIME WITHOUT TIME ZONE DEFAULT NULL,
    p_entities TEXT[] DEFAULT NULL,
    p_instruments TEXT[] DEFAULT NULL,
    p_assets TEXT[] DEFAULT NULL,
    p_day_of_week INTEGER DEFAULT NULL,
    p_sort TEXT DEFAULT 'newest',
    p_scope TEXT DEFAULT 'all',
    p_entity_types TEXT[] DEFAULT NULL,
    p_evidence_match TEXT DEFAULT 'contains'
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
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
        COALESCE(p_evidence_match, 'contains') = 'exact' AS exact_match
),
filtered AS (
    SELECT
        r.id AS report_id, r.incident_id AS video_id, r.model_run_id,
        COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}') AS stored_title,
        public.canonical_incident_type(i.type) AS incident_type, i.description, i.severity_level, i.confidence_score,
        r.generated_datetime, v.uploaded_datetime,
        regexp_replace(COALESCE(v.filepath, r.incident_id), '^.*/', '') AS filename,
        mr.model_name, public.run_outcome(mr.notes) AS outcome,
        v.selected_model_run_id IS NOT DISTINCT FROM r.model_run_id AS is_official,
        COALESCE(rs.status, 'unreviewed') AS review_status,
        rs.verified_by, rs.verified_at, rs.edited_by, rs.edited_at,
        v.filepath AS r2_key, v.source AS sensor_id
    FROM public.reports AS r
    JOIN public.incidents AS i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    JOIN public.model_runs AS mr ON mr.id = r.model_run_id
    JOIN public.videos AS v ON v.id = r.incident_id
    LEFT JOIN public.review_status AS rs ON rs.incident_id = r.incident_id AND rs.model_run_id = r.model_run_id
    CROSS JOIN parameters AS params
    WHERE (COALESCE(p_scope, 'all') <> 'official' OR v.selected_model_run_id = r.model_run_id)
      AND (p_type IS NULL OR public.canonical_incident_type(i.type) = params.canonical_type)
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'high' THEN i.severity_level >= 4
          WHEN 'medium' THEN i.severity_level = 3
          WHEN 'low' THEN i.severity_level <= 2
          ELSE i.severity_level = p_severity::INTEGER END)
      AND (p_status IS NULL OR COALESCE(rs.status, 'unreviewed') = p_status)
      AND (p_generated_after IS NULL OR r.generated_datetime >= p_generated_after)
      AND (p_generated_before IS NULL OR r.generated_datetime <= p_generated_before)
      AND (p_time_from IS NULL OR r.generated_datetime::TIME >= p_time_from)
      AND (p_time_to IS NULL OR r.generated_datetime::TIME <= p_time_to)
      AND (p_day_of_week IS NULL OR EXTRACT(DOW FROM r.generated_datetime)::INTEGER = p_day_of_week)
      AND (p_entity_types IS NULL OR EXISTS (
          SELECT 1 FROM public.entities e
          WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id
            AND public.canonical_entity_type(e.type) = ANY (params.entity_types)
      ))
      AND (p_entities IS NULL OR EXISTS (
          SELECT 1 FROM public.entities e
          WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id
            AND EXISTS (SELECT 1 FROM unnest(params.escaped_entities) term WHERE concat_ws(' ', e.type, e.description) ILIKE '%' || term || '%' ESCAPE E'\\')
      ))
      AND (p_instruments IS NULL OR EXISTS (
          SELECT 1 FROM public.instruments ins
          WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id
            AND CASE WHEN params.exact_match
                THEN public.normalized_name(ins.name) = ANY (params.exact_instruments)
                ELSE EXISTS (SELECT 1 FROM unnest(params.escaped_instruments) term WHERE concat_ws(' ', ins.name, ins.description) ILIKE '%' || term || '%' ESCAPE E'\\')
            END
      ))
      AND (p_assets IS NULL OR EXISTS (
          SELECT 1 FROM public.assets a
          WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id
            AND CASE WHEN params.exact_match
                THEN public.normalized_name(a.name) = ANY (params.exact_assets)
                ELSE EXISTS (SELECT 1 FROM unnest(params.escaped_assets) term WHERE concat_ws(' ', a.name, a.description) ILIKE '%' || term || '%' ESCAPE E'\\')
            END
      ))
      AND (params.escaped_search IS NULL
          OR concat_ws(' ', COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}'), public.canonical_incident_type(i.type), i.description, regexp_replace(COALESCE(v.filepath, ''), '^.*/', '')) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          OR EXISTS (SELECT 1 FROM public.entities e WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id AND concat_ws(' ', e.type, e.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM public.instruments ins WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id AND concat_ws(' ', ins.name, ins.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM public.assets a WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id AND concat_ws(' ', a.name, a.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'))
),
ordered AS (
    SELECT * FROM filtered
    ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, report_id ASC
    LIMIT LEAST(GREATEST(p_page_size, 1), 1000)
    OFFSET (GREATEST(p_page, 1) - 1) * LEAST(GREATEST(p_page_size, 1), 1000)
),
incident_types AS (
    SELECT COALESCE(jsonb_agg(type ORDER BY type), '[]'::JSONB) AS values
    FROM (SELECT DISTINCT public.canonical_incident_type(i.type) AS type FROM public.incidents i WHERE public.canonical_incident_type(i.type) IS NOT NULL) types
)
SELECT jsonb_build_object(
    'reports', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'reportId', report_id, 'videoId', video_id, 'modelRunId', model_run_id,
        'title', COALESCE(NULLIF(stored_title, ''), COALESCE(NULLIF(initcap(incident_type), ''), 'Incident') || ' report'),
        'filename', filename, 'incident_type', COALESCE(incident_type, 'Unclassified'),
        'description', COALESCE(description, 'No summary was recorded.'),
        'severity', COALESCE(severity_level, 1), 'confidence', confidence_score,
        'generatedAt', generated_datetime, 'uploadedAt', uploaded_datetime,
        'model', COALESCE(model_name, 'Unknown model'), 'status', review_status,
        'outcome', outcome, 'isOfficial', is_official,
        'verifiedBy', verified_by, 'verifiedAt', verified_at, 'editedBy', edited_by, 'editedAt', edited_at,
        'r2Key', r2_key, 'sensorId', sensor_id
    ) ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, report_id ASC) FROM ordered), '[]'::JSONB),
    'totalItems', (SELECT count(*) FROM filtered),
    'incidentTypes', (SELECT values FROM incident_types)
);
$$;

REVOKE ALL ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT) TO service_role;

DROP FUNCTION public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER
);

CREATE FUNCTION public.get_incident_dashboard(
    p_period_start TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_period_end TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_type TEXT DEFAULT NULL,
    p_severity TEXT DEFAULT NULL,
    p_day_of_week INTEGER DEFAULT NULL,
    p_hour INTEGER DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
WITH official_all AS (
    -- One incident per video: its explicitly selected official report.
    SELECT
        r.incident_id, r.model_run_id, r.generated_datetime,
        public.canonical_incident_type(i.type) AS incident_type,
        i.severity_level AS severity,
        i.confidence_score AS confidence,
        COALESCE(rs.status, 'unreviewed') AS review_status,
        EXTRACT(DOW FROM r.generated_datetime)::INTEGER AS day_of_week,
        EXTRACT(HOUR FROM r.generated_datetime)::INTEGER AS hour_of_day
    FROM public.videos AS v
    JOIN public.reports AS r ON r.incident_id = v.id AND r.model_run_id = v.selected_model_run_id
    JOIN public.incidents AS i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    LEFT JOIN public.review_status AS rs ON rs.incident_id = r.incident_id AND rs.model_run_id = r.model_run_id
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
        COUNT(*) FILTER (WHERE v.selected_model_run_id IS NOT NULL)::INTEGER AS with_official,
        COUNT(*) FILTER (WHERE v.selected_model_run_id IS NULL AND EXISTS (SELECT 1 FROM public.reports r WHERE r.incident_id = v.id))::INTEGER AS awaiting_selection,
        COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM public.incidents i WHERE i.incident_id = v.id))::INTEGER AS without_report
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
    SELECT DISTINCT f.incident_id, f.incident_type, public.canonical_entity_type(e.type) AS label
    FROM filtered f JOIN public.entities e ON e.incident_id = f.incident_id AND e.model_run_id = f.model_run_id
),
instrument_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(ins.name) AS label, ins.threat_level
    FROM filtered f JOIN public.instruments ins ON ins.incident_id = f.incident_id AND ins.model_run_id = f.model_run_id
    WHERE public.normalized_name(ins.name) IS NOT NULL
),
asset_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(a.name) AS label
    FROM filtered f JOIN public.assets a ON a.incident_id = f.incident_id AND a.model_run_id = f.model_run_id
    WHERE public.normalized_name(a.name) IS NOT NULL
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
    -- Every recorded analysis attempt in the period, by outcome; legacy runs
    -- are counted by their report rows.
    SELECT mr.model_name, public.run_outcome(mr.notes) AS outcome
    FROM public.model_runs mr
    WHERE public.run_outcome(mr.notes) IN ('contract_failed', 'request_failed')
      AND (p_period_start IS NULL OR mr.run_datetime >= p_period_start)
      AND (p_period_end IS NULL OR mr.run_datetime < p_period_end)
    UNION ALL
    SELECT mr.model_name, public.run_outcome(mr.notes)
    FROM public.reports r JOIN public.model_runs mr ON mr.id = r.model_run_id
    WHERE (p_period_start IS NULL OR r.generated_datetime >= p_period_start)
      AND (p_period_end IS NULL OR r.generated_datetime < p_period_end)
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
        COUNT(*) FILTER (WHERE review_status = 'verified')::INTEGER AS verified,
        COUNT(*) FILTER (WHERE review_status = 'unreviewed')::INTEGER AS unreviewed,
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
    'reviews', (SELECT jsonb_build_object('unreviewed', COUNT(*) FILTER (WHERE review_status = 'unreviewed'), 'under_review', COUNT(*) FILTER (WHERE review_status = 'under review'), 'verified', COUNT(*) FILTER (WHERE review_status = 'verified')) FROM filtered),
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
$$;

REVOKE ALL ON FUNCTION public.get_incident_dashboard(TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_incident_dashboard(TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER) TO service_role;

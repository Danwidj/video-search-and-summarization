-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Report-library summaries for incident-contract-v2 runs.
--
-- 1. Title: contract-v2 runs keep the complete, immutable model report in
--    model_runs.notes at incidentConsoleV2.report, where the title is nested
--    under report.incident.title. The previous lookups only knew the legacy
--    flat report.title, so v2 runs fell back to "<Type> report". The v2 path is
--    added after the legacy reviewer-edit path and before the legacy paths,
--    both for the displayed title and for the free-text search.
-- 2. Confidence: incident-contract-v2 allows a null confidence_score (the model
--    reports none). The summary now returns null instead of coercing it to 0,
--    and confidence sorts place nulls last in both directions.
--
-- Same signature and return type as 20260927140000, so CREATE OR REPLACE keeps
-- the existing grants; they are restated for clarity. No table or data change.

CREATE OR REPLACE FUNCTION public.list_incident_report_summaries(
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
    p_sort TEXT DEFAULT 'newest'
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
WITH parameters AS (
    SELECT
        replace(replace(replace(p_search, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') AS escaped_search,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_entities) AS value) AS escaped_entities,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_instruments) AS value) AS escaped_instruments,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_assets) AS value) AS escaped_assets
),
filtered AS (
    SELECT
        r.id AS report_id, r.incident_id AS video_id, r.model_run_id,
        COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}') AS stored_title,
        i.type AS incident_type, i.description, i.severity_level, i.confidence_score,
        r.generated_datetime, v.uploaded_datetime,
        regexp_replace(COALESCE(v.filepath, r.incident_id), '^.*/', '') AS filename,
        mr.model_name, COALESCE(rs.status, 'unreviewed') AS review_status,
        rs.verified_by, rs.verified_at, rs.edited_by, rs.edited_at,
        v.filepath AS r2_key, v.source AS sensor_id
    FROM public.reports AS r
    JOIN public.incidents AS i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    JOIN public.model_runs AS mr ON mr.id = r.model_run_id
    JOIN public.videos AS v ON v.id = r.incident_id
    LEFT JOIN public.review_status AS rs ON rs.incident_id = r.incident_id AND rs.model_run_id = r.model_run_id
    CROSS JOIN parameters AS params
    WHERE (p_type IS NULL OR i.type = p_type)
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
      AND (p_entities IS NULL OR EXISTS (
          SELECT 1 FROM public.entities e
          WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id
            AND EXISTS (SELECT 1 FROM unnest(params.escaped_entities) term WHERE concat_ws(' ', e.type, e.description) ILIKE '%' || term || '%' ESCAPE E'\\')
      ))
      AND (p_instruments IS NULL OR EXISTS (
          SELECT 1 FROM public.instruments ins
          WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id
            AND EXISTS (SELECT 1 FROM unnest(params.escaped_instruments) term WHERE concat_ws(' ', ins.name, ins.description) ILIKE '%' || term || '%' ESCAPE E'\\')
      ))
      AND (p_assets IS NULL OR EXISTS (
          SELECT 1 FROM public.assets a
          WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id
            AND EXISTS (SELECT 1 FROM unnest(params.escaped_assets) term WHERE concat_ws(' ', a.name, a.description) ILIKE '%' || term || '%' ESCAPE E'\\')
      ))
      AND (params.escaped_search IS NULL
          OR concat_ws(' ', COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}'), i.type, i.description, regexp_replace(COALESCE(v.filepath, ''), '^.*/', '')) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
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
    FROM (SELECT DISTINCT i.type FROM public.incidents i WHERE i.type IS NOT NULL AND i.type <> '') types
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

REVOKE ALL ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT) TO service_role;

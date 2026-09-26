-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Return one filtered, sorted page of lightweight report-library summaries.
-- Full report notes, evidence rows, and R2 playback URLs remain deferred to
-- the individual report route.

CREATE OR REPLACE FUNCTION public.try_parse_jsonb(p_value TEXT)
RETURNS JSONB
LANGUAGE plpgsql
IMMUTABLE
STRICT
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    RETURN p_value::JSONB;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.try_parse_jsonb(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.try_parse_jsonb(TEXT) TO service_role;

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
    p_sort TEXT DEFAULT 'newest'
) RETURNS JSONB
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $$
WITH parameters AS (
    SELECT replace(
        replace(
            replace(p_search, E'\\', E'\\\\'),
            '%',
            E'\\%'
        ),
        '_',
        E'\\_'
    ) AS escaped_search
),
filtered AS (
    SELECT
        r.id AS report_id,
        r.incident_id AS video_id,
        r.model_run_id,
        COALESCE(
            public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}',
            public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}'
        ) AS stored_title,
        i.type AS incident_type,
        i.description,
        i.severity_level,
        i.confidence_score,
        r.generated_datetime,
        v.uploaded_datetime,
        regexp_replace(COALESCE(v.filepath, r.incident_id), '^.*/', '') AS filename,
        mr.model_name,
        COALESCE(rs.status, 'unreviewed') AS review_status,
        rs.verified_by,
        rs.verified_at,
        rs.edited_by,
        rs.edited_at,
        v.filepath AS r2_key,
        v.source AS sensor_id
    FROM public.reports AS r
    JOIN public.incidents AS i
      ON i.incident_id = r.incident_id
     AND i.model_run_id = r.model_run_id
    JOIN public.model_runs AS mr ON mr.id = r.model_run_id
    JOIN public.videos AS v ON v.id = r.incident_id
    LEFT JOIN public.review_status AS rs
      ON rs.incident_id = r.incident_id
     AND rs.model_run_id = r.model_run_id
    CROSS JOIN parameters AS params
    WHERE (p_type IS NULL OR i.type = p_type)
      AND (
          p_severity IS NULL
          OR CASE
              WHEN p_severity = 'high' THEN i.severity_level >= 4
              ELSE i.severity_level = p_severity::INTEGER
          END
      )
      AND (p_status IS NULL OR COALESCE(rs.status, 'unreviewed') = p_status)
      AND (p_generated_after IS NULL OR r.generated_datetime >= p_generated_after)
      AND (p_generated_before IS NULL OR r.generated_datetime <= p_generated_before)
      AND (p_time_from IS NULL OR r.generated_datetime::TIME >= p_time_from)
      AND (p_time_to IS NULL OR r.generated_datetime::TIME <= p_time_to)
      AND (
          params.escaped_search IS NULL
          OR concat_ws(
              ' ',
              COALESCE(
                  public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}',
                  public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}'
              ),
              i.type,
              i.description,
              regexp_replace(COALESCE(v.filepath, ''), '^.*/', '')
          ) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          OR EXISTS (
              SELECT 1 FROM public.entities AS e
              WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id
                AND concat_ws(' ', e.type, e.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          )
          OR EXISTS (
              SELECT 1 FROM public.instruments AS ins
              WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id
                AND concat_ws(' ', ins.name, ins.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          )
          OR EXISTS (
              SELECT 1 FROM public.assets AS a
              WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id
                AND concat_ws(' ', a.name, a.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          )
      )
),
ordered AS (
    SELECT * FROM filtered
    ORDER BY
        CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC,
        report_id ASC
    LIMIT LEAST(GREATEST(p_page_size, 1), 1000)
    OFFSET (GREATEST(p_page, 1) - 1) * LEAST(GREATEST(p_page_size, 1), 1000)
),
incident_types AS (
    SELECT COALESCE(jsonb_agg(type ORDER BY type), '[]'::JSONB) AS values
    FROM (SELECT DISTINCT i.type FROM public.incidents AS i WHERE i.type IS NOT NULL AND i.type <> '') AS types
)
SELECT jsonb_build_object(
    'reports', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'reportId', report_id,
            'videoId', video_id,
            'modelRunId', model_run_id,
            'title', COALESCE(NULLIF(stored_title, ''), COALESCE(NULLIF(initcap(incident_type), ''), 'Incident') || ' report'),
            'filename', filename,
            'incident_type', COALESCE(incident_type, 'Unclassified'),
            'description', COALESCE(description, 'No summary was recorded.'),
            'severity', COALESCE(severity_level, 1),
            'confidence', COALESCE(confidence_score, 0),
            'generatedAt', generated_datetime,
            'uploadedAt', uploaded_datetime,
            'model', COALESCE(model_name, 'Unknown model'),
            'status', review_status,
            'verifiedBy', verified_by,
            'verifiedAt', verified_at,
            'editedBy', edited_by,
            'editedAt', edited_at,
            'r2Key', r2_key,
            'sensorId', sensor_id
        ) ORDER BY
            CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
            CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
            CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
            CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC,
            CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC,
            CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
            generated_datetime DESC,
            report_id ASC
        ) FROM ordered
    ), '[]'::JSONB),
    'totalItems', (SELECT count(*) FROM filtered),
    'incidentTypes', (SELECT values FROM incident_types)
);
$$;

REVOKE ALL ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT) TO service_role;

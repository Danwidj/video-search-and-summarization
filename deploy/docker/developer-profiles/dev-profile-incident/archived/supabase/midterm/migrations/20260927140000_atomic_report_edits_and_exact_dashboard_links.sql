-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Extend report summaries with weekday filtering while retaining the complete
-- existing evidence-search, sort, pagination, and projection behavior.
DROP FUNCTION public.list_incident_report_summaries(
    INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT,
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
    TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE,
    TEXT[], TEXT[], TEXT[], TEXT
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
        COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}') AS stored_title,
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
          OR concat_ws(' ', COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}'), i.type, i.description, regexp_replace(COALESCE(v.filepath, ''), '^.*/', '')) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          OR EXISTS (SELECT 1 FROM public.entities e WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id AND concat_ws(' ', e.type, e.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM public.instruments ins WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id AND concat_ws(' ', ins.name, ins.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM public.assets a WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id AND concat_ws(' ', a.name, a.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'))
),
ordered AS (
    SELECT * FROM filtered
    ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC,
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
        'severity', COALESCE(severity_level, 1), 'confidence', COALESCE(confidence_score, 0),
        'generatedAt', generated_datetime, 'uploadedAt', uploaded_datetime,
        'model', COALESCE(model_name, 'Unknown model'), 'status', review_status,
        'verifiedBy', verified_by, 'verifiedAt', verified_at, 'editedBy', edited_by, 'editedAt', edited_at,
        'r2Key', r2_key, 'sensorId', sensor_id
    ) ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, report_id ASC) FROM ordered), '[]'::JSONB),
    'totalItems', (SELECT count(*) FROM filtered),
    'incidentTypes', (SELECT values FROM incident_types)
);
$$;

REVOKE ALL ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_incident_report_summaries(INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT) TO service_role;

-- Merge changed fields, update relational/evidence projections, and advance the
-- edit timestamp inside one PostgreSQL transaction. Exceptions roll back all.
CREATE FUNCTION public.apply_incident_report_patch(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_original_report JSONB,
    p_report_patch JSONB
) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    current_notes JSONB;
    console_notes JSONB;
    base_report JSONB;
    effective_report JSONB;
    patch JSONB := COALESCE(p_report_patch, '{}'::JSONB);
    item JSONB;
    item_index INTEGER;
BEGIN
    SELECT public.try_parse_jsonb(mr.notes) INTO current_notes
    FROM public.model_runs AS mr WHERE mr.id = p_model_run_id FOR UPDATE OF mr;
    IF NOT FOUND THEN RAISE EXCEPTION 'Model run not found'; END IF;

    PERFORM 1 FROM public.incidents
    WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Report not found for this video and model run'; END IF;

    console_notes := COALESCE(current_notes->'incidentConsoleV2', '{}'::JSONB);
    base_report := COALESCE(console_notes->'editedReport', console_notes->'report', p_original_report, '{}'::JSONB);
    effective_report := base_report || patch;

    UPDATE public.model_runs
    SET notes = jsonb_set(
        COALESCE(current_notes, '{}'::JSONB),
        '{incidentConsoleV2}',
        console_notes || jsonb_build_object(
            'report', COALESCE(console_notes->'report', p_original_report),
            'editedReport', effective_report
        ),
        TRUE
    )::TEXT
    WHERE id = p_model_run_id;

    UPDATE public.incidents
    SET type = CASE WHEN patch ? 'incident_type' THEN effective_report->>'incident_type' ELSE type END,
        description = CASE WHEN patch ? 'description' THEN effective_report->>'description' ELSE description END,
        start_timestamp = CASE WHEN patch ? 'incident_start' THEN effective_report->>'incident_start' ELSE start_timestamp END,
        end_timestamp = CASE WHEN patch ? 'incident_end' THEN effective_report->>'incident_end' ELSE end_timestamp END,
        duration = CASE WHEN patch ? 'duration_seconds' THEN NULLIF(effective_report->>'duration_seconds', '')::INTEGER ELSE duration END,
        severity_level = CASE WHEN patch ? 'severity' THEN NULLIF(effective_report->>'severity', '')::INTEGER ELSE severity_level END,
        confidence_score = CASE WHEN patch ? 'confidence' THEN NULLIF(effective_report->>'confidence', '')::DOUBLE PRECISION ELSE confidence_score END
    WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;

    IF patch ? 'persons' THEN
        DELETE FROM public.entities WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
        item_index := 0;
        FOR item IN SELECT * FROM jsonb_array_elements(COALESCE(effective_report->'persons', '[]'::JSONB)) LOOP
            item_index := item_index + 1;
            INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description)
            VALUES (p_incident_id, 'e' || lpad(item_index::TEXT, 2, '0'), p_model_run_id, 'person',
                NULLIF(concat_ws(' ', NULLIF(item->>'description', ''), NULLIF(item->>'actions', '')), ''));
        END LOOP;
    END IF;
    IF patch ? 'instruments' THEN
        DELETE FROM public.instruments WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
        item_index := 0;
        FOR item IN SELECT * FROM jsonb_array_elements(COALESCE(effective_report->'instruments', '[]'::JSONB)) LOOP
            item_index := item_index + 1;
            INSERT INTO public.instruments (incident_id, instrument_id, model_run_id, name, description, threat_level)
            VALUES (p_incident_id, 'i' || lpad(item_index::TEXT, 2, '0'), p_model_run_id, item->>'name', item->>'description', NULLIF(item->>'threat_level', '')::INTEGER);
        END LOOP;
    END IF;
    IF patch ? 'assets' THEN
        DELETE FROM public.assets WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
        item_index := 0;
        FOR item IN SELECT * FROM jsonb_array_elements(COALESCE(effective_report->'assets', '[]'::JSONB)) LOOP
            item_index := item_index + 1;
            INSERT INTO public.assets (incident_id, asset_id, model_run_id, name, description)
            VALUES (p_incident_id, 'a' || lpad(item_index::TEXT, 2, '0'), p_model_run_id, item->>'name', item->>'description');
        END LOOP;
    END IF;

    INSERT INTO public.review_status (incident_id, model_run_id, edited_at)
    VALUES (p_incident_id, p_model_run_id, now() AT TIME ZONE 'utc')
    ON CONFLICT (incident_id, model_run_id) DO UPDATE SET edited_at = EXCLUDED.edited_at;

    RETURN effective_report;
END;
$$;

REVOKE ALL ON FUNCTION public.apply_incident_report_patch(TEXT, TEXT, JSONB, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_incident_report_patch(TEXT, TEXT, JSONB, JSONB) TO service_role;

-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Produce dashboard aggregates without transferring full reports or evidence.

CREATE FUNCTION public.get_incident_dashboard(
    p_period_start TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_period_end TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL,
    p_type TEXT DEFAULT NULL,
    p_severity TEXT DEFAULT NULL,
    p_day_of_week INTEGER DEFAULT NULL,
    p_hour INTEGER DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $$
WITH all_reports AS (
    SELECT
        r.incident_id,
        r.model_run_id,
        r.generated_datetime,
        i.type AS incident_type,
        COALESCE(i.severity_level, 1) AS severity,
        COALESCE(i.confidence_score, 0) AS confidence,
        COALESCE(rs.status, 'unreviewed') AS review_status,
        EXTRACT(DOW FROM r.generated_datetime)::INTEGER AS day_of_week,
        EXTRACT(HOUR FROM r.generated_datetime)::INTEGER AS hour_of_day
    FROM public.reports AS r
    JOIN public.incidents AS i
      ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    LEFT JOIN public.review_status AS rs
      ON rs.incident_id = r.incident_id AND rs.model_run_id = r.model_run_id
),
dimension_filtered AS (
    SELECT *
    FROM all_reports
    WHERE (p_type IS NULL OR incident_type = p_type)
      AND (
          p_severity IS NULL
          OR CASE p_severity
              WHEN 'low' THEN severity <= 2
              WHEN 'medium' THEN severity = 3
              WHEN 'high' THEN severity >= 4
              ELSE FALSE
          END
      )
      AND (p_day_of_week IS NULL OR day_of_week = p_day_of_week)
      AND (p_hour IS NULL OR hour_of_day = p_hour)
),
filtered AS (
    SELECT *
    FROM dimension_filtered
    WHERE (p_period_start IS NULL OR generated_datetime >= p_period_start)
      AND (p_period_end IS NULL OR generated_datetime < p_period_end)
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
    GROUP BY day
    ORDER BY day
),
severity_counts AS (
    SELECT
        COUNT(*) FILTER (WHERE severity <= 2)::INTEGER AS low,
        COUNT(*) FILTER (WHERE severity = 3)::INTEGER AS medium,
        COUNT(*) FILTER (WHERE severity >= 4)::INTEGER AS high
    FROM filtered
),
review_counts AS (
    SELECT
        COUNT(*) FILTER (WHERE review_status = 'unreviewed')::INTEGER AS unreviewed,
        COUNT(*) FILTER (WHERE review_status = 'under review')::INTEGER AS under_review,
        COUNT(*) FILTER (WHERE review_status = 'verified')::INTEGER AS verified
    FROM filtered
),
type_counts AS (
    SELECT incident_type, COUNT(*)::INTEGER AS count
    FROM filtered
    GROUP BY incident_type
),
type_details AS (
    SELECT jsonb_agg(jsonb_build_object(
        'type', COALESCE(tc.incident_type, 'Unclassified'),
        'count', tc.count,
        'severity', jsonb_build_object(
            'low', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity <= 2),
            'medium', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity = 3),
            'high', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity >= 4)
        ),
        'entities', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label)
            FROM (
                SELECT COALESCE(NULLIF(TRIM(e.description), ''), NULLIF(TRIM(e.type), ''), 'Unknown') AS label, COUNT(*)::INTEGER AS count
                FROM filtered f
                JOIN public.entities e ON e.incident_id = f.incident_id AND e.model_run_id = f.model_run_id
                WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type
                GROUP BY label ORDER BY count DESC, label LIMIT 3
            ) ranked
        ), '[]'::JSONB),
        'instruments', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label)
            FROM (
                SELECT COALESCE(NULLIF(TRIM(ins.name), ''), 'Unknown') AS label, COUNT(*)::INTEGER AS count
                FROM filtered f
                JOIN public.instruments ins ON ins.incident_id = f.incident_id AND ins.model_run_id = f.model_run_id
                WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type
                GROUP BY label ORDER BY count DESC, label LIMIT 3
            ) ranked
        ), '[]'::JSONB),
        'assets', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label)
            FROM (
                SELECT COALESCE(NULLIF(TRIM(a.name), ''), 'Unknown') AS label, COUNT(*)::INTEGER AS count
                FROM filtered f
                JOIN public.assets a ON a.incident_id = f.incident_id AND a.model_run_id = f.model_run_id
                WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type
                GROUP BY label ORDER BY count DESC, label LIMIT 3
            ) ranked
        ), '[]'::JSONB)
    ) ORDER BY tc.count DESC, tc.incident_type)
    AS values
    FROM type_counts tc
),
top_entities AS (
    SELECT COALESCE(jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label), '[]'::JSONB) AS values
    FROM (
        SELECT COALESCE(NULLIF(TRIM(e.description), ''), NULLIF(TRIM(e.type), ''), 'Unknown') AS label, COUNT(*)::INTEGER AS count
        FROM filtered f
        JOIN public.entities e ON e.incident_id = f.incident_id AND e.model_run_id = f.model_run_id
        GROUP BY label ORDER BY count DESC, label LIMIT 8
    ) ranked
),
top_assets AS (
    SELECT COALESCE(jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label), '[]'::JSONB) AS values
    FROM (
        SELECT COALESCE(NULLIF(TRIM(a.name), ''), 'Unknown') AS label, COUNT(*)::INTEGER AS count
        FROM filtered f
        JOIN public.assets a ON a.incident_id = f.incident_id AND a.model_run_id = f.model_run_id
        GROUP BY label ORDER BY count DESC, label LIMIT 8
    ) ranked
),
confidence_buckets AS (
    SELECT bucket, COUNT(*)::INTEGER AS count
    FROM (
        SELECT LEAST(9, GREATEST(0, FLOOR(confidence * 10)::INTEGER)) AS bucket FROM filtered
    ) bucket_values
    GROUP BY bucket
),
heatmap AS (
    SELECT day_of_week, hour_of_day, COUNT(*)::INTEGER AS count
    FROM filtered
    GROUP BY day_of_week, hour_of_day
),
previous AS (
    SELECT
        COUNT(*)::INTEGER AS total,
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
    'previous', CASE WHEN p_period_start IS NULL OR p_period_end IS NULL THEN NULL ELSE (SELECT to_jsonb(previous) FROM previous) END,
    'averageConfidence', COALESCE((SELECT AVG(confidence) FROM filtered), 0),
    'severity', (SELECT to_jsonb(severity_counts) FROM severity_counts),
    'reviews', (SELECT to_jsonb(review_counts) FROM review_counts),
    'types', COALESCE((SELECT values FROM type_details), '[]'::JSONB),
    'trend', COALESCE((SELECT jsonb_agg(jsonb_build_object('date', day, 'count', count) ORDER BY day) FROM daily), '[]'::JSONB),
    'heatmap', COALESCE((SELECT jsonb_agg(jsonb_build_object('day', day_of_week, 'hour', hour_of_day, 'count', count) ORDER BY day_of_week, hour_of_day) FROM heatmap), '[]'::JSONB),
    'confidence', COALESCE((SELECT jsonb_agg(jsonb_build_object('bucket', bucket, 'count', count) ORDER BY bucket) FROM confidence_buckets), '[]'::JSONB),
    'topEntities', (SELECT values FROM top_entities),
    'topAssets', (SELECT values FROM top_assets)
);
$$;

REVOKE ALL ON FUNCTION public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER
) TO service_role;

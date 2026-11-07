-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- The dashboard's "instrument threat by holder type" chart view needs the instruments of the counted reports split by
-- the type of the entity holding them and by threat band. The RPC returns the threat levels, but not the holder.
--
-- One addition to get_incident_dashboard, every other output unchanged (the chart-view figures of 20261107110000 stay):
--
-- threatByHolder: always four rows, in order human, animal, unknown, none, one per holder type of the counted
-- reports' instruments. Each row has high, medium and low (the threat bands below) and official and notOfficial
-- (the same instruments, split by whether their counted revision is official, so official + notOfficial equals
-- high + medium + low).
--   - An instrument's holder is the entity in the same report whose entity_id it names. Its type is the canonical
--     entity type (person is human, blank is unknown). A type other than human or animal counts as unknown.
--   - An instrument with no holder (a null entity_id, or one that names no entity of the report) is 'none'.
--   - Bands follow the severity bands on the 1-5 scale: low 1-2, medium 3, high 4-5. An instrument with no threat
--     level, or one outside 1 to 5, is in no band.
--   - An instrument is counted once per report for each distinct (normalised name, holder type, threat level),
--     the rule the existing instrument counts use, so a name listed twice with the same holder and level counts once.
--     Summed over the holder types, a band can exceed the threatLevels count of the same report, because one name
--     can be held by two holder types.
--   - Only names that normalise to something count, as in every instrument figure. Counted reports only: the same
--     period, status, incident type, severity band, weekday and hour filters as total.
--
-- Built on 20261107110000_dashboard_chart_evidence, the current definition (it must be applied first). Same signature,
-- rule and tie-breaks. The function is replaced with CREATE OR REPLACE, so its grants stay. Safe to run twice.
--
-- NOT APPLIED to the live (finals) database: applying it is ask-first (see dev-profile-incident/AGENTS.md). Until it is
-- applied the console answers the holder chart view with "not available yet" rather than showing invented figures.

BEGIN;

CREATE OR REPLACE FUNCTION public.get_incident_dashboard(
    p_period_start TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_period_end TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL::TIMESTAMP WITHOUT TIME ZONE,
    p_type TEXT DEFAULT NULL::TEXT,
    p_severity TEXT DEFAULT NULL::TEXT,
    p_day_of_week INTEGER DEFAULT NULL::INTEGER,
    p_hour INTEGER DEFAULT NULL::INTEGER,
    p_timezone TEXT DEFAULT 'UTC'::TEXT,
    p_scope TEXT DEFAULT 'official'::TEXT
) RETURNS JSONB
LANGUAGE sql STABLE SET search_path = ''
AS $function$
WITH target_tz AS (
    SELECT COALESCE(NULLIF(p_timezone, ''), 'UTC') AS tz
),
counted_all AS (
    -- One incident per video: its official revision, else its newest (the Library's rule, through
    -- searchable_revision_id). Its time is when that revision was made. version_count is every revision of the video.
    SELECT
        r.video_id AS incident_id, r.id AS revision_id, r.kind, r.created_at AS generated_datetime,
        v.official_revision_id IS NOT NULL AS is_official,
        r.incident_type, r.severity_level AS severity,
        CASE WHEN jsonb_typeof(r.payload #> '{incident,confidence_score}') = 'number'
            THEN (r.payload #>> '{incident,confidence_score}')::DOUBLE PRECISION END AS confidence,
        r.payload,
        (SELECT COUNT(*) FROM public.report_revisions AS x WHERE x.video_id = v.id)::INTEGER AS version_count,
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
      AND (COALESCE(p_scope, 'official') <> 'official' OR is_official)
      AND (COALESCE(p_scope, 'official') <> 'not_official' OR NOT is_official)
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
    SELECT DISTINCT f.incident_id, f.incident_type, f.is_official, public.canonical_entity_type(e ->> 'type') AS label
    FROM filtered f CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'entities', '[]'::JSONB)) AS e
),
instrument_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, f.is_official, public.normalized_name(ins ->> 'name') AS label,
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
report_items AS (
    -- The evidence items of each counted report: one per entity, instrument or asset entry in its payload.
    SELECT f.incident_type, f.severity, f.is_official,
        (CASE WHEN jsonb_typeof(f.payload -> 'entities') = 'array' THEN jsonb_array_length(f.payload -> 'entities') ELSE 0 END
         + CASE WHEN jsonb_typeof(f.payload -> 'instruments') = 'array' THEN jsonb_array_length(f.payload -> 'instruments') ELSE 0 END
         + CASE WHEN jsonb_typeof(f.payload -> 'assets') = 'array' THEN jsonb_array_length(f.payload -> 'assets') ELSE 0 END)::INTEGER AS items
    FROM filtered f
),
severity_evidence_cells AS (
    SELECT severity, items AS evidence_items, COUNT(*)::INTEGER AS count,
        COUNT(*) FILTER (WHERE is_official)::INTEGER AS official
    FROM report_items WHERE severity IS NOT NULL GROUP BY severity, items
),
type_details AS (
    SELECT jsonb_agg(jsonb_build_object(
        'type', COALESCE(tc.incident_type, 'Unclassified'),
        'count', tc.count,
        'official', tc.official,
        'notOfficial', tc.count - tc.official,
        'evidence', COALESCE((SELECT SUM(ri.items) FROM report_items ri WHERE ri.incident_type IS NOT DISTINCT FROM tc.incident_type), 0)::INTEGER,
        'severity', jsonb_build_object(
            'low', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity <= 2),
            'medium', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity = 3),
            'high', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity >= 4)),
        'entities', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label COLLATE "C") FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM entity_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label COLLATE "C" LIMIT 3) ranked), '[]'::JSONB),
        'instruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label COLLATE "C") FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM instrument_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label COLLATE "C" LIMIT 3) ranked), '[]'::JSONB),
        'assets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label COLLATE "C") FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM asset_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label COLLATE "C" LIMIT 3) ranked), '[]'::JSONB)
    ) ORDER BY tc.count DESC, tc.incident_type COLLATE "C") AS values
    FROM type_counts tc
),
ranked AS (
    SELECT 'entity' AS kind, label, COUNT(DISTINCT incident_id)::INTEGER AS count,
        COUNT(DISTINCT incident_id) FILTER (WHERE is_official)::INTEGER AS official FROM entity_rows GROUP BY label
    UNION ALL SELECT 'instrument', label, COUNT(DISTINCT incident_id)::INTEGER,
        COUNT(DISTINCT incident_id) FILTER (WHERE is_official)::INTEGER FROM instrument_rows GROUP BY label
    UNION ALL SELECT 'asset', label, COUNT(DISTINCT incident_id)::INTEGER,
        COUNT(DISTINCT incident_id) FILTER (WHERE is_official)::INTEGER FROM asset_rows GROUP BY label
),
threat_levels AS (
    SELECT threat_level AS level, COUNT(*)::INTEGER AS count FROM instrument_rows WHERE threat_level IS NOT NULL GROUP BY threat_level
),
instrument_holders AS (
    -- Each named instrument of a counted report, with its threat level and its holder's type (see the header).
    SELECT DISTINCT f.incident_id, f.is_official,
        public.normalized_name(ins ->> 'name') AS label,
        CASE WHEN jsonb_typeof(ins -> 'threat_level') = 'number'
            THEN (ins ->> 'threat_level')::NUMERIC::INTEGER END AS threat_level,
        CASE
            WHEN holder_entity.entity_type IS NULL THEN 'none'
            WHEN holder_entity.entity_type IN ('human', 'animal') THEN holder_entity.entity_type
            ELSE 'unknown'
        END AS holder
    FROM filtered f
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'instruments', '[]'::JSONB)) AS ins
    LEFT JOIN LATERAL (
        SELECT public.canonical_entity_type(e ->> 'type') AS entity_type
        FROM jsonb_array_elements(COALESCE(f.payload -> 'entities', '[]'::JSONB)) AS e
        WHERE e ->> 'entity_id' = ins ->> 'entity_id'
        LIMIT 1
    ) AS holder_entity ON TRUE
    WHERE public.normalized_name(ins ->> 'name') IS NOT NULL
),
threat_by_holder AS (
    -- Always four rows, in order, so a holder type with no instruments still shows as 0. Bands: low 1-2, medium 3, high 4-5.
    SELECT k.ord, k.holder,
        COUNT(ih.incident_id) FILTER (WHERE ih.threat_level BETWEEN 4 AND 5)::INTEGER AS high,
        COUNT(ih.incident_id) FILTER (WHERE ih.threat_level = 3)::INTEGER AS medium,
        COUNT(ih.incident_id) FILTER (WHERE ih.threat_level BETWEEN 1 AND 2)::INTEGER AS low,
        COUNT(ih.incident_id) FILTER (WHERE ih.threat_level BETWEEN 1 AND 5 AND ih.is_official)::INTEGER AS official,
        COUNT(ih.incident_id) FILTER (WHERE ih.threat_level BETWEEN 1 AND 5 AND NOT ih.is_official)::INTEGER AS not_official
    FROM (VALUES (1, 'human'), (2, 'animal'), (3, 'unknown'), (4, 'none')) AS k(ord, holder)
    LEFT JOIN instrument_holders AS ih ON ih.holder = k.holder
    GROUP BY k.ord, k.holder
),
evidence_items AS (
    -- One row per evidence item of a counted report: its kind and whether the counted revision is official.
    SELECT 'entities' AS kind, f.is_official FROM filtered f
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'entities', '[]'::JSONB)) AS item
    UNION ALL
    SELECT 'instruments', f.is_official FROM filtered f
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'instruments', '[]'::JSONB)) AS item
    UNION ALL
    SELECT 'assets', f.is_official FROM filtered f
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.payload -> 'assets', '[]'::JSONB)) AS item
),
evidence_totals AS (
    -- Always three rows, in order, so a kind with no items still shows as 0.
    SELECT k.ord, k.kind, COUNT(e.kind)::INTEGER AS count, COUNT(e.kind) FILTER (WHERE e.is_official)::INTEGER AS official
    FROM (VALUES (1, 'entities'), (2, 'instruments'), (3, 'assets')) AS k(ord, kind)
    LEFT JOIN evidence_items AS e ON e.kind = k.kind
    GROUP BY k.ord, k.kind
),
version_counts AS (
    -- Every revision of every counted video, not only the one that is counted.
    SELECT COUNT(*)::INTEGER AS total,
        COUNT(*) FILTER (WHERE r.kind = 'ai')::INTEGER AS ai,
        COUNT(*) FILTER (WHERE r.kind = 'human')::INTEGER AS human
    FROM filtered AS f JOIN public.report_revisions AS r ON r.video_id = f.incident_id
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
    ) ORDER BY with_report DESC, model_name COLLATE "C"), '[]'::JSONB) AS values
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
    'multipleVersions', (SELECT COUNT(*) FILTER (WHERE version_count > 1) FROM filtered),
    'versions', (SELECT jsonb_build_object('total', total, 'ai', ai, 'human', human) FROM version_counts),
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
    'evidence', COALESCE((SELECT jsonb_agg(jsonb_build_object('kind', kind, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY ord) FROM evidence_totals), '[]'::JSONB),
    'severityEvidence', COALESCE((SELECT jsonb_agg(jsonb_build_object('severity', severity, 'evidenceItems', evidence_items, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY severity, evidence_items) FROM severity_evidence_cells), '[]'::JSONB),
    'entityTypes', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY count DESC, label COLLATE "C") FROM ranked WHERE kind = 'entity'), '[]'::JSONB),
    'topInstruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY count DESC, label COLLATE "C") FROM (SELECT * FROM ranked WHERE kind = 'instrument' ORDER BY count DESC, label COLLATE "C" LIMIT 8) top), '[]'::JSONB),
    'topAssets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count, 'official', official, 'notOfficial', count - official) ORDER BY count DESC, label COLLATE "C") FROM (SELECT * FROM ranked WHERE kind = 'asset' ORDER BY count DESC, label COLLATE "C" LIMIT 8) top), '[]'::JSONB),
    'threatLevels', COALESCE((SELECT jsonb_agg(jsonb_build_object('level', level, 'count', count) ORDER BY level) FROM threat_levels), '[]'::JSONB),
    'threatByHolder', COALESCE((SELECT jsonb_agg(jsonb_build_object('holder', holder, 'high', high, 'medium', medium, 'low', low,
        'official', official, 'notOfficial', not_official) ORDER BY ord) FROM threat_by_holder), '[]'::JSONB),
    'modelCoverage', (SELECT values FROM model_coverage)
);
$function$;

-- PostgREST caches function signatures; reload so the new definition is served at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

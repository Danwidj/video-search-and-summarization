-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Searchable evidence for a video with no official revision, plus the library card fields.
--
-- Rule: each video has at most one "searchable revision", the one its evidence_crops rows belong to.
-- It is the official revision when there is one, otherwise the video's newest revision. Search
-- (search_evidence_items) reads only the searchable revision's crops, so a stale row for any other
-- revision is never returned.
--
--   * Marking a revision official (set_official_revision) makes it the searchable revision. A crop
--     list replaces the video's rows; with no crop list the revision keeps rows it already has (for
--     example the latest revision becoming official needs no new embeddings), so nothing is lost.
--   * Clearing the official revision (NULL) makes the newest revision searchable again. Rows of any
--     other revision are deleted; the newest revision's rows are kept, or replaced by a crop list.
--   * Saving a newer revision on a video with no official revision moves the searchable revision to
--     it. Its rows do not exist yet, so the video is not searchable until the writer calls
--     set_revision_crops for the new revision, which also deletes the old rows. With an official
--     revision a newer revision changes nothing.
--
-- Also adds videos.official_since (when the current official revision was marked) and extends the
-- library cards with officialSince, versionCount, evidenceCount and thumbnail. The file is safe to
-- run again: the column is added IF NOT EXISTS, the backfill touches only rows without a value and
-- every function is created with OR REPLACE.

BEGIN;

-- 1. videos.official_since -----------------------------------------------------------------------
-- Naive UTC, like every other timestamp. NULL when there is no official revision. Rows marked
-- before this column existed have no record of when; the official revision's creation time stands
-- in for them.
ALTER TABLE public.videos ADD COLUMN IF NOT EXISTS official_since TIMESTAMP WITHOUT TIME ZONE;
UPDATE public.videos AS v
SET official_since = r.created_at
FROM public.report_revisions AS r
WHERE r.id = v.official_revision_id AND r.video_id = v.id AND v.official_since IS NULL;

-- 2. Helpers -------------------------------------------------------------------------------------
-- The revision whose evidence_crops a video keeps: official, else newest. NULL for a video with no
-- revision.
CREATE OR REPLACE FUNCTION public.searchable_revision_id(p_video_id VARCHAR)
RETURNS BIGINT
LANGUAGE sql STABLE SET search_path = ''
AS $$
    SELECT COALESCE(
        (SELECT v.official_revision_id FROM public.videos AS v WHERE v.id = p_video_id),
        (SELECT r.id FROM public.report_revisions AS r WHERE r.video_id = p_video_id
         ORDER BY r.revision_no DESC LIMIT 1));
$$;

-- The R2 key of one evidence item of a revision's evidence list, or NULL when it has no image.
CREATE OR REPLACE FUNCTION public.evidence_image(p_item JSONB)
RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT NULLIF(btrim(COALESCE(p_item ->> 'image', '')), '');
$$;

-- Replace all of a video's evidence_crops with the rows built from p_crops, stored against
-- p_revision_id. Shared by set_official_revision and set_revision_crops; the callers lock the video
-- and check the revision. Returns the number of rows stored. Crop list format: see
-- set_official_revision in 20261023000100_report_revisions_functions.sql.
CREATE OR REPLACE FUNCTION public.replace_video_crops(p_video_id VARCHAR, p_revision_id BIGINT, p_crops JSONB)
RETURNS INTEGER
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_crops INTEGER := 0;
BEGIN
    DELETE FROM public.evidence_crops
    WHERE revision_id IN (SELECT id FROM public.report_revisions WHERE video_id = p_video_id);

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
    RETURN v_crops;
END;
$$;

-- 3. set_official_revision -----------------------------------------------------------------------
-- Point a video at one official revision (NULL clears it) and make that the searchable revision:
-- the official one, or the newest when clearing. A non-empty p_crops replaces the video's
-- evidence_crops with those rows. An empty p_crops keeps the rows the target revision already has
-- and deletes every other revision's rows. official_since is set when the pointer moves to a
-- different revision and cleared with it; marking the same revision again keeps the original time.
--
-- Returns {videoId, officialRevisionId, crops}, where crops is the number of rows now stored.
CREATE OR REPLACE FUNCTION public.set_official_revision(
    p_video_id VARCHAR,
    p_revision_id BIGINT,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_target BIGINT;
    v_crops INTEGER;
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

    UPDATE public.videos
    SET official_revision_id = p_revision_id,
        official_since = CASE
            WHEN p_revision_id IS NULL THEN NULL
            WHEN official_revision_id IS NOT DISTINCT FROM p_revision_id AND official_since IS NOT NULL THEN official_since
            ELSE now() AT TIME ZONE 'utc' END
    WHERE id = p_video_id;

    v_target := public.searchable_revision_id(p_video_id);
    IF jsonb_array_length(COALESCE(p_crops, '[]'::JSONB)) = 0 AND v_target IS NOT NULL THEN
        DELETE FROM public.evidence_crops
        WHERE revision_id <> v_target
          AND revision_id IN (SELECT id FROM public.report_revisions WHERE video_id = p_video_id);
        SELECT count(*) INTO v_crops FROM public.evidence_crops WHERE revision_id = v_target;
    ELSE
        v_crops := public.replace_video_crops(p_video_id, v_target, p_crops);
    END IF;

    RETURN jsonb_build_object(
        'videoId', p_video_id,
        'officialRevisionId', p_revision_id,
        'crops', v_crops
    );
END;
$$;

-- 4. set_revision_crops --------------------------------------------------------------------------
-- Store the crops of the video's searchable revision without changing the official pointer: the
-- way to give a video with no official revision its searchable evidence (its newest revision), or
-- to refresh the official revision's rows. p_revision_id must be the searchable revision, else the
-- call is refused; a newer revision saved since the caller read the video therefore cannot be
-- overwritten by stale crops. The video's other rows are deleted. p_crops has the format of
-- set_official_revision; an empty list clears the revision's rows.
--
-- Returns {videoId, revisionId, crops}.
CREATE OR REPLACE FUNCTION public.set_revision_crops(
    p_video_id VARCHAR,
    p_revision_id BIGINT,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_crops INTEGER;
BEGIN
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Video not found: %', p_video_id USING ERRCODE = 'P0001';
    END IF;
    IF p_revision_id IS NULL OR p_revision_id IS DISTINCT FROM public.searchable_revision_id(p_video_id) THEN
        RAISE EXCEPTION 'Revision % is not the searchable revision of video % (the official revision, else the newest)',
            p_revision_id, p_video_id USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;

    v_crops := public.replace_video_crops(p_video_id, p_revision_id, p_crops);
    RETURN jsonb_build_object('videoId', p_video_id, 'revisionId', p_revision_id, 'crops', v_crops);
END;
$$;

-- 5. search_evidence_items -----------------------------------------------------------------------
-- Same arguments and columns as before; now searches each video's searchable revision (official,
-- else newest), so a video with no official revision is searchable once its crops are stored.
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
    JOIN public.videos AS v ON v.id = r.video_id AND public.searchable_revision_id(v.id) = r.id
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

-- 6. list_incident_report_summaries ---------------------------------------------------------------
-- Same arguments as before. The card is the official revision, else the newest. New keys:
-- officialSince (when the official revision was marked; null otherwise), versionCount (revisions of
-- the video), evidenceCount and thumbnail (the revision's evidence items that carry an image, and
-- the R2 key of the first of them).
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

-- 7. Security ------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION
    public.searchable_revision_id(VARCHAR),
    public.evidence_image(JSONB),
    public.replace_video_crops(VARCHAR, BIGINT, JSONB),
    public.set_official_revision(VARCHAR, BIGINT, JSONB),
    public.set_revision_crops(VARCHAR, BIGINT, JSONB),
    public.search_evidence_items(extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER),
    public.list_incident_report_summaries(
        INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
        TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.searchable_revision_id(VARCHAR),
    public.evidence_image(JSONB),
    public.replace_video_crops(VARCHAR, BIGINT, JSONB),
    public.set_official_revision(VARCHAR, BIGINT, JSONB),
    public.set_revision_crops(VARCHAR, BIGINT, JSONB),
    public.search_evidence_items(extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER),
    public.list_incident_report_summaries(
        INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
        TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT)
TO service_role;

-- PostgREST caches function signatures; reload so the new ones are callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

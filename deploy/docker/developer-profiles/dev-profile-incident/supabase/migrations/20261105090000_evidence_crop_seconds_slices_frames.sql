-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Evidence search: the second a box was found at (with its fraction), a slice range per item, a stored frame, and a repair list.
--
-- 1. evidence_crops.timestamp_seconds becomes NUMERIC(8,3). It held the item's own whole second, because the console
--    dropped a fractional box_seconds (18 of 53 live crops stored a second different from the box's, up to 19.7 s off). It
--    now stores the second the box was found at, to 3 decimals.
-- 2. New columns slice_start_seconds and slice_end_seconds: the play range of the item's slice of the existing video (no clip
--    file). First to last seen where the entry has a track, else 3 s either side of the box second, never below 0. The viewer
--    clamps the end to the video's length.
-- 3. New column frame: the R2 key of the whole frame the box was found in (what the search card shows, with the box drawn over
--    it). NULL for an entry that has no stored frame.
-- 4. replace_video_crops reads the new fields from the crop list; an old crop list without them still works (NULL slice and frame).
-- 5. search_evidence_items returns the fractional second, the slice range and the frame key. The return type changes, so the
--    old function is dropped first. An agent that predates this reads only the columns it knows, and int() of the new second
--    still works, so the shared agent keeps serving until it is restarted with the new code.
-- 6. evidence_slice(entry) derives the second and slice from an evidence entry; the backfill below uses it, and the console
--    (revision.ts evidenceSlice) follows the same rules. list_revisions_missing_crops lists each video's searchable revision that
--    has image-bearing evidence and no evidence_crops rows: the console's repair step stores their crops.
--
-- Existing rows are rewritten from each revision's evidence JSON, not from the old second. Embeddings are not touched. The file
-- is safe to run again.

BEGIN;

-- 1-3. Columns -----------------------------------------------------------------------------------
ALTER TABLE public.evidence_crops ALTER COLUMN timestamp_seconds TYPE NUMERIC(8, 3);
ALTER TABLE public.evidence_crops ADD COLUMN IF NOT EXISTS slice_start_seconds NUMERIC(8, 3);
ALTER TABLE public.evidence_crops ADD COLUMN IF NOT EXISTS slice_end_seconds NUMERIC(8, 3);
ALTER TABLE public.evidence_crops ADD COLUMN IF NOT EXISTS frame VARCHAR(1024);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.evidence_crops'::regclass AND conname = 'evidence_crops_slice_check'
    ) THEN
        ALTER TABLE public.evidence_crops ADD CONSTRAINT evidence_crops_slice_check CHECK (
            (slice_start_seconds IS NULL AND slice_end_seconds IS NULL)
            OR (slice_start_seconds >= 0 AND slice_end_seconds >= slice_start_seconds));
    END IF;
END;
$$;

-- 6a. evidence_slice -----------------------------------------------------------------------------
-- The second the box was found at, and the play range, of one evidence entry. box_seconds (a fractional retry second included)
-- wins over the item's own timestamp_seconds, then 0. A track (a key plus first and last seen) gives first to last seen;
-- otherwise 3 s either side of the box second. All to 3 decimals, never below 0.
CREATE OR REPLACE FUNCTION public.evidence_slice(
    p_item JSONB, OUT box_second NUMERIC, OUT slice_start NUMERIC, OUT slice_end NUMERIC)
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    WITH raw AS (
        SELECT
            COALESCE(
                CASE WHEN jsonb_typeof(p_item -> 'box_seconds') = 'number' THEN (p_item ->> 'box_seconds')::NUMERIC END,
                CASE WHEN jsonb_typeof(p_item -> 'timestamp_seconds') = 'number' THEN (p_item ->> 'timestamp_seconds')::NUMERIC END,
                0) AS at,
            CASE WHEN jsonb_typeof(p_item -> 'track_first_seen_seconds') = 'number'
                THEN (p_item ->> 'track_first_seen_seconds')::NUMERIC END AS first_seen,
            CASE WHEN jsonb_typeof(p_item -> 'track_last_seen_seconds') = 'number'
                THEN (p_item ->> 'track_last_seen_seconds')::NUMERIC END AS last_seen,
            NULLIF(btrim(COALESCE(p_item ->> 'track', '')), '') IS NOT NULL AS has_track
    ), span AS (
        SELECT at, CASE WHEN has_track AND first_seen IS NOT NULL AND last_seen IS NOT NULL AND last_seen >= first_seen
                        THEN first_seen ELSE at - 3 END AS lo,
                  CASE WHEN has_track AND first_seen IS NOT NULL AND last_seen IS NOT NULL AND last_seen >= first_seen
                        THEN last_seen ELSE at + 3 END AS hi
        FROM raw
    )
    SELECT round(GREATEST(0, at), 3),
           round(GREATEST(0, lo), 3),
           round(GREATEST(GREATEST(0, lo), hi), 3)
    FROM span;
$$;

-- Backfill: every row without a slice is rewritten from its revision's evidence entry.
UPDATE public.evidence_crops AS ec
SET timestamp_seconds = d.box_second,
    slice_start_seconds = d.slice_start,
    slice_end_seconds = d.slice_end,
    frame = d.frame
FROM (
    SELECT old.revision_id, old.item_type, old.item_id, s.box_second, s.slice_start, s.slice_end,
           NULLIF(btrim(COALESCE(entry.item ->> 'frame', '')), '') AS frame
    FROM public.evidence_crops AS old
    JOIN public.report_revisions AS r ON r.id = old.revision_id
    CROSS JOIN LATERAL (
        SELECT e AS item
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(r.evidence) = 'array' THEN r.evidence ELSE '[]'::JSONB END) AS e
        WHERE e ->> 'item_type' = old.item_type AND e ->> 'item_id' = old.item_id
        LIMIT 1
    ) AS entry
    CROSS JOIN LATERAL public.evidence_slice(entry.item) AS s
    WHERE old.slice_start_seconds IS NULL
) AS d
WHERE ec.revision_id = d.revision_id AND ec.item_type = d.item_type AND ec.item_id = d.item_id;

-- 4. replace_video_crops -------------------------------------------------------------------------
-- Replace all of a video's evidence_crops with the rows built from p_crops, stored against p_revision_id. Crop list format: see
-- set_official_revision in 20261023000100_report_revisions_functions.sql, plus the optional slice_start_seconds,
-- slice_end_seconds and frame. timestamp_seconds keeps its fraction (3 decimals).
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
            timestamp_seconds, slice_start_seconds, slice_end_seconds, frame, bounding_box, image, embedding
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
                    THEN round((e ->> 'timestamp_seconds')::NUMERIC, 3) END,
                0),
            CASE WHEN jsonb_typeof(e -> 'slice_start_seconds') = 'number'
                      AND jsonb_typeof(e -> 'slice_end_seconds') = 'number'
                THEN round(GREATEST(0, (e ->> 'slice_start_seconds')::NUMERIC), 3) END,
            CASE WHEN jsonb_typeof(e -> 'slice_start_seconds') = 'number'
                      AND jsonb_typeof(e -> 'slice_end_seconds') = 'number'
                THEN round(GREATEST(GREATEST(0, (e ->> 'slice_start_seconds')::NUMERIC),
                                    (e ->> 'slice_end_seconds')::NUMERIC), 3) END,
            left(NULLIF(btrim(COALESCE(e ->> 'frame', '')), ''), 1024),
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

-- 5. search_evidence_items -----------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.search_evidence_items(
    extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, VARCHAR);

CREATE OR REPLACE FUNCTION public.search_evidence_items(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
    p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset'],
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INTEGER DEFAULT NULL,
    p_max_severity INTEGER DEFAULT NULL,
    p_video_id VARCHAR DEFAULT NULL
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
    timestamp_seconds NUMERIC(8, 3),
    bounding_box INTEGER[4],
    similarity_score DOUBLE PRECISION,
    slice_start_seconds NUMERIC(8, 3),
    slice_end_seconds NUMERIC(8, 3),
    frame VARCHAR(1024)
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
        CASE WHEN p_query_embedding IS NULL THEN 0.0
             ELSE (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION
        END,
        ec.slice_start_seconds,
        ec.slice_end_seconds,
        ec.frame
    FROM public.evidence_crops AS ec
    JOIN public.report_revisions AS r ON r.id = ec.revision_id
    JOIN public.videos AS v ON v.id = r.video_id AND public.searchable_revision_id(v.id) = r.id
    WHERE (p_video_id IS NULL OR r.video_id = p_video_id)
      AND (p_item_types IS NULL OR ec.item_type = ANY (p_item_types))
      AND (p_query_embedding IS NULL OR ec.embedding IS NOT NULL)
      AND (p_query_embedding IS NULL
           OR (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity)
      AND (p_incident_types IS NULL OR r.incident_type = ANY (p_incident_types))
      AND (p_min_severity IS NULL OR r.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR r.severity_level <= p_max_severity)
    ORDER BY ec.embedding OPERATOR(extensions.<=>) p_query_embedding ASC NULLS LAST,
             ec.timestamp_seconds ASC, ec.item_id ASC
    LIMIT p_top_k;
END;
$$;

-- 6b. list_revisions_missing_crops ---------------------------------------------------------------
-- Each video's searchable revision (official, else newest) that has at least one image-bearing evidence entry and no
-- evidence_crops rows: a revision the console never stored crops for, so its video cannot be found by search. p_video_id limits
-- the list to one video.
CREATE OR REPLACE FUNCTION public.list_revisions_missing_crops(p_video_id VARCHAR DEFAULT NULL)
RETURNS TABLE (video_id VARCHAR(20), revision_id BIGINT)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
    SELECT v.id, r.id
    FROM public.videos AS v
    JOIN public.report_revisions AS r ON r.id = public.searchable_revision_id(v.id)
    WHERE (p_video_id IS NULL OR v.id = p_video_id)
      AND jsonb_typeof(r.evidence) = 'array'
      AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.evidence) AS e WHERE public.evidence_image(e) IS NOT NULL)
      AND NOT EXISTS (SELECT 1 FROM public.evidence_crops AS ec WHERE ec.revision_id = r.id)
    ORDER BY v.id;
$$;

-- 7. Security ------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION
    public.evidence_slice(JSONB),
    public.replace_video_crops(VARCHAR, BIGINT, JSONB),
    public.search_evidence_items(
        extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, VARCHAR),
    public.list_revisions_missing_crops(VARCHAR)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.evidence_slice(JSONB),
    public.replace_video_crops(VARCHAR, BIGINT, JSONB),
    public.search_evidence_items(
        extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER, VARCHAR),
    public.list_revisions_missing_crops(VARCHAR)
TO service_role;

-- PostgREST caches function signatures; reload so the new ones are callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

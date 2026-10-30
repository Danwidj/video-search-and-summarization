-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Crop functions per incident revision with a source video (mvp3, P3.3).
--
-- Applied after 20261030110000_analyses_suggestions_crops.sql (evidence_crops.video_id) on an empty
-- database. Defines only the functions this step owns:
--   searchable_revision_id(incident)               the revision whose crops the incident keeps:
--                                                  the official one, else the newest
--   replace_video_crops(incident, video, rev, crops)  replace ONE video's crops, stored against rev
--   set_revision_crops(incident, rev, crops)       set ALL of the searchable revision's crops;
--                                                  each crop names its source video in "video_id"
--   evidence_image(item)                           unchanged: the R2 key of one evidence item
--
-- apply_r2_rename is dropped, not adapted: it was the one-off helper of the old per-video R2 rename
-- (supabase/r2/migrate_r2_names.py) and 20261030100000_revisions_per_incident.sql already removed it.
-- mvp3 starts from real names, so there is nothing to rename.
--
-- Crop list format (unchanged): an array of objects with item_type (entity | instrument | asset),
-- item_id, image (R2 key, prefix-free) and optionally item_name, description, threat_level,
-- holder_entity_id, timestamp_seconds, bounding_box and embedding. Items without an image or with a
-- different item_type are skipped.

BEGIN;

-- 1. searchable_revision_id ----------------------------------------------------------------------
-- NULL for an incident with no revision (or an unknown incident).
CREATE OR REPLACE FUNCTION public.searchable_revision_id(p_incident_id BIGINT)
RETURNS BIGINT
LANGUAGE sql STABLE SET search_path = ''
AS $$
    SELECT COALESCE(
        (SELECT i.official_revision_id FROM public.incidents AS i WHERE i.id = p_incident_id),
        (SELECT r.id FROM public.report_revisions AS r WHERE r.incident_id = p_incident_id
         ORDER BY r.revision_no DESC LIMIT 1));
$$;

-- 2. evidence_image ------------------------------------------------------------------------------
-- Same body as before; kept here because this step owns it.
CREATE OR REPLACE FUNCTION public.evidence_image(p_item JSONB)
RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT NULLIF(btrim(COALESCE(p_item ->> 'image', '')), '');
$$;

-- 3. replace_video_crops -------------------------------------------------------------------------
-- Delete every crop of p_video_id (on any revision of the incident, so no stale row survives), then
-- store the rows built from p_crops against p_revision_id. The crops of the incident's other videos
-- are untouched. A NULL p_revision_id only deletes. Returns the number of rows stored.
-- The caller locks the incident when it needs to; this function checks that the video and the
-- revision belong to the incident.
CREATE OR REPLACE FUNCTION public.replace_video_crops(
    p_incident_id BIGINT,
    p_video_id TEXT,
    p_revision_id BIGINT,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_crops INTEGER := 0;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.videos AS v WHERE v.id = p_video_id AND v.incident_id = p_incident_id) THEN
        RAISE EXCEPTION 'Video % is not in incident %', p_video_id, p_incident_id USING ERRCODE = 'P0001';
    END IF;
    IF p_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.report_revisions AS r WHERE r.id = p_revision_id AND r.incident_id = p_incident_id
    ) THEN
        RAISE EXCEPTION 'Revision % is not in incident %', p_revision_id, p_incident_id USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;

    DELETE FROM public.evidence_crops AS c WHERE c.video_id = p_video_id;

    IF p_revision_id IS NOT NULL THEN
        INSERT INTO public.evidence_crops (
            revision_id, video_id, item_type, item_id, item_name, description, threat_level, holder_entity_id,
            timestamp_seconds, bounding_box, image, embedding
        )
        SELECT DISTINCT ON (e ->> 'item_type', e ->> 'item_id')
            p_revision_id,
            p_video_id,
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

-- 4. set_revision_crops --------------------------------------------------------------------------
-- Store the crops of the incident's searchable revision without changing the official pointer. All
-- of the incident's existing crops are replaced: each object of p_crops names its source video in
-- "video_id" (a video of the incident), and the incident's videos missing from the list end with no
-- crops. p_revision_id must be the searchable revision, else the call is refused, so a newer
-- revision saved since the caller read the incident cannot be overwritten by stale crops. An empty
-- list clears them. Use replace_video_crops to change one video only.
--
-- Returns {incidentId, revisionId, crops}.
CREATE OR REPLACE FUNCTION public.set_revision_crops(
    p_incident_id BIGINT,
    p_revision_id BIGINT,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_video TEXT;
    v_crops INTEGER := 0;
BEGIN
    PERFORM 1 FROM public.incidents AS i WHERE i.id = p_incident_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Incident not found: %', p_incident_id USING ERRCODE = 'P0001';
    END IF;
    IF p_revision_id IS NULL OR p_revision_id IS DISTINCT FROM public.searchable_revision_id(p_incident_id) THEN
        RAISE EXCEPTION 'Revision % is not the searchable revision of incident % (the official revision, else the newest)',
            p_revision_id, p_incident_id USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(p_crops, '[]'::JSONB)) AS e
        WHERE jsonb_typeof(e) <> 'object'
           OR NOT EXISTS (SELECT 1 FROM public.videos AS v
                          WHERE v.id = e ->> 'video_id' AND v.incident_id = p_incident_id)
    ) THEN
        RAISE EXCEPTION 'Every crop must name a video_id that belongs to incident %', p_incident_id
            USING ERRCODE = 'P0001';
    END IF;

    DELETE FROM public.evidence_crops AS c
    WHERE c.video_id IN (SELECT v.id FROM public.videos AS v WHERE v.incident_id = p_incident_id);

    FOR v_video IN
        SELECT DISTINCT e ->> 'video_id' FROM jsonb_array_elements(COALESCE(p_crops, '[]'::JSONB)) AS e
    LOOP
        v_crops := v_crops + public.replace_video_crops(
            p_incident_id, v_video, p_revision_id,
            (SELECT jsonb_agg(e) FROM jsonb_array_elements(p_crops) AS e WHERE e ->> 'video_id' = v_video));
    END LOOP;

    RETURN jsonb_build_object('incidentId', p_incident_id, 'revisionId', p_revision_id, 'crops', v_crops);
END;
$$;

-- 5. Security: service role only, like the other functions ----------------------------------------
REVOKE ALL ON FUNCTION
    public.searchable_revision_id(BIGINT),
    public.evidence_image(JSONB),
    public.replace_video_crops(BIGINT, TEXT, BIGINT, JSONB),
    public.set_revision_crops(BIGINT, BIGINT, JSONB)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.searchable_revision_id(BIGINT),
    public.evidence_image(JSONB),
    public.replace_video_crops(BIGINT, TEXT, BIGINT, JSONB),
    public.set_revision_crops(BIGINT, BIGINT, JSONB)
TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;

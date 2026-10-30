-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- mvp3 merge and remove (P3.5): merge one incident into another, and remove one video from its
-- incident either by deleting it or by moving it to a new incident of its own.
--
-- Applied after 20261030110000_analyses_suggestions_crops.sql. Defines only the two functions below.
--
--   merge_incidents(p_target_incident_id, p_source_incident_id) -> JSONB
--     The source's videos move to the target (their analyses follow by video id). The source incident
--     is deleted with what hangs off it: revisions, their crops, suggestions. The source's old URL,
--     human edits and official choice are not carried over. A pending suggestion for the pair is
--     marked accepted before the source goes (the cascade then removes the row with the source).
--     Returns {incident_id (the target), source_incident_id, moved_video_ids, orphaned_crop_images}.
--     orphaned_crop_images are the image keys of crops that went with the source's revisions; the
--     console decides what to do with the files (merge moves no files; its sweep handles orphans).
--
--   remove_video(p_video_id, p_mode) -> JSONB
--     p_mode = 'delete': delete the video with its analyses and crops (the cascade of videos). The
--       incident's revisions stay as history and keep the name in video_names. When it was the
--       incident's last video the incident is deleted too, with its revisions, crops and suggestions.
--     p_mode = 'move': move the video to a new incident; its analyses and crops follow by video id and
--       the old incident's revisions stay untouched. Refused for the last video. The pair (old, new)
--       is recorded as a rejected suggestion so it is never suggested back.
--     Returns {mode, video_id, incident_id (the incident it was in), new_incident_id (move, else null),
--       incident_deleted, deleted_video_key (the video's logical R2 key, delete only, else null),
--       deleted_crop_images (image keys of the rows removed, empty for a move)}.
--
-- Both lock the incident rows they touch, so two concurrent calls on one incident run one after the
-- other. Service role only, like every function in this schema.

BEGIN;

-- 1. merge_incidents -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.merge_incidents(p_target_incident_id BIGINT, p_source_incident_id BIGINT)
RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_found INTEGER;
    v_moved TEXT[];
    v_images TEXT[];
BEGIN
    IF p_target_incident_id IS NULL OR p_source_incident_id IS NULL THEN
        RAISE EXCEPTION 'merge_incidents needs a target and a source incident' USING ERRCODE = '22023';
    END IF;
    IF p_target_incident_id = p_source_incident_id THEN
        RAISE EXCEPTION 'cannot merge incident % into itself', p_target_incident_id USING ERRCODE = '22023';
    END IF;

    -- Lock in id order so two merges over the same pair cannot deadlock.
    SELECT count(*) INTO v_found FROM (
        SELECT i.id FROM public.incidents AS i
        WHERE i.id IN (p_target_incident_id, p_source_incident_id)
        ORDER BY i.id FOR UPDATE
    ) AS locked;
    IF v_found <> 2 THEN
        RAISE EXCEPTION 'incident % or % does not exist', p_target_incident_id, p_source_incident_id
            USING ERRCODE = 'P0002';
    END IF;

    SELECT COALESCE(array_agg(DISTINCT ec.image), '{}'::TEXT[]) INTO v_images
    FROM public.evidence_crops AS ec
    JOIN public.report_revisions AS r ON r.id = ec.revision_id
    WHERE r.incident_id = p_source_incident_id AND ec.image IS NOT NULL;

    WITH moved AS (
        UPDATE public.videos SET incident_id = p_target_incident_id
        WHERE incident_id = p_source_incident_id
        RETURNING id
    )
    SELECT COALESCE(array_agg(id ORDER BY id), '{}'::TEXT[]) INTO v_moved FROM moved;

    UPDATE public.incident_match_suggestions SET status = 'accepted', decided_at = (now() AT TIME ZONE 'utc')
    WHERE status = 'pending'
      AND LEAST(incident_a_id, incident_b_id) = LEAST(p_target_incident_id, p_source_incident_id)
      AND GREATEST(incident_a_id, incident_b_id) = GREATEST(p_target_incident_id, p_source_incident_id);

    -- The source has no videos left; this removes its revisions, crops and suggestions.
    DELETE FROM public.incidents WHERE id = p_source_incident_id;

    RETURN jsonb_build_object(
        'incident_id', p_target_incident_id,
        'source_incident_id', p_source_incident_id,
        'moved_video_ids', to_jsonb(v_moved),
        'orphaned_crop_images', to_jsonb(v_images)
    );
END;
$$;

-- 2. remove_video --------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.remove_video(p_video_id TEXT, p_mode TEXT)
RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_incident_id BIGINT;
    v_filepath TEXT;
    v_video_count INTEGER;
    v_new_incident_id BIGINT;
    v_images TEXT[] := '{}'::TEXT[];
    v_incident_deleted BOOLEAN := FALSE;
BEGIN
    IF p_mode IS NULL OR p_mode NOT IN ('delete', 'move') THEN
        RAISE EXCEPTION 'remove_video mode must be delete or move, got %', COALESCE(p_mode, 'NULL')
            USING ERRCODE = '22023';
    END IF;

    SELECT v.incident_id INTO v_incident_id FROM public.videos AS v WHERE v.id = p_video_id;
    IF v_incident_id IS NULL THEN
        RAISE EXCEPTION 'video % does not exist', p_video_id USING ERRCODE = 'P0002';
    END IF;

    -- Lock the incident, then re-read the video: it may have moved or gone while we waited.
    PERFORM 1 FROM public.incidents AS i WHERE i.id = v_incident_id FOR UPDATE;
    SELECT v.incident_id, v.filepath INTO v_incident_id, v_filepath
    FROM public.videos AS v WHERE v.id = p_video_id FOR UPDATE;
    IF v_incident_id IS NULL THEN
        RAISE EXCEPTION 'video % does not exist', p_video_id USING ERRCODE = 'P0002';
    END IF;
    SELECT count(*) INTO v_video_count FROM public.videos AS v WHERE v.incident_id = v_incident_id;

    IF p_mode = 'move' THEN
        IF v_video_count < 2 THEN
            RAISE EXCEPTION 'video % is the last video of incident %; delete it instead of moving it',
                p_video_id, v_incident_id USING ERRCODE = '23514';
        END IF;
        INSERT INTO public.incidents DEFAULT VALUES RETURNING id INTO v_new_incident_id;
        UPDATE public.videos SET incident_id = v_new_incident_id WHERE id = p_video_id;
        -- Remembered as decided so the pair is never suggested back.
        INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score, reasons, status, decided_at)
        VALUES (v_incident_id, v_new_incident_id, 0, '[]'::JSONB, 'rejected', (now() AT TIME ZONE 'utc'));
        v_filepath := NULL;
    ELSIF v_video_count < 2 THEN
        -- Last video: the incident goes with it, and so do all crops on its revisions.
        SELECT COALESCE(array_agg(DISTINCT ec.image), '{}'::TEXT[]) INTO v_images
        FROM public.evidence_crops AS ec
        LEFT JOIN public.report_revisions AS r ON r.id = ec.revision_id
        WHERE ec.image IS NOT NULL AND (ec.video_id = p_video_id OR r.incident_id = v_incident_id);
        DELETE FROM public.incidents WHERE id = v_incident_id;
        v_incident_deleted := TRUE;
    ELSE
        SELECT COALESCE(array_agg(DISTINCT ec.image), '{}'::TEXT[]) INTO v_images
        FROM public.evidence_crops AS ec WHERE ec.video_id = p_video_id AND ec.image IS NOT NULL;
        DELETE FROM public.videos WHERE id = p_video_id;
    END IF;

    RETURN jsonb_build_object(
        'mode', p_mode,
        'video_id', p_video_id,
        'incident_id', v_incident_id,
        'new_incident_id', v_new_incident_id,
        'incident_deleted', v_incident_deleted,
        'deleted_video_key', v_filepath,
        'deleted_crop_images', to_jsonb(v_images)
    );
END;
$$;

-- 3. Access: service role only -------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.merge_incidents(BIGINT, BIGINT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.merge_incidents(BIGINT, BIGINT) TO service_role;
REVOKE ALL ON FUNCTION public.remove_video(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.remove_video(TEXT, TEXT) TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;

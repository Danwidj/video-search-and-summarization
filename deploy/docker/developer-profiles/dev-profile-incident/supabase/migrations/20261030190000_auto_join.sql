-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Automatic join record. The console joins an incident to its best match scoring at or above the
-- automatic threshold without a reviewer. A merge deletes the source incident and its suggestion rows
-- with it, so the record of why a video joined lives on the video itself.
--
-- Applied after 20261030180000_matching.sql. Adds, all additive:
--   videos.auto_joined_score, auto_joined_reasons, auto_joined_at
--     NULL for a video nobody joined automatically (uploaded alone, joined by a reviewer, or moved out).
--   auto_merge_incidents(p_target_incident_id, p_source_incident_id, p_score, p_reasons) -> JSONB
--     merge_incidents, then stamps the videos it moved that carry no record yet with the score,
--     reasons and time, in one transaction. Returns merge_incidents' result.
--   remove_video: 'move' also clears the moved video's record (same signature; the pair is still
--     recorded as rejected so it is never joined or suggested again).

BEGIN;

ALTER TABLE public.videos
    ADD COLUMN auto_joined_score DOUBLE PRECISION,
    ADD COLUMN auto_joined_reasons JSONB,
    ADD COLUMN auto_joined_at TIMESTAMP WITHOUT TIME ZONE,
    ADD CONSTRAINT videos_auto_joined_score_check CHECK (auto_joined_score IS NULL OR (auto_joined_score >= 0 AND auto_joined_score <= 1));

CREATE OR REPLACE FUNCTION public.auto_merge_incidents(
    p_target_incident_id BIGINT, p_source_incident_id BIGINT, p_score DOUBLE PRECISION, p_reasons JSONB)
RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_result JSONB;
BEGIN
    IF p_score IS NULL OR p_score < 0 OR p_score > 1 THEN
        RAISE EXCEPTION 'auto_merge_incidents score must be between 0 and 1' USING ERRCODE = '22023';
    END IF;
    v_result := public.merge_incidents(p_target_incident_id, p_source_incident_id);
    UPDATE public.videos
    SET auto_joined_score = p_score,
        auto_joined_reasons = COALESCE(p_reasons, '[]'::JSONB),
        auto_joined_at = (now() AT TIME ZONE 'utc')
    WHERE id IN (SELECT jsonb_array_elements_text(v_result -> 'moved_video_ids'))
      AND auto_joined_at IS NULL;
    RETURN v_result;
END;
$$;

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
        -- A moved-out video is no longer joined to anything: its automatic-join record goes with the move.
        UPDATE public.videos
        SET incident_id = v_new_incident_id,
            auto_joined_score = NULL, auto_joined_reasons = NULL, auto_joined_at = NULL
        WHERE id = p_video_id;
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

REVOKE ALL ON FUNCTION public.auto_merge_incidents(BIGINT, BIGINT, DOUBLE PRECISION, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.auto_merge_incidents(BIGINT, BIGINT, DOUBLE PRECISION, JSONB) TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;

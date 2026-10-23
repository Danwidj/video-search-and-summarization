-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- A human save that stores its searchable crops in the same transaction as the revision.
--
-- The console embeds a new revision's evidence before it saves (the agent embeds the evidence it is
-- posted, see incident-console-v2 Save), then calls this function with the crop rows. Inside one
-- call the revision is inserted and, when the video has no official revision, its crops replace the
-- video's rows (replace_video_crops, as set_revision_crops does). So a save whose embedding failed
-- never reaches this function, and a revision never exists without the crops that make it searchable.
-- With an official revision the crops are ignored and the official revision's rows stay as they are.
--
-- save_human_revision is unchanged and still callable. The file is safe to run again: the function is
-- created with OR REPLACE.
--
-- Returns the save_human_revision result plus {crops}, the number of crop rows now stored for the video
-- (0 when the video has an official revision, which keeps its own rows).

BEGIN;

CREATE OR REPLACE FUNCTION public.save_human_revision_with_crops(
    p_video_id VARCHAR,
    p_parent_id BIGINT,
    p_created_by TEXT,
    p_note TEXT,
    p_payload JSONB,
    p_evidence JSONB,
    p_incident_type TEXT,
    p_severity_level INTEGER,
    p_start_seconds INTEGER,
    p_end_seconds INTEGER,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_saved JSONB;
    v_revision BIGINT;
    v_official BIGINT;
    v_crops INTEGER := 0;
BEGIN
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;

    v_saved := public.save_human_revision(
        p_video_id, p_parent_id, p_created_by, p_note, p_payload, p_evidence,
        p_incident_type, p_severity_level, p_start_seconds, p_end_seconds);
    v_revision := (v_saved ->> 'revisionId')::BIGINT;

    -- save_human_revision locked the video row, so this read cannot race another save or official change.
    SELECT v.official_revision_id INTO v_official FROM public.videos AS v WHERE v.id = p_video_id;
    IF v_official IS NULL THEN
        v_crops := public.replace_video_crops(p_video_id, v_revision, p_crops);
    END IF;

    RETURN v_saved || jsonb_build_object('crops', v_crops);
END;
$$;

-- Security: service role only, exactly like the other write functions.
REVOKE ALL ON FUNCTION
    public.save_human_revision_with_crops(VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.save_human_revision_with_crops(VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB)
TO service_role;

-- PostgREST caches function signatures; reload so the new one is callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

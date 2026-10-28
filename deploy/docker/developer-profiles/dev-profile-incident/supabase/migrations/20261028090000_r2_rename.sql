-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Readable R2 object names: the one function that points database rows at renamed objects.
--
-- supabase/r2/migrate_r2_names.py copies each R2 object to a readable key, verifies the
-- copy, then calls apply_r2_rename once per video. The function rewrites the three places that
-- hold an R2 key for that video, in one transaction:
--   videos.filepath                      the video object
--   report_revisions.evidence[].image    each evidence item's crop
--   evidence_crops.image                 the searchable copy of the same key
-- Nothing else changes. model_runs.notes (immutable) is not touched; report_revisions.payload holds no
-- R2 keys (the script checks that before it calls this).
--
-- report_revisions is append-only, so the guard gets one narrow exception: inside apply_r2_rename
-- (it sets the transaction-local flag app.r2_rename) a revision may change its evidence column and no
-- other column. Any other UPDATE, and any UPDATE without the flag, is still refused. The file is safe
-- to run again: both functions are created with OR REPLACE.
--
-- Returns {videoId, filepath, revisions, crops}: the number of revision and crop rows changed.

BEGIN;

CREATE OR REPLACE FUNCTION public.report_revisions_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
        RETURN OLD;
    END IF;
    -- apply_r2_rename may point evidence at renamed R2 objects; every other column must be unchanged.
    IF TG_OP = 'UPDATE'
       AND pg_catalog.current_setting('app.r2_rename', true) = 'on'
       AND pg_catalog.to_jsonb(NEW) - 'evidence' = pg_catalog.to_jsonb(OLD) - 'evidence' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'report_revisions is append-only' USING ERRCODE = 'P0001';
END;
$$;

CREATE OR REPLACE FUNCTION public.apply_r2_rename(
    p_video_id VARCHAR,
    p_filepath TEXT,
    p_key_map JSONB DEFAULT '{}'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_revisions INTEGER := 0;
    v_crops INTEGER := 0;
BEGIN
    IF p_key_map IS NULL OR pg_catalog.jsonb_typeof(p_key_map) <> 'object' THEN
        RAISE EXCEPTION 'p_key_map must be an object of old key to new key' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_catalog.jsonb_each(p_key_map) AS m WHERE pg_catalog.jsonb_typeof(m.value) <> 'string') THEN
        RAISE EXCEPTION 'every new key in p_key_map must be a string' USING ERRCODE = '22023';
    END IF;

    PERFORM 1 FROM public.videos AS v WHERE v.id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Video not found' USING ERRCODE = 'P0002';
    END IF;

    IF p_filepath IS NOT NULL AND p_filepath <> '' THEN
        UPDATE public.videos AS v SET filepath = p_filepath WHERE v.id = p_video_id;
    END IF;

    PERFORM pg_catalog.set_config('app.r2_rename', 'on', true);
    UPDATE public.report_revisions AS r
    SET evidence = (
        SELECT COALESCE(pg_catalog.jsonb_agg(
            CASE WHEN pg_catalog.jsonb_typeof(item.value) = 'object' AND p_key_map ? (item.value ->> 'image')
                 THEN pg_catalog.jsonb_set(item.value, '{image}', p_key_map -> (item.value ->> 'image'))
                 ELSE item.value END
            ORDER BY item.ordinality), '[]'::JSONB)
        FROM pg_catalog.jsonb_array_elements(r.evidence) WITH ORDINALITY AS item (value, ordinality))
    WHERE r.video_id = p_video_id
      AND pg_catalog.jsonb_typeof(r.evidence) = 'array'
      AND EXISTS (
          SELECT 1 FROM pg_catalog.jsonb_array_elements(r.evidence) AS e (value)
          WHERE pg_catalog.jsonb_typeof(e.value) = 'object' AND p_key_map ? (e.value ->> 'image'));
    GET DIAGNOSTICS v_revisions = ROW_COUNT;
    PERFORM pg_catalog.set_config('app.r2_rename', 'off', true);

    UPDATE public.evidence_crops AS c
    SET image = p_key_map ->> c.image
    FROM public.report_revisions AS r
    WHERE r.id = c.revision_id AND r.video_id = p_video_id AND p_key_map ? c.image;
    GET DIAGNOSTICS v_crops = ROW_COUNT;

    RETURN pg_catalog.jsonb_build_object(
        'videoId', p_video_id, 'filepath', p_filepath, 'revisions', v_revisions, 'crops', v_crops);
END;
$$;

-- Security: service role only, exactly like the other write functions.
REVOKE ALL ON FUNCTION public.apply_r2_rename(VARCHAR, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_r2_rename(VARCHAR, TEXT, JSONB) TO service_role;
REVOKE ALL ON FUNCTION public.report_revisions_append_only() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.report_revisions_append_only() TO service_role;

-- PostgREST caches function signatures; reload so the new one is callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- The summary text now leads with the incident type ("burglary: title"), so the stored summary vectors are re-embedded.
--
-- 1. report_revisions is append-only and set_revision_embedding fills a vector only from NULL. This file adds a third narrow
--    exception beside app.r2_rename and app.revision_embedding: inside refresh_revision_embedding (transaction-local flag
--    app.revision_embedding_refresh) a row may REPLACE its embedding column with another vector and change no other column.
--    Setting it to NULL stays refused.
-- 2. refresh_revision_embedding(video, revision, vector) does that for the video's searchable version only (the official
--    revision, else the newest) and returns true when it replaced a vector. A version with no vector is left to
--    set_revision_embedding.
-- 3. list_revisions_missing_embeddings also returns the incident type, because the text to embed now includes it. The return
--    type changes, so the old function is dropped first.
--
-- The file is safe to run again.

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
    -- set_revision_embedding may fill a missing summary vector; no other column changes.
    IF TG_OP = 'UPDATE'
       AND pg_catalog.current_setting('app.revision_embedding', true) = 'on'
       AND OLD.embedding IS NULL
       AND NEW.embedding IS NOT NULL
       AND pg_catalog.to_jsonb(NEW) - 'embedding' = pg_catalog.to_jsonb(OLD) - 'embedding' THEN
        RETURN NEW;
    END IF;
    -- refresh_revision_embedding may replace a stored summary vector with another; no other column changes.
    IF TG_OP = 'UPDATE'
       AND pg_catalog.current_setting('app.revision_embedding_refresh', true) = 'on'
       AND OLD.embedding IS NOT NULL
       AND NEW.embedding IS NOT NULL
       AND pg_catalog.to_jsonb(NEW) - 'embedding' = pg_catalog.to_jsonb(OLD) - 'embedding' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'report_revisions is append-only' USING ERRCODE = 'P0001';
END;
$$;

CREATE OR REPLACE FUNCTION public.refresh_revision_embedding(
    p_video_id VARCHAR,
    p_revision_id BIGINT,
    p_embedding extensions.vector(1024)
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_changed INTEGER;
BEGIN
    IF p_embedding IS NULL THEN
        RAISE EXCEPTION 'An embedding is required' USING ERRCODE = 'P0001';
    END IF;
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Video not found: %', p_video_id USING ERRCODE = 'P0001';
    END IF;
    IF p_revision_id IS NULL OR p_revision_id IS DISTINCT FROM public.searchable_revision_id(p_video_id) THEN
        RAISE EXCEPTION 'Revision % is not the searchable revision of video % (the official revision, else the newest)',
            p_revision_id, p_video_id USING ERRCODE = 'P0001';
    END IF;

    PERFORM pg_catalog.set_config('app.revision_embedding_refresh', 'on', true);
    UPDATE public.report_revisions AS r
    SET embedding = p_embedding
    WHERE r.id = p_revision_id AND r.video_id = p_video_id AND r.embedding IS NOT NULL;
    GET DIAGNOSTICS v_changed = ROW_COUNT;
    PERFORM pg_catalog.set_config('app.revision_embedding_refresh', 'off', true);
    RETURN v_changed > 0;
END;
$$;

DROP FUNCTION IF EXISTS public.list_revisions_missing_embeddings(VARCHAR);
CREATE OR REPLACE FUNCTION public.list_revisions_missing_embeddings(p_video_id VARCHAR DEFAULT NULL)
RETURNS TABLE (video_id VARCHAR(20), revision_id BIGINT, incident_type TEXT, title TEXT, description TEXT)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
    SELECT v.id, r.id, r.payload #>> '{incident,type}', r.payload #>> '{incident,title}', r.payload #>> '{incident,description}'
    FROM public.videos AS v
    JOIN public.report_revisions AS r ON r.id = public.searchable_revision_id(v.id)
    WHERE (p_video_id IS NULL OR v.id = p_video_id)
      AND r.embedding IS NULL
      AND (COALESCE(btrim(r.payload #>> '{incident,title}'), '') <> ''
           OR COALESCE(btrim(r.payload #>> '{incident,description}'), '') <> '')
    ORDER BY v.id;
$$;

REVOKE ALL ON FUNCTION
    public.refresh_revision_embedding(VARCHAR, BIGINT, extensions.vector),
    public.list_revisions_missing_embeddings(VARCHAR)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.refresh_revision_embedding(VARCHAR, BIGINT, extensions.vector),
    public.list_revisions_missing_embeddings(VARCHAR)
TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;

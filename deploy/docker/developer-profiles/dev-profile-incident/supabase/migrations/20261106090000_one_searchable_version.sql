-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- One searchable version per incident, for both searches.
--
-- A video's searchable version is searchable_revision_id(video): the official revision, else the newest. Nothing stores
-- that id; it is derived on every read, so marking official, clearing official and saving a new version each move it with
-- no extra step. search_evidence_items already matched evidence_crops of that revision only. This file makes the summary
-- search do the same and closes the gaps around it:
--
-- 1. search_report_revisions matches only the searchable version, so one video returns at most one hit. p_min_similarity is kept.
-- 2. save_human_revision and save_human_revision_with_crops take p_embedding (the summary vector of incident.title plus
--    incident.description, embedded by the agent like an AI version's), so a human version is found by the summary search.
--    NULL stays allowed: a save whose embedding failed still succeeds, and step 3 repairs it. The old signatures are dropped,
--    because two overloads with a defaulted last argument make a PostgREST call ambiguous.
-- 3. A searchable version with no summary vector gets one later. report_revisions is append-only, so the guard gets a second
--    narrow exception beside app.r2_rename: inside set_revision_embedding (transaction-local flag app.revision_embedding) a
--    row may change its embedding column and no other, and only from NULL. A stored vector is never replaced.
--    set_revision_embedding refuses a version that is not the searchable one. list_revisions_missing_embeddings lists the
--    searchable versions that still need one (with the text to embed).
-- 4. repair_revision_crops stores a searchable version's crops only when it has none and is still the searchable version,
--    so the console's automatic repair never overwrites rows another console stored meanwhile (set_revision_crops replaces).
--
-- The file is safe to run again: functions are created with OR REPLACE, the old signatures dropped IF EXISTS.

BEGIN;

-- 1. search_report_revisions ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.search_report_revisions(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.0
)
RETURNS TABLE (
    revision_id BIGINT,
    video_id VARCHAR(20),
    revision_no INTEGER,
    kind VARCHAR(8),
    model_run_id VARCHAR(20),
    title TEXT,
    description TEXT,
    incident_type VARCHAR(64),
    severity_level INTEGER,
    start_seconds INTEGER,
    end_seconds INTEGER,
    similarity_score DOUBLE PRECISION
)
LANGUAGE plpgsql SECURITY INVOKER STABLE SET search_path = ''
AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.id,
        r.video_id,
        r.revision_no,
        r.kind,
        r.model_run_id,
        r.payload #>> '{incident,title}',
        r.payload #>> '{incident,description}',
        r.incident_type,
        r.severity_level,
        r.start_seconds,
        r.end_seconds,
        (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION
    FROM public.report_revisions AS r
    WHERE r.embedding IS NOT NULL
      AND r.id = public.searchable_revision_id(r.video_id)
      AND (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity
    ORDER BY r.embedding OPERATOR(extensions.<=>) p_query_embedding ASC
    LIMIT p_top_k;
END;
$$;

-- 2. save_human_revision(_with_crops) with p_embedding -------------------------------------------
DROP FUNCTION IF EXISTS public.save_human_revision_with_crops(
    VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB);
DROP FUNCTION IF EXISTS public.save_human_revision(
    VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER);

CREATE OR REPLACE FUNCTION public.save_human_revision(
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
    p_embedding extensions.vector(1024) DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_parent public.report_revisions;
    v_by TEXT := btrim(COALESCE(p_created_by, ''));
    v_row public.report_revisions;
BEGIN
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Video not found: %', p_video_id USING ERRCODE = 'P0001';
    END IF;
    IF p_parent_id IS NULL THEN
        RAISE EXCEPTION 'A parent revision is required' USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_parent
    FROM public.report_revisions
    WHERE id = p_parent_id AND video_id = p_video_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Revision not found for this video: %', p_parent_id USING ERRCODE = 'P0001';
    END IF;
    IF v_by = '' OR length(v_by) > 256 THEN
        RAISE EXCEPTION 'A reviewer name of 1 to 256 characters is required' USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
        OR jsonb_typeof(p_payload -> 'incident') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'The report payload must be an object with an incident' USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(p_evidence) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The evidence must be a list' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.report_revisions (
        video_id, revision_no, kind, model_run_id, parent_id, payload, evidence,
        incident_type, severity_level, start_seconds, end_seconds, created_by, note, embedding
    )
    SELECT
        p_video_id,
        COALESCE(MAX(r.revision_no), 0) + 1,
        'human',
        v_parent.model_run_id,
        v_parent.id,
        p_payload,
        p_evidence,
        p_incident_type,
        p_severity_level,
        p_start_seconds,
        p_end_seconds,
        v_by,
        NULLIF(btrim(COALESCE(p_note, '')), ''),
        p_embedding
    FROM public.report_revisions AS r
    WHERE r.video_id = p_video_id
    RETURNING * INTO v_row;

    RETURN jsonb_build_object(
        'revisionId', v_row.id,
        'revisionNo', v_row.revision_no,
        'videoId', v_row.video_id,
        'kind', v_row.kind,
        'parentId', v_row.parent_id,
        'modelRunId', v_row.model_run_id,
        'createdBy', v_row.created_by,
        'createdAt', v_row.created_at,
        'note', v_row.note
    );
END;
$$;

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
    p_crops JSONB DEFAULT '[]'::JSONB,
    p_embedding extensions.vector(1024) DEFAULT NULL
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
        p_incident_type, p_severity_level, p_start_seconds, p_end_seconds, p_embedding);
    v_revision := (v_saved ->> 'revisionId')::BIGINT;

    -- save_human_revision locked the video row, so this read cannot race another save or official change.
    SELECT v.official_revision_id INTO v_official FROM public.videos AS v WHERE v.id = p_video_id;
    IF v_official IS NULL THEN
        v_crops := public.replace_video_crops(p_video_id, v_revision, p_crops);
    END IF;

    RETURN v_saved || jsonb_build_object('crops', v_crops);
END;
$$;

-- 3. The embedding exception, set_revision_embedding, list_revisions_missing_embeddings ------------
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
    -- set_revision_embedding may fill a missing summary vector; it never replaces one, and no other column changes.
    IF TG_OP = 'UPDATE'
       AND pg_catalog.current_setting('app.revision_embedding', true) = 'on'
       AND OLD.embedding IS NULL
       AND NEW.embedding IS NOT NULL
       AND pg_catalog.to_jsonb(NEW) - 'embedding' = pg_catalog.to_jsonb(OLD) - 'embedding' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'report_revisions is append-only' USING ERRCODE = 'P0001';
END;
$$;

-- Returns true when the vector was stored; false when the version already has one.
CREATE OR REPLACE FUNCTION public.set_revision_embedding(
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

    PERFORM pg_catalog.set_config('app.revision_embedding', 'on', true);
    UPDATE public.report_revisions AS r
    SET embedding = p_embedding
    WHERE r.id = p_revision_id AND r.video_id = p_video_id AND r.embedding IS NULL;
    GET DIAGNOSTICS v_changed = ROW_COUNT;
    PERFORM pg_catalog.set_config('app.revision_embedding', 'off', true);
    RETURN v_changed > 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.list_revisions_missing_embeddings(p_video_id VARCHAR DEFAULT NULL)
RETURNS TABLE (video_id VARCHAR(20), revision_id BIGINT, title TEXT, description TEXT)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
    SELECT v.id, r.id, r.payload #>> '{incident,title}', r.payload #>> '{incident,description}'
    FROM public.videos AS v
    JOIN public.report_revisions AS r ON r.id = public.searchable_revision_id(v.id)
    WHERE (p_video_id IS NULL OR v.id = p_video_id)
      AND r.embedding IS NULL
      AND (COALESCE(btrim(r.payload #>> '{incident,title}'), '') <> ''
           OR COALESCE(btrim(r.payload #>> '{incident,description}'), '') <> '')
    ORDER BY v.id;
$$;

-- 4. repair_revision_crops ------------------------------------------------------------------------
-- Returns the number of crop rows stored, or NULL when nothing was written because the revision is no longer the
-- video's searchable one, or the video already has crop rows for it.
CREATE OR REPLACE FUNCTION public.repair_revision_crops(
    p_video_id VARCHAR,
    p_revision_id BIGINT,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF p_revision_id IS NULL OR p_revision_id IS DISTINCT FROM public.searchable_revision_id(p_video_id) THEN
        RETURN NULL;
    END IF;
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM public.evidence_crops AS ec WHERE ec.revision_id = p_revision_id) THEN
        RETURN NULL;
    END IF;
    RETURN public.replace_video_crops(p_video_id, p_revision_id, p_crops);
END;
$$;

-- Security: service role only, exactly like the other write functions.
REVOKE ALL ON FUNCTION
    public.save_human_revision(VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, extensions.vector),
    public.save_human_revision_with_crops(
        VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB, extensions.vector),
    public.set_revision_embedding(VARCHAR, BIGINT, extensions.vector),
    public.list_revisions_missing_embeddings(VARCHAR),
    public.repair_revision_crops(VARCHAR, BIGINT, JSONB),
    public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.save_human_revision(VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, extensions.vector),
    public.save_human_revision_with_crops(
        VARCHAR, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB, extensions.vector),
    public.set_revision_embedding(VARCHAR, BIGINT, extensions.vector),
    public.list_revisions_missing_embeddings(VARCHAR),
    public.repair_revision_crops(VARCHAR, BIGINT, JSONB),
    public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
TO service_role;

-- PostgREST caches function signatures; reload so the new ones are callable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

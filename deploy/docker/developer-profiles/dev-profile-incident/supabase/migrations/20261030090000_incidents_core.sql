-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- DB core migration for mvp3: incidents root table, real-name video ids, readable model-run ids.
--
-- Applied to an empty database (new mvp3 project); no back-fill is needed.
-- Changes:
--   1. Widen videos.id, model_runs.id and the FK columns that reference them to TEXT,
--      so real file names and readable run ids (<subject>@<UTC timestamp>) fit.
--   2. Create the incidents root table: id (identity), official_revision_id, official_since,
--      created_at. The official pointer moves here from videos.
--   3. Add videos.incident_id NOT NULL (FK incidents, cascade on delete) and
--      videos.recorded_at (optional timestamp from file metadata).
--   4. Drop videos.official_revision_id and videos.official_since (moved to incidents).
--   5. Drop functions that read or write the removed columns; they are rewritten in P3.1-P3.7.
--
-- The chain remains referentially valid after this migration alone.
-- Safe to run once; designed for an empty schema.

BEGIN;

-- 1. Drop FK constraints that span columns whose types are changing --------------------------------

ALTER TABLE public.videos
    DROP CONSTRAINT IF EXISTS videos_official_revision_fkey;

ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_video_id_fkey;

ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_parent_fkey;

ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_model_run_id_fkey;

-- 2. Widen ids to unrestricted TEXT ---------------------------------------------------------------

ALTER TABLE public.videos          ALTER COLUMN id            TYPE TEXT;
ALTER TABLE public.report_revisions ALTER COLUMN video_id     TYPE TEXT;
ALTER TABLE public.model_runs      ALTER COLUMN id            TYPE TEXT;
ALTER TABLE public.report_revisions ALTER COLUMN model_run_id TYPE TEXT;

-- 3. Re-add the FK constraints on the widened types -----------------------------------------------

ALTER TABLE public.report_revisions
    ADD CONSTRAINT report_revisions_video_id_fkey
    FOREIGN KEY (video_id) REFERENCES public.videos(id) ON DELETE CASCADE;

ALTER TABLE public.report_revisions
    ADD CONSTRAINT report_revisions_parent_fkey
    FOREIGN KEY (video_id, parent_id) REFERENCES public.report_revisions(video_id, id);

ALTER TABLE public.report_revisions
    ADD CONSTRAINT report_revisions_model_run_id_fkey
    FOREIGN KEY (model_run_id) REFERENCES public.model_runs(id);

-- 4. Create the incidents root table --------------------------------------------------------------

CREATE TABLE public.incidents (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    official_revision_id BIGINT,
    official_since TIMESTAMP WITHOUT TIME ZONE,
    created_at     TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

ALTER TABLE public.incidents ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.incidents FROM anon, authenticated;
GRANT  ALL  ON TABLE public.incidents TO   service_role;

-- The identity sequence must also be service-role only.
DO $$
DECLARE seq TEXT;
BEGIN
    seq := pg_get_serial_sequence('public.incidents', 'id');
    IF seq IS NOT NULL THEN
        EXECUTE 'REVOKE ALL ON SEQUENCE ' || seq || ' FROM anon, authenticated';
        EXECUTE 'GRANT  ALL  ON SEQUENCE ' || seq || ' TO   service_role';
    END IF;
END;
$$;

-- 5. Update videos -------------------------------------------------------------------------------

-- Remove the official pointer (it moves to incidents).
ALTER TABLE public.videos DROP COLUMN IF EXISTS official_revision_id;
ALTER TABLE public.videos DROP COLUMN IF EXISTS official_since;

-- Each video belongs to exactly one incident.
-- The database is empty, so a NOT NULL column with no default is valid.
ALTER TABLE public.videos
    ADD COLUMN incident_id BIGINT NOT NULL
    REFERENCES public.incidents(id) ON DELETE CASCADE;

-- Optional recording timestamp read from file metadata.
ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP WITH TIME ZONE;

-- 6. Wire incidents.official_revision_id → report_revisions(id) ---------------------------------

ALTER TABLE public.incidents
    ADD CONSTRAINT incidents_official_revision_fkey
    FOREIGN KEY (official_revision_id) REFERENCES public.report_revisions(id);

-- 7. Drop functions that referenced the removed columns ------------------------------------------
-- They are rewritten from scratch in P3.1-P3.7 against the new schema.

DO $$
DECLARE rec RECORD;
BEGIN
    FOR rec IN
        SELECT p.oid::regprocedure::TEXT AS sig
        FROM   pg_proc p
        JOIN   pg_namespace n ON n.oid = p.pronamespace
        WHERE  n.nspname = 'public'
          AND  p.proname IN (
               'set_official_revision',
               'searchable_revision_id',
               'replace_video_crops',
               'set_revision_crops',
               'search_evidence_items',
               'list_incident_report_summaries',
               'get_incident_dashboard',
               'save_human_revision_with_crops'
          )
    LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || rec.sig;
    END LOOP;
END;
$$;

-- 8. Update functions whose declared signatures used VARCHAR(20) for ids that are now TEXT ---------
-- search_report_revisions declares video_id and model_run_id in its RETURNS TABLE; the RETURN QUERY
-- body now returns TEXT values, so the declared types must match.
-- PostgreSQL requires DROP before CREATE OR REPLACE when the return type changes.

DROP FUNCTION IF EXISTS public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION);

CREATE OR REPLACE FUNCTION public.search_report_revisions(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.0
)
RETURNS TABLE (
    revision_id BIGINT,
    video_id TEXT,
    revision_no INTEGER,
    kind VARCHAR(8),
    model_run_id TEXT,
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
      AND (1.0 - (r.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity
    ORDER BY r.embedding OPERATOR(extensions.<=>) p_query_embedding ASC
    LIMIT p_top_k;
END;
$$;

REVOKE ALL ON FUNCTION public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_report_revisions(extensions.vector, INTEGER, DOUBLE PRECISION)
    TO service_role;

-- save_human_revision: parameter type VARCHAR is assignment-compatible with TEXT column values,
-- so the function body works unchanged; no recreation needed.

NOTIFY pgrst, 'reload schema';

COMMIT;

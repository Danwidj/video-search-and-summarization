-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Background analysis jobs: the console's queue of uploaded videos waiting for analysis.
--
-- The browser uploads and converts a file, then enqueues one analysis_jobs row for it. A loop inside
-- the console's Node process claims one queued job at a time, runs the same analysis as
-- POST /api/analysis, heartbeats while it runs and stores done (with the new video and revision) or
-- failed (with the reason). Progress lives here, so closing the tab loses nothing once a file is
-- queued.
--
-- Every state change goes through a function so each one uses the database clock (the stale rule
-- compares heartbeat_at with now(), whichever machine runs the console):
--   claim_analysis_job(p_stale_seconds)  first recovers stale running jobs (back to queued after the
--                                        first stale run, failed after the second), then claims the
--                                        oldest queued job (FOR UPDATE SKIP LOCKED, so two loops never
--                                        claim the same job)
--   touch_analysis_job(p_id, p_attempt)  heartbeat; false when the claim is no longer this runner's
--   finish_analysis_job(...)             done or failed, only for the claim that is still running
--   retry_analysis_job(p_id)             failed or cancelled back to queued, attempts reset
--   cancel_analysis_job(p_id)            queued to cancelled
-- p_attempt is the attempts value a claim returned: it names one claim, so a runner whose job was
-- recovered as stale and claimed again cannot overwrite the newer claim.
--
-- Additive only: one new table and its functions; nothing existing changes. Safe to run again
-- (IF NOT EXISTS, CREATE OR REPLACE). Timestamps are naive UTC like the rest of the schema.

BEGIN;

CREATE TABLE IF NOT EXISTS public.analysis_jobs (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    file_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    model VARCHAR(128),
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    started_at TIMESTAMP WITHOUT TIME ZONE,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    heartbeat_at TIMESTAMP WITHOUT TIME ZONE,
    video_id VARCHAR(20),
    revision_id BIGINT,
    CONSTRAINT analysis_jobs_pkey PRIMARY KEY (id),
    CONSTRAINT analysis_jobs_status_check CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    CONSTRAINT analysis_jobs_attempts_check CHECK (attempts >= 0),
    -- Deleting a video or its revisions keeps the job as history, without the link (so a done job's
    -- video_id and revision_id may be NULL later; finish_analysis_job requires them when it sets done).
    CONSTRAINT analysis_jobs_video_id_fkey FOREIGN KEY (video_id) REFERENCES public.videos (id) ON DELETE SET NULL,
    CONSTRAINT analysis_jobs_revision_id_fkey FOREIGN KEY (revision_id) REFERENCES public.report_revisions (id) ON DELETE SET NULL
);
-- The claim reads the oldest queued job; the recovery reads running jobs.
CREATE INDEX IF NOT EXISTS analysis_jobs_status_created_idx ON public.analysis_jobs USING btree (status, created_at, id);
CREATE INDEX IF NOT EXISTS analysis_jobs_created_idx ON public.analysis_jobs USING btree (created_at DESC);

CREATE OR REPLACE FUNCTION public.claim_analysis_job(p_stale_seconds INTEGER DEFAULT 180)
RETURNS SETOF public.analysis_jobs
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMP WITHOUT TIME ZONE := pg_catalog.now() AT TIME ZONE 'utc';
BEGIN
    IF p_stale_seconds IS NULL OR p_stale_seconds < 1 THEN
        RAISE EXCEPTION 'p_stale_seconds must be at least 1' USING ERRCODE = '22023';
    END IF;

    -- A running job nobody has heartbeated for p_stale_seconds lost its runner (the console stopped).
    -- Its first stale run sends it back to the queue; a second fails it, so nothing hangs forever.
    UPDATE public.analysis_jobs AS j
    SET status = CASE WHEN j.attempts >= 2 THEN 'failed' ELSE 'queued' END,
        error = CASE WHEN j.attempts >= 2
                     THEN 'The console stopped twice while analysing this video'
                     ELSE NULL END,
        finished_at = CASE WHEN j.attempts >= 2 THEN v_now ELSE NULL END,
        heartbeat_at = NULL
    WHERE j.status = 'running'
      AND COALESCE(j.heartbeat_at, j.started_at, j.created_at) < v_now - pg_catalog.make_interval(secs => p_stale_seconds);

    RETURN QUERY
    UPDATE public.analysis_jobs AS j
    SET status = 'running', attempts = j.attempts + 1, started_at = v_now, heartbeat_at = v_now,
        finished_at = NULL, error = NULL
    WHERE j.id = (
        SELECT q.id FROM public.analysis_jobs AS q
        WHERE q.status = 'queued'
        ORDER BY q.created_at, q.id
        LIMIT 1
        FOR UPDATE SKIP LOCKED)
    RETURNING j.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.touch_analysis_job(p_id BIGINT, p_attempt INTEGER)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    UPDATE public.analysis_jobs AS j
    SET heartbeat_at = pg_catalog.now() AT TIME ZONE 'utc'
    WHERE j.id = p_id AND j.status = 'running' AND j.attempts = p_attempt;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.finish_analysis_job(
    p_id BIGINT,
    p_attempt INTEGER,
    p_status TEXT,
    p_error TEXT DEFAULT NULL,
    p_video_id VARCHAR DEFAULT NULL,
    p_revision_id BIGINT DEFAULT NULL
) RETURNS SETOF public.analysis_jobs
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    IF p_status NOT IN ('done', 'failed') THEN
        RAISE EXCEPTION 'p_status must be done or failed' USING ERRCODE = '22023';
    END IF;
    IF p_status = 'done' AND (p_video_id IS NULL OR p_revision_id IS NULL) THEN
        RAISE EXCEPTION 'a done job needs its video and revision' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE public.analysis_jobs AS j
    SET status = p_status,
        error = CASE WHEN p_status = 'failed' THEN COALESCE(NULLIF(pg_catalog.btrim(p_error), ''), 'The analysis failed') END,
        video_id = CASE WHEN p_status = 'done' THEN p_video_id END,
        revision_id = CASE WHEN p_status = 'done' THEN p_revision_id END,
        finished_at = pg_catalog.now() AT TIME ZONE 'utc',
        heartbeat_at = NULL
    WHERE j.id = p_id AND j.status = 'running' AND j.attempts = p_attempt
    RETURNING j.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.retry_analysis_job(p_id BIGINT)
RETURNS SETOF public.analysis_jobs
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.analysis_jobs AS j
    SET status = 'queued', attempts = 0, error = NULL, started_at = NULL, finished_at = NULL, heartbeat_at = NULL,
        video_id = NULL, revision_id = NULL
    WHERE j.id = p_id AND j.status IN ('failed', 'cancelled')
    RETURNING j.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.cancel_analysis_job(p_id BIGINT)
RETURNS SETOF public.analysis_jobs
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.analysis_jobs AS j
    SET status = 'cancelled', finished_at = pg_catalog.now() AT TIME ZONE 'utc'
    WHERE j.id = p_id AND j.status = 'queued'
    RETURNING j.*;
END;
$$;

-- Security: service role only, exactly like the rest of the schema.
ALTER TABLE public.analysis_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.analysis_jobs FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.analysis_jobs TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
REVOKE ALL ON FUNCTION public.claim_analysis_job(INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.touch_analysis_job(BIGINT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finish_analysis_job(BIGINT, INTEGER, TEXT, TEXT, VARCHAR, BIGINT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retry_analysis_job(BIGINT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cancel_analysis_job(BIGINT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_analysis_job(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.touch_analysis_job(BIGINT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_analysis_job(BIGINT, INTEGER, TEXT, TEXT, VARCHAR, BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION public.retry_analysis_job(BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION public.cancel_analysis_job(BIGINT) TO service_role;

-- PostgREST caches the schema; reload so the table and functions are reachable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

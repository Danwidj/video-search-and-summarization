-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Privacy blur: a per-video toggle, and analysis jobs that re-analyse an existing video.
--
-- videos.blur_faces is the reviewer's toggle on the report page. When it is on, every analysis of the video asks the
-- agent for blur_faces, so the heads of the people in its stored evidence frames and crops are pixelated, and the
-- console blurs the same heads in each evidence clip it cuts (cached under a separate -clip-blur.mp4 key). Switching
-- the toggle queues one re-analysis job for the video; the new run's media replaces what the report shows, and the
-- older runs stay in the version history as they were.
--
-- analysis_jobs.reanalyse_video_id names the existing video a job re-analyses (NULL: the job analyses a new upload,
-- as before), and analysis_jobs.blur_faces is what that job asks the agent for. Deleting the video deletes its
-- pending and finished re-analysis jobs, so a queued job never analyses a video that is gone.
--
-- The queue is shared by every console pointed at finals, and a console built before this migration reads neither
-- column: it would run a re-analysis job as a new upload (a second video row on the same R2 object, unblurred). So
-- the claim moves into claim_queued_analysis_job(p_stale_seconds, p_uploads_only), which the console now calls with
-- p_uploads_only false, and claim_analysis_job(p_stale_seconds), the function older consoles call, claims upload jobs
-- only. Nothing else about the claim changes (stale recovery first, oldest queued job, FOR UPDATE SKIP LOCKED).
--
-- Additive for existing rows: three columns with defaults, one new function, and claim_analysis_job behaves as before
-- for every job that is not a re-analysis. Safe to run again (IF NOT EXISTS, CREATE OR REPLACE).

BEGIN;

ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS blur_faces BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE public.analysis_jobs
    ADD COLUMN IF NOT EXISTS reanalyse_video_id VARCHAR(20)
        CONSTRAINT analysis_jobs_reanalyse_video_id_fkey REFERENCES public.videos (id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS blur_faces BOOLEAN NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION public.claim_queued_analysis_job(p_stale_seconds INTEGER, p_uploads_only BOOLEAN)
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
          AND (q.reanalyse_video_id IS NULL OR NOT COALESCE(p_uploads_only, true))
        ORDER BY q.created_at, q.id
        LIMIT 1
        FOR UPDATE SKIP LOCKED)
    RETURNING j.*;
END;
$$;

-- What consoles built before this migration call: upload jobs only (they cannot run a re-analysis).
CREATE OR REPLACE FUNCTION public.claim_analysis_job(p_stale_seconds INTEGER DEFAULT 180)
RETURNS SETOF public.analysis_jobs
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    RETURN QUERY SELECT * FROM public.claim_queued_analysis_job(p_stale_seconds, true);
END;
$$;

-- Security: service role only, exactly like the rest of the schema.
REVOKE ALL ON FUNCTION public.claim_queued_analysis_job(INTEGER, BOOLEAN) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_queued_analysis_job(INTEGER, BOOLEAN) TO service_role;

-- PostgREST caches the schema; reload so the new columns and function are reachable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

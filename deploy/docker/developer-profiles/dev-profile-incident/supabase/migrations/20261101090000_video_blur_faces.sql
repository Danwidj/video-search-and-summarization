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
-- Additive only: three columns with defaults; no row, function or grant changes. Safe to run again (IF NOT EXISTS).

BEGIN;

ALTER TABLE public.videos
    ADD COLUMN IF NOT EXISTS blur_faces BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE public.analysis_jobs
    ADD COLUMN IF NOT EXISTS reanalyse_video_id VARCHAR(20)
        CONSTRAINT analysis_jobs_reanalyse_video_id_fkey REFERENCES public.videos (id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS blur_faces BOOLEAN NOT NULL DEFAULT false;

-- PostgREST caches the schema; reload so the new columns are reachable at once.
NOTIFY pgrst, 'reload schema';

COMMIT;

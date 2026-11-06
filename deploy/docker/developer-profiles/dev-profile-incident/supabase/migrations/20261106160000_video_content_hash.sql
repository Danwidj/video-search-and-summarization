-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Block a repeat upload by file content.
--
-- videos.content_sha256 is the SHA-256 (lower-case hex) of the file as the reviewer uploaded it, before any
-- conversion to H.264. A unique index makes a second video with the same content impossible. The same
-- hash is carried by analysis_jobs while a job is queued or running (the video row only exists once the job
-- starts), and a second queued or running job with the same hash is refused, so two uploads of one file in
-- the same second still end with one video and one analysis job.
--
-- Additive only: two nullable columns and three indexes. Rows without a hash (older videos until the backfill
-- script supabase/r2/backfill_content_hash.py has run, and the seeded eval clips) are never constrained.
-- Safe to run again (IF NOT EXISTS). The unique index on videos fails to build only if two existing rows
-- already share a hash, and none has one yet.

BEGIN;

ALTER TABLE public.videos ADD COLUMN IF NOT EXISTS content_sha256 CHAR(64);
ALTER TABLE public.analysis_jobs ADD COLUMN IF NOT EXISTS content_sha256 CHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint WHERE conname = 'videos_content_sha256_check') THEN
        ALTER TABLE public.videos
            ADD CONSTRAINT videos_content_sha256_check CHECK (content_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint WHERE conname = 'analysis_jobs_content_sha256_check') THEN
        ALTER TABLE public.analysis_jobs
            ADD CONSTRAINT analysis_jobs_content_sha256_check CHECK (content_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS videos_content_sha256_key
    ON public.videos USING btree (content_sha256) WHERE content_sha256 IS NOT NULL;

-- Only queued and running jobs: once the job runs its video row holds the hash, and a failed or cancelled
-- job must not block uploading the file again.
CREATE UNIQUE INDEX IF NOT EXISTS analysis_jobs_active_content_sha256_key
    ON public.analysis_jobs USING btree (content_sha256)
    WHERE content_sha256 IS NOT NULL AND status IN ('queued', 'running');

COMMIT;

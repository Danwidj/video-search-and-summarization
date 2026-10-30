-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Revisions per incident for mvp3.
--
-- Applied to an empty database after 20261030090000_incidents_core.sql; no back-fill is needed.
-- Changes:
--   1. report_revisions belongs to an incident (incident_id, ON DELETE CASCADE) instead of a video.
--      video_id and every constraint built on it are removed.
--   2. report_revisions.video_names TEXT[] stores the real names of the videos a revision covers.
--      The append-only trigger already refuses every UPDATE, so coverage is immutable after insert.
--   3. (incident_id, revision_no) is unique; the parent link stays inside one incident.
--   4. incidents.official_revision_id must name a revision of the same incident (composite key).
--   5. Drop the functions that still read report_revisions.video_id; P3.3, P3.4 and P3.7 rewrite them.
--
-- The AI-needs-a-run and human-needs-a-creator checks and the append-only trigger are unchanged.
-- The trigger's depth > 1 exception now lets revisions go only with their incident (ON DELETE CASCADE).

BEGIN;

-- 1. Drop constraints and functions that depend on report_revisions.video_id --------------------------

DO $$
DECLARE rec RECORD;
BEGIN
    FOR rec IN
        SELECT p.oid::regprocedure::TEXT AS sig
        FROM   pg_proc p
        JOIN   pg_namespace n ON n.oid = p.pronamespace
        WHERE  n.nspname = 'public'
          AND  p.proname IN ('save_human_revision', 'apply_r2_rename', 'search_report_revisions')
    LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || rec.sig;
    END LOOP;
END;
$$;

ALTER TABLE public.incidents
    DROP CONSTRAINT IF EXISTS incidents_official_revision_fkey;

ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_parent_fkey;
ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_video_id_fkey;
ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_video_rev_key;
ALTER TABLE public.report_revisions
    DROP CONSTRAINT IF EXISTS report_revisions_video_id_id_key;

-- 2. Move revisions from the video to the incident ------------------------------------------------
-- The database is empty, so NOT NULL columns without a back-fill are valid.

DROP INDEX IF EXISTS public.report_revisions_video_idx;
ALTER TABLE public.report_revisions DROP COLUMN video_id;

ALTER TABLE public.report_revisions
    ADD COLUMN incident_id BIGINT NOT NULL
    REFERENCES public.incidents (id) ON DELETE CASCADE;

ALTER TABLE public.report_revisions
    ADD COLUMN video_names TEXT[] NOT NULL DEFAULT '{}'::TEXT[];

-- 3. Keys: revision numbers are per incident; the parent stays in the same incident -----------------

ALTER TABLE public.report_revisions
    ADD CONSTRAINT report_revisions_incident_rev_key UNIQUE (incident_id, revision_no);
ALTER TABLE public.report_revisions
    ADD CONSTRAINT report_revisions_incident_id_id_key UNIQUE (incident_id, id);
ALTER TABLE public.report_revisions
    ADD CONSTRAINT report_revisions_parent_fkey FOREIGN KEY (incident_id, parent_id)
    REFERENCES public.report_revisions (incident_id, id);

CREATE INDEX report_revisions_incident_idx
    ON public.report_revisions USING btree (incident_id, revision_no DESC);

-- 4. The official revision must belong to the same incident --------------------------------------
-- NULL official_revision_id means no official revision (MATCH SIMPLE skips the check).

ALTER TABLE public.incidents
    ADD CONSTRAINT incidents_official_revision_fkey FOREIGN KEY (id, official_revision_id)
    REFERENCES public.report_revisions (incident_id, id);

NOTIFY pgrst, 'reload schema';

COMMIT;

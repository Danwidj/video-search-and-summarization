-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- mvp3 storage for per-video analyses, incident match suggestions and the crop source video.
--
-- Applied to an empty database (new mvp3 project); no back-fill is needed.
-- Changes:
--   1. video_analyses: one row per analysis run of a video; the latest row per video wins.
--      Deleted with its video.
--   2. incident_match_suggestions: one row per unordered pair of incidents, never against itself.
--      Deleted with either incident.
--   3. evidence_crops.video_id: the source video of a crop, added to the primary key.
--      Deleted with its video.
-- Every new table has row level security on and is reachable by the service role only.

BEGIN;

-- 1. video_analyses ------------------------------------------------------------------------------
-- payload is the contract-valid report for one video, unchanged. The facet columns are plain copies
-- of payload fields (as on report_revisions). created_at is naive UTC.
CREATE TABLE public.video_analyses (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    video_id TEXT NOT NULL,
    model_run_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,
    incident_type VARCHAR(64),
    severity_level INTEGER,
    start_seconds INTEGER,
    end_seconds INTEGER,
    embedding extensions.vector(1024),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT video_analyses_pkey PRIMARY KEY (id),
    CONSTRAINT video_analyses_video_id_fkey FOREIGN KEY (video_id)
        REFERENCES public.videos (id) ON DELETE CASCADE,
    CONSTRAINT video_analyses_model_run_id_fkey FOREIGN KEY (model_run_id)
        REFERENCES public.model_runs (id)
);
-- Latest analysis per video: ORDER BY created_at DESC, id DESC LIMIT 1.
CREATE INDEX video_analyses_video_idx
    ON public.video_analyses USING btree (video_id, created_at DESC, id DESC);
CREATE INDEX video_analyses_model_run_idx
    ON public.video_analyses USING btree (model_run_id);

-- 2. incident_match_suggestions ------------------------------------------------------------------
-- The pair is unordered: (a, b) and (b, a) are the same pair, so the unique index is on the
-- least/greatest ids. Rejected pairs stay as rows so they are never suggested again.
CREATE TABLE public.incident_match_suggestions (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    incident_a_id BIGINT NOT NULL,
    incident_b_id BIGINT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    reasons JSONB NOT NULL DEFAULT '[]'::JSONB,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    decided_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT incident_match_suggestions_pkey PRIMARY KEY (id),
    CONSTRAINT incident_match_suggestions_a_fkey FOREIGN KEY (incident_a_id)
        REFERENCES public.incidents (id) ON DELETE CASCADE,
    CONSTRAINT incident_match_suggestions_b_fkey FOREIGN KEY (incident_b_id)
        REFERENCES public.incidents (id) ON DELETE CASCADE,
    CONSTRAINT incident_match_suggestions_distinct_check CHECK (incident_a_id <> incident_b_id),
    CONSTRAINT incident_match_suggestions_score_check CHECK (score >= 0 AND score <= 1),
    CONSTRAINT incident_match_suggestions_status_check CHECK (status IN ('pending', 'accepted', 'rejected'))
);
CREATE UNIQUE INDEX incident_match_suggestions_pair_key
    ON public.incident_match_suggestions (LEAST(incident_a_id, incident_b_id), GREATEST(incident_a_id, incident_b_id));
CREATE INDEX incident_match_suggestions_b_idx
    ON public.incident_match_suggestions USING btree (incident_b_id);
CREATE INDEX incident_match_suggestions_status_idx
    ON public.incident_match_suggestions USING btree (status);

-- 3. evidence_crops.video_id ---------------------------------------------------------------------
-- The database is empty, so a NOT NULL column with no default is valid.
ALTER TABLE public.evidence_crops ADD COLUMN video_id TEXT NOT NULL;
ALTER TABLE public.evidence_crops
    ADD CONSTRAINT evidence_crops_video_id_fkey FOREIGN KEY (video_id)
    REFERENCES public.videos (id) ON DELETE CASCADE;
ALTER TABLE public.evidence_crops DROP CONSTRAINT evidence_crops_pkey;
ALTER TABLE public.evidence_crops
    ADD CONSTRAINT evidence_crops_pkey PRIMARY KEY (revision_id, video_id, item_type, item_id);
CREATE INDEX evidence_crops_video_idx ON public.evidence_crops USING btree (video_id);

-- 4. Access: service role only -------------------------------------------------------------------
ALTER TABLE public.video_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_match_suggestions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.video_analyses, public.incident_match_suggestions FROM PUBLIC, anon, authenticated;
GRANT  ALL ON TABLE public.video_analyses, public.incident_match_suggestions TO service_role;

DO $$
DECLARE seq TEXT;
BEGIN
    FOREACH seq IN ARRAY ARRAY[
        pg_get_serial_sequence('public.video_analyses', 'id'),
        pg_get_serial_sequence('public.incident_match_suggestions', 'id')
    ]
    LOOP
        EXECUTE 'REVOKE ALL ON SEQUENCE ' || seq || ' FROM PUBLIC, anon, authenticated';
        EXECUTE 'GRANT  ALL ON SEQUENCE ' || seq || ' TO   service_role';
    END LOOP;
END;
$$;

NOTIFY pgrst, 'reload schema';

COMMIT;

-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Versioned report snapshots: replace the relational report model with append-only revisions.
--
-- The captain applied this schema by hand to the live finals database on 2026-10-22, so every
-- statement here must also be safe on a database that already has it: tables are created with
-- IF NOT EXISTS, columns are added with IF NOT EXISTS, and constraints are added only when the
-- catalog does not have them. A fresh rebuild applies the baseline first, so the obsolete tables
-- and functions the baseline still creates are dropped here.
--
-- After this migration finals holds exactly six tables: videos, queries, model_runs,
-- report_revisions, evidence_crops and query_results. report_revisions is the source of truth for
-- every report; videos.official_revision_id names the one official revision per video. The
-- functions that read and write revisions live in 20261023000100_report_revisions_functions.sql.

BEGIN;

-- 1. Retire the relational report functions ------------------------------------------------------
-- Their bodies read tables dropped below, and the new functions (next migration) replace the
-- three reader RPCs.
DROP FUNCTION IF EXISTS public.insert_incident(TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, INTEGER, DOUBLE PRECISION);
DROP FUNCTION IF EXISTS public.select_official_report(TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.clear_official_report(TEXT, TEXT);
DROP FUNCTION IF EXISTS public.create_human_report_from_ai(TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE);
DROP FUNCTION IF EXISTS public.save_human_report_edit(TEXT, TEXT, JSONB, TEXT);
DROP FUNCTION IF EXISTS public.apply_structured_report_edit(TEXT, TEXT, JSONB, TEXT);
DROP FUNCTION IF EXISTS public.set_review_status(TEXT, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.list_incident_report_summaries(
    INTEGER, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE,
    TIME WITHOUT TIME ZONE, TIME WITHOUT TIME ZONE, TEXT[], TEXT[], TEXT[], INTEGER, TEXT, TEXT, TEXT[], TEXT, TEXT);
DROP FUNCTION IF EXISTS public.get_incident_dashboard(
    TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITHOUT TIME ZONE, TEXT, TEXT, INTEGER, INTEGER, TEXT);
DROP FUNCTION IF EXISTS public.search_evidence_items(
    extensions.vector, INTEGER, DOUBLE PRECISION, TEXT[], TEXT[], INTEGER, INTEGER);

-- 2. Drop the obsolete tables --------------------------------------------------------------------
-- CASCADE removes the effective_* views that hang off incidents. IF EXISTS keeps a rebuild from a
-- database where the drop already happened (the live finals database) working.
DROP TABLE IF EXISTS public.gt_assets CASCADE;
DROP TABLE IF EXISTS public.gt_instruments CASCADE;
DROP TABLE IF EXISTS public.gt_entities CASCADE;
DROP TABLE IF EXISTS public.gt_incidents CASCADE;
DROP TABLE IF EXISTS public.severity_eval_log CASCADE;
DROP TABLE IF EXISTS public.review_status CASCADE;
DROP TABLE IF EXISTS public.human_report_assets CASCADE;
DROP TABLE IF EXISTS public.human_report_instruments CASCADE;
DROP TABLE IF EXISTS public.human_report_entities CASCADE;
DROP TABLE IF EXISTS public.human_reports CASCADE;
DROP TABLE IF EXISTS public.assets CASCADE;
DROP TABLE IF EXISTS public.instruments CASCADE;
DROP TABLE IF EXISTS public.entities CASCADE;
DROP TABLE IF EXISTS public.reports CASCADE;
DROP TABLE IF EXISTS public.incidents CASCADE;

-- evidence_crops and query_results changed shape (revision_id instead of incident_id/model_run_id).
-- Drop the old shape only; on the live database they are already the new shape and their data must
-- survive.
DO $$
BEGIN
    IF to_regclass('public.evidence_crops') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'evidence_crops' AND column_name = 'revision_id'
    ) THEN
        DROP TABLE public.evidence_crops CASCADE;
    END IF;
    IF to_regclass('public.query_results') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'query_results' AND column_name = 'revision_id'
    ) THEN
        DROP TABLE public.query_results CASCADE;
    END IF;
END;
$$;

-- 3. videos --------------------------------------------------------------------------------------
-- The old official-run pointer and its provenance columns are gone. One composite FK replaces them
-- (added after report_revisions exists).
ALTER TABLE public.videos
    DROP COLUMN IF EXISTS selected_model_run_id,
    DROP COLUMN IF EXISTS selected_by,
    DROP COLUMN IF EXISTS selected_at;
ALTER TABLE public.videos ADD COLUMN IF NOT EXISTS official_revision_id BIGINT;

-- 4. report_revisions ----------------------------------------------------------------------------
-- Append-only snapshots. kind='ai' rows are written by the agent (model_run_id required);
-- kind='human' rows are written by save_human_revision (created_by required). parent_id links an
-- edit to the revision it was made from. payload is the full contract report; evidence is the list
-- of evidence items the revision uses (R2 keys and item details). The facet columns are plain
-- copies of payload fields, written by the writer so the library and dashboard can filter without
-- unpacking JSONB. created_at is naive UTC.
CREATE TABLE IF NOT EXISTS public.report_revisions (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    video_id VARCHAR(20) NOT NULL,
    revision_no INTEGER NOT NULL,
    kind VARCHAR(8) NOT NULL,
    model_run_id VARCHAR(20),
    parent_id BIGINT,
    payload JSONB NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,
    incident_type VARCHAR(64),
    severity_level INTEGER,
    start_seconds INTEGER,
    end_seconds INTEGER,
    created_by VARCHAR(256),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    note TEXT,
    CONSTRAINT report_revisions_pkey PRIMARY KEY (id),
    CONSTRAINT report_revisions_video_rev_key UNIQUE (video_id, revision_no),
    CONSTRAINT report_revisions_video_id_id_key UNIQUE (video_id, id),
    CONSTRAINT report_revisions_video_id_fkey FOREIGN KEY (video_id) REFERENCES public.videos (id) ON DELETE CASCADE,
    CONSTRAINT report_revisions_model_run_id_fkey FOREIGN KEY (model_run_id) REFERENCES public.model_runs (id),
    CONSTRAINT report_revisions_parent_fkey FOREIGN KEY (video_id, parent_id)
        REFERENCES public.report_revisions (video_id, id),
    CONSTRAINT report_revisions_kind_check CHECK (kind IN ('ai', 'human')),
    CONSTRAINT report_revisions_ai_run_check CHECK (kind <> 'ai' OR model_run_id IS NOT NULL),
    CONSTRAINT report_revisions_human_by_check CHECK (kind <> 'human' OR created_by IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS report_revisions_video_idx
    ON public.report_revisions USING btree (video_id, revision_no DESC);
CREATE INDEX IF NOT EXISTS report_revisions_type_idx
    ON public.report_revisions USING btree (incident_type);
CREATE INDEX IF NOT EXISTS report_revisions_severity_idx
    ON public.report_revisions USING btree (severity_level);

-- The unique pair is the target of the official pointer and the parent link. Add it if an existing
-- live table was created without the named constraint; the pair is already unique in that shape.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.report_revisions'::regclass
          AND conname = 'report_revisions_video_id_id_key'
    ) THEN
        ALTER TABLE public.report_revisions
            ADD CONSTRAINT report_revisions_video_id_id_key UNIQUE (video_id, id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.report_revisions'::regclass
          AND conname = 'report_revisions_parent_fkey'
    ) THEN
        ALTER TABLE public.report_revisions
            ADD CONSTRAINT report_revisions_parent_fkey FOREIGN KEY (video_id, parent_id)
            REFERENCES public.report_revisions (video_id, id);
    END IF;
END;
$$;

-- Append-only guard. The one exception is a row removed by the ON DELETE CASCADE of its video
-- (trigger depth > 1): without it a video that has any revision could never be deleted. A direct
-- UPDATE or DELETE of a revision is still refused.
CREATE OR REPLACE FUNCTION public.report_revisions_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'report_revisions is append-only' USING ERRCODE = 'P0001';
END;
$$;
DROP TRIGGER IF EXISTS report_revisions_no_update_delete ON public.report_revisions;
CREATE TRIGGER report_revisions_no_update_delete
    BEFORE UPDATE OR DELETE ON public.report_revisions
    FOR EACH ROW EXECUTE FUNCTION public.report_revisions_append_only();

-- 5. videos.official_revision_id ----------------------------------------------------------------
-- The composite key pins the official revision to the same video. NULL means no official revision.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.videos'::regclass AND conname = 'videos_official_revision_fkey'
    ) THEN
        ALTER TABLE public.videos
            ADD CONSTRAINT videos_official_revision_fkey
            FOREIGN KEY (id, official_revision_id)
            REFERENCES public.report_revisions (video_id, id);
    END IF;
END;
$$;

-- 6. evidence_crops ------------------------------------------------------------------------------
-- Searchable evidence of official revisions only. Rows are keyed by revision and replaced in the
-- same transaction that changes videos.official_revision_id (set_official_revision).
CREATE TABLE IF NOT EXISTS public.evidence_crops (
    revision_id BIGINT NOT NULL,
    item_type VARCHAR(16) NOT NULL,
    item_id VARCHAR(20) NOT NULL,
    item_name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    threat_level INTEGER,
    holder_entity_id VARCHAR(20),
    timestamp_seconds INTEGER NOT NULL,
    bounding_box INTEGER[4] NOT NULL, -- [ymin, xmin, ymax, xmax], normalised 0-1000
    image VARCHAR(1024) NOT NULL,     -- R2 key
    embedding extensions.vector(1024),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT evidence_crops_pkey PRIMARY KEY (revision_id, item_type, item_id),
    CONSTRAINT evidence_crops_revision_id_fkey FOREIGN KEY (revision_id)
        REFERENCES public.report_revisions (id) ON DELETE CASCADE,
    CONSTRAINT evidence_crops_item_type_check CHECK (item_type IN ('entity', 'instrument', 'asset'))
);
CREATE INDEX IF NOT EXISTS evidence_crops_embedding_hnsw_idx ON public.evidence_crops
    USING hnsw (embedding extensions.vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- 7. query_results -------------------------------------------------------------------------------
-- Search history. No foreign key to evidence_crops: un-marking or re-marking a revision keeps the
-- audit trail. It does reference the revision (CASCADE when the video is deleted).
CREATE TABLE IF NOT EXISTS public.query_results (
    id VARCHAR(36) NOT NULL,
    query_id VARCHAR(20) NOT NULL,
    revision_id BIGINT NOT NULL,
    item_type VARCHAR(16) NOT NULL,
    item_id VARCHAR(20) NOT NULL,
    rank INTEGER NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    critic_verdict VARCHAR(16) NOT NULL,
    critic_rationale TEXT,
    retrieved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT query_results_pkey PRIMARY KEY (id),
    CONSTRAINT query_results_query_id_fkey FOREIGN KEY (query_id) REFERENCES public.queries (id) ON DELETE CASCADE,
    CONSTRAINT query_results_revision_id_fkey FOREIGN KEY (revision_id)
        REFERENCES public.report_revisions (id) ON DELETE CASCADE,
    CONSTRAINT query_results_critic_verdict_check CHECK (critic_verdict IN ('confirmed', 'rejected', 'unverified')),
    CONSTRAINT query_results_item_type_check CHECK (item_type IN ('entity', 'instrument', 'asset'))
);
CREATE INDEX IF NOT EXISTS query_results_revision_item_idx
    ON public.query_results USING btree (revision_id, item_type, item_id);
CREATE INDEX IF NOT EXISTS query_results_query_rank_idx
    ON public.query_results USING btree (query_id, rank);

-- 8. Security ------------------------------------------------------------------------------------
-- Service-role only, exactly like the rest of the schema. The trigger function needs a fixed
-- search_path too (security_check.sql fails otherwise).
ALTER TABLE public.report_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_crops ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.query_results ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.report_revisions, public.evidence_crops, public.query_results
    FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.report_revisions, public.evidence_crops, public.query_results TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
REVOKE ALL ON FUNCTION public.report_revisions_append_only() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.report_revisions_append_only() TO service_role;

COMMIT;

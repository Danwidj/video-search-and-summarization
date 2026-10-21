-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Finals baseline: the whole incident schema for a new, empty Supabase project.
--
-- Midterm grew from tables that no migration created (incident-console/db.py metadata) plus 14
-- migrations, two of them never applied. This one file replaces that history for the finals
-- database. It builds:
--   1. the operational, evaluation and search tables exactly as they are on midterm (same columns,
--      types, precision, defaults, keys, foreign keys and indexes; verified against the live catalog
--      on 2026-10-20), minus the four legacy pre-v1 tables;
--   2. the reviewer ("human") version of a report next to the immutable AI version, and the
--      effective_* views every reader uses (human version if there is one, otherwise the AI one);
--   3. every function still called, with the superseded edit RPCs left out;
--   4. security from the start: RLS on every table, nothing for anon/authenticated/PUBLIC,
--      every function service_role-only, default privileges locked first.
--
-- Data is not created here; supabase/copy/copy_midterm_to_finals.py loads it. The midterm history
-- is archived, never to be pushed, in supabase/midterm/.

-- 0. Extensions --------------------------------------------------------------------------------
-- pgvector lives in the extensions schema (Supabase's recommended place), not in public, so none
-- of its functions become PostgREST RPCs.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- 1. Default privileges, before any object exists -----------------------------------------------
-- A new Supabase project grants anon and authenticated everything on objects postgres creates in
-- public. Turn that off first, so nothing created below is ever exposed, even for a moment.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role;

-- 2. Tables (as on midterm) ---------------------------------------------------------------------
-- Constraint names are midterm's: PostgREST embed hints name them (e.g. incidents_incident_id_fkey).
-- Timestamps are naive UTC (TIMESTAMP WITHOUT TIME ZONE), as everywhere in this schema.

-- Shared reference tables.
CREATE TABLE public.videos (
    id VARCHAR(20) NOT NULL,
    filepath VARCHAR(1024),
    uploaded_datetime TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    duration INTEGER,
    source VARCHAR(512),
    selected_model_run_id VARCHAR(20),
    selected_by VARCHAR(256),
    selected_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT videos_pkey PRIMARY KEY (id)
);

CREATE TABLE public.queries (
    id VARCHAR(20) NOT NULL,
    query_text TEXT NOT NULL,
    submitted_datetime TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT queries_pkey PRIMARY KEY (id)
);

CREATE TABLE public.model_runs (
    id VARCHAR(20) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    model_version VARCHAR(128),
    prompt_version VARCHAR(64),
    run_datetime TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    notes TEXT, -- immutable analysis-attempt record; never modified after it is written
    CONSTRAINT model_runs_pkey PRIMARY KEY (id)
);

-- Model output (the AI report). After the report split these rows are written once per run
-- (insert_incident and the item inserts) and never edited; reviewer changes go to human_*.
CREATE TABLE public.incidents (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    type VARCHAR(32),
    start_timestamp VARCHAR(32),
    end_timestamp VARCHAR(32),
    duration INTEGER,
    description TEXT,
    severity_level INTEGER,
    confidence_score DOUBLE PRECISION,
    CONSTRAINT incidents_pkey PRIMARY KEY (incident_id, model_run_id),
    CONSTRAINT incidents_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.videos (id) ON DELETE CASCADE,
    CONSTRAINT incidents_model_run_id_fkey FOREIGN KEY (model_run_id) REFERENCES public.model_runs (id) ON DELETE CASCADE
);

-- The video's official report (D6). Added after incidents because the two reference each other.
ALTER TABLE public.videos
    ADD CONSTRAINT videos_selected_run_fkey FOREIGN KEY (id, selected_model_run_id)
    REFERENCES public.incidents (incident_id, model_run_id) ON DELETE SET NULL (selected_model_run_id);
CREATE INDEX videos_selected_run_idx ON public.videos USING btree (id, selected_model_run_id)
    WHERE (selected_model_run_id IS NOT NULL);

CREATE TABLE public.reports (
    id VARCHAR(20) NOT NULL,
    incident_id VARCHAR(20) NOT NULL,
    query_id VARCHAR(20),
    model_run_id VARCHAR(20) NOT NULL,
    filepath VARCHAR(1024),
    generated_datetime TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT reports_pkey PRIMARY KEY (id),
    CONSTRAINT reports_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT reports_query_id_fkey FOREIGN KEY (query_id) REFERENCES public.queries (id) ON DELETE SET NULL
);

CREATE TABLE public.entities (
    incident_id VARCHAR(20) NOT NULL,
    entity_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    type VARCHAR(16),
    description TEXT,
    image VARCHAR(1024),
    CONSTRAINT entities_pkey PRIMARY KEY (incident_id, entity_id, model_run_id),
    CONSTRAINT entities_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE
);

CREATE TABLE public.instruments (
    incident_id VARCHAR(20) NOT NULL,
    instrument_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    entity_id VARCHAR(20),
    name VARCHAR(256),
    description TEXT,
    threat_level INTEGER,
    image VARCHAR(1024),
    CONSTRAINT instruments_pkey PRIMARY KEY (incident_id, instrument_id, model_run_id),
    CONSTRAINT instruments_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE
);

CREATE TABLE public.assets (
    incident_id VARCHAR(20) NOT NULL,
    asset_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    name VARCHAR(256),
    description TEXT,
    image VARCHAR(1024),
    CONSTRAINT assets_pkey PRIMARY KEY (incident_id, asset_id, model_run_id),
    CONSTRAINT assets_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE
);

-- Review workflow and operational tables.
CREATE TABLE public.review_status (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    status VARCHAR(32) DEFAULT 'unreviewed' NOT NULL,
    verified_by VARCHAR(256),
    verified_at TIMESTAMP WITHOUT TIME ZONE,
    edited_by VARCHAR(256), -- last content edit only (set by save_human_report_edit), never a status change
    edited_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT review_status_pkey PRIMARY KEY (incident_id, model_run_id),
    CONSTRAINT review_status_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE
);

CREATE TABLE public.notifications (
    id SERIAL NOT NULL,
    incident_id VARCHAR(20),
    model_run_id VARCHAR(20),
    severity INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    acknowledged BOOLEAN DEFAULT false NOT NULL,
    CONSTRAINT notifications_pkey PRIMARY KEY (id),
    CONSTRAINT notifications_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE
);

CREATE TABLE public.severity_eval_log (
    id SERIAL NOT NULL,
    incident_id VARCHAR(20),
    model_run_id VARCHAR(20),
    ai_severity INTEGER,
    human_severity INTEGER,
    rater VARCHAR(256),
    rated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT severity_eval_log_pkey PRIMARY KEY (id),
    CONSTRAINT severity_eval_log_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE
);

-- Ground truth (human annotations, one per video, no model_run_id) and Tier 1 matches.
CREATE TABLE public.gt_incidents (
    incident_id VARCHAR(20) NOT NULL,
    type VARCHAR(32),
    start_timestamp VARCHAR(32),
    end_timestamp VARCHAR(32),
    duration INTEGER,
    description TEXT,
    severity_level INTEGER,
    labelled_by VARCHAR(256),
    labelled_datetime TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT gt_incidents_pkey PRIMARY KEY (incident_id),
    CONSTRAINT gt_incidents_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.videos (id) ON DELETE CASCADE
);

CREATE TABLE public.gt_entities (
    incident_id VARCHAR(20) NOT NULL,
    entity_id VARCHAR(20) NOT NULL,
    type VARCHAR(16),
    description TEXT,
    image VARCHAR(1024),
    CONSTRAINT gt_entities_pkey PRIMARY KEY (incident_id, entity_id),
    CONSTRAINT gt_entities_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.gt_incidents (incident_id) ON DELETE CASCADE
);

CREATE TABLE public.gt_instruments (
    incident_id VARCHAR(20) NOT NULL,
    instrument_id VARCHAR(20) NOT NULL,
    entity_id VARCHAR(20),
    name VARCHAR(256),
    description TEXT,
    threat_level INTEGER,
    image VARCHAR(1024),
    CONSTRAINT gt_instruments_pkey PRIMARY KEY (incident_id, instrument_id),
    CONSTRAINT gt_instruments_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.gt_incidents (incident_id) ON DELETE CASCADE
);

CREATE TABLE public.gt_assets (
    incident_id VARCHAR(20) NOT NULL,
    asset_id VARCHAR(20) NOT NULL,
    name VARCHAR(256),
    description TEXT,
    image VARCHAR(1024),
    CONSTRAINT gt_assets_pkey PRIMARY KEY (incident_id, asset_id),
    CONSTRAINT gt_assets_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.gt_incidents (incident_id) ON DELETE CASCADE
);

CREATE TABLE public.entity_matches (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    entity_id VARCHAR(20) NOT NULL,
    gt_entity_id VARCHAR(20) NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    matched_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT entity_matches_pkey PRIMARY KEY (incident_id, model_run_id, entity_id),
    CONSTRAINT entity_matches_incident_id_entity_id_model_run_id_fkey FOREIGN KEY (incident_id, entity_id, model_run_id)
        REFERENCES public.entities (incident_id, entity_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT entity_matches_incident_id_gt_entity_id_fkey FOREIGN KEY (incident_id, gt_entity_id)
        REFERENCES public.gt_entities (incident_id, entity_id) ON DELETE CASCADE
);

CREATE TABLE public.instrument_matches (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    instrument_id VARCHAR(20) NOT NULL,
    gt_instrument_id VARCHAR(20) NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    matched_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT instrument_matches_pkey PRIMARY KEY (incident_id, model_run_id, instrument_id),
    CONSTRAINT instrument_matches_incident_id_gt_instrument_id_fkey FOREIGN KEY (incident_id, gt_instrument_id)
        REFERENCES public.gt_instruments (incident_id, instrument_id) ON DELETE CASCADE,
    CONSTRAINT instrument_matches_incident_id_instrument_id_model_run_id_fkey FOREIGN KEY (incident_id, instrument_id, model_run_id)
        REFERENCES public.instruments (incident_id, instrument_id, model_run_id) ON DELETE CASCADE
);

CREATE TABLE public.asset_matches (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    asset_id VARCHAR(20) NOT NULL,
    gt_asset_id VARCHAR(20) NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    matched_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT asset_matches_pkey PRIMARY KEY (incident_id, model_run_id, asset_id),
    CONSTRAINT asset_matches_incident_id_asset_id_model_run_id_fkey FOREIGN KEY (incident_id, asset_id, model_run_id)
        REFERENCES public.assets (incident_id, asset_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT asset_matches_incident_id_gt_asset_id_fkey FOREIGN KEY (incident_id, gt_asset_id)
        REFERENCES public.gt_assets (incident_id, asset_id) ON DELETE CASCADE
);

-- MVP2 evidence crops (keyed to the AI item, which never changes) and search audit.
CREATE TABLE public.evidence_crops (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    item_type VARCHAR(16) NOT NULL,
    item_id VARCHAR(20) NOT NULL,
    item_name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    threat_level INTEGER,
    holder_entity_id VARCHAR(20),
    timestamp_seconds INTEGER NOT NULL,
    bounding_box INTEGER[4] NOT NULL, -- [ymin, xmin, ymax, xmax], normalised 0-1000
    image VARCHAR(1024) NOT NULL, -- R2 key evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg
    embedding extensions.vector(1024),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc') NOT NULL,
    CONSTRAINT evidence_crops_pkey PRIMARY KEY (incident_id, model_run_id, item_type, item_id),
    CONSTRAINT evidence_crops_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT evidence_crops_item_type_check CHECK (item_type IN ('entity', 'instrument', 'asset'))
);
CREATE INDEX evidence_crops_embedding_hnsw_idx ON public.evidence_crops
    USING hnsw (embedding extensions.vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX evidence_crops_lookup_idx ON public.evidence_crops USING btree (incident_id, model_run_id);

CREATE TABLE public.query_results (
    id VARCHAR(36) NOT NULL,
    query_id VARCHAR(20) NOT NULL,
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    item_type VARCHAR(16) NOT NULL,
    item_id VARCHAR(20) NOT NULL,
    rank INTEGER NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    critic_verdict VARCHAR(16) NOT NULL,
    critic_rationale TEXT,
    retrieved_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc') NOT NULL,
    CONSTRAINT query_results_pkey PRIMARY KEY (id),
    CONSTRAINT query_results_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT query_results_query_id_fkey FOREIGN KEY (query_id) REFERENCES public.queries (id) ON DELETE CASCADE,
    CONSTRAINT query_results_critic_verdict_check CHECK (critic_verdict IN ('confirmed', 'rejected', 'unverified')),
    CONSTRAINT query_results_item_type_check CHECK (item_type IN ('entity', 'instrument', 'asset'))
);
CREATE INDEX query_results_incident_item_idx ON public.query_results USING btree (incident_id, model_run_id, item_type, item_id);
CREATE INDEX query_results_query_rank_idx ON public.query_results USING btree (query_id, rank);

-- 3. Reviewer (human) version of a report -------------------------------------------------------
-- One per run, created on the first edit or on verification, never on analysis. It is a complete,
-- contract-valid report; each item records the AI item it came from (source_*_id, NULL when the
-- reviewer added it), so crops and search stay keyed to the unchanging AI item. The item links
-- use ON DELETE SET NULL, not NO ACTION: deleting a run cascades to the AI items and to the
-- reviewer version along two paths, and a NO ACTION check can fire between them.

CREATE TABLE public.human_reports (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    type VARCHAR(32) NOT NULL,
    start_seconds INTEGER NOT NULL,
    end_seconds INTEGER NOT NULL,
    duration INTEGER GENERATED ALWAYS AS (end_seconds - start_seconds) STORED,
    description TEXT NOT NULL,
    severity_level INTEGER NOT NULL,
    revision INTEGER DEFAULT 1 NOT NULL, -- +1 per saved edit
    created_by VARCHAR(256) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc') NOT NULL,
    edited_by VARCHAR(256), -- last content edit; NULL = verified as the AI wrote it
    edited_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT human_reports_pkey PRIMARY KEY (incident_id, model_run_id),
    CONSTRAINT human_reports_incident_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.incidents (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT human_reports_type_check CHECK (type IN ('road accident', 'burglary', 'explosion', 'assault', 'animal attack')),
    CONSTRAINT human_reports_window_check CHECK (start_seconds >= 0 AND end_seconds >= start_seconds),
    CONSTRAINT human_reports_severity_check CHECK (severity_level BETWEEN 1 AND 5),
    CONSTRAINT human_reports_revision_check CHECK (revision >= 1),
    CONSTRAINT human_reports_edit_stamp_check CHECK ((edited_by IS NULL) = (edited_at IS NULL))
);

CREATE TABLE public.human_report_entities (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    entity_id VARCHAR(20) NOT NULL, -- E1..En
    source_entity_id VARCHAR(20),
    type VARCHAR(16) NOT NULL,
    description TEXT NOT NULL,
    CONSTRAINT human_report_entities_pkey PRIMARY KEY (incident_id, model_run_id, entity_id),
    CONSTRAINT human_report_entities_source_key UNIQUE (incident_id, model_run_id, source_entity_id),
    CONSTRAINT human_report_entities_report_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.human_reports (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT human_report_entities_source_fkey FOREIGN KEY (incident_id, source_entity_id, model_run_id)
        REFERENCES public.entities (incident_id, entity_id, model_run_id) ON DELETE SET NULL (source_entity_id),
    CONSTRAINT human_report_entities_id_check CHECK (entity_id ~ '^E[1-9][0-9]*$'),
    CONSTRAINT human_report_entities_type_check CHECK (type IN ('human', 'animal', 'unknown'))
);

CREATE TABLE public.human_report_instruments (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    instrument_id VARCHAR(20) NOT NULL, -- I1..In
    source_instrument_id VARCHAR(20),
    entity_id VARCHAR(20), -- holder: one of this human version's entities
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    threat_level INTEGER NOT NULL,
    CONSTRAINT human_report_instruments_pkey PRIMARY KEY (incident_id, model_run_id, instrument_id),
    CONSTRAINT human_report_instruments_source_key UNIQUE (incident_id, model_run_id, source_instrument_id),
    CONSTRAINT human_report_instruments_report_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.human_reports (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT human_report_instruments_source_fkey FOREIGN KEY (incident_id, source_instrument_id, model_run_id)
        REFERENCES public.instruments (incident_id, instrument_id, model_run_id) ON DELETE SET NULL (source_instrument_id),
    CONSTRAINT human_report_instruments_holder_fkey FOREIGN KEY (incident_id, model_run_id, entity_id)
        REFERENCES public.human_report_entities (incident_id, model_run_id, entity_id) ON DELETE SET NULL (entity_id),
    CONSTRAINT human_report_instruments_id_check CHECK (instrument_id ~ '^I[1-9][0-9]*$'),
    CONSTRAINT human_report_instruments_threat_check CHECK (threat_level BETWEEN 1 AND 5)
);

CREATE TABLE public.human_report_assets (
    incident_id VARCHAR(20) NOT NULL,
    model_run_id VARCHAR(20) NOT NULL,
    asset_id VARCHAR(20) NOT NULL, -- A1..An
    source_asset_id VARCHAR(20),
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    CONSTRAINT human_report_assets_pkey PRIMARY KEY (incident_id, model_run_id, asset_id),
    CONSTRAINT human_report_assets_source_key UNIQUE (incident_id, model_run_id, source_asset_id),
    CONSTRAINT human_report_assets_report_fkey FOREIGN KEY (incident_id, model_run_id)
        REFERENCES public.human_reports (incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT human_report_assets_source_fkey FOREIGN KEY (incident_id, source_asset_id, model_run_id)
        REFERENCES public.assets (incident_id, asset_id, model_run_id) ON DELETE SET NULL (source_asset_id),
    CONSTRAINT human_report_assets_id_check CHECK (asset_id ~ '^A[1-9][0-9]*$')
);

-- 4. Effective views: the report every reader means -------------------------------------------
-- Same columns, in the same order, as the AI tables (so a reader switches by changing only the
-- relation name), plus source_*_id and source ('ai' | 'human'). security_invoker makes the
-- caller's own privileges and RLS apply, so the views expose nothing the tables do not.

CREATE VIEW public.effective_incidents WITH (security_invoker = true) AS
SELECT
    i.incident_id,
    i.model_run_id,
    CASE WHEN h.incident_id IS NULL THEN i.type ELSE h.type END AS type,
    CASE WHEN h.incident_id IS NULL THEN i.start_timestamp ELSE h.start_seconds::TEXT END AS start_timestamp,
    CASE WHEN h.incident_id IS NULL THEN i.end_timestamp ELSE h.end_seconds::TEXT END AS end_timestamp,
    CASE WHEN h.incident_id IS NULL THEN i.duration ELSE h.duration END AS duration,
    CASE WHEN h.incident_id IS NULL THEN i.description ELSE h.description END AS description,
    CASE WHEN h.incident_id IS NULL THEN i.severity_level ELSE h.severity_level END AS severity_level,
    i.confidence_score, -- model-sourced, never edited
    CASE WHEN h.incident_id IS NULL THEN 'ai' ELSE 'human' END AS source
FROM public.incidents AS i
LEFT JOIN public.human_reports AS h ON h.incident_id = i.incident_id AND h.model_run_id = i.model_run_id;

CREATE VIEW public.effective_entities WITH (security_invoker = true) AS
SELECT e.incident_id, e.entity_id, e.model_run_id, e.type, e.description, e.image,
       e.entity_id AS source_entity_id, 'ai' AS source
FROM public.entities AS e
WHERE NOT EXISTS (SELECT 1 FROM public.human_reports AS h WHERE h.incident_id = e.incident_id AND h.model_run_id = e.model_run_id)
UNION ALL
SELECT he.incident_id, he.entity_id, he.model_run_id, he.type, he.description, NULL::VARCHAR(1024),
       he.source_entity_id, 'human'
FROM public.human_report_entities AS he;

CREATE VIEW public.effective_instruments WITH (security_invoker = true) AS
SELECT ins.incident_id, ins.instrument_id, ins.model_run_id, ins.entity_id, ins.name, ins.description, ins.threat_level, ins.image,
       ins.instrument_id AS source_instrument_id, 'ai' AS source
FROM public.instruments AS ins
WHERE NOT EXISTS (SELECT 1 FROM public.human_reports AS h WHERE h.incident_id = ins.incident_id AND h.model_run_id = ins.model_run_id)
UNION ALL
SELECT hi.incident_id, hi.instrument_id, hi.model_run_id, hi.entity_id, hi.name, hi.description, hi.threat_level, NULL::VARCHAR(1024),
       hi.source_instrument_id, 'human'
FROM public.human_report_instruments AS hi;

CREATE VIEW public.effective_assets WITH (security_invoker = true) AS
SELECT a.incident_id, a.asset_id, a.model_run_id, a.name, a.description, a.image,
       a.asset_id AS source_asset_id, 'ai' AS source
FROM public.assets AS a
WHERE NOT EXISTS (SELECT 1 FROM public.human_reports AS h WHERE h.incident_id = a.incident_id AND h.model_run_id = a.model_run_id)
UNION ALL
SELECT ha.incident_id, ha.asset_id, ha.model_run_id, ha.name, ha.description, NULL::VARCHAR(1024),
       ha.source_asset_id, 'human'
FROM public.human_report_assets AS ha;

-- 5. Functions ----------------------------------------------------------------------------------
-- Every function is SECURITY INVOKER with an empty search_path (names are schema-qualified) and is
-- executable by service_role only (section 6 revokes PUBLIC/anon/authenticated and checks it).
-- Left out on purpose: apply_incident_report_patch and replace_incident_evidence (superseded on
-- 2026-09-27, no callers) and the legacy pre-v1 tables they never touched.

-- 5.1 Helpers (bodies as on midterm, 20260927180000).
CREATE FUNCTION public.try_parse_jsonb(p_value TEXT)
RETURNS JSONB
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = ''
AS $$
BEGIN
    RETURN p_value::JSONB;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$;

CREATE FUNCTION public.canonical_incident_type(p_type TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT CASE lower(btrim(p_type))
        WHEN 'fighting' THEN 'assault'
        WHEN 'animal' THEN 'animal attack'
        ELSE NULLIF(lower(btrim(p_type)), '')
    END;
$$;

CREATE FUNCTION public.canonical_entity_type(p_type TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT CASE lower(btrim(COALESCE(p_type, '')))
        WHEN '' THEN 'unknown'
        WHEN 'person' THEN 'human'
        ELSE lower(btrim(p_type))
    END;
$$;

CREATE FUNCTION public.normalized_name(p_name TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT NULLIF(regexp_replace(lower(btrim(COALESCE(p_name, ''))), '\s+', ' ', 'g'), '');
$$;

CREATE FUNCTION public.run_outcome(p_notes TEXT)
RETURNS TEXT
LANGUAGE sql STABLE SET search_path = ''
AS $$
    SELECT CASE
        WHEN parsed #>> '{incidentConsoleV2,contractVersion}' IS NULL THEN 'legacy'
        WHEN parsed #>> '{incidentConsoleV2,status}' IN ('valid_after_structural_repair', 'contract_failed', 'request_failed')
            THEN parsed #>> '{incidentConsoleV2,status}'
        ELSE 'valid_first_pass'
    END
    FROM (SELECT public.try_parse_jsonb(p_notes) AS parsed) AS notes;
$$;

-- Integer seconds from a stored timestamp: "21", "0:18" or "1:02:03"; NULL for anything else
-- (e.g. eval's fractional "15.6").
CREATE FUNCTION public.timestamp_seconds(p_value TEXT)
RETURNS INTEGER
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT CASE
        WHEN btrim(p_value) ~ '^[0-9]{1,9}$' THEN btrim(p_value)::INTEGER
        WHEN btrim(p_value) ~ '^[0-9]{1,6}:[0-5][0-9]$'
            THEN split_part(btrim(p_value), ':', 1)::INTEGER * 60 + split_part(btrim(p_value), ':', 2)::INTEGER
        WHEN btrim(p_value) ~ '^[0-9]{1,4}:[0-5][0-9]:[0-5][0-9]$'
            THEN split_part(btrim(p_value), ':', 1)::INTEGER * 3600 + split_part(btrim(p_value), ':', 2)::INTEGER * 60
                 + split_part(btrim(p_value), ':', 3)::INTEGER
    END;
$$;

-- 5.2 insert_incident: the atomic AI-report write used by every PostgREST writer (console,
-- vss-agent, eval). Same signature and behaviour as midterm (20260925031000), plus an empty
-- search_path and a guard: re-running a run ID that already has a reviewer version would
-- cascade-delete that version, so it is refused (analyses always use a new model_run_id).
CREATE FUNCTION public.insert_incident(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_type TEXT,
    p_start_timestamp TEXT,
    p_end_timestamp TEXT,
    p_duration INTEGER,
    p_description TEXT,
    p_severity_level INTEGER,
    p_confidence_score DOUBLE PRECISION
) RETURNS VOID
LANGUAGE plpgsql SET search_path = ''
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.human_reports WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id) THEN
        RAISE EXCEPTION 'Run % of % has a reviewer version; analyse with a new model_run_id', p_model_run_id, p_incident_id;
    END IF;

    -- Delete-then-insert: cascades to this run's items, report, review and evidence rows.
    DELETE FROM public.incidents WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    INSERT INTO public.incidents (
        incident_id, model_run_id, type, start_timestamp, end_timestamp, duration, description, severity_level, confidence_score
    ) VALUES (
        p_incident_id, p_model_run_id, p_type, p_start_timestamp, p_end_timestamp, p_duration, p_description, p_severity_level, p_confidence_score
    );

    DELETE FROM public.review_status WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    INSERT INTO public.review_status (incident_id, model_run_id, status)
    VALUES (p_incident_id, p_model_run_id, 'unreviewed');
END;
$$;

-- 5.3 Official report selection (D6), bodies as on midterm (20260927170000).
CREATE FUNCTION public.select_official_report(
    p_video_id TEXT,
    p_model_run_id TEXT,
    p_selected_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_selected_at TIMESTAMP WITHOUT TIME ZONE := now() AT TIME ZONE 'utc';
BEGIN
    IF p_selected_by IS NULL OR btrim(p_selected_by) = '' THEN
        RAISE EXCEPTION 'A reviewer name is required';
    END IF;
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Video not found'; END IF;
    PERFORM 1 FROM public.reports r
    JOIN public.incidents i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    WHERE r.incident_id = p_video_id AND r.model_run_id = p_model_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Only a successful analysis of this video that has a report can be the official report';
    END IF;

    UPDATE public.videos
    SET selected_model_run_id = p_model_run_id,
        selected_by = btrim(p_selected_by),
        selected_at = v_selected_at
    WHERE id = p_video_id;

    RETURN jsonb_build_object('videoId', p_video_id, 'officialRunId', p_model_run_id, 'selectedBy', btrim(p_selected_by), 'selectedAt', v_selected_at);
END;
$$;

CREATE FUNCTION public.clear_official_report(
    p_video_id TEXT,
    p_cleared_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    IF p_cleared_by IS NULL OR btrim(p_cleared_by) = '' THEN
        RAISE EXCEPTION 'A reviewer name is required';
    END IF;
    UPDATE public.videos
    SET selected_model_run_id = NULL, selected_by = NULL, selected_at = NULL
    WHERE id = p_video_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Video not found'; END IF;
    RETURN jsonb_build_object('videoId', p_video_id, 'officialRunId', NULL, 'clearedBy', btrim(p_cleared_by));
END;
$$;

-- 5.4 Report library and dashboard: bodies and signatures exactly as on midterm
-- (20260928000000, with p_timezone), reading the effective_* views instead of the AI tables, so
-- they show the reviewer's version where there is one. Only the "video has no incident at all"
-- count still reads public.incidents (any run counts there).
CREATE FUNCTION public.list_incident_report_summaries(p_page integer DEFAULT 1, p_page_size integer DEFAULT 6, p_search text DEFAULT NULL::text, p_type text DEFAULT NULL::text, p_severity text DEFAULT NULL::text, p_status text DEFAULT NULL::text, p_generated_after timestamp without time zone DEFAULT NULL::timestamp without time zone, p_generated_before timestamp without time zone DEFAULT NULL::timestamp without time zone, p_time_from time without time zone DEFAULT NULL::time without time zone, p_time_to time without time zone DEFAULT NULL::time without time zone, p_entities text[] DEFAULT NULL::text[], p_instruments text[] DEFAULT NULL::text[], p_assets text[] DEFAULT NULL::text[], p_day_of_week integer DEFAULT NULL::integer, p_sort text DEFAULT 'newest'::text, p_scope text DEFAULT 'all'::text, p_entity_types text[] DEFAULT NULL::text[], p_evidence_match text DEFAULT 'contains'::text, p_timezone text DEFAULT 'UTC'::text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
WITH parameters AS (
    SELECT
        replace(replace(replace(p_search, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') AS escaped_search,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_entities) AS value) AS escaped_entities,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_instruments) AS value) AS escaped_instruments,
        ARRAY(SELECT replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') FROM unnest(p_assets) AS value) AS escaped_assets,
        ARRAY(SELECT public.normalized_name(value) FROM unnest(p_instruments) AS value) AS exact_instruments,
        ARRAY(SELECT public.normalized_name(value) FROM unnest(p_assets) AS value) AS exact_assets,
        ARRAY(SELECT public.canonical_entity_type(value) FROM unnest(p_entity_types) AS value) AS entity_types,
        public.canonical_incident_type(p_type) AS canonical_type,
        COALESCE(p_evidence_match, 'contains') = 'exact' AS exact_match,
        COALESCE(NULLIF(p_timezone, ''), 'UTC') AS target_tz
),
filtered AS (
    SELECT
        r.id AS report_id, r.incident_id AS video_id, r.model_run_id,
        COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}') AS stored_title,
        public.canonical_incident_type(i.type) AS incident_type, i.description, i.severity_level, i.confidence_score,
        r.generated_datetime, v.uploaded_datetime,
        regexp_replace(COALESCE(v.filepath, r.incident_id), '^.*/', '') AS filename,
        mr.model_name, public.run_outcome(mr.notes) AS outcome,
        v.selected_model_run_id IS NOT DISTINCT FROM r.model_run_id AS is_official,
        COALESCE(rs.status, 'unreviewed') AS review_status,
        rs.verified_by, rs.verified_at, rs.edited_by, rs.edited_at,
        v.filepath AS r2_key, v.source AS sensor_id
    FROM public.reports AS r
    JOIN public.effective_incidents AS i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    JOIN public.model_runs AS mr ON mr.id = r.model_run_id
    JOIN public.videos AS v ON v.id = r.incident_id
    LEFT JOIN public.review_status AS rs ON rs.incident_id = r.incident_id AND rs.model_run_id = r.model_run_id
    CROSS JOIN parameters AS params
    WHERE (COALESCE(p_scope, 'all') <> 'official' OR v.selected_model_run_id = r.model_run_id)
      AND (p_type IS NULL OR public.canonical_incident_type(i.type) = params.canonical_type)
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'high' THEN i.severity_level >= 4
          WHEN 'medium' THEN i.severity_level = 3
          WHEN 'low' THEN i.severity_level <= 2
          ELSE i.severity_level = p_severity::INTEGER END)
      AND (p_status IS NULL OR COALESCE(rs.status, 'unreviewed') = p_status)
      AND (p_generated_after IS NULL OR r.generated_datetime >= p_generated_after)
      AND (p_generated_before IS NULL OR r.generated_datetime <= p_generated_before)
      AND (p_time_from IS NULL OR (r.generated_datetime AT TIME ZONE 'utc' AT TIME ZONE params.target_tz)::TIME >= p_time_from)
      AND (p_time_to IS NULL OR (r.generated_datetime AT TIME ZONE 'utc' AT TIME ZONE params.target_tz)::TIME <= p_time_to)
      AND (p_day_of_week IS NULL OR EXTRACT(DOW FROM (r.generated_datetime AT TIME ZONE 'utc' AT TIME ZONE params.target_tz))::INTEGER = p_day_of_week)
      AND (p_entity_types IS NULL OR EXISTS (
          SELECT 1 FROM public.effective_entities e
          WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id
            AND public.canonical_entity_type(e.type) = ANY (params.entity_types)
      ))
      AND (p_entities IS NULL OR EXISTS (
          SELECT 1 FROM public.effective_entities e
          WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id
            AND EXISTS (SELECT 1 FROM unnest(params.escaped_entities) term WHERE concat_ws(' ', e.type, e.description) ILIKE '%' || term || '%' ESCAPE E'\\')
      ))
      AND (p_instruments IS NULL OR EXISTS (
          SELECT 1 FROM public.effective_instruments ins
          WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id
            AND CASE WHEN params.exact_match
                THEN public.normalized_name(ins.name) = ANY (params.exact_instruments)
                ELSE EXISTS (SELECT 1 FROM unnest(params.escaped_instruments) term WHERE concat_ws(' ', ins.name, ins.description) ILIKE '%' || term || '%' ESCAPE E'\\')
            END
      ))
      AND (p_assets IS NULL OR EXISTS (
          SELECT 1 FROM public.effective_assets a
          WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id
            AND CASE WHEN params.exact_match
                THEN public.normalized_name(a.name) = ANY (params.exact_assets)
                ELSE EXISTS (SELECT 1 FROM unnest(params.escaped_assets) term WHERE concat_ws(' ', a.name, a.description) ILIKE '%' || term || '%' ESCAPE E'\\')
            END
      ))
      AND (params.escaped_search IS NULL
          OR concat_ws(' ', COALESCE(public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,editedReport,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,incident,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,title}', public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,title}'), public.canonical_incident_type(i.type), i.description, regexp_replace(COALESCE(v.filepath, ''), '^.*/', '')) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'
          OR EXISTS (SELECT 1 FROM public.effective_entities e WHERE e.incident_id = r.incident_id AND e.model_run_id = r.model_run_id AND concat_ws(' ', e.type, e.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM public.effective_instruments ins WHERE ins.incident_id = r.incident_id AND ins.model_run_id = r.model_run_id AND concat_ws(' ', ins.name, ins.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\')
          OR EXISTS (SELECT 1 FROM public.effective_assets a WHERE a.incident_id = r.incident_id AND a.model_run_id = r.model_run_id AND concat_ws(' ', a.name, a.description) ILIKE '%' || params.escaped_search || '%' ESCAPE E'\\'))
),
ordered AS (
    SELECT * FROM filtered
    ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, report_id ASC
    LIMIT LEAST(GREATEST(p_page_size, 1), 1000)
    OFFSET (GREATEST(p_page, 1) - 1) * LEAST(GREATEST(p_page_size, 1), 1000)
),
incident_types AS (
    SELECT COALESCE(jsonb_agg(type ORDER BY type), '[]'::JSONB) AS values
    FROM (SELECT DISTINCT public.canonical_incident_type(i.type) AS type FROM public.effective_incidents i WHERE public.canonical_incident_type(i.type) IS NOT NULL) types
)
SELECT jsonb_build_object(
    'reports', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'reportId', report_id, 'videoId', video_id, 'modelRunId', model_run_id,
        'title', COALESCE(NULLIF(stored_title, ''), COALESCE(NULLIF(initcap(incident_type), ''), 'Incident') || ' report'),
        'filename', filename, 'incident_type', COALESCE(incident_type, 'Unclassified'),
        'description', COALESCE(description, 'No summary was recorded.'),
        'severity', COALESCE(severity_level, 1), 'confidence', confidence_score,
        'generatedAt', generated_datetime, 'uploadedAt', uploaded_datetime,
        'model', COALESCE(model_name, 'Unknown model'), 'status', review_status,
        'outcome', outcome, 'isOfficial', is_official,
        'verifiedBy', verified_by, 'verifiedAt', verified_at, 'editedBy', edited_by, 'editedAt', edited_at,
        'r2Key', r2_key, 'sensorId', sensor_id
    ) ORDER BY CASE WHEN p_sort = 'oldest' THEN generated_datetime END ASC,
        CASE WHEN p_sort = 'severity-high' THEN severity_level END DESC,
        CASE WHEN p_sort = 'severity-low' THEN severity_level END ASC,
        CASE WHEN p_sort = 'confidence-high' THEN confidence_score END DESC NULLS LAST,
        CASE WHEN p_sort = 'confidence-low' THEN confidence_score END ASC NULLS LAST,
        CASE WHEN p_sort = 'newest' THEN generated_datetime END DESC,
        generated_datetime DESC, report_id ASC) FROM ordered), '[]'::JSONB),
    'totalItems', (SELECT count(*) FROM filtered),
    'incidentTypes', (SELECT values FROM incident_types)
);
$function$;

CREATE FUNCTION public.get_incident_dashboard(p_period_start timestamp without time zone DEFAULT NULL::timestamp without time zone, p_period_end timestamp without time zone DEFAULT NULL::timestamp without time zone, p_type text DEFAULT NULL::text, p_severity text DEFAULT NULL::text, p_day_of_week integer DEFAULT NULL::integer, p_hour integer DEFAULT NULL::integer, p_timezone text DEFAULT 'UTC'::text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
WITH target_tz AS (
    SELECT COALESCE(NULLIF(p_timezone, ''), 'UTC') AS tz
),
official_all AS (
    -- One incident per video: its explicitly selected official report.
    SELECT
        r.incident_id, r.model_run_id, r.generated_datetime,
        public.canonical_incident_type(i.type) AS incident_type,
        i.severity_level AS severity,
        i.confidence_score AS confidence,
        COALESCE(rs.status, 'unreviewed') AS review_status,
        EXTRACT(DOW FROM (r.generated_datetime AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS day_of_week,
        EXTRACT(HOUR FROM (r.generated_datetime AT TIME ZONE 'utc' AT TIME ZONE target_tz.tz))::INTEGER AS hour_of_day
    FROM public.videos AS v
    JOIN public.reports AS r ON r.incident_id = v.id AND r.model_run_id = v.selected_model_run_id
    JOIN public.effective_incidents AS i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    LEFT JOIN public.review_status AS rs ON rs.incident_id = r.incident_id AND rs.model_run_id = r.model_run_id
    CROSS JOIN target_tz
),
dimension_filtered AS (
    SELECT * FROM official_all
    WHERE (p_type IS NULL OR incident_type = public.canonical_incident_type(p_type))
      AND (p_severity IS NULL OR CASE p_severity
          WHEN 'low' THEN severity <= 2 WHEN 'medium' THEN severity = 3 WHEN 'high' THEN severity >= 4 ELSE FALSE END)
      AND (p_day_of_week IS NULL OR day_of_week = p_day_of_week)
      AND (p_hour IS NULL OR hour_of_day = p_hour)
),
filtered AS (
    SELECT * FROM dimension_filtered
    WHERE (p_period_start IS NULL OR generated_datetime >= p_period_start)
      AND (p_period_end IS NULL OR generated_datetime < p_period_end)
),
video_counts AS (
    SELECT
        COUNT(*)::INTEGER AS uploaded,
        COUNT(*) FILTER (WHERE v.selected_model_run_id IS NOT NULL)::INTEGER AS with_official,
        COUNT(*) FILTER (WHERE v.selected_model_run_id IS NULL AND EXISTS (SELECT 1 FROM public.reports r WHERE r.incident_id = v.id))::INTEGER AS awaiting_selection,
        COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM public.incidents i WHERE i.incident_id = v.id))::INTEGER AS without_report
    -- All time, independent of the period, so these numbers match the /videos lists they link to.
    FROM public.videos AS v
),
date_bounds AS (
    SELECT
        COALESCE(p_period_start::DATE, MIN(generated_datetime)::DATE, CURRENT_DATE) AS first_day,
        COALESCE((p_period_end - INTERVAL '1 microsecond')::DATE, MAX(generated_datetime)::DATE, CURRENT_DATE) AS last_day
    FROM filtered
),
daily AS (
    SELECT day::DATE AS day, COUNT(f.incident_id)::INTEGER AS count
    FROM date_bounds
    CROSS JOIN LATERAL generate_series(first_day, last_day, INTERVAL '1 day') AS day
    LEFT JOIN filtered AS f ON f.generated_datetime::DATE = day::DATE
    GROUP BY day ORDER BY day
),
entity_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.canonical_entity_type(e.type) AS label
    FROM filtered f JOIN public.effective_entities e ON e.incident_id = f.incident_id AND e.model_run_id = f.model_run_id
),
instrument_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(ins.name) AS label, ins.threat_level
    FROM filtered f JOIN public.effective_instruments ins ON ins.incident_id = f.incident_id AND ins.model_run_id = f.model_run_id
    WHERE public.normalized_name(ins.name) IS NOT NULL
),
asset_rows AS (
    SELECT DISTINCT f.incident_id, f.incident_type, public.normalized_name(a.name) AS label
    FROM filtered f JOIN public.effective_assets a ON a.incident_id = f.incident_id AND a.model_run_id = f.model_run_id
    WHERE public.normalized_name(a.name) IS NOT NULL
),
type_counts AS (
    SELECT incident_type, COUNT(*)::INTEGER AS count FROM filtered GROUP BY incident_type
),
type_details AS (
    SELECT jsonb_agg(jsonb_build_object(
        'type', COALESCE(tc.incident_type, 'Unclassified'),
        'count', tc.count,
        'severity', jsonb_build_object(
            'low', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity <= 2),
            'medium', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity = 3),
            'high', (SELECT COUNT(*) FROM filtered f WHERE f.incident_type IS NOT DISTINCT FROM tc.incident_type AND f.severity >= 4)),
        'entities', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM entity_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label LIMIT 3) ranked), '[]'::JSONB),
        'instruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM instrument_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label LIMIT 3) ranked), '[]'::JSONB),
        'assets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (
            SELECT label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM asset_rows WHERE incident_type IS NOT DISTINCT FROM tc.incident_type GROUP BY label ORDER BY count DESC, label LIMIT 3) ranked), '[]'::JSONB)
    ) ORDER BY tc.count DESC, tc.incident_type) AS values
    FROM type_counts tc
),
ranked AS (
    SELECT 'entity' AS kind, label, COUNT(DISTINCT incident_id)::INTEGER AS count FROM entity_rows GROUP BY label
    UNION ALL SELECT 'instrument', label, COUNT(DISTINCT incident_id)::INTEGER FROM instrument_rows GROUP BY label
    UNION ALL SELECT 'asset', label, COUNT(DISTINCT incident_id)::INTEGER FROM asset_rows GROUP BY label
),
threat_levels AS (
    SELECT threat_level AS level, COUNT(*)::INTEGER AS count FROM instrument_rows WHERE threat_level IS NOT NULL GROUP BY threat_level
),
attempts AS (
    -- Every recorded analysis attempt in the period, by outcome; legacy runs
    -- are counted by their report rows.
    SELECT mr.model_name, public.run_outcome(mr.notes) AS outcome
    FROM public.model_runs mr
    WHERE public.run_outcome(mr.notes) IN ('contract_failed', 'request_failed')
      AND (p_period_start IS NULL OR mr.run_datetime >= p_period_start)
      AND (p_period_end IS NULL OR mr.run_datetime < p_period_end)
    UNION ALL
    SELECT mr.model_name, public.run_outcome(mr.notes)
    FROM public.reports r JOIN public.model_runs mr ON mr.id = r.model_run_id
    WHERE (p_period_start IS NULL OR r.generated_datetime >= p_period_start)
      AND (p_period_end IS NULL OR r.generated_datetime < p_period_end)
),
model_coverage AS (
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'model', model_name,
        'withReport', with_report, 'validFirstPass', valid_first_pass, 'repaired', repaired,
        'legacy', legacy, 'contractFailed', contract_failed, 'requestFailed', request_failed
    ) ORDER BY with_report DESC, model_name), '[]'::JSONB) AS values
    FROM (
        SELECT COALESCE(model_name, 'Unknown model') AS model_name,
            COUNT(*) FILTER (WHERE outcome NOT IN ('contract_failed', 'request_failed'))::INTEGER AS with_report,
            COUNT(*) FILTER (WHERE outcome = 'valid_first_pass')::INTEGER AS valid_first_pass,
            COUNT(*) FILTER (WHERE outcome = 'valid_after_structural_repair')::INTEGER AS repaired,
            COUNT(*) FILTER (WHERE outcome = 'legacy')::INTEGER AS legacy,
            COUNT(*) FILTER (WHERE outcome = 'contract_failed')::INTEGER AS contract_failed,
            COUNT(*) FILTER (WHERE outcome = 'request_failed')::INTEGER AS request_failed
        FROM attempts GROUP BY COALESCE(model_name, 'Unknown model')
    ) per_model
),
confidence_buckets AS (
    SELECT LEAST(9, GREATEST(0, FLOOR(confidence * 10)::INTEGER)) AS bucket, COUNT(*)::INTEGER AS count
    FROM filtered WHERE confidence IS NOT NULL GROUP BY 1
),
heatmap AS (
    SELECT day_of_week, hour_of_day, COUNT(*)::INTEGER AS count FROM filtered GROUP BY day_of_week, hour_of_day
),
previous AS (
    SELECT COUNT(*)::INTEGER AS total,
        COUNT(*) FILTER (WHERE review_status = 'verified')::INTEGER AS verified,
        COUNT(*) FILTER (WHERE review_status = 'unreviewed')::INTEGER AS unreviewed,
        COUNT(*) FILTER (WHERE severity >= 4)::INTEGER AS high
    FROM dimension_filtered
    WHERE p_period_start IS NOT NULL AND p_period_end IS NOT NULL
      AND generated_datetime >= p_period_start - (p_period_end - p_period_start)
      AND generated_datetime < p_period_start
)
SELECT jsonb_build_object(
    'total', (SELECT COUNT(*) FROM filtered),
    'videos', (SELECT jsonb_build_object('uploaded', uploaded, 'withOfficial', with_official, 'awaitingSelection', awaiting_selection, 'withoutReport', without_report) FROM video_counts),
    'previous', CASE WHEN p_period_start IS NULL OR p_period_end IS NULL THEN NULL ELSE (SELECT to_jsonb(previous) FROM previous) END,
    'averageConfidence', (SELECT AVG(confidence) FROM filtered WHERE confidence IS NOT NULL),
    'confidenceNotProvided', (SELECT COUNT(*) FROM filtered WHERE confidence IS NULL),
    'severity', (SELECT jsonb_build_object('low', COUNT(*) FILTER (WHERE severity <= 2), 'medium', COUNT(*) FILTER (WHERE severity = 3), 'high', COUNT(*) FILTER (WHERE severity >= 4)) FROM filtered),
    'reviews', (SELECT jsonb_build_object('unreviewed', COUNT(*) FILTER (WHERE review_status = 'unreviewed'), 'under_review', COUNT(*) FILTER (WHERE review_status = 'under review'), 'verified', COUNT(*) FILTER (WHERE review_status = 'verified')) FROM filtered),
    'types', COALESCE((SELECT values FROM type_details), '[]'::JSONB),
    'trend', COALESCE((SELECT jsonb_agg(jsonb_build_object('date', day, 'count', count) ORDER BY day) FROM daily), '[]'::JSONB),
    'heatmap', COALESCE((SELECT jsonb_agg(jsonb_build_object('day', day_of_week, 'hour', hour_of_day, 'count', count) ORDER BY day_of_week, hour_of_day) FROM heatmap), '[]'::JSONB),
    'confidence', COALESCE((SELECT jsonb_agg(jsonb_build_object('bucket', bucket, 'count', count) ORDER BY bucket) FROM confidence_buckets), '[]'::JSONB),
    'entityTypes', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM ranked WHERE kind = 'entity'), '[]'::JSONB),
    'topInstruments', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (SELECT * FROM ranked WHERE kind = 'instrument' ORDER BY count DESC, label LIMIT 8) top), '[]'::JSONB),
    'topAssets', COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'count', count) ORDER BY count DESC, label) FROM (SELECT * FROM ranked WHERE kind = 'asset' ORDER BY count DESC, label LIMIT 8) top), '[]'::JSONB),
    'threatLevels', COALESCE((SELECT jsonb_agg(jsonb_build_object('level', level, 'count', count) ORDER BY level) FROM threat_levels), '[]'::JSONB),
    'modelCoverage', (SELECT values FROM model_coverage)
);
$function$;

-- 5.5 Evidence search: signature and output columns as on midterm (20261016120000), so the
-- agent's SupabaseSearchStore is unchanged. Still official reports only. Crops stay keyed to the
-- AI item; when the run has a reviewer version the incident fields and the item text come from it,
-- and a crop whose AI item the reviewer removed is not returned. Ranking still uses the stored
-- embedding of the AI text.
CREATE FUNCTION public.search_evidence_items(
    p_query_embedding extensions.vector(1024),
    p_top_k INTEGER DEFAULT 10,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
    p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset'],
    p_incident_types TEXT[] DEFAULT NULL,
    p_min_severity INTEGER DEFAULT NULL,
    p_max_severity INTEGER DEFAULT NULL
)
RETURNS TABLE (
    incident_id VARCHAR(20),
    model_run_id VARCHAR(20),
    video_filepath VARCHAR(1024),
    incident_type VARCHAR(32),
    severity_level INTEGER,
    incident_description TEXT,
    incident_start_timestamp VARCHAR(32),
    incident_end_timestamp VARCHAR(32),
    item_type VARCHAR(16),
    item_id VARCHAR(20),
    item_name VARCHAR(256),
    item_description TEXT,
    threat_level INTEGER,
    holder_entity_id VARCHAR(20),
    image VARCHAR(1024),
    timestamp_seconds INTEGER,
    bounding_box INTEGER[4],
    similarity_score DOUBLE PRECISION
)
LANGUAGE plpgsql SECURITY INVOKER STABLE SET search_path = ''
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ec.incident_id,
        ec.model_run_id,
        v.filepath AS video_filepath,
        inc.type::VARCHAR(32) AS incident_type,
        inc.severity_level,
        inc.description AS incident_description,
        inc.start_timestamp::VARCHAR(32) AS incident_start_timestamp,
        inc.end_timestamp::VARCHAR(32) AS incident_end_timestamp,
        ec.item_type,
        ec.item_id,
        COALESCE(hi.name, ec.item_name)::VARCHAR(256) AS item_name,
        COALESCE(hi.description, ec.description) AS item_description,
        CASE WHEN hi.found THEN hi.threat_level ELSE ec.threat_level END AS threat_level,
        CASE WHEN hi.found THEN hi.holder_entity_id ELSE ec.holder_entity_id END AS holder_entity_id,
        ec.image,
        ec.timestamp_seconds,
        ec.bounding_box,
        (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding))::DOUBLE PRECISION AS similarity_score
    FROM public.evidence_crops ec
    JOIN public.videos v ON v.id = ec.incident_id AND v.selected_model_run_id = ec.model_run_id
    JOIN public.effective_incidents inc ON inc.incident_id = ec.incident_id AND inc.model_run_id = ec.model_run_id
    LEFT JOIN LATERAL (
        SELECT TRUE AS found, he.type::VARCHAR(256) AS name, he.description, NULL::INTEGER AS threat_level, NULL::VARCHAR(20) AS holder_entity_id
        FROM public.human_report_entities he
        WHERE ec.item_type = 'entity' AND he.incident_id = ec.incident_id AND he.model_run_id = ec.model_run_id AND he.source_entity_id = ec.item_id
        UNION ALL
        SELECT TRUE, hn.name, hn.description, hn.threat_level, hn.entity_id
        FROM public.human_report_instruments hn
        WHERE ec.item_type = 'instrument' AND hn.incident_id = ec.incident_id AND hn.model_run_id = ec.model_run_id AND hn.source_instrument_id = ec.item_id
        UNION ALL
        SELECT TRUE, ha.name, ha.description, NULL::INTEGER, NULL::VARCHAR(20)
        FROM public.human_report_assets ha
        WHERE ec.item_type = 'asset' AND ha.incident_id = ec.incident_id AND ha.model_run_id = ec.model_run_id AND ha.source_asset_id = ec.item_id
    ) hi ON TRUE
    WHERE (p_item_types IS NULL OR ec.item_type = ANY(p_item_types))
      AND ec.embedding IS NOT NULL
      AND (inc.source = 'ai' OR hi.found)
      AND (1.0 - (ec.embedding OPERATOR(extensions.<=>) p_query_embedding)) >= p_min_similarity
      AND (p_incident_types IS NULL OR inc.type = ANY(p_incident_types))
      AND (p_min_severity IS NULL OR inc.severity_level >= p_min_severity)
      AND (p_max_severity IS NULL OR inc.severity_level <= p_max_severity)
    ORDER BY ec.embedding OPERATOR(extensions.<=>) p_query_embedding ASC
    LIMIT p_top_k;
END;
$$;

-- 5.6 Reviewer-version RPCs. None of them changes an AI row or model_runs.notes.

-- Copies one run's AI report into a new reviewer version (used when a report is verified without
-- edits, and by the midterm-to-finals copy). Legacy rows are normalised the way the console's
-- editor does it: e01 -> E1 (keeping source_entity_id = 'e01'), person -> human,
-- fighting -> assault, "0:18" -> 18. Raises when the AI report cannot be a valid reviewer version
-- as it stands (no severity, unrated instrument, fractional timestamps, ...): edit it first.
CREATE FUNCTION public.create_human_report_from_ai(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_created_by TEXT,
    p_created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc')
) RETURNS VOID
LANGUAGE plpgsql SET search_path = ''
AS $$
DECLARE
    ai public.incidents%ROWTYPE;
    v_type TEXT;
    v_start INTEGER;
    v_end INTEGER;
    bad TEXT;
BEGIN
    IF p_created_by IS NULL OR btrim(p_created_by) = '' THEN
        RAISE EXCEPTION 'A reviewer name is required';
    END IF;
    SELECT * INTO ai FROM public.incidents WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Report not found for this video and model run'; END IF;
    IF EXISTS (SELECT 1 FROM public.human_reports WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id) THEN
        RAISE EXCEPTION 'Run % of % already has a reviewer version', p_model_run_id, p_incident_id;
    END IF;

    v_type := public.canonical_incident_type(ai.type);
    v_start := public.timestamp_seconds(ai.start_timestamp);
    v_end := public.timestamp_seconds(ai.end_timestamp);
    IF v_type IS NULL OR NOT (v_type = ANY (ARRAY['road accident', 'burglary', 'explosion', 'assault', 'animal attack']))
        OR v_start IS NULL OR v_end IS NULL OR v_end < v_start
        OR ai.severity_level IS NULL OR ai.severity_level NOT BETWEEN 1 AND 5 OR ai.description IS NULL THEN
        RAISE EXCEPTION 'The AI report of run % cannot be verified as it stands (type %, window %-%, severity %); edit it first',
            p_model_run_id, ai.type, ai.start_timestamp, ai.end_timestamp, ai.severity_level;
    END IF;

    INSERT INTO public.human_reports (incident_id, model_run_id, type, start_seconds, end_seconds, description, severity_level,
        revision, created_by, created_at, edited_by, edited_at)
    VALUES (p_incident_id, p_model_run_id, v_type, v_start, v_end, ai.description, ai.severity_level,
        1, btrim(p_created_by), p_created_at, NULL, NULL);

    -- Items keep their order; IDs become sequential (E1.., I1.., A1..). entity_map pairs each AI
    -- entity ID with its new ID, so instrument holders follow their entity.
    SELECT string_agg(e.entity_id, ', ') INTO bad FROM public.entities e
    WHERE e.incident_id = p_incident_id AND e.model_run_id = p_model_run_id
      AND (e.description IS NULL OR public.canonical_entity_type(e.type) NOT IN ('human', 'animal', 'unknown'));
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'Entities % of run % are not valid as they stand; edit first', bad, p_model_run_id; END IF;
    WITH entity_map AS (
        SELECT e.entity_id AS source_id,
            'E' || row_number() OVER (ORDER BY NULLIF(regexp_replace(e.entity_id, '\D', '', 'g'), '')::INTEGER NULLS LAST, e.entity_id) AS new_id
        FROM public.entities e WHERE e.incident_id = p_incident_id AND e.model_run_id = p_model_run_id
    )
    INSERT INTO public.human_report_entities (incident_id, model_run_id, entity_id, source_entity_id, type, description)
    SELECT e.incident_id, e.model_run_id, m.new_id, e.entity_id, public.canonical_entity_type(e.type), e.description
    FROM public.entities e JOIN entity_map m ON m.source_id = e.entity_id
    WHERE e.incident_id = p_incident_id AND e.model_run_id = p_model_run_id;

    SELECT string_agg(ins.instrument_id, ', ') INTO bad FROM public.instruments ins
    LEFT JOIN public.human_report_entities he
        ON he.incident_id = ins.incident_id AND he.model_run_id = ins.model_run_id AND he.source_entity_id = ins.entity_id
    WHERE ins.incident_id = p_incident_id AND ins.model_run_id = p_model_run_id
      AND (ins.name IS NULL OR ins.description IS NULL OR ins.threat_level IS NULL OR ins.threat_level NOT BETWEEN 1 AND 5
           OR (ins.entity_id IS NOT NULL AND he.entity_id IS NULL));
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'Instruments % of run % are not valid as they stand; edit first', bad, p_model_run_id; END IF;
    INSERT INTO public.human_report_instruments (incident_id, model_run_id, instrument_id, source_instrument_id, entity_id, name, description, threat_level)
    SELECT ins.incident_id, ins.model_run_id,
        'I' || row_number() OVER (ORDER BY NULLIF(regexp_replace(ins.instrument_id, '\D', '', 'g'), '')::INTEGER NULLS LAST, ins.instrument_id),
        ins.instrument_id, he.entity_id, ins.name, ins.description, ins.threat_level
    FROM public.instruments ins
    LEFT JOIN public.human_report_entities he
        ON he.incident_id = ins.incident_id AND he.model_run_id = ins.model_run_id AND he.source_entity_id = ins.entity_id
    WHERE ins.incident_id = p_incident_id AND ins.model_run_id = p_model_run_id;

    SELECT string_agg(a.asset_id, ', ') INTO bad FROM public.assets a
    WHERE a.incident_id = p_incident_id AND a.model_run_id = p_model_run_id AND (a.name IS NULL OR a.description IS NULL);
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'Assets % of run % are not valid as they stand; edit first', bad, p_model_run_id; END IF;
    INSERT INTO public.human_report_assets (incident_id, model_run_id, asset_id, source_asset_id, name, description)
    SELECT a.incident_id, a.model_run_id,
        'A' || row_number() OVER (ORDER BY NULLIF(regexp_replace(a.asset_id, '\D', '', 'g'), '')::INTEGER NULLS LAST, a.asset_id),
        a.asset_id, a.name, a.description
    FROM public.assets a
    WHERE a.incident_id = p_incident_id AND a.model_run_id = p_model_run_id;
END;
$$;

-- Saves the reviewer's version of one run (created on the first edit, replaced on later ones).
-- Validation is apply_structured_report_edit's (midterm 20260927160000), plus: every item
-- carries a "source_id" key naming the AI item of the same kind in this run it came from, at most
-- once, or an explicit null for an item the reviewer added. The editor renumbers items by
-- position, so an item's own ID says nothing about its origin: an edit with a keyless item (a
-- console that predates source ids) is refused rather than guessed. A content edit sends a
-- verified report back to "under review" and clears the verifier (the captain's decision, 2026-10-20).
CREATE FUNCTION public.save_human_report_edit(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_edit JSONB,
    p_edited_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SET search_path = ''
AS $$
DECLARE
    incident JSONB := p_edit->'incident';
    item JSONB;
    item_index INTEGER;
    start_seconds INTEGER;
    end_seconds INTEGER;
    source_id TEXT;
    entity_ids TEXT[] := ARRAY[]::TEXT[];
    source_ids TEXT[];
    keyless TEXT;
    v_now TIMESTAMP WITHOUT TIME ZONE := now() AT TIME ZONE 'utc';
    v_editor TEXT := btrim(p_edited_by);
    v_revision INTEGER;
    v_status TEXT;
BEGIN
    IF p_edited_by IS NULL OR v_editor = '' THEN
        RAISE EXCEPTION 'An editor name is required';
    END IF;
    IF jsonb_typeof(p_edit) IS DISTINCT FROM 'object' OR jsonb_typeof(incident) IS DISTINCT FROM 'object'
        OR jsonb_typeof(p_edit->'entities') IS DISTINCT FROM 'array' OR jsonb_typeof(p_edit->'instruments') IS DISTINCT FROM 'array'
        OR jsonb_typeof(p_edit->'assets') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The edit must contain incident, entities, instruments and assets';
    END IF;

    PERFORM 1 FROM public.incidents
    WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Report not found for this video and model run'; END IF;

    -- Incident fields.
    IF incident->>'type' IS NULL OR NOT (incident->>'type' = ANY (ARRAY['road accident', 'burglary', 'explosion', 'assault', 'animal attack'])) THEN
        RAISE EXCEPTION 'Invalid incident type: %', incident->>'type';
    END IF;
    IF jsonb_typeof(incident->'start_timestamp') IS DISTINCT FROM 'number' OR jsonb_typeof(incident->'end_timestamp') IS DISTINCT FROM 'number'
        OR (incident->>'start_timestamp') !~ '^[0-9]{1,9}$' OR (incident->>'end_timestamp') !~ '^[0-9]{1,9}$' THEN
        RAISE EXCEPTION 'start_timestamp and end_timestamp must be non-negative integer seconds';
    END IF;
    start_seconds := (incident->>'start_timestamp')::INTEGER;
    end_seconds := (incident->>'end_timestamp')::INTEGER;
    IF end_seconds < start_seconds THEN
        RAISE EXCEPTION 'end_timestamp % is before start_timestamp %', end_seconds, start_seconds;
    END IF;
    IF jsonb_typeof(incident->'severity_level') IS DISTINCT FROM 'number' OR (incident->>'severity_level') !~ '^[1-5]$' THEN
        RAISE EXCEPTION 'severity_level must be an integer from 1 to 5';
    END IF;
    IF jsonb_typeof(incident->'description') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'description must be text';
    END IF;

    -- Every item names its AI origin (or null); refused before anything is written.
    SELECT string_agg(COALESCE(x.item->>kind.id_key, '?'), ', ') INTO keyless
    FROM (VALUES ('entities', 'entity_id'), ('instruments', 'instrument_id'), ('assets', 'asset_id')) AS kind(list, id_key)
    CROSS JOIN LATERAL jsonb_array_elements(p_edit->kind.list) AS x(item)
    WHERE jsonb_typeof(x.item->'source_id') IS NULL OR jsonb_typeof(x.item->'source_id') NOT IN ('string', 'null');
    IF keyless IS NOT NULL THEN
        RAISE EXCEPTION 'Items % have no source_id (the AI item each came from, null for an added item). Update incident-console-v2 to a version that sends source_id; this database does not guess an item''s origin', keyless;
    END IF;

    INSERT INTO public.human_reports AS h (incident_id, model_run_id, type, start_seconds, end_seconds, description, severity_level,
        revision, created_by, created_at, edited_by, edited_at)
    VALUES (p_incident_id, p_model_run_id, incident->>'type', start_seconds, end_seconds, incident->>'description',
        (incident->>'severity_level')::INTEGER, 1, v_editor, v_now, v_editor, v_now)
    ON CONFLICT (incident_id, model_run_id) DO UPDATE SET
        type = EXCLUDED.type, start_seconds = EXCLUDED.start_seconds, end_seconds = EXCLUDED.end_seconds,
        description = EXCLUDED.description, severity_level = EXCLUDED.severity_level,
        revision = h.revision + 1, edited_by = EXCLUDED.edited_by, edited_at = EXCLUDED.edited_at
    RETURNING h.revision INTO v_revision;

    DELETE FROM public.human_report_instruments WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    DELETE FROM public.human_report_assets WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    DELETE FROM public.human_report_entities WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;

    -- Entities: sequential E1..En.
    item_index := 0;
    source_ids := ARRAY[]::TEXT[];
    FOR item IN SELECT value FROM jsonb_array_elements(p_edit->'entities') LOOP
        item_index := item_index + 1;
        IF item->>'entity_id' IS DISTINCT FROM 'E' || item_index THEN
            RAISE EXCEPTION 'entity_id % is not sequential (expected E%)', item->>'entity_id', item_index;
        END IF;
        IF item->>'type' IS NULL OR NOT (item->>'type' = ANY (ARRAY['human', 'animal', 'unknown'])) THEN
            RAISE EXCEPTION 'Invalid entity type: %', item->>'type';
        END IF;
        IF jsonb_typeof(item->'description') IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'entity description must be text'; END IF;
        source_id := item->>'source_id';
        IF source_id IS NOT NULL THEN
            IF NOT EXISTS (SELECT 1 FROM public.entities e WHERE e.incident_id = p_incident_id AND e.model_run_id = p_model_run_id AND e.entity_id = source_id) THEN
                RAISE EXCEPTION '% names source_id %, which is not an AI entity of this run', item->>'entity_id', source_id;
            END IF;
            IF source_id = ANY (source_ids) THEN RAISE EXCEPTION 'AI entity % is the source of more than one entity', source_id; END IF;
            source_ids := source_ids || source_id;
        END IF;
        INSERT INTO public.human_report_entities (incident_id, model_run_id, entity_id, source_entity_id, type, description)
        VALUES (p_incident_id, p_model_run_id, item->>'entity_id', source_id, item->>'type', item->>'description');
        entity_ids := entity_ids || (item->>'entity_id');
    END LOOP;

    -- Instruments: sequential I1..In; holder is NULL or an edited entity.
    item_index := 0;
    source_ids := ARRAY[]::TEXT[];
    FOR item IN SELECT value FROM jsonb_array_elements(p_edit->'instruments') LOOP
        item_index := item_index + 1;
        IF item->>'instrument_id' IS DISTINCT FROM 'I' || item_index THEN
            RAISE EXCEPTION 'instrument_id % is not sequential (expected I%)', item->>'instrument_id', item_index;
        END IF;
        IF jsonb_typeof(item->'entity_id') IS NULL OR jsonb_typeof(item->'entity_id') NOT IN ('null', 'string')
            OR (item->>'entity_id' IS NOT NULL AND NOT (item->>'entity_id' = ANY (entity_ids))) THEN
            RAISE EXCEPTION '% references unknown entity_id %', item->>'instrument_id', item->>'entity_id';
        END IF;
        IF jsonb_typeof(item->'threat_level') IS DISTINCT FROM 'number' OR (item->>'threat_level') !~ '^[1-5]$' THEN
            RAISE EXCEPTION 'threat_level of % must be an integer from 1 to 5', item->>'instrument_id';
        END IF;
        IF jsonb_typeof(item->'name') IS DISTINCT FROM 'string' OR jsonb_typeof(item->'description') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'instrument name and description must be text';
        END IF;
        source_id := item->>'source_id';
        IF source_id IS NOT NULL THEN
            IF NOT EXISTS (SELECT 1 FROM public.instruments i WHERE i.incident_id = p_incident_id AND i.model_run_id = p_model_run_id AND i.instrument_id = source_id) THEN
                RAISE EXCEPTION '% names source_id %, which is not an AI instrument of this run', item->>'instrument_id', source_id;
            END IF;
            IF source_id = ANY (source_ids) THEN RAISE EXCEPTION 'AI instrument % is the source of more than one instrument', source_id; END IF;
            source_ids := source_ids || source_id;
        END IF;
        INSERT INTO public.human_report_instruments (incident_id, model_run_id, instrument_id, source_instrument_id, entity_id, name, description, threat_level)
        VALUES (p_incident_id, p_model_run_id, item->>'instrument_id', source_id, item->>'entity_id', item->>'name', item->>'description',
            (item->>'threat_level')::INTEGER);
    END LOOP;

    -- Assets: sequential A1..An.
    item_index := 0;
    source_ids := ARRAY[]::TEXT[];
    FOR item IN SELECT value FROM jsonb_array_elements(p_edit->'assets') LOOP
        item_index := item_index + 1;
        IF item->>'asset_id' IS DISTINCT FROM 'A' || item_index THEN
            RAISE EXCEPTION 'asset_id % is not sequential (expected A%)', item->>'asset_id', item_index;
        END IF;
        IF jsonb_typeof(item->'name') IS DISTINCT FROM 'string' OR jsonb_typeof(item->'description') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'asset name and description must be text';
        END IF;
        source_id := item->>'source_id';
        IF source_id IS NOT NULL THEN
            IF NOT EXISTS (SELECT 1 FROM public.assets a WHERE a.incident_id = p_incident_id AND a.model_run_id = p_model_run_id AND a.asset_id = source_id) THEN
                RAISE EXCEPTION '% names source_id %, which is not an AI asset of this run', item->>'asset_id', source_id;
            END IF;
            IF source_id = ANY (source_ids) THEN RAISE EXCEPTION 'AI asset % is the source of more than one asset', source_id; END IF;
            source_ids := source_ids || source_id;
        END IF;
        INSERT INTO public.human_report_assets (incident_id, model_run_id, asset_id, source_asset_id, name, description)
        VALUES (p_incident_id, p_model_run_id, item->>'asset_id', source_id, item->>'name', item->>'description');
    END LOOP;

    INSERT INTO public.review_status AS rs (incident_id, model_run_id, edited_by, edited_at)
    VALUES (p_incident_id, p_model_run_id, v_editor, v_now)
    ON CONFLICT (incident_id, model_run_id) DO UPDATE SET
        edited_by = EXCLUDED.edited_by,
        edited_at = EXCLUDED.edited_at,
        status = CASE WHEN rs.status = 'verified' THEN 'under review' ELSE rs.status END,
        verified_by = CASE WHEN rs.status = 'verified' THEN NULL ELSE rs.verified_by END,
        verified_at = CASE WHEN rs.status = 'verified' THEN NULL ELSE rs.verified_at END
    RETURNING rs.status INTO v_status;

    RETURN jsonb_build_object(
        'incidentId', p_incident_id,
        'modelRunId', p_model_run_id,
        'editedBy', v_editor,
        'editedAt', v_now,
        'duration', end_seconds - start_seconds,
        'revision', v_revision,
        'status', v_status
    );
END;
$$;

-- Compatibility shim: the midterm edit RPC's name, arguments and result keys. It writes the
-- reviewer version, never the AI rows, and like save_human_report_edit refuses items without
-- source_id: the midterm console, which sends none, gets the update message, not a guessed link.
-- Drop it once no deployed console calls it.
CREATE FUNCTION public.apply_structured_report_edit(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_edit JSONB,
    p_edited_by TEXT
) RETURNS JSONB
LANGUAGE sql SET search_path = ''
AS $$
    SELECT public.save_human_report_edit(p_incident_id, p_model_run_id, p_edit, p_edited_by);
$$;

-- One atomic review transition. Never writes edited_by/edited_at (those mean "last content
-- edit"). Verifying a report with no reviewer version first copies the AI report into one
-- (the captain's decision, 2026-10-20), so every verified report has a reviewer version.
CREATE FUNCTION public.set_review_status(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_status TEXT,
    p_reviewer TEXT
) RETURNS JSONB
LANGUAGE plpgsql SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMP WITHOUT TIME ZONE := now() AT TIME ZONE 'utc';
    v_reviewer TEXT := btrim(p_reviewer);
    v_current TEXT;
    v_created BOOLEAN := FALSE;
BEGIN
    IF p_status IS NULL OR NOT (p_status = ANY (ARRAY['unreviewed', 'under review', 'verified'])) THEN
        RAISE EXCEPTION 'Invalid review status: %', p_status;
    END IF;
    IF p_reviewer IS NULL OR v_reviewer = '' THEN
        RAISE EXCEPTION 'A reviewer name is required';
    END IF;
    PERFORM 1 FROM public.incidents WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Report not found for this video and model run'; END IF;

    SELECT status INTO v_current FROM public.review_status WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    IF COALESCE(v_current, 'unreviewed') = p_status THEN
        RETURN jsonb_build_object('incidentId', p_incident_id, 'modelRunId', p_model_run_id, 'status', p_status, 'changed', FALSE);
    END IF;

    IF p_status = 'verified' AND NOT EXISTS (
        SELECT 1 FROM public.human_reports WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id) THEN
        PERFORM public.create_human_report_from_ai(p_incident_id, p_model_run_id, v_reviewer, v_now);
        v_created := TRUE;
    END IF;

    INSERT INTO public.review_status AS rs (incident_id, model_run_id, status, verified_by, verified_at)
    VALUES (p_incident_id, p_model_run_id, p_status,
        CASE WHEN p_status = 'verified' THEN v_reviewer END, CASE WHEN p_status = 'verified' THEN v_now END)
    ON CONFLICT (incident_id, model_run_id) DO UPDATE SET
        status = EXCLUDED.status, verified_by = EXCLUDED.verified_by, verified_at = EXCLUDED.verified_at;

    RETURN jsonb_build_object(
        'incidentId', p_incident_id,
        'modelRunId', p_model_run_id,
        'status', p_status,
        'verifiedBy', CASE WHEN p_status = 'verified' THEN v_reviewer END,
        'verifiedAt', CASE WHEN p_status = 'verified' THEN v_now END,
        'changed', TRUE,
        'humanVersionCreated', v_created
    );
END;
$$;

-- 6. Security -----------------------------------------------------------------------------------
-- Services use service_role (PostgREST) or postgres (direct DSN); both have BYPASSRLS. RLS with
-- no policies therefore denies everyone else and changes nothing for the services.

ALTER TABLE public.videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.queries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.review_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.severity_eval_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entity_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instrument_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.asset_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_crops ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.query_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.human_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.human_report_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.human_report_instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.human_report_assets ENABLE ROW LEVEL SECURITY;

-- Belt and braces on top of the default privileges in section 1: whatever exists in public now,
-- however it was created, is service_role-only.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
-- The views are read-only by intent: readers use them, writers use the tables and RPCs.
REVOKE INSERT, UPDATE, DELETE ON public.effective_incidents, public.effective_entities,
    public.effective_instruments, public.effective_assets FROM service_role;

-- Fail the migration if anything is still exposed (the same checks as supabase/tests/security_check.sql).
DO $$
DECLARE
    problems TEXT;
BEGIN
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO problems
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity;
    IF problems IS NOT NULL THEN RAISE EXCEPTION 'RLS is off on: %', problems; END IF;

    SELECT string_agg(DISTINCT c.relname || ' (' || r.rolname || ')', ', ') INTO problems
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN (SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')) r
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
      AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(r.rolname, c.oid, 'USAGE,SELECT,UPDATE')
               ELSE has_table_privilege(r.rolname, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END;
    IF problems IS NOT NULL THEN RAISE EXCEPTION 'anon/authenticated can reach: %', problems; END IF;

    SELECT string_agg(DISTINCT p.oid::regprocedure::TEXT || ' (' || r.rolname || ')', ', ') INTO problems
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    CROSS JOIN (SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')) r
    WHERE n.nspname = 'public'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
      AND has_function_privilege(r.rolname, p.oid, 'EXECUTE');
    IF problems IS NOT NULL THEN RAISE EXCEPTION 'anon/authenticated can execute: %', problems; END IF;

    SELECT string_agg(p.oid::regprocedure::TEXT, ', ') INTO problems
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
      AND (p.prosecdef OR NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) cfg WHERE cfg LIKE 'search_path=%'));
    IF problems IS NOT NULL THEN RAISE EXCEPTION 'SECURITY DEFINER or mutable search_path: %', problems; END IF;
END;
$$;

NOTIFY pgrst, 'reload schema';

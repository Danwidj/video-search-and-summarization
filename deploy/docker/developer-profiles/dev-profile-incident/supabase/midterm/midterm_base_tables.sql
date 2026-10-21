-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Midterm base tables as they existed before the first migration, reconstructed from the live
-- catalog on 2026-10-20 (no file in the repo creates them). This file + midterm/migrations/ up to
-- 20260928000000 + 20261016120000 rebuilds midterm exactly (verified: identical columns, keys,
-- defaults, indexes and all 14 function bodies). Test fixture only.

-- videos
CREATE TABLE public.videos (
    id character varying(20) NOT NULL,
    filepath character varying(1024),
    uploaded_datetime timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    duration integer,
    source character varying(512),
    CONSTRAINT videos_pkey PRIMARY KEY (id)
);

-- queries
CREATE TABLE public.queries (
    id character varying(20) NOT NULL,
    query_text text NOT NULL,
    submitted_datetime timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT queries_pkey PRIMARY KEY (id)
);

-- model_runs
CREATE TABLE public.model_runs (
    id character varying(20) NOT NULL,
    model_name character varying(128) NOT NULL,
    model_version character varying(128),
    prompt_version character varying(64),
    run_datetime timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    notes text,
    CONSTRAINT model_runs_pkey PRIMARY KEY (id)
);

-- incidents
CREATE TABLE public.incidents (
    incident_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    type character varying(32),
    start_timestamp character varying(32),
    end_timestamp character varying(32),
    duration integer,
    description text,
    severity_level integer,
    confidence_score double precision,
    CONSTRAINT incidents_pkey PRIMARY KEY (incident_id, model_run_id),
    CONSTRAINT incidents_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES videos(id) ON DELETE CASCADE,
    CONSTRAINT incidents_model_run_id_fkey FOREIGN KEY (model_run_id) REFERENCES model_runs(id) ON DELETE CASCADE
);

-- reports
CREATE TABLE public.reports (
    id character varying(20) NOT NULL,
    incident_id character varying(20) NOT NULL,
    query_id character varying(20),
    model_run_id character varying(20) NOT NULL,
    filepath character varying(1024),
    generated_datetime timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT reports_pkey PRIMARY KEY (id),
    CONSTRAINT reports_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT reports_query_id_fkey FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE SET NULL
);

-- entities
CREATE TABLE public.entities (
    incident_id character varying(20) NOT NULL,
    entity_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    type character varying(16),
    description text,
    image character varying(1024),
    CONSTRAINT entities_pkey PRIMARY KEY (incident_id, entity_id, model_run_id),
    CONSTRAINT entities_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- instruments
CREATE TABLE public.instruments (
    incident_id character varying(20) NOT NULL,
    instrument_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    entity_id character varying(20),
    name character varying(256),
    description text,
    threat_level integer,
    image character varying(1024),
    CONSTRAINT instruments_pkey PRIMARY KEY (incident_id, instrument_id, model_run_id),
    CONSTRAINT instruments_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- assets
CREATE TABLE public.assets (
    incident_id character varying(20) NOT NULL,
    asset_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    name character varying(256),
    description text,
    image character varying(1024),
    CONSTRAINT assets_pkey PRIMARY KEY (incident_id, asset_id, model_run_id),
    CONSTRAINT assets_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- gt_incidents
CREATE TABLE public.gt_incidents (
    incident_id character varying(20) NOT NULL,
    type character varying(32),
    start_timestamp character varying(32),
    end_timestamp character varying(32),
    duration integer,
    description text,
    severity_level integer,
    labelled_by character varying(256),
    labelled_datetime timestamp without time zone,
    CONSTRAINT gt_incidents_pkey PRIMARY KEY (incident_id),
    CONSTRAINT gt_incidents_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- gt_entities
CREATE TABLE public.gt_entities (
    incident_id character varying(20) NOT NULL,
    entity_id character varying(20) NOT NULL,
    type character varying(16),
    description text,
    image character varying(1024),
    CONSTRAINT gt_entities_pkey PRIMARY KEY (incident_id, entity_id),
    CONSTRAINT gt_entities_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES gt_incidents(incident_id) ON DELETE CASCADE
);

-- gt_instruments
CREATE TABLE public.gt_instruments (
    incident_id character varying(20) NOT NULL,
    instrument_id character varying(20) NOT NULL,
    entity_id character varying(20),
    name character varying(256),
    description text,
    threat_level integer,
    image character varying(1024),
    CONSTRAINT gt_instruments_pkey PRIMARY KEY (incident_id, instrument_id),
    CONSTRAINT gt_instruments_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES gt_incidents(incident_id) ON DELETE CASCADE
);

-- gt_assets
CREATE TABLE public.gt_assets (
    incident_id character varying(20) NOT NULL,
    asset_id character varying(20) NOT NULL,
    name character varying(256),
    description text,
    image character varying(1024),
    CONSTRAINT gt_assets_pkey PRIMARY KEY (incident_id, asset_id),
    CONSTRAINT gt_assets_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES gt_incidents(incident_id) ON DELETE CASCADE
);

-- entity_matches
CREATE TABLE public.entity_matches (
    incident_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    entity_id character varying(20) NOT NULL,
    gt_entity_id character varying(20) NOT NULL,
    similarity_score double precision NOT NULL,
    matched_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT entity_matches_pkey PRIMARY KEY (incident_id, model_run_id, entity_id),
    CONSTRAINT entity_matches_incident_id_entity_id_model_run_id_fkey FOREIGN KEY (incident_id, entity_id, model_run_id) REFERENCES entities(incident_id, entity_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT entity_matches_incident_id_gt_entity_id_fkey FOREIGN KEY (incident_id, gt_entity_id) REFERENCES gt_entities(incident_id, entity_id) ON DELETE CASCADE
);

-- instrument_matches
CREATE TABLE public.instrument_matches (
    incident_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    instrument_id character varying(20) NOT NULL,
    gt_instrument_id character varying(20) NOT NULL,
    similarity_score double precision NOT NULL,
    matched_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT instrument_matches_pkey PRIMARY KEY (incident_id, model_run_id, instrument_id),
    CONSTRAINT instrument_matches_incident_id_gt_instrument_id_fkey FOREIGN KEY (incident_id, gt_instrument_id) REFERENCES gt_instruments(incident_id, instrument_id) ON DELETE CASCADE,
    CONSTRAINT instrument_matches_incident_id_instrument_id_model_run_id_fkey FOREIGN KEY (incident_id, instrument_id, model_run_id) REFERENCES instruments(incident_id, instrument_id, model_run_id) ON DELETE CASCADE
);

-- asset_matches
CREATE TABLE public.asset_matches (
    incident_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    asset_id character varying(20) NOT NULL,
    gt_asset_id character varying(20) NOT NULL,
    similarity_score double precision NOT NULL,
    matched_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT asset_matches_pkey PRIMARY KEY (incident_id, model_run_id, asset_id),
    CONSTRAINT asset_matches_incident_id_asset_id_model_run_id_fkey FOREIGN KEY (incident_id, asset_id, model_run_id) REFERENCES assets(incident_id, asset_id, model_run_id) ON DELETE CASCADE,
    CONSTRAINT asset_matches_incident_id_gt_asset_id_fkey FOREIGN KEY (incident_id, gt_asset_id) REFERENCES gt_assets(incident_id, asset_id) ON DELETE CASCADE
);

-- review_status
CREATE TABLE public.review_status (
    incident_id character varying(20) NOT NULL,
    model_run_id character varying(20) NOT NULL,
    status character varying(32) DEFAULT 'unreviewed'::character varying NOT NULL,
    verified_by character varying(256),
    verified_at timestamp without time zone,
    edited_by character varying(256),
    edited_at timestamp without time zone,
    CONSTRAINT review_status_pkey PRIMARY KEY (incident_id, model_run_id),
    CONSTRAINT review_status_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- notifications
CREATE TABLE public.notifications (
    id serial NOT NULL,
    incident_id character varying(20),
    model_run_id character varying(20),
    severity integer,
    created_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    acknowledged boolean DEFAULT false NOT NULL,
    CONSTRAINT notifications_pkey PRIMARY KEY (id),
    CONSTRAINT notifications_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- severity_eval_log
CREATE TABLE public.severity_eval_log (
    id serial NOT NULL,
    incident_id character varying(20),
    model_run_id character varying(20),
    ai_severity integer,
    human_severity integer,
    rater character varying(256),
    rated_at timestamp without time zone DEFAULT (now() AT TIME ZONE 'utc'::text),
    CONSTRAINT severity_eval_log_pkey PRIMARY KEY (id),
    CONSTRAINT severity_eval_log_incident_id_model_run_id_fkey FOREIGN KEY (incident_id, model_run_id) REFERENCES incidents(incident_id, model_run_id) ON DELETE CASCADE
);

-- incident_reports
CREATE TABLE public.incident_reports (
    id serial NOT NULL,
    video_id integer,
    incident_type character varying(64),
    severity integer,
    confidence double precision,
    incident_start character varying(32),
    incident_end character varying(32),
    incident_start_confirmed boolean,
    description text,
    persons jsonb,
    location character varying(512),
    status character varying(32) NOT NULL,
    verified_by character varying(256),
    verified_at timestamp without time zone,
    edited_by character varying(256),
    edited_at timestamp without time zone,
    created_at timestamp without time zone,
    duration_sec integer,
    model_version character varying(128),
    CONSTRAINT incident_reports_pkey PRIMARY KEY (id)
);

-- incident_entities
CREATE TABLE public.incident_entities (
    id serial NOT NULL,
    report_id integer NOT NULL,
    entity_id character varying(16),
    type character varying(16),
    description text,
    image_key character varying(1024),
    CONSTRAINT incident_entities_pkey PRIMARY KEY (id),
    CONSTRAINT incident_entities_report_id_fkey FOREIGN KEY (report_id) REFERENCES incident_reports(id) ON DELETE CASCADE
);

-- incident_instruments
CREATE TABLE public.incident_instruments (
    id serial NOT NULL,
    report_id integer NOT NULL,
    instrument_id character varying(16),
    entity_id character varying(16),
    name character varying(256),
    description text,
    threat_level integer,
    image_key character varying(1024),
    CONSTRAINT incident_instruments_pkey PRIMARY KEY (id),
    CONSTRAINT incident_instruments_report_id_fkey FOREIGN KEY (report_id) REFERENCES incident_reports(id) ON DELETE CASCADE
);

-- incident_assets
CREATE TABLE public.incident_assets (
    id serial NOT NULL,
    report_id integer NOT NULL,
    asset_id character varying(16),
    name character varying(256),
    description text,
    image_key character varying(1024),
    CONSTRAINT incident_assets_pkey PRIMARY KEY (id),
    CONSTRAINT incident_assets_report_id_fkey FOREIGN KEY (report_id) REFERENCES incident_reports(id) ON DELETE CASCADE
);

-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Migration: Enable Row-Level Security and lockdown anonymous access
--
-- Closes known issue 8 and follow-up 5 (dev-profile-incident/.docs/status.md):
-- 1. Revokes execute privilege on insert_incident from PUBLIC, anon, and authenticated.
-- 2. Enables Row-Level Security on all 18 operational/eval tables and 4 legacy tables.
-- 3. Revokes all table and sequence permissions in schema public from anon and authenticated.
-- 4. Updates default privileges for objects later created by the migrating role (postgres):
--    no table, sequence or function grants to anon/authenticated in schema public, and no
--    EXECUTE for PUBLIC on new functions in any schema. Objects created by other roles are
--    not covered, so each new function still carries its own explicit REVOKE.
-- 5. Leaves service_role and postgres unrestricted by RLS through their BYPASSRLS attribute.

-- 1. Close insert_incident RPC privilege loophole
REVOKE ALL ON FUNCTION public.insert_incident(TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, INTEGER, DOUBLE PRECISION)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.insert_incident(TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, INTEGER, DOUBLE PRECISION)
    TO service_role;

-- 2. Enable Row-Level Security on all public tables (Default Deny for non-bypass roles)
-- Shared reference tables
ALTER TABLE public.videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.queries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_runs ENABLE ROW LEVEL SECURITY;

-- Model output tables
ALTER TABLE public.incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY;

-- Review and operational tables
ALTER TABLE public.review_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.severity_eval_log ENABLE ROW LEVEL SECURITY;

-- Ground-truth and evaluation tables
ALTER TABLE public.gt_incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gt_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entity_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instrument_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.asset_matches ENABLE ROW LEVEL SECURITY;

-- Legacy pre-v1 tables (secured pending formal drop approval)
ALTER TABLE public.incident_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_assets ENABLE ROW LEVEL SECURITY;

-- 3. Explicitly revoke table privileges from anon and authenticated
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- 4. Adjust default privileges for future objects created by the migrating role
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- Ensure service_role and postgres retain full privileges on future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;

-- 5. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';

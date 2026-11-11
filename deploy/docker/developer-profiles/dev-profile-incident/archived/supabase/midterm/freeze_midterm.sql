-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Freeze the MIDTERM database (project rfevukimyftzbxlehwel) as a read-only record.
-- Run once, as postgres, in the Supabase SQL editor of the midterm project, at the start of the
-- switchover window (before the copy). Undo with unfreeze_midterm.sql.
--
-- 1. Lockdown (what 20261016000000_enable_rls_and_lockdown_anon.sql would have done): RLS on every
--    table, nothing for anon/authenticated/PUBLIC. Closes the open anon key for good.
-- 2. No more writes through the API: service_role keeps SELECT and the read RPCs, loses
--    INSERT/UPDATE/DELETE/TRUNCATE and every write RPC. A console, agent, loader or eval run still
--    pointed at midterm fails loudly ("permission denied") instead of writing to the wrong database.
-- 3. No more writes over the direct DSN: new postgres sessions start read-only.

BEGIN;

-- 1. Lockdown --------------------------------------------------------------------------------
DO $$
DECLARE t RECORD;
BEGIN
    FOR t IN SELECT c.oid::regclass AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t.rel);
    END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
-- pgvector lives in public on midterm; its functions were callable by anon. Keep them for service_role.
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- 2. Read-only for service_role ----------------------------------------------------------------
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM service_role;
REVOKE UPDATE ON ALL SEQUENCES IN SCHEMA public FROM service_role;
REVOKE EXECUTE ON FUNCTION
    public.insert_incident(TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, INTEGER, DOUBLE PRECISION),
    public.apply_structured_report_edit(TEXT, TEXT, JSONB, TEXT),
    public.apply_incident_report_patch(TEXT, TEXT, JSONB, JSONB),
    public.replace_incident_evidence(TEXT, TEXT, JSONB, JSONB, JSONB),
    public.select_official_report(TEXT, TEXT, TEXT),
    public.clear_official_report(TEXT, TEXT)
FROM service_role;

-- 3. Direct-DSN sessions (eval, scripts, v1 console) start read-only from the next connection.
ALTER ROLE postgres SET default_transaction_read_only = on;

COMMIT;

NOTIFY pgrst, 'reload schema';

-- Check (expect: rls_off 0, anon 0, service_role can read but not insert):
SELECT
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity) AS rls_off,
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r' AND has_table_privilege('anon', c.oid, 'SELECT')) AS anon_readable,
    has_table_privilege('service_role', 'public.incidents', 'SELECT') AS service_reads,
    has_table_privilege('service_role', 'public.incidents', 'INSERT') AS service_writes;

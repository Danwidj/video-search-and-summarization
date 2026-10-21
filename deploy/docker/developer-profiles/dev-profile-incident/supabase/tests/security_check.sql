-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Read-only security audit of schema public. Run it in the Supabase SQL editor or with psql
-- against the finals database after the baseline, after the copy, and after every later
-- migration. It returns one row per problem; no rows means:
--   RLS is on for every table; anon/authenticated can reach no table, view, sequence or function;
--   PUBLIC has no EXECUTE; no SECURITY DEFINER function; every function pins its search_path;
--   new objects created by postgres in public will not be granted to anon/authenticated;
--   pgvector is not installed in public.
SELECT 'rls off' AS problem, c.relname AS object
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
UNION ALL
SELECT 'reachable by ' || r.rolname, c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN (SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')) r
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
  AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(r.rolname, c.oid, 'USAGE,SELECT,UPDATE')
           ELSE has_table_privilege(r.rolname, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END
UNION ALL
SELECT 'executable by ' || r.rolname, p.oid::regprocedure::TEXT
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
CROSS JOIN (SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')) r
WHERE n.nspname = 'public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
  AND has_function_privilege(r.rolname, p.oid, 'EXECUTE')
UNION ALL
SELECT 'security definer or mutable search_path', p.oid::regprocedure::TEXT
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
  AND (p.prosecdef OR NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) cfg WHERE cfg LIKE 'search_path=%'))
UNION ALL
SELECT 'default privileges grant ' || d.defaclobjtype::TEXT || ' to ' || CASE WHEN g.grantee = 0 THEN 'PUBLIC' ELSE g.grantee::regrole::TEXT END, 'schema public, owner ' || d.defaclrole::regrole::TEXT
FROM pg_default_acl d
CROSS JOIN LATERAL aclexplode(d.defaclacl) g
WHERE d.defaclrole = 'postgres'::regrole
  AND (d.defaclnamespace = 'public'::regnamespace OR d.defaclnamespace = 0)
  AND (g.grantee = 0 OR g.grantee IN (SELECT oid FROM pg_roles WHERE rolname IN ('anon', 'authenticated')))
UNION ALL
SELECT 'new functions get EXECUTE for PUBLIC', 'owner postgres (no global default revoke)'
WHERE NOT EXISTS (SELECT 1 FROM pg_default_acl WHERE defaclrole = 'postgres'::regrole AND defaclnamespace = 0 AND defaclobjtype = 'f')
UNION ALL
SELECT 'view without security_invoker', c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'v'
  AND NOT COALESCE(c.reloptions @> ARRAY['security_invoker=true'] OR c.reloptions @> ARRAY['security_invoker=on'], FALSE)
UNION ALL
SELECT 'extension in public', e.extname
FROM pg_extension e WHERE e.extnamespace = 'public'::regnamespace
ORDER BY 1, 2;

# Midterm database: frozen record — never push

This folder is the record of the **midterm** Supabase project (`rfevukimyftzbxlehwel`). The finals
project is built from scratch by [`../migrations/`](../migrations/) and filled by
[`../copy/`](../copy/) (see [`../README.md`](../README.md)). Nothing here is ever applied to finals.

- **Not a CLI workdir.** `supabase db push` only reads `<workdir>/supabase/migrations/`, so these
  files can never be pushed by accident. Pushing the finals folder at midterm fails too: midterm's
  history lists versions that no longer exist in `../migrations/` ("remote migration versions not
  found").
- **Unchanged.** The 14 files in `migrations/` were moved here with `git mv` and are byte for byte
  what midterm was built from. Do not edit them; a finals change is a new file in `../migrations/`.

## What is in here

| File | What it is |
|---|---|
| `migrations/*.sql` (14) | The midterm migration history, in order |
| `midterm_base_tables.sql` | The base tables no repo file created (they came from `incident-console/db.py` metadata via `init_schema()`), rebuilt from the live catalog on 2026-10-20. Test fixture only |
| `freeze_midterm.sql` | Makes midterm a read-only record: RLS on every table, nothing for `anon`/`authenticated`/`PUBLIC`, `service_role` keeps `SELECT` and the read RPCs but loses every write, and new `postgres` sessions start read-only. Run once in the midterm SQL editor at the cutover |
| `unfreeze_midterm.sql` | Undo of the freeze (writes come back; the anon lockdown stays). Rollback only |

`midterm_base_tables.sql` plus the applied migrations below rebuilds midterm exactly (all 22
tables and all 14 live function bodies, compared with the live catalog on 2026-10-20).
[`../tests/test_freeze.py`](../tests/test_freeze.py) builds that replica locally and proves the
freeze and unfreeze files:

```bash
cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_freeze.py
```

## The 14 migrations and what midterm actually ran

Midterm's `supabase_migrations.schema_migrations` does not match what is applied, which is one
reason finals starts from a clean baseline.

| Migration | Content | Applied to midterm | In midterm's history |
|---|---|---|---|
| `20260917141225_insert_incident_function` | `insert_incident` RPC: atomic delete-then-insert of `incidents` + `review_status` | yes | yes |
| `20260925031000_schema_defaults_and_precision` | Server-side UTC defaults; `p_confidence_score DOUBLE PRECISION` | yes | yes |
| `20260926120000_list_incident_report_summaries` | Report library RPC (later replaced) | yes | **no** |
| `20260927120000_filter_report_evidence` | Evidence filters; `replace_incident_evidence` (superseded) | yes | yes |
| `20260927130000_dashboard_analytics` | `get_incident_dashboard` | yes | yes |
| `20260927140000_atomic_report_edits_and_exact_dashboard_links` | Weekday/severity filters; `apply_incident_report_patch` (superseded) | yes | as `20260927075044` |
| `20260927150000_report_summaries_contract_v2_title` | Contract-v2 titles in the library | yes | yes |
| `20260927160000_apply_structured_report_edit` | Structured reviewer edit RPC (in place on the AI rows) | yes | yes |
| `20260927170000_official_report_selection` | `videos.selected_model_run_id`; select/clear official report | yes | yes |
| `20260927180000_official_dashboard_and_library_filters` | Canonical-type helpers; official-only dashboard | yes | yes |
| `20260928000000_local_time_heatmap_and_time_filters` | `p_timezone` on dashboard and library | yes | **no** |
| `20261016000000_enable_rls_and_lockdown_anon` | RLS and anon lockdown | **no** (`freeze_midterm.sql` includes its effect) | no |
| `20261016010000_legacy_taxonomy_and_orphan_cleanup` | Relabel `fighting`/`animal`/`person`; delete 20 orphan runs | **no** (finals gets both through the copy) | no |
| `20261016120000_mvp2_evidence_search_and_crops` | pgvector (in `public`), `evidence_crops`, `query_results`, `search_evidence_items` | yes | **no** |

Security on midterm before the freeze: RLS on only `evidence_crops` and `query_results`;
`anon`/`authenticated` held every privilege on the other 20 tables; `insert_incident` was
executable by `PUBLIC`. Background: [`../../.docs/decisions.md`](../../.docs/decisions.md)
("One Supabase project per phase").

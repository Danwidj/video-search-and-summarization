# Incident Profile Status

> **As of 2026-10-22.** A short snapshot of what works, what is pending and what is known to be wrong. Rewrite it as reality changes; do not append history.

## 1. What is live

| Area | State | Where |
|---|---|---|
| Console (`incident-console-v2`) | Upload, analysis on `incident-contract-v3` with a three-model picker, run history and re-analysis, structured reviewer edits, explicit official report, official-incident dashboard. API routes reach Supabase through the middle layer (ports and adapters), except analysis saving and run history. The report page renders on the server through the same use case; the other pages still fetch `/api/*` from the browser. Merged in PR 149 and runs against the live finals database (`effective_*` views, `set_review_status`, `save_human_report_edit`) | [`analysis-schema.md`](analysis-schema.md), [`architecture.md`](architecture.md), [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md) |
| Analysis modes | Gateway (`vlm-gateway`, zero GPU) and agent (native `vss-agent` on `kwanz-ws`) share one contract, validation policy and attempt recording | [`analysis-schema.md`](analysis-schema.md) |
| Storage | Supabase rows (finals project) plus Cloudflare R2 videos; uploads verified by `HeadObject` before analysis | [`data.md`](data.md) |
| Evaluation | Standalone P1/RP1 pipeline in `eval/` on the same contract; Tier 1 ground-truth scoring | `eval/README.md` |
| Launcher | `./start.sh --mode local\|vm` with SSH preflight, self-healing VM deploy, stop-on-last-exit coordination via VM flock, and an always-on search route. Launches `incident-console-v2`, the only console; the Streamlit v1 console is archived under `archived/incident-console/` and never started | [`incident-profile-operations.md`](incident-profile-operations.md) |
| Mocks | `base_profile_mock` (:7777) and `search_profile_mock` (:7778), including search and chat routes | `mock-backend/` |

## 2. MVP2: natural-language evidence search

Specification and architecture: [`mvp2/README.md`](mvp2/README.md).

- **Delivered:** `search-contract-v1` and `chat-contract-v1`; crop evidence service; `vss-agent` search route (`SupabaseSearchStore`, R2 presigned crop URLs, always-on critic with `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS`); chat route; `evidence_crops` / `query_results` / `search_evidence_items` migration; the analyze route writes `report_revisions` with evidence crops, and `POST /api/v1/incidents/evidence-embeddings` serves the embeddings the console stores in `evidence_crops`.
- **Live on `kwanz-ws`:** not re-verified since the move to `report_revisions`. The 2026-10-18 check of the retired backfill loader (64 of 69 items loaded) no longer applies; re-run the search checks in [`vm-api-contracts.md`](vm-api-contracts.md) once the console fills `evidence_crops` from official revisions.
- **In progress:** frontend search UI (the console's report page chat already calls `POST /api/v1/incidents/chat`; the console's search port mirrors `search-contract-v1`; its agent adapter is not written yet); retrieval eval: specification in [`mvp2/eval.md`](mvp2/eval.md) (tracks, metrics, dataset rules, proposals awaiting approval); harness and query set not written; data layer work.
- **Not started:** multi-subagent routing config; full RT-CV / RT-Embed indexing; retrieval benchmark implementation and runs ([`mvp2/eval.md`](mvp2/eval.md) Track R).

## 3. Database status

The finals Supabase project (baseline [`supabase/migrations/20261020000000_finals_baseline.sql`](../supabase/migrations/20261020000000_finals_baseline.sql)) is the live database; both the laptop console and the VM agent point at it. Midterm (`rfevukimyftzbxlehwel`) is the archived record; the historical copy and freeze procedures are in [`supabase/README.md`](../supabase/README.md).

The finals baseline incorporates all prior migration effects:
- `p_timezone` parameter on the report library and dashboard RPCs (`list_incident_report_summaries`, `get_incident_dashboard`);
- Row-Level Security enabled on all 20 public tables, with permissions revoked from `PUBLIC`, `anon` and `authenticated` (services authenticate via `service_role` or `postgres`, both having `BYPASSRLS`);
- Legacy labels relabelled during copy (`fighting` to `assault`, `animal` to `animal attack`, `person` to `human`), with query-time canonical folding retained as a guard;
- The four legacy pre-v1 tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`), four retired v1 tables (`asset_matches`, `entity_matches`, `instrument_matches`, `notifications`), and ground-truth / eval tables (`gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets`, `severity_eval_log`) are dropped from the schema.

There are no pending database migrations.

## 4. Known issues

1. **Two writers in agent mode.** The console writes every row; the agent persists only standalone calls (no `model_run_id`) and never writes `videos`. Consolidating writers is not planned in detail.
2. **Model output lives in `model_runs.notes` (TEXT).** Intentional, as an immutable per-attempt record; queried via `try_parse_jsonb` and a `like` pre-filter. A JSONB column or index would be needed at volume.
3. **Cosmos models often break the timeline rule** (lead-up or aftermath events outside the incident window). Recorded, never repaired; see [`analysis-schema.md`](analysis-schema.md) section 7.
4. **One run has no recorded outcome.** `m86a5c319e26659804b0` predates recorded outcomes and shows as `valid_first_pass` (inferred).
5. **`other` incident type in one run's notes** (`m5629b0938e679c9873d`, no incident row) stays, because attempt notes are immutable.
6. **`selected_by` / `selected_at` can outlive a cleared selection**; the UI treats a NULL `selected_model_run_id` as no official report.
7. **Fixed P1 eval run ids overwrite benchmark rows** in the database; runs also keep an immutable copy under `results/runs/`.
8. **Agent runtime video-bounds exception.** `vss_agents.incident_contract` supports contextual `WINDOW_BEYOND_VIDEO` and `TIMELINE_BEYOND_VIDEO` rules when given `video_duration_seconds`. At runtime, `vss-agent` has no R2 credentials to perform byte-range reads on MP4 headers; in agent mode, the console performs the header read and enforces the video-bounds rule upon receiving agent output.

## 5. Follow-ups

- Run the eval benchmark under `core-scored-v1` (malformed-ID frequency, per-model core and enrichment failure rates).
- Consider a contract v4 with ID patterns only if the malformed-ID evidence justifies it (it changes eval).

## 6. Live VM configuration (`kwanz-ws`)

Read from `generated.env.remote`; verify with `incident-operate-vm` before relying on it.

| Setting | Value |
|---|---|
| `VSS_APPS_DIR` / `VSS_DATA_DIR` | `/srv/rise-up/vss/deploy/docker` / `/srv/rise-up/vss-apps-data` |
| `HOST_IP` | VM LAN address; changes with DHCP and is rewritten by `.scripts/vm-ensure-docker.sh` |
| `EXTERNAL_IP` | `localhost` (tunnelled browser access) |
| `VSS_AGENT_HOST` | `127.0.0.1` (loopback only; haproxy reaches it via `VSS_AGENT_BACKEND_HOST=127.0.0.1` in `compose.override.yml`, the laptop via the SSH tunnel) |
| `VSS_AGENT_CONFIG_FILE` | `./deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` |
| `STREAM_PROCESSOR_HTTP_PORT` | `10000` |
| `LLM_NAME` / `VLM_NAME` | `nvidia/nemotron-3-ultra` / `nvidia/cosmos-3-super-reasoner` |
| `LLM_BASE_URL` / `VLM_BASE_URL` | `https://switchyard-13doh4lsz.brevlab.com` (no trailing `/v1`) |
| `LLM_MODEL_TYPE` / `VLM_MODEL_TYPE` | `openai` |
| `GPU allocation` | GPU 0 only (`CUDA_VISIBLE_DEVICES=0`, `NVIDIA_VISIBLE_DEVICES=0`, all Docker appliances and native services pinned to GPU 0; GPU 1 reserved for co-tenant training workloads) |
| Secrets | `OPENAI_API_KEY`, `NVIDIA_API_KEY`, `NGC_CLI_API_KEY`, `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (set, never printed) |

The VM `vss-agent` virtualenv is installed editable from the repository checkout (`services/agent`); see [`incident-profile-operations.md`](incident-profile-operations.md).

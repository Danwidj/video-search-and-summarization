# Incident Profile Status

> **As of 2026-10-23.** A short snapshot of what works, what is pending and what is known to be wrong. Rewrite it as reality changes; do not append history.

## 1. What is live

| Area | State | Where |
|---|---|---|
| Console (`incident-console-v2`) | Upload, analysis on `incident-contract-v4` with a three-model picker, versioned reports (History, Save, Restore, evidence-image replacement), explicit official revision, official-revision dashboard, run history and re-generation with a reviewer prompt. API routes reach Supabase through the middle layer (ports and adapters), except analysis saving. Requires the versioned-report schema (`report_revisions`, `evidence_crops`, `query_results`, `videos.official_revision_id`, `save_human_revision`, `set_official_revision`) delivered by the schema task | [`analysis-schema.md`](analysis-schema.md), [`architecture.md`](architecture.md), [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md) |
| Analysis modes | Gateway (`vlm-gateway`, zero GPU) and agent (native `vss-agent` on `kwanz-ws`) share one contract, validation policy and attempt recording | [`analysis-schema.md`](analysis-schema.md) |
| Storage | Versioned `report_revisions` rows plus Cloudflare R2 videos and evidence images; uploads verified by `HeadObject` before analysis | [`data.md`](data.md) |
| Evaluation | Standalone P1/RP1 pipeline in `eval/` on the same contract; Tier 1 ground-truth scoring | `eval/README.md` |
| Launcher | `./start.sh --mode mock\|vm` with SSH preflight, self-healing VM deploy, stop-on-last-exit coordination via VM flock, and an always-on search route. Launches `incident-console-v2`, the only console; the Streamlit v1 console is archived under `archived/incident-console/` and never started | [`incident-profile-operations.md`](incident-profile-operations.md) |
| Mocks | `base_profile_mock` (:7777) and `search_profile_mock` (:7778), including search and chat routes | `mock-backend/` |

## 2. MVP2: natural-language evidence search

Specification and architecture: [`mvp2/README.md`](mvp2/README.md).

- **Delivered:** `search-contract-v1` and `chat-contract-v1`; crop evidence service; `vss-agent` search route (`SupabaseSearchStore`, R2 presigned crop URLs, always-on critic with `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS`); chat route; `evidence_crops` / `query_results` / `search_evidence_items` migration; the analyze route writes `report_revisions` with evidence crops; `POST /api/v1/incidents/evidence-embeddings` serves the embeddings; and marking a revision official rebuilds that incident's `evidence_crops` from it.
- **Live on `kwanz-ws`:** not re-verified since the move to `report_revisions`. The 2026-10-18 check of the retired backfill loader (64 of 69 items loaded) no longer applies; re-run the search checks in [`vm-api-contracts.md`](vm-api-contracts.md) after marking a console revision official.
- **In progress:** frontend search UI (the console's report page chat already calls `POST /api/v1/incidents/chat`; the console's search port mirrors `search-contract-v1`; its agent adapter is not written yet); retrieval eval: specification in [`mvp2/eval.md`](mvp2/eval.md) (tracks, metrics, dataset rules, proposals awaiting approval); harness and query set not written; data layer work.
- **Not started:** multi-subagent routing config; full RT-CV / RT-Embed indexing; retrieval benchmark implementation and runs ([`mvp2/eval.md`](mvp2/eval.md) Track R).

## 3. Database status

The finals Supabase project (baseline [`supabase/migrations/20261020000000_finals_baseline.sql`](../supabase/migrations/20261020000000_finals_baseline.sql), then the versioned-report schema and functions from the schema task) is the live database; both the laptop console and the VM agent point at it. Midterm (`rfevukimyftzbxlehwel`) is the archived record; the historical copy and freeze procedures are in [`supabase/README.md`](../supabase/README.md).

The finals baseline incorporates all prior migration effects:
- `p_timezone` parameter on the report library and dashboard RPCs (`list_incident_report_summaries`, `get_incident_dashboard`);
- Row-Level Security enabled on all 20 public tables, with permissions revoked from `PUBLIC`, `anon` and `authenticated` (services authenticate via `service_role` or `postgres`, both having `BYPASSRLS`);
- Legacy labels relabelled during copy (`fighting` to `assault`, `animal` to `animal attack`, `person` to `human`), with query-time canonical folding retained as a guard;
- The four legacy pre-v1 tables (`incident_reports`, `incident_entities`, `incident_instruments`, `incident_assets`), four retired v1 tables (`asset_matches`, `entity_matches`, `instrument_matches`, `notifications`), and ground-truth / eval tables (`gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets`, `severity_eval_log`) are dropped from the schema.

The console in this branch requires the versioned-report schema and its functions; the migrations that create them are delivered by the schema task, not by this change. Do not point the console at a database without them.

`supabase/migrations/20261023000200_searchable_latest_revision.sql` is written and tested on the hermetic harness but **not yet applied** to the live database (the captain applies it). Until then a video with no official revision has no searchable evidence, and library cards lack `officialSince`, `versionCount`, `evidenceCount` and `thumbnail`. Nothing writes the newest revision's crops yet: the console and agent still need to call `set_revision_crops`.

## 4. Known issues

1. **The AI revision has two writers.** In agent mode the agent inserts it and returns `revision_id`; in gateway mode the console inserts it. Both are append-only and the console verifies the agent's row, but there is no single writer.
2. **Attempt records live in `model_runs.notes` (TEXT).** The validated report itself is in `report_revisions.payload`; the notes keep the request, raw response, validation and repair record, queried via `try_parse_jsonb` and a `like` pre-filter. A JSONB column or index would be needed at volume.
3. **Cosmos models often break the timeline rule** (lead-up or aftermath events outside the incident window). Recorded, never repaired; see [`analysis-schema.md`](analysis-schema.md) section 7.
4. **One run has no recorded outcome.** `m86a5c319e26659804b0` predates recorded outcomes and shows as `valid_first_pass` (inferred).
5. **`other` incident type in one run's notes** (`m5629b0938e679c9873d`, no revision) stays, because attempt notes are immutable.
6. **Fixed P1 eval run ids overwrite benchmark rows** in the database; runs also keep an immutable copy under `results/runs/`.
7. **Agent runtime video-bounds exception.** `vss_agents.incident_contract` supports contextual `WINDOW_BEYOND_VIDEO` and `TIMELINE_BEYOND_VIDEO` rules when given `video_duration_seconds`. At runtime, `vss-agent` has no R2 credentials to perform byte-range reads on MP4 headers; in agent mode, the console performs the header read and enforces the video-bounds rule upon receiving agent output.

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

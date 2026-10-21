# Incident Profile Status

> **As of 2026-10-21.** A short snapshot of what works, what is pending and what is known to be wrong. Rewrite it as reality changes; do not append history.

## 1. What is live

| Area | State | Where |
|---|---|---|
| Console (`incident-console-v2`) | Upload, analysis on `incident-contract-v3` with a three-model picker, run history and re-analysis, structured reviewer edits, explicit official report, official-incident dashboard. API routes reach Supabase through the middle layer (ports and adapters), except ground truth, analysis saving and run history. Needs the finals database (`effective_*` views, `set_review_status`, `save_human_report_edit`) and fails against midterm, so it merges in the cutover window | [`analysis-schema.md`](analysis-schema.md), [`architecture.md`](architecture.md), [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md) |
| Analysis modes | Gateway (`vlm-gateway`, zero GPU) and agent (native `vss-agent` on `kwanz-ws`) share one contract, validation policy and attempt recording | [`analysis-schema.md`](analysis-schema.md) |
| Storage | Supabase rows plus Cloudflare R2 videos; uploads verified by `HeadObject` before analysis | [`data.md`](data.md) |
| Evaluation | Standalone P1/RP1 pipeline in `eval/` on the same contract; Tier 1 ground-truth scoring | `eval/README.md` |
| Launcher | `./start.sh --mode local\|vm` with SSH preflight, self-healing VM deploy and an always-on search route | [`incident-profile-operations.md`](incident-profile-operations.md) |
| Mocks | `base_profile_mock` (:7777) and `search_profile_mock` (:7778), including search and chat routes | `mock-backend/` |

## 2. MVP2: natural-language evidence search

Specification and architecture: [`mvp2/README.md`](mvp2/README.md).

- **Delivered:** `search-contract-v1` and `chat-contract-v1`; crop evidence service; `vss-agent` search route (`SupabaseSearchStore`, R2 presigned crop URLs, always-on critic with `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS`); chat route; `evidence_crops` / `query_results` / `search_evidence_items` migration; timestamp backfill script (`scripts/backfill_official_timestamps.py`).
- **Live on `kwanz-ws` (verified 2026-10-18):** the evidence loader (`scripts/backfill_official_timestamps.py`: remote VLM grounding and boxes, R2 upload, `nvidia/llama-nemotron-embed-vl-1b-v2` embeddings at 1024 dimensions, upsert) loaded 64 of 69 items from the 13 official reports into `evidence_crops`. 7 items were recovered by PR 141's whole-frame fallback (4 items with no VLM box: `SUV`, `ATM machine`, `Fireball`, and `weapon`) and JSON repair (3 truncated JSON replies). The remaining 5 failures are all from video `v5c609184047f88c720e` and still fail with remote gateway HTTP 500. `POST /api/v1/incidents/search` (`top_k=5`) returns 2-5 hits in about 6-9 s across benchmark queries ("weapon" surfaces the assault weapon at rank 1, similarity 0.331); crop URLs are fetchable via HTTP 206 Partial Content, with critic verdicts (`confirmed`, `rejected`, `unverified`). Rerun the loader only after the remote gateway recovers to fill the remaining 5 items.
- **In progress:** frontend search UI and chat (the console's search port mirrors `search-contract-v1`; its agent adapter is not written yet); retrieval eval: specification in [`mvp2/eval.md`](mvp2/eval.md) (tracks, metrics, dataset rules, proposals awaiting approval); harness and query set not written; data layer and RLS work.
- **Not started:** multi-subagent routing config; full RT-CV / RT-Embed indexing; retrieval benchmark implementation and runs ([`mvp2/eval.md`](mvp2/eval.md) Track R).

## 3. Pending approvals (migrations not yet applied to shared Supabase)

`20261016120000_mvp2_evidence_search_and_crops.sql` (pgvector, `evidence_crops`, `query_results`, `search_evidence_items`) is already applied.

| Migration | Effect |
|---|---|
| `20260928000000_local_time_heatmap_and_time_filters.sql` | `p_timezone` on the dashboard and library RPCs. The console already sends it, so `/api/dashboard` and `/api/reports` fail until it is applied. |
| `20261016000000_enable_rls_and_lockdown_anon.sql` | RLS on all 22 public tables; `anon` / `authenticated` revoked. Services use `service_role`, so nothing should break. |
| `20261016010000_legacy_taxonomy_and_orphan_cleanup.sql` | `fighting` to `assault`, `animal` to `animal attack`, `person` to `human`, removes 20 orphaned runs. Query-time folding stays until applied. |

## 4. Known issues

1. **Two writers in agent mode.** The console writes every row; the agent persists only standalone calls (no `model_run_id`) and never writes `videos`. Consolidating writers is not planned in detail.
2. **Model output lives in `model_runs.notes` (TEXT).** Intentional, as an immutable per-attempt record; queried via `try_parse_jsonb` and a `like` pre-filter. A JSONB column or index would be needed at volume.
3. **Cosmos models often break the timeline rule** (lead-up or aftermath events outside the incident window). Recorded, never repaired; see [`analysis-schema.md`](analysis-schema.md) section 7.
4. **One run has no recorded outcome.** `m86a5c319e26659804b0` predates recorded outcomes and shows as `valid_first_pass` (inferred).
5. **`other` incident type in one run's notes** (`m5629b0938e679c9873d`, no incident row) stays, because attempt notes are immutable.
6. **Four legacy pre-v1 tables remain**; dropping them is a separate approval.
7. **`selected_by` / `selected_at` can outlive a cleared selection**; the UI treats a NULL `selected_model_run_id` as no official report.
8. **Fixed P1 eval run ids overwrite benchmark rows** in the database; runs also keep an immutable copy under `results/runs/`.
9. **Agent runtime video-bounds exception.** `vss_agents.incident_contract` supports contextual `WINDOW_BEYOND_VIDEO` and `TIMELINE_BEYOND_VIDEO` rules when given `video_duration_seconds`. At runtime, `vss-agent` has no R2 credentials to perform byte-range reads on MP4 headers; in agent mode, the console performs the header read and enforces the video-bounds rule upon receiving agent output.

## 5. Follow-ups

- Run the eval benchmark under `core-scored-v1` (malformed-ID frequency, per-model core and enrichment failure rates).
- Consider a contract v4 with ID patterns only if the malformed-ID evidence justifies it (it changes eval).
- Apply the migrations in section 3 once approved.

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

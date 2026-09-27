# Incident Profile Status

> **As of 2026-09-27**
>
> This is a volatile snapshot document capturing the current operational state, delivery milestones, known issues, and environment configuration. It is intended to be rewritten as reality evolves, not monotonically appended.

---

## 1. Milestone Status: Done vs. Outstanding

Current delivery status verified against the codebase:

| Component / Feature | Current State | Verifiable Source Files |
|---|---|---|
| **incident-console-v2 (Next.js)** | **Contract-v2 analysis, run history, official reports and official-incident dashboard live-verified 2026-09-27** | Gateway analysis uses `incident-contract-v2` with a model picker (3 allowlisted VLMs), strict validation, ID-only repair and four recorded outcomes (`lib/analysis/run-contract-analysis.ts`, `lib/contract/`). Report view = structured projection + read-only model output + run details (`components/incident-report.tsx`, `lib/reports/view.ts`); Class A editing via `apply_structured_report_edit` (`components/structured-editor.tsx`). `/videos`, `/videos/[id]` (history + re-analysis), `/videos/[id]/ground-truth`; explicit official report selection; dashboard counts official incidents only and links into `/reports?scope=official`. Migrations `20260927150000`–`20260927180000` applied to shared Supabase. Timestamps render UTC-correctly in local time (`lib/time.ts`). |
| **vlm-gateway Proxy** | **Done** | `vlm-gateway/app.py`, `vlm-gateway/README.md` (FastAPI proxy on port 8600 holding upstream API credentials) |
| **mock-backend (Zero-GPU)** | **Done** | `mock-backend/base_profile_mock/` (port 7777, mock VST upload, mock stream registration, mock incident analysis) |
| **Agent /analyze Route & Tool** | **Done** | `services/agent/src/vss_agents/api/incident_analyze.py`, `services/agent/src/vss_agents/tools/incident_report_gen.py` |
| **Native VM Services Architecture** | **Done** | `.scripts/native-services.sh`, `.scripts/prune-native-images.sh` (`vss-agent` runs natively on `kwanz-ws` for 2s fast restarts; relinked editable to `services/agent/` with Brev inference) |
| **PostgREST Agent Persistence** | **Done** | `services/agent/src/vss_agents/utils/incident_db.py`, `supabase/migrations/20260917141225_insert_incident_function.sql`, `supabase/migrations/20260925031000_schema_defaults_and_precision.sql` |
| **Database Defaults & Precision Fix** | **Done (Live)** | `supabase/migrations/20260925031000_schema_defaults_and_precision.sql` applied to live Supabase DB on 2026-09-25: server-side UTC defaults on 9 timestamp columns, `review_status.status` default `'unreviewed'`, `notifications.acknowledged` default `FALSE`, and `insert_incident` updated to `p_confidence_score DOUBLE PRECISION`. PostgREST writers (`incident-console/db_postgrest.py`, `eval/db_postgrest.py`) updated to use `/rpc/insert_incident`. Agent extraction validation failure now surfaces HTTP 422/504 instead of persisting default reports. |
| **Cloudflare R2 Integration** | **Done** | `incident-console-v2/lib/r2/config.ts`, `incident-console-v2/app/api/uploads/r2/route.ts`, `incident-console/r2_videos.py`. Direct uploads are verified by `HeadObject` against the submitted byte length, and analysis re-verifies that the object is nonempty before inference. |
| **Tier 1 Ground-Truth Evaluation** | **Done** | Scoring stays in `eval/` (`eval/eval_gt.py`, `eval/matching.py`); the console's ground-truth page (`components/ground-truth-screen.tsx`) edits GT (never pre-filled from model output) and shows a read-only comparison with a chosen analysis. |
| **Unified Launcher (`start.sh`)** | **Done** | `start.sh`, `.scripts/tunnel.sh`, `.scripts/resolve-ssh-target.sh` (supports `--mode local` and `--mode vm` with non-interactive SSH resolution, preflight check, and auto self-heal) |
| **Unified Prompt & Structured-Output Contract** | **Phases 1–2 implemented (eval + console gateway mode); eval benchmark run pending; phases 3–5 not started** | `contracts/` (`incident-contract-v2`, `inference.json`, shared `fixtures/`), `eval/contract.py`, `incident-console-v2/lib/contract/` (TS validator verified against the same fixtures). Agent mode still uses the older contract (phase 3). The type/entity data migration (phase 4) is replaced for now by query-time folding. |
| **Agent-mode contract** | **Legacy (agent mode only)** | `incident-console-v2/lib/analysis/schema.ts`, `lib/analysis/incident-report-contract.json`, `services/agent/src/vss_agents/data_models/incident_report.py`: the older snake_case contract, still used when `ANALYSIS_MODE=agent` until prompt-contract phase 3. |
| **Live VM & Brev Verification** | **Done (Live)** | Two-flows end-to-end run on 2026-09-25 with `~/Desktop/test2.mp4` against Brev Switchyard (see §5): `./start.sh --mode vm` (agent mode on `kwanz-ws`) and `./start.sh --mode local` (gateway mode via `mock-backend` + `vlm-gateway`) both produce valid non-empty snake_case reports; each re-analysis writes a distinct `model_runs` row in both modes; review flow `unreviewed` -> `verified` works in both modes. Schema/field parity holds across the flows; content consistency does not (different VLMs, see known issue 7). Fixed HITL `NotImplementedError` and short-duration filter empty-report bugs in `services/agent` |
| **Multi-Subagent Search Config** | **Outstanding (MVP2)** | `deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` multi-subagent routing (`report_agent` + `search_agent`) planned; not yet wired together |
| **Natural Language Search Route** | **Outstanding (MVP2)** | `POST /api/v1/incidents/search` on `vss-agent` and UI search box not yet implemented |
| **Full RT-CV + RT-Embed Indexing** | **Outstanding (MVP2)** | DeepStream perception and vector embedding pipeline integration with Elasticsearch under live incident load |
| **Retrieval Benchmark Framework** | **Outstanding (MVP2)** | Precision/Recall/F1 benchmark suite for search queries |

---

## 2. Known Issues & Technical Debt

1. **Two writers and agent-mode double write.** In gateway mode the console writes all rows; in agent mode the agent writes `incidents`/evidence and the console writes `model_runs`/`videos`/`reports`. Agent mode also still uses the older contract, and the agent overwrites `videos.filepath` with a VST URL (the console restores the R2 key). Consolidation (Option B) is not started.
2. **Model output lives in `model_runs.notes` (TEXT).** It is intentional: an immutable per-attempt record. It is queried through `try_parse_jsonb` in RPCs and a `like` pre-filter plus parsing in the app. Scale is small today (57 runs); a JSONB column or index would be needed at volume.
3. **Cosmos Super often breaks the timeline rule.** It includes lead-up/aftermath events outside its own incident window (seen on 2 clips). These are recorded as `contract_failed` (not repairable; strict timeline rule kept). The eval benchmark should quantify the rate before deciding whether to keep Super.
4. **Pre-existing orphaned runs.** 20 legacy console `model_runs` rows name videos that no longer exist (left by earlier deletions). They are not shown anywhere and were not deleted (a destructive production-data change); new deletions clean up explicitly associated run records.
5. **Unrecorded outcome for the earliest contract run.** `m86a5c319e26659804b0` (stage-1 smoke test) predates recorded outcomes and is shown as `valid_first_pass` (inferred).
6. **Legacy values are folded at query time only.** `fighting`/`animal` types and `person` entities remain stored; one legacy report has the non-contract type `other`. A data migration (prompt-contract phase 4) would need approval.
7. **Heatmap and time-of-day filters use UTC hours.** Labelled as UTC; not localised.
8. **Legacy tables and RLS.** The four pre-v1 tables remain; RLS is disabled on public tables (service role only in code).
9. **`selected_by/selected_at` can outlive a selection** cleared by the FK when the official incident is deleted; the UI treats a NULL `selected_model_run_id` as no official report.

---

## 3. Follow-Ups & Out-of-Scope Items

1. **Prompt-contract phase 3:** move `vss-agent` onto `incident-contract-v2` (then retire `lib/analysis/schema.ts` and `incident-report-contract.json`).
2. **Eval benchmark run** on the contract, including malformed-ID frequency (from `contract_error` text) and per-model contract-failure rates.
3. **Possible contract v3:** ID patterns in the schema only if the malformed-ID evidence justifies it (changes eval).
4. **Legacy type/entity data migration** (phase 4) and legacy table cleanup: approval needed.
5. **RLS policies** and **writer consolidation (Option B).**

---

## 4. Live VM Configuration Snapshot (`kwanz-ws`)

*Verified live read-only over SSH via `.scripts/resolve-ssh-target.sh` on 2026-09-25 01:43:45+08:00 (2026-09-24T17:43:45Z).*

Active configuration inspected in `/srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote`:

| Setting | Live Value on `kwanz-ws` | Notes |
|---|---|---|
| `VSS_APPS_DIR` | `/srv/rise-up/vss/deploy/docker` | Points to docker deployment directory |
| `VSS_DATA_DIR` | `/srv/rise-up/vss-apps-data` | Persistent container volume mounts on host |
| `HOST_IP` | `10.131.1.5` | VM internal network interface IP |
| `EXTERNAL_IP` | `localhost` | Embedded URL host for tunneled browser access |
| `VSS_AGENT_CONFIG_FILE` | `./deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` | Base profile config providing report-generation |
| `REPORT_REFERENCE_BASE_DIR` | `/tmp` | Required by agent evaluation config schema |
| `STREAM_PROCESSOR_HTTP_PORT` | `10000` | Streamprocessing HTTP port (ingress on :30888 proxies /vst/api/v1 and /vst/storage here) |
| `LLM_NAME` | `nvidia/nemotron-3-ultra` | Brev Switchyard model for LLM router and eval judge |
| `VLM_NAME` | `nvidia/cosmos-3-super-reasoner` | Brev Switchyard model for video understanding |
| `LLM_BASE_URL` | `https://switchyard-13doh4lsz.brevlab.com` | Brev inference endpoint (no trailing `/v1`) |
| `VLM_BASE_URL` | `https://switchyard-13doh4lsz.brevlab.com` | Brev inference endpoint (no trailing `/v1`) |
| `LLM_MODEL_TYPE` | `openai` | Required client type for Brev compatibility |
| `VLM_MODEL_TYPE` | `openai` | Required client type for Brev compatibility |
| `OPENAI_API_KEY` | *(Set)* | Brev Switchyard API Key |
| `NVIDIA_API_KEY` | *(Set)* | NGC inference API Key |
| `NGC_CLI_API_KEY` | *(Set)* | NGC container registry authentication key |
| `INCIDENT_SUPABASE_URL` | *(Set)* | Supabase PostgREST endpoint |
| `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | *(Set)* | Supabase Service Role Key |

> [!NOTE]
> On 2026-09-25, the VM `vss-agent` venv was relinked editable to the repository checkout (`services/agent`) with public dependencies (`supabase`, `opencv-python-headless`, `setuptools`). The live agent process was restarted and is actively connected to Brev Switchyard for LLM (`nvidia/nemotron-3-ultra`), VLM (`nvidia/cosmos-3-super-reasoner`), and eval judge inference.

---

## 5. Live Verification Log: Contract-v2 console (2026-09-27)

All on the local stack (`./start.sh --mode local`, shared Supabase and R2). Test video `v4992173cd9c16efbd15` is a copy of `anomaly/assault/Assault018_x264.mp4` uploaded as `smoke-test-contract-v2-assault018.mp4`.

| # | Check | Result |
|---|---|---|
| 1 | Upload + analysis with each model | cosmos-3-nano `m86a5c319e26659804b0`: valid. cosmos-3-super: 422 (timeline outside window). nemotron-omni: 422 before ID repair existed. The gateway received eval's exact P1 request (prompt and schema fingerprints matched). |
| 2 | ID-only repair | nemotron-omni re-run `m811cf2b237f50ff9812`: first pass `ID_NOT_SEQUENTIAL_ENTITY` + `_INSTRUMENT`; operations: reorder `[E2,E1]`, rename `"," → I2`; re-validated; stored raw reply byte-identical to the earlier capture; one model call. |
| 3 | Structured edit + restore through the UI | Severity 3→2, end 13→12 (duration 12→11), then restored. Notes byte-identical throughout; review status unchanged; `edited_by/at` recorded. |
| 4 | Re-analysis | cosmos-nano with an instruction: `ma5fa04781cc50f1cae7`, new report. cosmos-super: `m233514c76646100da3f`, contract_failed, recorded in history only. `uploaded_datetime` unchanged; earlier runs untouched. |
| 5 | Official report | Selected and cleared through the UI; review status untouched. The test video is back to awaiting selection. |
| 6 | Dashboard parity | Temporary official selection: every dashboard number equals the `/reports?scope=official` total (8/8 live; 40/40 per period in the rolled-back dry run). Selection cleared afterwards. |

The 2026-09-25 two-flows verification (agent and gateway modes on `test2.mp4`) is recorded in the git history of this file.

# Incident Profile Status

> **As of 2026-10-24 (SGT).** A short snapshot of what works, what is pending and what is known to be wrong. Rewrite it as reality changes; do not append history.

## 1. What is live

| Area | State | Where |
|---|---|---|
| Console (`incident-console-v2`, the only console) | Upload, analysis on `incident-contract-v4` with a three-model picker in both modes, versioned reports (View and Edit modes, History, Save as new version with a note, evidence-image replacement uploaded on Save, a chat that follows the selected version), `/library` incident and evidence search, explicit official revision, official-revision dashboard, run history with re-generation (model and reviewer prompt), and a per-video orphan sweep for evidence images. API routes reach Supabase only through ports wired in `src/lib/container.ts`; no route builds a PostgREST query | [`architecture.md`](architecture.md), [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md) |
| Console code layout | `src/app`, `src/modules/<feature>/{domain,application,infrastructure}`, `src/sections`, `src/lib`. `npm test` enforces the import boundaries; `npm run lint` is Biome plus `tsc --noEmit` | [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md) |
| Analysis modes | Gateway (`vlm-gateway`, zero GPU) and agent (native `vss-agent` on `kwanz-ws`) share one contract, validation policy and attempt recording | [`analysis-schema.md`](analysis-schema.md) |
| Storage | Append-only `report_revisions` rows plus Cloudflare R2 videos and evidence images; uploads verified by `HeadObject` before analysis | [`data.md`](data.md) |
| Evaluation | Everything about the eval (state, handoff, open items) is in [`mvp2/eval.md`](mvp2/eval.md) | `eval/` |
| Launcher | `./start.sh --mode mock\|vm` with SSH preflight, self-healing VM deploy, stop-on-last-exit coordination via a VM flock, and an always-on search route | [`incident-profile-operations.md`](incident-profile-operations.md) |
| Mocks | `base_profile_mock` (:7777, started by `--mode mock`) and `search_profile_mock` (:7778, standalone) answer incident search and revision search from one finals snapshot; :7777 also answers chat from it ([decision](decisions.md#2026-10-24-the-mocks-answer-search-and-chat-from-one-finals-snapshot)) | `mock-backend/` |

## 2. MVP2: natural-language evidence search

Specification and architecture: [`mvp2/README.md`](mvp2/README.md).

- **Delivered:** `search-contract-v1` and `chat-contract-v1`; the crop service; the `vss-agent` search route (always-on critic) and chat route; revision-keyed `evidence_crops` and `query_results`; the analyze route writes the AI revision with its evidence crops; `POST /api/v1/incidents/evidence-embeddings` (by stored `revision_id`, or by evidence entries posted before a save); each video's searchable revision is its official revision, else its newest; `/library` Find incidents and Find evidence; the report page chat.
- **Revision vector search:** migration `20261023120000` adds `report_revisions.embedding`, its HNSW index and `search_report_revisions`; the agent embeds each AI revision's `incident.title` and `incident.description` on insert and serves `POST /api/v1/incidents/revisions/search`, which Find incidents calls.
- **Live on `kwanz-ws`:** the 2026-10-24 read-only check found the five incident routes in `openapi.json` and the agent running the stock base config; the VM checkout was at `02b543ecf` (#205), three PRs behind main.
- **Dropped from MVP2 (2026-10-24):** the multi-subagent routing config and full RT-CV / RT-Embed indexing ([decision](decisions.md#2026-10-24-drop-multi-subagent-routing-and-full-rt-cv--rt-embed-indexing-from-mvp2)).

## 3. Database status

Finals is the live database; the laptop console and the VM agent both point at it. Midterm (`rfevukimyftzbxlehwel`) is the frozen record; the copy and freeze procedures are in [`supabase/README.md`](../supabase/README.md). The schema is the baseline plus the later migrations in [`supabase/migrations/`](../supabase/migrations/); [`data.md`](data.md) describes the result.

| Migration | On finals |
|---|---|
| `20261020000000_finals_baseline.sql`, `20261022123252_drop_unused_tables.sql` | Applied |
| `20261023000000_report_revisions_schema.sql`, `20261023000100_report_revisions_functions.sql` | Applied (the captain applied the schema by hand; these files reproduce it) |
| `20261023000200_searchable_latest_revision.sql`, `20261023120000_report_revision_embeddings.sql` | Applied (confirmed by the captain, 2026-10-24) |
| `20261024090000_save_human_revision_with_crops.sql` | Applied (by the captain, before #207 merged). Every console Save calls `save_human_revision_with_crops` |

Test data: on 2026-10-24 the rows and R2 objects of the three end-to-end test videos (`vc35c6116a88c37d51c9`, `v614eba7ad8510751a8c`, `va978aaf39b01270294a`), their 10 test `queries` rows and the 2 scout uploads with no `videos` row were removed from finals and R2, with a rollback snapshot kept outside the repo. Three items of unknown origin were kept: upload `uploads/c19fb16d-.../b4d71165-....mp4`, video `veb492932dac2d1d52e0`, and five `queries` rows with the text "car" ([decision](decisions.md#2026-10-24-finals-test-data-is-removed-by-direct-delete-and-unproven-items-are-kept)).

## 4. Known issues

Deliberate behaviour that can look like an issue (the Cosmos timeline, chat about the official version, a human revision's search text) is recorded in [`decisions.md`](decisions.md).

1. **TO FIX (not started): the agent does not enforce the video-bounds rules.** `vss_agents.incident_contract` supports `WINDOW_BEYOND_VIDEO` and `TIMELINE_BEYOND_VIDEO` when given `video_duration_seconds`, but the analyze route never passes one (it gets only a signed playback URL and reads no MP4 header). In agent mode the console reads the header from R2 and enforces the rules on the agent's output. Fix: the route passes the duration so the agent enforces the rules itself.
2. **Deleting a video leaves its evidence images in R2.** `deleteVideoAndReports` removes the video object and its thumbnail, then the rows; `evidence/<videoId>/` stays, and the orphan sweep refuses an unknown video, so nothing removes those images.
3. **The mock snapshot holds deleted test videos.** `finals_snapshot.json` was captured before the 2026-10-24 cleanup and still includes `vc35c6116a88c37d51c9`, `v614eba7ad8510751a8c` and `va978aaf39b01270294a`, so mock search can return videos that no longer exist on finals. Refresh it by hand (`mock-backend/base_profile_mock/README.md`).
4. **TO FIX (not started): the library thumbnails differ from MVP1.** The captain wants them identical to MVP1's. They do show; the cause of the difference has not been investigated. One thumbnail request on `/library` (`thumbnails/anomaly/assault/Assault050_x264.mp4.webp`) was also blocked by the browser (`net::ERR_BLOCKED_BY_ORB`) in the mock-mode walk and is unreproduced.
5. **Real-data search has never been exercised since the audit.** On 2026-10-24 the native `vss-agent` on `kwanz-ws` was stopped (clean shutdown at 12:16 SGT, cause unknown), so Find incidents, Find evidence and chat were only checked against the mock, which is keyword-backed and shows every hit as a 100% match. `./start.sh` defaults to `--mode vm`; `--mode mock` never starts the VM agent.
6. **The agent tests changed for the embedding-key fix have not been run.** `tests/unit_test/api/test_incident_search.py` had 11 failures on the VM (`TestSearchRouteEndToEnd`, `TestCriticDelaySpacing`) wherever an embedding key is in the environment; the fix from #212 could not run locally because `uv sync` needs NVIDIA's internal index. Run them on the VM.
7. **The 18 Oct backfill rerun ended with failures.** `backfill-rerun.log` on the VM ends with `entity E2: OverflowError: int too large to convert to float` and a Brev 500 for an asset. How many evidence crops or embeddings are missing is unknown; check once the agent is up.
8. **Unconfirmed: `start.sh` may not stop its children on SIGINT or SIGTERM.** `next-server`, the mock and the gateway kept listening in one test, but that run was launched detached, so it may be an artefact. Re-test from a normal terminal.

## 5. Follow-ups

- Whole-profile validation of `dev-profile-incident` with no-mistakes over the entire folder, not a diff (not started). Open: how to point the pipeline at a whole folder, whether its reviewer can run Haiku 5.5 at low effort (the reviewer list is opencode and antigravity only), and the size and cost. A first attempt on a free opencode model stopped at its usage cap.
- Triage the 108 Biome warnings and 5 infos from `npm run lint` in the console.

- PDF export (parked by the captain, not started): no server PDF endpoint and no Download PDF dialog exist; today a report prints only through the browser, styled by the `@media print` rules in `incident-console-v2/src/app/styles.css`. To build: the endpoint and the dialog, then remove the print path.
- Console hexagonal plan, strict Step 6: inject a `ContractCatalog` port and move `run-contract-analysis.ts`'s `node:crypto` (`randomUUID`) behind a port, which removes the loader and `node:crypto` exceptions in `tests/import-boundaries.test.mjs` (the upload hook's exception is by design).

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
| GPU | GPU 0 only; GPU 1 is never used ([GPU rule](incident-profile-operations.md#5-vm-deployment-configuration-principles-generatedenvremote), item 10) |
| Secrets | `OPENAI_API_KEY`, `NVIDIA_API_KEY`, `NGC_CLI_API_KEY`, `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (set, never printed) |

The VM `vss-agent` virtualenv is installed editable from the repository checkout (`services/agent`); see [`incident-profile-operations.md`](incident-profile-operations.md).

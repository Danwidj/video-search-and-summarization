# Incident Profile Decision Log

Decisions that still shape `dev-profile-incident`, newest first. Each entry: decision, why, alternatives rejected, links. Superseded and purely historical decisions are removed; git history has them.

### 2026-10-20: One Supabase project per phase; finals built from one baseline; midterm frozen
- **Decision:**
  - The midterm project (`rfevukimyftzbxlehwel`) becomes a frozen, read-only record, and a new finals project is built from scratch with `supabase/migrations/20261020000000_finals_baseline.sql`, then filled once by `supabase/copy/copy_midterm_to_finals.py`.
  - The 14 midterm migrations move unchanged to `supabase/midterm/migrations/` (an archive, not a CLI workdir); `supabase/migrations/` holds only finals files, so the CLI workdir and commands stay the same.
  - Security is on from the first statement: default privileges are revoked before any object exists, RLS is on for every table, nothing is granted to `PUBLIC`/`anon`/`authenticated`, every function pins `search_path`, pgvector lives in `extensions`, and a self-check block fails the migration if anything is exposed. No `FORCE ROW LEVEL SECURITY` (no effect with a `BYPASSRLS` owner).
  - The copy brings over every real row plus the ground truth, evaluation data and seed/fake test reports, and leaves behind 20 orphan runs, 15 unlinked test runs, 8 broken uploads and the 4 pre-v1 tables (guards fail on anything else, and on any edit the copy cannot turn into a reviewer version). A stamp is cleared only when provably a status change (a contract run whose rows equal its notes record); a stamped legacy run stops the copy until a person passes `--not-edited` or `--edited`, because the midterm console rewrote the stamp with the verifier on every status change, so a stamp equal to the verification proves nothing. It relabels `fighting`/`animal`/`person` once; query-time folding stays as a guard, and the one `other` value stays in an immutable run's notes.
  - At the cutover `supabase/midterm/freeze_midterm.sql` locks midterm (anon out, `service_role` read-only, direct-DSN sessions read-only); `unfreeze_midterm.sql` is the rollback. R2 is shared, so no object moves.
  - A SQL harness (`supabase/tests/`, `pgserver`) tests the schema hermetically; every later finals migration extends it.
  - Finals uses the new `sb_secret_` / `sb_publishable_` keys (no legacy JWT keys). They are sent in `apikey` only; the VM's unpinned `supabase-py` is proven with a one-row connection test before the switch ([`incident-manage-database`](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_)).
- **Why:** The supervisor asked for one database per project phase. Midterm's migration history does not match what is applied (three applied migrations unrecorded, one recorded under another version, two never applied), its base tables came from no repo file, and the public key could read and change everything (RLS on 2 of 22 tables, default grants to `anon`). Starting clean removes the junk and the open access in one step, and the frozen midterm stays readable as the phase record. Freezing rather than leaving it writable makes a forgotten env file fail loudly instead of writing to the wrong database (the agent only warns when it cannot record a search).
- **Rejected:** more migrations on the shared database (the history is inconsistent and the lockdown and clean-up were never applied); a separate `supabase/finals/` workdir (changes every doc path, and the old folder stays pushable at midterm); pausing midterm at once (no longer a readable record); a bucket per phase (doubles 59.5 GB for no gain); copying the orphan and test runs or the pre-v1 tables (no reader can reach them).
- **Links:** [`../supabase/README.md`](../supabase/README.md); [`../supabase/midterm/README.md`](../supabase/midterm/README.md); [`data.md`](data.md); [`architecture.md`](architecture.md#two-supabase-projects-one-per-phase).

### 2026-10-20: AI report and reviewer version stored separately
- **Decision:**
  - The AI report's relational rows (`incidents`, `entities`, `instruments`, `assets`) are written once by analysis and never edited. A reviewer's changes go to a separate full copy, `human_reports` and its items, **one per run**, each item recording its source AI item (`source_*_id`; `ON DELETE SET NULL`).
  - Readers use the `effective_*` views (reviewer version if present, else AI). The library, dashboard and search RPCs keep their signatures and output.
  - **Editing a verified report sends it back to `under review`** and clears the verifier (`save_human_report_edit`).
  - **Verifying without edits still copies the AI report** into the reviewer version (`set_review_status`, one transaction), so every verified report has one. Status changes no longer write `edited_by/at`.
  - Evidence crops stay keyed to AI items, which never change; they are made for every report (Daniel's crop pipeline). Every edited item carries `source_id` (`null` for a reviewer-added item); `save_human_report_edit` and its shim refuse an edit with a keyless item instead of guessing, so the console change that sends it is a cutover prerequisite.
  - `apply_structured_report_edit` stays as a compatibility shim over `save_human_report_edit` until no console calls it.
- **Why:** The meeting asked that the AI version is never overwritten. In-place edits made the AI original survive only in notes, renumbered items so a crop could attach to the wrong item, left an edited report "verified", and turned every status change into a misleading "last edited by". Stable AI rows also keep reviewer edits out of eval.
- **Rejected:** storing only the edits (merge logic in every reader); renaming/splitting `incidents` (every FK, writer and RPC changes); JSON revisions (the library, dashboard and search filter on relational item rows); one reviewer version per video (would sit between runs and look like ground truth); guessing a missing `source_id`, whether from the AI item or the stored reviewer item with the same ID (the editor renumbers by position, so a deleted or reordered item hands its text to another item's crop, a legacy `e01` run loses every link, and nothing errors); plain foreign keys from reviewer items to AI items (run and video deletes fail: the cascade reaches the reviewer items along two paths and a `NO ACTION` check fires in between).
- **Links:** [`analysis-schema.md`](analysis-schema.md#ai-version-and-reviewer-version); [`data.md`](data.md#reviewer-version-and-effective-views); [`../supabase/migrations/20261020000000_finals_baseline.sql`](../supabase/migrations/20261020000000_finals_baseline.sql).

### 2026-10-19: Hexagonal architecture for incident-console-v2 UI and database decoupling
- **Decision:** (adopted 2026-10-16 in PR 120; scope amended 2026-10-17 and 2026-10-19)
  - `incident-console-v2` route handlers (`app/api/*`) depend on domain ports (`lib/ports/`) and reach Supabase only through PostgREST adapters (`lib/adapters/supabase/`) wired by `getDbAdapters()`. Ports, thin use cases (`lib/application/`, only for the multi-step routes: report detail, review status change, delete) and adapters are the console's middle layer, inside the app. Components keep calling `/api` and never touch the database.
  - Ports keep everything the routes use: runs keyed by `(videoId, modelRunId)`, the three review states with verifier, editor and timestamps, and the full filter sets and results of `get_incident_dashboard` and `list_incident_report_summaries`.
  - On the ports: health, dashboard, report library, videos list, official selection, report detail, review, edit and delete. Not yet: ground truth (untouched), analysis saving and run history (they move with the planned split of human-verified and AI-generated reports).
  - Console search goes through the vss-agent's `POST /api/v1/incidents/search` (search-contract-v1). `EvidenceSearchRepository` mirrors that contract; its adapter and a console search route come later. The search tables and RPC were delivered in PR 134; the remaining database work and VM persistence checks are PR 126.
  - The dependency rules are conventions upheld in review (spec §2), with the callers not yet migrated listed in spec §7.
- **Why:** Routes built PostgREST queries and RPC arguments themselves and passed rows or RPC JSON to the browser with only a cast, so the API did not translate data properly. The adapters now own every table, column and `p_*` name, map rows and RPC JSON field by field into camelCase domain types, and turn database refusals into `StoreRejection`. In-memory fakes make use cases testable without a database; contract suites keep them faithful to the adapters. Use cases keep orchestration and domain rules (R2 before the database on whole-video delete, the review transition) out of HTTP handlers. The agent already embeds the query, runs the critic and records queries and hits, so the console needs no embedding model of its own.
- **Rejected:** an ad-hoc `lib/db/` helper without refactoring the routes (they stay coupled to PostgREST); one PR combining the console refactor with the live migration (harder to review and roll back); routes calling ports directly for multi-step flows (the rules would stay in HTTP handlers); console search straight against Supabase (no critic, and it would duplicate the agent's embedding and query recording); a test that regex-matches `import` lines (proves nothing about behaviour); ESLint `no-restricted-imports` or dependency-cruiser (a new dependency).
- **Links:** [PR 120](https://github.com/Danwidj/video-search-and-summarization/pull/120); [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md); [`vm-api-contracts.md`](vm-api-contracts.md); [`../incident-console-v2/`](../incident-console-v2/).

### 2026-10-19: Pin all VSS Docker appliances and native services to GPU 0 only
- **Decision:** Restrict the entire VSS system on `kwanz-ws` to GPU 0. Set `RT_EMBED_DEVICE_ID='0'`, `RTVI_EMBED_NVIDIA_VISIBLE_DEVICES='0'`, `FIXED_SHARED_DEVICE_IDS='0'`, `CUDA_VISIBLE_DEVICES='0'`, and `NVIDIA_VISIBLE_DEVICES='0'` in `dev-profile-incident/.env`. Override `streamprocessing-ms`, `sensor-ms`, and `rtvi-embed` in `compose.override.yml` with explicit GPU 0 device reservations (`device_ids: ["0"]`) and `NVIDIA_VISIBLE_DEVICES=0` / `CUDA_VISIBLE_DEVICES=0` environment variables (alongside `nvstreamer-2d-fusion` and `perception-2d-fusion`). Export `CUDA_VISIBLE_DEVICES=0` and `NVIDIA_VISIBLE_DEVICES=0` in `native-services.sh`, `vm-ensure-docker.sh`, and `start.sh`. Pin `vss-rtvi-embed` to GPU 0 even though it is unused by MVP2 (MVP2 uses remote `nvidia/llama-nemotron-embed-vl-1b-v2` text embeddings and remote Brev VLM).
- **Why:** `kwanz-ws` is shared with another user whose training job occupies GPU 1 (46.9 / 49 GB at 87°C). VSS must leave GPU 1 completely untouched. Previously `RT_EMBED_DEVICE_ID` and `FIXED_SHARED_DEVICE_IDS` defaulted to `1`, while `streamprocessing-ms` and `sensor-ms` ran with `runtime: nvidia` without a device reservation or visible device pin, exposing all GPUs.
- **Rejected:** Removing `vss-rtvi-embed` completely (pinning to GPU 0 preserves compatibility if stock VSS embedding flows are ever re-evaluated); dynamically sharing GPU 1 (the co-tenant workload leaves negligible memory and runs at high thermal load).
- **Links:** [`compose.override.yml`](../compose.override.yml); [`.env`](../.env); [`architecture.md`](architecture.md); [`status.md`](status.md).

### 2026-10-18: Drop retired Streamlit incident-console from compose.yml
- **Decision:** Remove `./incident-console/compose.yml` from `deploy/docker/developer-profiles/dev-profile-incident/compose.yml` and correct the comments stating it is the profile-exclusive service.
- **Why:** The Streamlit v1 console is retired (`incident-console-v2` is the sole UI). Nothing depends on including `vss-incident-console` in the profile's compose stack.
- **Rejected:** keeping the inactive include in `compose.yml`.
- **Links:** [`compose.yml`](../compose.yml); [`../incident-console/README.md`](../incident-console/README.md); [`AGENTS.md`](../AGENTS.md).

### 2026-10-18: Console and agent bind loopback
- **Decision:** `incident-console-v2` runs with `-H 127.0.0.1` (npm `dev`/`start` scripts and `start.sh`). `VSS_AGENT_HOST` defaults to `127.0.0.1`; haproxy's agent backend uses `VSS_AGENT_BACKEND_HOST=127.0.0.1` (profile override of a new shared-template variable defaulting to `HOST_IP`) and the tunnel forwards to the VM loopback.
- **Why:** Next defaults to all interfaces and the console holds database and storage admin keys with no authentication. haproxy is host-network, so it can reach a loopback agent once its backend host is configurable; the console reaches the agent through the tunnel, not haproxy, and no `vss-ui` runs on the VM.
- **Rejected:** leaving the agent on 0.0.0.0 or HOST_IP (exposes unauthenticated search and DB key to the network); hardcoding 127.0.0.1 in the shared haproxy template (breaks other profiles).
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-10-18: No search similarity cutoff; hide critic-rejected hits; loader keeps unboxed items
- **Decision:** `POST /api/v1/incidents/search` defaults `min_similarity` to 0.0 and takes top_k; hits the critic marks `rejected` are dropped unless `hide_rejected` is false. The loader stores the whole frame (box `[0,0,1000,1000]`, confidence 0.0) when the detector finds no box, raises grounding `max_tokens` to 2048 and recovers `timestamp_seconds` and `label` from a truncated reply.
- **Why:** Scores of all 57 loaded rows sit between 0.14 and 0.35, so the 0.2 cutoff flipped "edged weapon" between 0 and 5 hits on a 0.01 difference (best score 0.192). The critic already judges relevance. Whole-frame crops keep items (including the only weapon) searchable, since scoring uses the description embedding.
- **Rejected:** a relative cutoff (the critic call is paid per hit anyway).
- **Links:** [`vm-api-contracts.md`](vm-api-contracts.md); [`data.md`](data.md).

### 2026-10-18: Remote embeddings and remote-VLM cropping for evidence search
- **Decision:**
  - Evidence descriptions (loader, input type `passage`) and search queries (`DefaultQueryEmbedder`, input type `query`) use one remote model, `nvidia/llama-nemotron-embed-vl-1b-v2` on `https://integrate.api.nvidia.com/v1/embeddings`, requesting `dimensions=1024` to match `evidence_crops.embedding`. Client: `utils/embeddings.py` (`EVIDENCE_EMBEDDING_BASE_URL`, `EVIDENCE_EMBEDDING_MODEL`, `EVIDENCE_EMBEDDING_API_KEY`, falling back to `NVIDIA_API_KEY` then `NGC_CLI_API_KEY`). Without a key, only the in-memory store falls back to a deterministic placeholder vector (zero-VM mocks and unit tests only); with the Supabase store or on an embedder error, the route fails with HTTP 503.
  - `DefaultDetector` in `crop_evidence.py` is backed by the remote VLM (one tight `bbox_2d` per frame, normalised 0-1000), not a local detector. `R2EvidenceStore`, `SupabaseEvidenceStore` and the composing `LiveEvidenceStore` replace the stubs.
  - `scripts/backfill_official_timestamps.py` is the production evidence loader: Supabase report source, VLM grounding, VLM box and crop, R2 upload, embedding, `evidence_crops` upsert. Dry runs keep the fakes.
- **Why:** The earlier loader wrote nothing, so search returned 200 with zero hits on `kwanz-ws`. The Brev key cannot call `/v1/embeddings` (403), and `nv-embedqa-e5-v5` and `llama-3.2-nv-embedqa-1b-v2` are end-of-life (410). `llama-nemotron-embed-vl-1b-v2` is live and accepts `dimensions=1024` (`nemotron-3-embed-1b` only 2048). The remote VLM already serves grounding, and no local GPU model may be started.
- **Rejected:** a local MiniLM server (384 dimensions, not on the VM); padding or truncating 2048-d vectors (breaks cosine geometry); a local Grounding DINO / OWLv2 detector (needs a GPU model on the VM; detector comparison stays in the retrieval eval).
- **Links:** [`services/agent/src/vss_agents/utils/embeddings.py`](../../../../../services/agent/src/vss_agents/utils/embeddings.py); [`services/agent/src/vss_agents/utils/crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py); [`scripts/backfill_official_timestamps.py`](../../../../../scripts/backfill_official_timestamps.py); [`status.md`](status.md).

### 2026-10-18: start.sh vm mode explains unreachable VMs, bounds every VM step and detects the VM address
- **Decision:** `start.sh --mode vm` classifies an SSH failure first (`.scripts/vm-preflight.sh`: Tailscale state, VM offline, DNS, timeout, refused, no route, auth, host key) and prints cause and next step. The Docker deploy runs from `.scripts/vm-ensure-docker.sh`, piped over SSH: it clones a missing checkout, requires `generated.env.remote`, rewrites a stale `HOST_IP` (timestamped backup first), pulls missing images and runs `docker compose up -d` under `VSS_COMPOSE_UP_TIMEOUT`. Native start, ssh calls and the tunnel wait are bounded too. `VSS_VM_IP` defaults to the VM's default-route source address (`ip -4 route get 1.1.1.1`, fallback `10.131.1.5`); an explicit value wins. `--no-console` stops after the tunnel.
- **Why:** A stale `HOST_IP` hung `docker compose up` on the Kafka health check with no timeout, and the VM's DHCP address had moved.
- **Rejected:** only adding timeouts (the stale `HOST_IP` still fails); hand-editing `HOST_IP`; auto-installing the agent virtualenv (its dependencies resolve only via NVIDIA's internal artifactory).
- **Links:** [`start.sh`](../start.sh); [`.scripts/vm-preflight.sh`](../.scripts/vm-preflight.sh); [`.scripts/vm-ensure-docker.sh`](../.scripts/vm-ensure-docker.sh); [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-10-18: incident-console-v2 on TypeScript 5.9 with bundler module resolution
- **Decision:** Pin `typescript` 5.9.3, set `moduleResolution: bundler` and drop `baseUrl`; the `@/*` alias stays in `paths`.
- **Why:** TypeScript 6 deprecates `baseUrl` and node10 resolution; `bundler` needs TypeScript 5.0 or later.
- **Rejected:** `ignoreDeprecations: "6.0"` (silences the warning only); staying on 4.9.5.
- **Links:** [`incident-console-v2/tsconfig.json`](../incident-console-v2/tsconfig.json).

### 2026-10-17: MVP2 search storage: evidence_crops, query_results, SupabaseSearchStore, R2 presigned crops
- **Decision:**
  - Migration `20261016120000_mvp2_evidence_search_and_crops.sql` adds pgvector, one unified `evidence_crops` table keyed `(incident_id, model_run_id, item_type, item_id)` (HNSW cosine index, `vector(1024)`), `query_results` (rank, similarity, critic verdict and rationale) and the `search_evidence_items` RPC. RLS on, `service_role` only. The RPC joins `videos.selected_model_run_id`, so only official reports are searchable.
  - `vss-agent` uses `SupabaseSearchStore` when `INCIDENT_SEARCH_STORE=supabase` or Supabase credentials are configured, otherwise `InMemorySearchStore`. Crop keys resolve to public URLs (`INCIDENT_VIDEO_BASE_URL`) or boto3 presigned R2 URLs (`utils/r2.py`). Queries and results are persisted.
  - Query embedding is covered by the remote-embeddings decision above.
- **Why:** The sample-data store pointed at a non-existent host, so the critic failed to fetch images and every hit was `unverified`. One table avoids three vector columns and three UNIONs. Official scoping stops re-analysis runs producing duplicate hits.
- **Rejected:** altering the legacy `entities` / `instruments` / `assets` tables; unscoped search; public-only URLs (private buckets need presigning); an external embedding service for now.
- **Links:** [`../supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`](../supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql); [`data.md`](data.md); [`mvp2/README.md`](mvp2/README.md).

### 2026-10-16: MVP2 search route, chat route, crop service, backfill and launcher
- **Decision:**
  - `POST /api/v1/incidents/search` (`search-contract-v1`) and `POST /api/v1/incidents/chat` (`chat-contract-v1`) in `vss-agent`, mounted unconditionally, behind hexagonal ports (`SearchStore`, `QueryEmbedder`, `SearchClient`) with in-memory adapters; mock routes on :7777 and :7778 serve the frontend without a GPU.
  - The VLM critic is always on. A failed or timed-out critic call degrades to `verdict="unverified"` with `confidence=None`; hits are never dropped. Critic calls start `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` apart (default 1.0, 0 disables) to avoid upstream 429/500 bursts.
  - `CropEvidenceService` crops keyframes at `timestamp_seconds` using a detector port (remote VLM boxes, see above) (5% margin, JPEG quality 85) and stores them via an `EvidenceStore` port under `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg`.
  - `scripts/backfill_official_timestamps.py` re-queries the VLM only for timestamps and detector labels of existing official reports (idempotent, resumable, `--dry-run`), never rewriting reviewed text.
  - `start.sh` always brings up and checks search (no `--search` flag); local readiness polls `/health`; `.scripts/tunnel-check.sh` probes search through the tunnel.
- **Why:** A pilot showed VLM bounding boxes were 0% well-framed but timestamps over 95% accurate, so the VLM supplies timestamps and labels and a detector supplies boxes. Ports let the workstreams proceed in parallel. Spacing call starts smooths bursts without retries or sequential latency.
- **Rejected:** VLM bounding boxes; dropping hits on critic failure; a feature flag for search; retries or thread pools for the critic; full re-analysis for backfill (destroys reviewer edits).
- **Links:** [`../contracts/search-contract-v1/`](../contracts/search-contract-v1/); [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/); [`mvp2/README.md`](mvp2/README.md).

### 2026-10-16: Contract v3 temporal grounding and RP1 on core_ok
- **Decision:** `incident-contract-v3` adds required `timestamp_seconds` and `label` to entities, instruments and assets; bounding boxes are detector-produced only. Console validation is version-aware, so v2 runs stay viewable. RP1 runs when `core_ok` (not only `full_contract_ok`), receives the unchanged prediction, and `report_generation_prompt.md` says timeline events outside the incident time are context.
- **Why:** Cosmos models consistently emit lead-up and aftermath events; gating RP1 on full validity skipped prose for otherwise valid incidents. A two-clip pilot showed the extra line kept the reported window while describing context.
- **Rejected:** sub-versions in recorded results; clipping timeline events before RP1 (loses narrative context).
- **Links:** [`../contracts/README.md`](../contracts/README.md); [`analysis-schema.md`](analysis-schema.md).

### 2026-10-16: vss-agent on incident-contract-v3
- **Decision:** `vss_agents/incident_contract/` vendors `contracts/` with strict Pydantic models and parity tests. `incident_report_gen` runs P1 then RP1 directly. `POST /api/v1/incidents/{id}/analyze` takes `{ video_url, model_run_id?, skip_rp1? }`: 422 on contract violation, 504 on timeout, 501 when unconfigured. It validates under `core-scored-v1` with `id-normalization-v1` and persists best-effort only when called without `model_run_id`; the console is otherwise the only writer, and the agent never writes `videos`. Console agent mode runs the same `runContractAnalysis` and `persistContractRun` as gateway mode.
- **Why:** One contract, validation policy and attempt recording across both modes; removes the markdown-then-extract chain and duplicate video writes.
- **Rejected:** separate agent and gateway validation policies; keeping the legacy console schema files.
- **Links:** [`analysis-schema.md`](analysis-schema.md); `services/agent/src/vss_agents/incident_contract/`.

### 2026-10-16: unless-stopped restart policy
- **Decision:** `compose.override.yml` sets `restart: unless-stopped` on the persistent services, plus `deploy.restart_policy.condition: unless-stopped` on `streamprocessing-ms` (upstream's deploy `always` overrides `restart`). `nvstreamer-2d-fusion` keeps upstream `on-failure`.
- **Why:** Upstream `restart: always` restarts stopped containers on every VM reboot; runtime `docker update` is lost on recreate.
- **Rejected:** ad-hoc `docker update`; editing upstream compose files.
- **Links:** [`compose.override.yml`](../compose.override.yml); [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-28: Dashboard and time filters use the viewer's timezone
- **Decision:** `get_incident_dashboard` and `list_incident_report_summaries` take `p_timezone` (default `'UTC'`) and convert `reports.generated_datetime` (naive UTC) for weekday and hour grouping and filtering. The console sends the viewer's IANA zone (offsets rejected) detected after mount; labels show local hours with the zone name. Migration `20260928000000` must be applied before or with the console deploy.
- **Why:** Operators analyse by local shift. Dashboard drill-down links stay count-exact because both pages detect the same zone.
- **Rejected:** client-side re-bucketing; converting the column to `timestamptz`.
- **Links:** [`../supabase/midterm/migrations/20260928000000_local_time_heatmap_and_time_filters.sql`](../supabase/midterm/migrations/20260928000000_local_time_heatmap_and_time_filters.sql); [`../incident-console-v2/lib/time.ts`](../incident-console-v2/lib/time.ts).

### 2026-09-27: Validation policy core-scored-v1
- **Decision:** Only database-backed fields (type, window, description, severity, confidence, entities, instruments, assets) decide persistence and scoring. `title`, `severity_reason`, `location`, `timeline` and `uncertainties` are best-effort enrichment: a `TIMELINE_*` failure is recorded and shown but neither rejects the report nor empties the eval prediction, and is never repaired. A contextual core rule requires the window to lie within the video when its length is readable (`0 <= T < duration + 1`). Schema violations stay fatal. `full_contract_ok` keeps contract validity; `core_ok` decides.
- **Why:** In a 12-call pilot the strict timeline rule rejected 7 answers, 4 with windows matching ground truth, yet accepted a 29-36 s window on a 12.5 s clip. Recovered answers rose from 6 of 15 to 13 of 15.
- **Rejected:** a whole-video timeline (deferred); isolating enrichment schema errors (needs partial parsing).
- **Links:** [`../contracts/README.md`](../contracts/README.md); [`../eval/contract.py`](../eval/contract.py); [`../incident-console-v2/lib/contract/validate.ts`](../incident-console-v2/lib/contract/validate.ts).

### 2026-09-27: Console on the shared contract with ID-only repair
- **Decision:** Gateway analysis sends eval's exact P1 request (allowlisted model from `contracts/inference.json`, canonical prompt, strict `response_format`, 16384 tokens, 64 frames) plus an optional fenced reviewer instruction. It validates strictly and records every attempt immutably in `model_runs.notes` with outcome `valid_first_pass`, `valid_after_structural_repair`, `contract_failed` or `request_failed`. The only repair is `id-normalization-v1`: it applies only when every violation is ID-only, changes only IDs, holder references and order, then re-validates. Eval never credits repaired output.
- **Why:** The endpoint enforces the schema, but cross-field rules (sequential IDs, timeline window) can only be checked afterwards. Malformed IDs are safely repairable; timeline content is a model judgement.
- **Rejected:** LLM repair passes; retrying the same request (deterministic at temperature 0); ID patterns in the schema (only if malformed-ID evidence justifies a v4).
- **Links:** [`analysis-schema.md`](analysis-schema.md); [`../incident-console-v2/lib/contract/repair.ts`](../incident-console-v2/lib/contract/repair.ts).

### 2026-09-27: Unified contract decisions (eval, console, agent)
- **Decision:** The eval P1 prompt is the base. Nested snake_case output enforced by `response_format: json_schema`, with the prompt describing field meaning only. One request pattern everywhere: P1 (video to JSON) then RP1 (JSON to prose). Strict parsing, no few-shot, no alias normalisation. Taxonomy is eval's five labels: road accident, burglary, explosion, assault, animal attack. Video is a 1 h signed R2 URL in every path. `confidence_score` is null unless the API gives a native score. `incident.duration` is computed as `end_timestamp - start_timestamp` and is not in the schema. Files live in `contracts/`, validated in Python with `jsonschema` plus cross-field checks in `eval/contract.py`.
- **Why:** The three paths previously differed in prompt, schema, taxonomy, video encoding and parsing, so the benchmark did not measure production behaviour; category few-shot leaked the label; asking a model for a value code can compute only adds a failure mode.
- **Rejected:** a seven-label taxonomy (overlapping labels the ground truth cannot score); base64 video; tolerant parsing; Pydantic as the shared source (the schema file is the neutral source).
- **Links:** [`../contracts/README.md`](../contracts/README.md); [`analysis-schema.md`](analysis-schema.md).

### 2026-09-27: Review and reporting model
- **Decision:**
  - **Official report:** `videos.selected_model_run_id/selected_by/selected_at` with a composite FK to the video's own incidents (ON DELETE SET NULL on the run column), set only by `select_official_report` / `clear_official_report`. Analysis never selects, and selection is independent of review status. PostgREST embeds between `videos` and `incidents` must name `incidents_incident_id_fkey`.
  - **Dashboard:** counts official incidents only; unselected videos are counted separately. Every number links to `/reports?scope=official&...`, the URL is the filter state, and the library's default scope stays "all successful reports".
  - **History:** a video is the parent of its analyses. History combines incident-backed runs with incident-less attempt records whose notes name the video. Re-analysis always creates a new run and never writes the video row or the official selection. Deleting a video removes run records that name it and have no incident left.
  - **Editing:** model output is immutable. Reviewers edit Class A fields, validated against the contract sub-schemas, never touching notes; since 2026-10-20 the edits go to a separate reviewer version (entry above). Ground truth has its own page and is never pre-filled from model output.
  - **Alerts** were removed from the console; the `notifications` table stays for the retired Streamlit console and eval tooling.
- **Why:** Official statistics need one explicit report per video (counting runs multiplies categories on re-runs); failed attempts must be auditable without becoming reports; reviewer edits must never alter what the model produced.
- **Rejected:** "latest run wins" or the verified run as official; a separate attempts table; editing notes; making Class B fields editable.
- **Links:** [`../supabase/midterm/migrations/20260927170000_official_report_selection.sql`](../supabase/midterm/migrations/20260927170000_official_report_selection.sql); [`../supabase/midterm/migrations/20260927160000_apply_structured_report_edit.sql`](../supabase/midterm/migrations/20260927160000_apply_structured_report_edit.sql); [`../supabase/midterm/migrations/20260927180000_official_dashboard_and_library_filters.sql`](../supabase/midterm/migrations/20260927180000_official_dashboard_and_library_filters.sql); [`analysis-schema.md`](analysis-schema.md).

### 2026-09-27: Report library and thumbnails
- **Decision:** `/reports` is served by the `list_incident_report_summaries` RPC (`SECURITY INVOKER`, `service_role` only), six summaries per page, returning no notes, evidence arrays or signed URLs. Cards never load video. The browser captures a frame 25% into each new upload (at most 640x360 WebP) and uploads it to `thumbnails/<video-key>.webp`; a missing thumbnail shows a skeleton, and deleting a video deletes its thumbnail. `GET /api/reports/<videoId>?run=<modelRunId>` is the only path that signs and loads a video.
- **Why:** The old library read eight tables, parsed every report and signed every video before becoming usable.
- **Rejected:** a summary table; client-side slicing; per-card video loading; server-side frame extraction per request.
- **Links:** [`../supabase/midterm/migrations/20260926120000_list_incident_report_summaries.sql`](../supabase/midterm/migrations/20260926120000_list_incident_report_summaries.sql); [`../incident-console-v2/app/api/reports/route.ts`](../incident-console-v2/app/api/reports/route.ts).

### 2026-09-26: Durability checks and upload key layout
- **Decision:** `incident-console-v2` verifies direct uploads with R2 `HeadObject`, verifies again before inference, then reads back `videos`, `model_runs`, `incidents` and `reports` and confirms `videos.filepath` is the submitted R2 key before `POST /api/analysis` returns 200. All new uploads go under `uploads/<sensorId>/<uuid>.<ext>`; `anomaly/<category>/` is reserved for classified seed and eval media.
- **Why:** A valid-looking key does not prove the object exists, independent PostgREST writes can partly succeed, and an upload path cannot encode a classification that happens after storage.
- **Rejected:** trusting individual write responses; moving objects after analysis.
- **Links:** [`../incident-console-v2/lib/r2/config.ts`](../incident-console-v2/lib/r2/config.ts); [`data.md`](data.md).

### 2026-09-25: Database defaults, atomic RPC writers and error surfacing
- **Decision:** Server-side UTC defaults on timestamp columns, `review_status.status` default `'unreviewed'`, `notifications.acknowledged` default `FALSE`, and `insert_incident` with `p_confidence_score DOUBLE PRECISION` (migration `20260925031000`). PostgREST writers call `/rpc/insert_incident` atomically. The agent returns HTTP 422/504 on extraction failure instead of persisting a default report. Composite `ON DELETE CASCADE` stays.
- **Why:** Defaults were client-side only, leaving NULL timestamps; the `REAL` parameter lost precision; non-RPC writes were not atomic; failures persisted a fake default report. Cascade is intentional for re-analysis under one run id.
- **Rejected:** dropping `ON DELETE CASCADE`; overloading `insert_incident` (PostgREST reports ambiguity).
- **Links:** [`../supabase/midterm/migrations/20260925031000_schema_defaults_and_precision.sql`](../supabase/midterm/migrations/20260925031000_schema_defaults_and_precision.sql); [`data.md`](data.md).

### 2026-09-25: Remote Brev inference, no local GPU NIMs
- **Decision:** `vss-agent` and the eval judge use the Brev Switchyard endpoint with `_type: openai` (never `nim`) and bare base URLs, `LLM_NAME=nvidia/nemotron-3-ultra`, `VLM_NAME=nvidia/cosmos-3-super-reasoner`. On-prem GPU NIM deployment is retired.
- **Why:** The NGC free tier caps at 16 concurrent requests and hung report generation; local NIMs would consume a GPU for no benefit. `_type: nim` leaks `verify_ssl` into the request body (HTTP 400). Probes passed tool calling and `json_schema` on Nemotron and base64 `video_url` on Cosmos. Cosmos models reject tool calling on Brev, so they cannot be the LLM.
- **Rejected:** Cosmos for both roles; splitting endpoints between Brev and NGC (shared `OPENAI_API_KEY`).
- **Links:** [`architecture.md`](architecture.md); [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-25: Agent-doc layout and SDRC removal
- **Decision:** A profile `AGENTS.md` for code changes and agentskills.io skills under `skills/` for operations, linked into repo-root `.claude/skills/` by symlinks. `sdr-controller` and its helper services are scaled to 0 in `compose.override.yml`, the single mechanism for disabling SDRC; `SDR_CONTROLLER_CONFIG_PATH` stays because upstream interpolates it at parse time.
- **Why:** Mirrors NVIDIA's split of coding guidance and operating guidance. SDRC is unused (file upload, not live RTSP routing) and clashed with streamprocessing on port 10000, crash-looping.
- **Rejected:** skills in root `skills/` (merge conflicts with upstream); editing shared SDRC files.
- **Links:** [`../AGENTS.md`](../AGENTS.md); [`../skills/README.md`](../skills/README.md); [`../compose.override.yml`](../compose.override.yml).

### 2026-09-24: Retire the Streamlit console; separate eval pipeline; R2 upload fallback
- **Decision:** `incident-console-v2` (Next.js) is the sole UI; the Streamlit `incident-console` is retired (fixes only). Evaluation is a standalone P1/RP1 pipeline in `eval/`, not `nat eval`, because it scores per-field extraction against tabular ground truth rather than chat trajectories. When a real VST chunk upload returns no durable R2 key, the console uploads directly to R2 via `/api/uploads/r2`.
- **Why:** The Streamlit UI was slow; real VST never returns an R2 key, only the mock faked it.
- **Links:** [`../eval/`](../eval/); [`../incident-console-v2/app/api/uploads/r2/route.ts`](../incident-console-v2/app/api/uploads/r2/route.ts).

### 2026-09-21: Native services on kwanz-ws
- **Decision:** Run `vss-agent`, `video-analytics-api` and `behavior-analytics` as native host processes via `.scripts/native-services.sh`; VIOS/VST media and infrastructure stay in Docker.
- **Why:** A code change is a ~2 s restart instead of a container rebuild. Media, DeepStream, Triton and JVM appliances depend on container toolchains and gain nothing natively. All services use host networking, so native processes reach Docker ones on localhost.
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-17: Agent database access through PostgREST
- **Decision:** The agent uses Supabase PostgREST over HTTPS (`utils/incident_db.py`, `supabase-py`) and the `insert_incident` RPC for atomic upserts and review resets.
- **Why:** The campus firewall on `kwanz-ws` drops outbound port 5432, so raw Postgres drivers fail; PostgREST lacks client-held transactions, so atomicity needs the RPC.
- **Rejected:** direct Postgres / `asyncpg` on the VM.
- **Links:** [`data.md`](data.md); `services/agent/src/vss_agents/utils/incident_db.py`.

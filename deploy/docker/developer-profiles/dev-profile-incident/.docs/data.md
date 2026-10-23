# Incident Search & Reporting Capstone — Data Layer & Schema

This document defines the relational database schema (Supabase PostgreSQL), the object storage layout
(Cloudflare R2), and documented data layer edge cases in the `dev-profile-incident` architecture.

---

## 1. Supabase PostgreSQL Schema

There is one Supabase project per project phase ([decision](decisions.md)): **finals** is the live database and **midterm** (`rfevukimyftzbxlehwel`) is a frozen, read-only record. The finals schema is defined authoritatively by the baseline
[`supabase/migrations/20261020000000_finals_baseline.sql`](../supabase/migrations/20261020000000_finals_baseline.sql) and any later finals migration in the same folder (applied via `supabase db push`; see [`../supabase/README.md`](../supabase/README.md)). Schema authority is the migrations, not the archived Streamlit v1 console's `archived/incident-console/db.py`. The midterm history is archived, never to be pushed, in [`supabase/midterm/`](../supabase/midterm/README.md). The SQL harness in `supabase/tests/` tests the schema on a throwaway local Postgres. It supports multi-model runs over the same video, a parallel
evaluation structure, human review workflows, and the MVP2 vector search extension
(`evidence_crops`, `query_results`; see [`mvp2/README.md`](mvp2/README.md)).

### Report-library summary RPC

`list_incident_report_summaries` (finals baseline) is a `SECURITY INVOKER`, `STABLE` SQL function exposed only to `service_role`.
- **Inputs:** it joins `reports`, `effective_incidents` (the [reviewer version](#reviewer-version-and-effective-views) if there is one, else the AI rows), `model_runs`, `videos` and `review_status` and applies search, filter, sort and pagination in Postgres. Beyond the earlier type, severity, status, date/time/weekday and evidence-substring filters it takes:
  - `p_scope`: `'all'` (default: every successful report) or `'official'` (only each video's selected official report);
  - `p_entity_types`: exact canonical entity type;
  - `p_evidence_match`: `'contains'` (default) or `'exact'` (normalised instrument/asset name equality);
  - `p_timezone`: IANA zone for the weekday and time-of-day filters (default `'UTC'`).
- **Folding:** legacy incident types are folded (`fighting` → `assault`, `animal` → `animal attack`) for both filtering and display. The midterm-to-finals copy rewrote every stored legacy value once; folding stays as a guard for any writer that still sends a legacy value.

- **Per-report outputs:**
  - the analysis `outcome`, from `run_outcome(notes)`;
  - `isOfficial`;
  - a nullable `confidence`;
  - the contract-v2 title (`incidentConsoleV2.report.incident.title`), falling back to the legacy title paths.
- **What it never returns:** notes, evidence arrays, signed URLs or video content. The normal library API fixes `page_size` at 6; `all=true` may request up to 1,000 lightweight summaries.

Helper functions (service role):
- `canonical_incident_type`, `canonical_entity_type` (`person` → `human`) and `normalized_name` (lower-case, trimmed, single spaces);
- `run_outcome(notes)`: `valid_first_pass`, `valid_after_structural_repair`, `contract_failed`, `request_failed` or `legacy`;
- `timestamp_seconds(text)`: integer seconds from `"18"` or `"0:18"`, NULL otherwise;
- `try_parse_jsonb(text)`: JSON or NULL.

**Reviewer edits and review status.** The AI rows (`incidents`, `entities`, `instruments`, `assets`) are written once by analysis and never edited. Reviewers write a separate [reviewer version](#reviewer-version-and-effective-views). All RPCs below are service-role only and none touches an AI row or `model_runs.notes`:
- `save_human_report_edit(p_incident_id, p_model_run_id, p_edit, p_edited_by)` saves the reviewer version in one transaction (created on the first edit, replaced on later ones; `revision + 1`). It re-checks the contract's types, ranges, sequential IDs and holder references. **Every item must carry `source_id`**, the AI item it came from: it must name an AI item of the same kind in this run, at most once; an explicit `null` marks a reviewer-added item. The editor renumbers items by position, so an item's own ID says nothing about its origin, and the function never guesses one: an edit with any item lacking the key (text or `null`) is refused, before anything is written, with a message naming those items and asking for the console update that sends `source_id`. The console sends it from the `incident-console-v2` reviewer-version change on (`lib/reports/edit-draft.ts`; it reads each item's origin from the `effective_*` views' `source_*_id`); the midterm console sends none, so its edits are refused on finals. It sets `review_status.edited_by/at`, and **an edit of a verified report sends it back to `under review` and clears the verifier**. Returns `incidentId`, `modelRunId`, `editedBy`, `editedAt`, `duration`, `revision`, `status`.
- `apply_structured_report_edit` (same arguments) is a compatibility shim over `save_human_report_edit` with the midterm RPC's name and result keys. It refuses keyless edits the same way. It goes once no console calls it.
- `set_review_status(p_incident_id, p_model_run_id, p_status, p_reviewer)` is one atomic transition (`unreviewed`, `under review`, `verified`). **Verifying a report with no reviewer version first copies the AI report into one** (`create_human_report_from_ai`), so every verified report has a reviewer version. It refuses with a clear message when the AI report is not valid as it stands (for example an unrated instrument); the reviewer edits first. It never writes `edited_by/at`. Returns `status`, `verifiedBy`, `verifiedAt`, `changed`, `humanVersionCreated`.
- `create_human_report_from_ai(p_incident_id, p_model_run_id, p_created_by, p_created_at)` copies the AI report into a new reviewer version, normalising legacy values the way the console editor does (`e01` → `E1` with `source_entity_id = 'e01'`, `person` → `human`, `fighting` → `assault`, `"0:18"` → 18).

The superseded midterm RPCs `apply_incident_report_patch` and `replace_incident_evidence` do not exist in finals.

**Official report selection (D6).** `select_official_report(p_video_id, p_model_run_id, p_selected_by)` and `clear_official_report(p_video_id, p_cleared_by)`:
- only a successful analysis of the same video with a `reports` row can be selected;
- analysis never selects;
- selection is independent of review status.

**Dashboard.** `get_incident_dashboard` (finals baseline) is a service-role-only aggregation RPC over **official incidents only**, reading the `effective_*` views: one per video with an official report, filtered by the official report's generation time plus optional type, severity-band, weekday and hour (in the target timezone specified by `p_timezone`, defaulting to UTC). It returns:
- `total`;
- all-time `videos` counts: `uploaded`, `withOfficial`, `awaitingSelection` (has reports, none official) and `withoutReport` (no incident);
- severity, review funnel, types with per-type evidence, daily trend and heatmap;
- `entityTypes`, `topInstruments` and `topAssets` (by normalised name, counted per distinct incident);
- `threatLevels`;
- a confidence histogram excluding nulls, plus `confidenceNotProvided`;
- `modelCoverage`: per model, attempts by outcome, including failed attempts in the period.

Every dashboard count equals the library total for `scope=official` with the same filters (instrument/asset links use `match=exact`).

### Relationships

Composite FKs `(incident_id, model_run_id)` to `incidents` (ON DELETE CASCADE) are the spine: `reports`, `entities`, `instruments`, `assets`, `human_reports`, `evidence_crops`, `query_results`, and `review_status` all hang off it. The `human_report_*` item tables hang off `human_reports` (CASCADE), and their `source_*_id` links to the AI items are `ON DELETE SET NULL` (a `NO ACTION` link would make run and video deletes fail, because the delete reaches the reviewer items along two cascade paths). `incidents` references `videos` and `model_runs` (CASCADE). `reports.query_id` and `query_results.query_id` reference `queries`. (The retired `notifications`, `entity_matches`, `instrument_matches`, `asset_matches`, `severity_eval_log`, `gt_incidents`, `gt_entities`, `gt_instruments`, and `gt_assets` tables have been dropped from the live finals database; formerly `gt_incidents` referenced `videos` and `gt_entities`, `gt_instruments` and `gt_assets` referenced `gt_incidents`). Column-level detail is in the table specifications below and in the finals baseline.

---

### Detailed Table Specifications

#### 1. Shared Reference Tables

##### `videos`
Primary registry of ingested video assets.
- **Identity Rule:** 1 video = 1 incident (`incidents.incident_id` == `videos.id`, no separate `video_id` column). `videos.id` serves as the natural primary key.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(20)` | PRIMARY KEY | Video identifier: `'v' + first 19 hex of sha256(sensorId)` for uploads (20 chars); clip-name ids (e.g. `Burglary012`, `RoadAccidents...`, `SYN-...`, `MOCK-...`) for fixture/eval rows. Equals `incident_id`. Raw sensor ids are never used directly as `id` since they can be up to 128 chars. |
| `filepath` | `VARCHAR(1024)` | NULLABLE | R2 object key (`uploads/<sensorId>/<uuid>.<ext>`, `anomaly/<category>/<clip>.mp4`, or `normal_videos/<clip>.mp4`). Not guaranteed: legacy v1-console rows may hold an absolute VST path (`/home/vst/...`) — validate with `isValidR2Key` before presigning. (The agent no longer writes `videos`; the console owns `videos.filepath`). |
| `uploaded_datetime` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC timestamp (`timestamp without time zone`) when uploaded. Database default; some historical rows are NULL. |
| `duration` | `INTEGER` | NULLABLE | Video duration in integer seconds |
| `source` | `VARCHAR(512)` | NULLABLE | Sensor ID, ingestion source, or camera stream name |
| `selected_model_run_id` | `VARCHAR(20)` | NULLABLE; composite FK `(id, selected_model_run_id)` → `incidents(incident_id, model_run_id)` ON DELETE SET NULL (`selected_model_run_id`) | The video's explicitly selected **official report** (D6). NULL = awaiting selection. Only set/cleared by `select_official_report` / `clear_official_report`; analysis never writes it. Because of this second relationship, PostgREST embeds between `videos` and `incidents` must name `incidents_incident_id_fkey`. |
| `selected_by` / `selected_at` | `VARCHAR(256)` / `TIMESTAMP` | NULLABLE | Who selected the official report and when (naive UTC). May outlive a selection cleared by the FK when the official incident is deleted; the UI treats `selected_model_run_id IS NULL` as "no official report". |

##### `queries`
Tracks natural language queries submitted by users (MVP2 search).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(20)` | PRIMARY KEY | Unique query identifier |
| `query_text` | `TEXT` | NOT NULL | Natural language query string |
| `submitted_datetime` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC timestamp when submitted |

##### `model_runs`
Tracks each execution of an AI pipeline run over an incident video.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(20)` | PRIMARY KEY | Unique model execution identifier |
| `model_name` | `VARCHAR(128)` | NOT NULL | Model identifier (e.g. `nvidia/cosmos-3-nano-reasoner`, `incident_report_gen`, `vss-agent`) |
| `model_version` | `VARCHAR(128)` | NULLABLE | Optional version tag of the model |
| `prompt_version` | `VARCHAR(64)` | NULLABLE | Prompt template version tag |
| `run_datetime` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC execution timestamp |
| `notes` | `TEXT` | NULLABLE | Free text, nullable. `incident-console-v2` writes the **immutable analysis-attempt record** `{"incidentConsoleV2":{recordType:"analysis_attempt", status, stage, failure, contractVersion, videoId, r2Key, attemptedAt, request, response, validation, repair, report?}}` for every attempt (see [`analysis-schema.md` §4](analysis-schema.md#4-storage)); it is never modified afterwards. Failed attempts (`contract_failed` / `request_failed`) are `model_runs` rows with no incident, report, review or evidence rows; their video association is `notes.incidentConsoleV2.videoId`. Older console rows hold `{"incidentConsoleV2":{report,editedReport?,rawModelOutput,normalizedModelOutput}}`; `mock-backend` stores a plain-text note; agent/seed/eval runs leave it NULL. Batch eval/seed runs (`P1-*`, `MR-SEED`, `MOCK8`) are shared by many videos: run history is keyed by (video, run), not by `model_runs` row. Any count of runs must filter by outcome (`run_outcome(notes)`) or count via `reports`. |

---

#### 2. Model Output Tables

##### `incidents`
AI-extracted incident intelligence for a specific model run over a video.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `incident_id` | `VARCHAR(20)` | PRIMARY KEY, FK -> `videos.id` ON DELETE CASCADE | Associated video/incident identifier |
| `model_run_id` | `VARCHAR(20)` | PRIMARY KEY, FK -> `model_runs.id` ON DELETE CASCADE | Model run identifier |
| `type` | `VARCHAR(32)` | NULLABLE | Free text (VARCHAR(32)); contract taxonomy `road accident`, `burglary`, `explosion`, `assault`, `animal attack` (`incident-contract-v2` / `incident-contract-v3`) is not enforced by a DB CHECK constraint. The midterm-to-finals copy relabelled stored `fighting` → `assault` and `animal` → `animal attack` (33 rows); 0 rows hold `other`. The `MOCK8` demo rows keep types outside the taxonomy (`warehouse safety`, `equipment`, ...). Consumers still fold legacy values. NULL is allowed (eval and seed rows). |
| `start_timestamp` | `VARCHAR(32)` | NULLABLE | Free text: either a clock string (`M:SS` / `H:MM:SS`, agent & console) or bare seconds (e.g. `"21"`, `"15.6"`, eval/P1 and `gt_*` rows). Consumers must accept both (see `eval_gt._timestamp_seconds`). |
| `end_timestamp` | `VARCHAR(32)` | NULLABLE | Free text: either a clock string (`M:SS` / `H:MM:SS`, agent & console) or bare seconds (e.g. `"21"`, `"15.6"`, eval/P1 and `gt_*` rows). Consumers must accept both (see `eval_gt._timestamp_seconds`). |
| `duration` | `INTEGER` | NULLABLE | Incident duration in seconds |
| `description` | `TEXT` | NULLABLE | Narrative summary of the incident |
| `severity_level` | `INTEGER` | NULLABLE | Severity score (1 to 5) |
| `confidence_score`| `DOUBLE PRECISION` | NULLABLE | Model confidence score (0.0 to 1.0). Rows written before the RPC parameter was widened to `DOUBLE PRECISION` may hold float4-rounded values. |

##### `reports`
Artifact pointer table linking an incident and model run to external files or queries.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(20)` | PRIMARY KEY | Report record identifier |
| `incident_id` | `VARCHAR(20)` | NOT NULL; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked incident identifier |
| `query_id` | `VARCHAR(20)` | NULLABLE, FK -> `queries.id` ON DELETE SET NULL | Triggering search query (always NULL today) |
| `model_run_id` | `VARCHAR(20)` | NOT NULL; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked model run identifier |
| `filepath` | `VARCHAR(1024)` | NULLABLE | Optional path to rendered report artifact: NULL (`incident-console-v2`) or `mock://reports/<file>` (`mock-backend`). |
| `generated_datetime`| `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC generation timestamp |

##### `entities`
Observed actors or persons extracted by the model during a specific run.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `incident_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked incident identifier |
| `entity_id` | `VARCHAR(20)` | PRIMARY KEY | Writer-specific id: `E1`/`E2` (seed/eval, contract, console-v2), `e01`/`e02` (3 legacy console runs), `E1`/`E2` (agent standalone), `p...` (mock). |
| `model_run_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked model run identifier |
| `type` | `VARCHAR(16)` | NULLABLE | Free text (VARCHAR(16)): both analysis modes write contract entity types (`human`, `animal`, `unknown`). The midterm-to-finals copy relabelled the 6 stored `person` rows to `human`; `canonical_entity_type` still folds `person` → `human` at query time. `GET /api/reports/[videoId]` maps every entity row (including legacy `animal` rows) into the report's `persons` list. |
| `description` | `TEXT` | NULLABLE | Visual description and observed actions |
| `image` | `VARCHAR(1024)` | NULLABLE | R2 object key for cropped evidence screenshot (schema-only, always NULL today) |

##### `instruments`
Observed tools, objects, or weapons extracted by the model.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `incident_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked incident identifier |
| `instrument_id`| `VARCHAR(20)` | PRIMARY KEY | Writer-specific id: `I1` (seed/eval, contract, console-v2), `i01` (3 legacy console runs), `I1` (agent standalone). |
| `model_run_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked model run identifier |
| `entity_id` | `VARCHAR(20)` | NULLABLE | Wielding entity identifier (if identified) |
| `name` | `VARCHAR(256)` | NULLABLE | Instrument name (e.g. `crowbar`, `knife`) |
| `description` | `TEXT` | NULLABLE | Contextual usage description |
| `threat_level` | `INTEGER` | NULLABLE | Threat rating (1 to 5, or NULL when not rated) |
| `image` | `VARCHAR(1024)` | NULLABLE | R2 object key for cropped evidence screenshot (always NULL today) |

##### `assets`
Observed physical property, infrastructure, or vehicles extracted by the model.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `incident_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked incident identifier |
| `asset_id` | `VARCHAR(20)` | PRIMARY KEY | Writer-specific id: `A1` (seed/eval, contract, console-v2), `a01` (3 legacy console runs), `A1` (agent standalone). |
| `model_run_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked model run identifier |
| `name` | `VARCHAR(256)` | NULLABLE | Asset name (e.g. `cash register`, `sedan`) |
| `description` | `TEXT` | NULLABLE | Observed physical damage or involvement |
| `image` | `VARCHAR(1024)` | NULLABLE | R2 object key for cropped evidence screenshot (always NULL today) |

---

#### 3. Review Workflow & Operational Tables

##### `review_status`
Carries the reviewer verification state independently of the AI report.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `incident_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked incident identifier |
| `model_run_id` | `VARCHAR(20)` | PRIMARY KEY; composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Linked model run identifier |
| `status` | `VARCHAR(32)` | NOT NULL, DEFAULT `'unreviewed'` | State (`unreviewed`, `under review`, `verified`). |
| `verified_by` | `VARCHAR(256)` | NULLABLE | Reviewer username who verified the report |
| `verified_at` | `TIMESTAMP` | NULLABLE | Naive UTC timestamp of verification |
| `edited_by` | `VARCHAR(256)` | NULLABLE | Editor of the last **content** edit (`save_human_report_edit`). Status changes never write it. The copy clears a midterm stamp only when it was provably a status change (a contract run whose rows equal its notes record, 4 runs at the 2026-10-21 rehearsal) or when a person decided so for a legacy run (`--not-edited`; `m37883594f65802c8a31` is the one such run) |
| `edited_at` | `TIMESTAMP` | NULLABLE | Naive UTC timestamp of the last content edit |

##### `notifications` (dropped)
Dropped from the live finals database; formerly used by the archived Streamlit v1 console.

##### `severity_eval_log` (dropped)
Dropped from the live finals database; formerly tracked comparative human vs. AI severity scoring for human-in-the-loop evaluation.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INTEGER` | PRIMARY KEY, AUTOINCREMENT | Log entry identifier |
| `incident_id` | `VARCHAR(20)` | composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Associated incident |
| `model_run_id` | `VARCHAR(20)` | composite FK `(incident_id, model_run_id)` -> `incidents` ON DELETE CASCADE | Associated model run |
| `ai_severity` | `INTEGER` | NULLABLE | Severity score produced by the AI |
| `human_severity`| `INTEGER` | NULLABLE | Severity score assigned by human reviewer |
| `rater` | `VARCHAR(256)` | NULLABLE | Evaluator name |
| `rated_at` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Evaluation timestamp (naive UTC) |

---

##### Reviewer version and effective views

The reviewer's version of one run's report, next to the immutable AI rows. One per run, keyed like `review_status`; created on the first edit (`save_human_report_edit`) or on verification (`set_review_status` copies the AI report), never by analysis. It is always a complete, contract-valid report (CHECKs enforce the taxonomy, 1-5 ranges and sequential `E/I/A` IDs).

| Table | Key | Columns |
|---|---|---|
| `human_reports` | `(incident_id, model_run_id)`, FK → `incidents` ON DELETE CASCADE | `type`, `start_seconds`, `end_seconds` (integer seconds), `duration` (generated), `description`, `severity_level`, `revision` (+1 per saved edit), `created_by/at`, `edited_by/at` (last content edit; NULL = verified as the AI wrote it) |
| `human_report_entities` | `+ entity_id` (`E1..`) | `source_entity_id` (the AI entity it came from; NULL = added by the reviewer; unique per run), `type`, `description` |
| `human_report_instruments` | `+ instrument_id` (`I1..`) | `source_instrument_id`, `entity_id` (holder: one of this version's entities), `name`, `description`, `threat_level` (1-5, required) |
| `human_report_assets` | `+ asset_id` (`A1..`) | `source_asset_id`, `name`, `description` |

`insert_incident` refuses to re-run a run that has a reviewer version (it would cascade it away).

**Effective views.** `effective_incidents`, `effective_entities`, `effective_instruments` and `effective_assets` give the report every reader means: the reviewer version if the run has one, otherwise the AI rows. They have the same columns in the same order as the AI tables (timestamps as text; `confidence_score` always from the AI row), plus `source_*_id` and `source` (`'ai'` or `'human'`), so a reader switches by changing only the relation name. They are `security_invoker`, read-only, and `service_role` only. The library, dashboard and search RPCs read them; eval and the crop loader read the AI tables, which are guaranteed model output.

#### 4. Ground-Truth (GT) & Evaluation Matching Tables (dropped)

##### `gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets` (dropped)
Dropped from the live finals database; formerly parallel tables mirroring `incidents`, `entities`, `instruments`, and `assets`, but without
`model_run_id`, storing verified human annotations.
- `gt_incidents.type`: Free text (`VARCHAR(32)`), not CHECK-constrained. `eval/scripts/eval_ingest_gt.py` wrote the canonical lowercase type (one of the five standard types); rows ingested earlier may still have been capitalised (`Assault`, `Animal Attack`).
- `gt_incidents.start_timestamp` / `end_timestamp`: Free text (`VARCHAR(32)`), storing bare seconds (e.g. `"21"`, `"15.6"`).
- `gt_incidents` included `labelled_by` and `labelled_datetime` (naive UTC) instead of AI confidence/model fields.
- `gt_entities`, `gt_instruments`, and `gt_assets` referenced `gt_incidents(incident_id)` with `ON DELETE CASCADE` (they referenced `gt_incidents`, not `videos` or `incidents`).
- `image` columns in `gt_*` tables were schema-only and always NULL.

##### `entity_matches`, `instrument_matches`, `asset_matches` (dropped)
Dropped from the live finals database; formerly stored accepted similarity pairings during v1 ground-truth evaluation.
Evaluation code in `eval/` still contains match persistence routines against these tables, which is out of scope here and handled separately.

#### 5. MVP2 Vector Search & Evidence Crops Tables

##### `evidence_crops`
Unified storage for item-level evidence crops, detector bounding boxes, and pgvector semantic embeddings. Crops belong to **AI items** (which never change); a reviewer item reaches its crop through `source_*_id`, and a reviewer-added item has none.
- **Primary Key:** `(incident_id, model_run_id, item_type, item_id)`
- **Foreign Key:** `(incident_id, model_run_id)` -> `incidents(incident_id, model_run_id) ON DELETE CASCADE`
- **Vector Index:** HNSW cosine distance (`extensions.vector_cosine_ops`) index `evidence_crops_embedding_hnsw_idx` with `m = 16, ef_construction = 64` on `embedding`.
- **Secondary Index:** Composite lookup index `evidence_crops_lookup_idx` on `(incident_id, model_run_id)`.
- **Row-Level Security:** RLS enabled; all permissions revoked from `anon` and `authenticated`; granted exclusively to `service_role`.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `incident_id` | `VARCHAR(20)` | PRIMARY KEY, composite FK -> `incidents` ON DELETE CASCADE | Associated video/incident identifier |
| `model_run_id` | `VARCHAR(20)` | PRIMARY KEY, composite FK -> `incidents` ON DELETE CASCADE | Model run identifier |
| `item_type` | `VARCHAR(16)` | PRIMARY KEY, CHECK (`item_type IN ('entity', 'instrument', 'asset')`) | Evidence category |
| `item_id` | `VARCHAR(20)` | PRIMARY KEY | Sequential item identifier (`E1..`, `I1..`, `A1..`) |
| `item_name` | `VARCHAR(256)` | NOT NULL | Item name or detector label (the copy relabelled 3 entity crops `person` → `human`) |
| `description` | `TEXT` | NOT NULL | Item visual description |
| `threat_level` | `INTEGER` | NULLABLE | Threat rating (1 to 5, or NULL for entities/assets) |
| `holder_entity_id` | `VARCHAR(20)` | NULLABLE | Identifier of holding entity (instruments only) |
| `timestamp_seconds` | `INTEGER` | NOT NULL | Whole-second offset from video start where item is visible |
| `bounding_box` | `INTEGER[4]` | NOT NULL | Normalized coordinates `[ymin, xmin, ymax, xmax]` (0–1000) from detector pass |
| `image` | `VARCHAR(1024)` | NOT NULL | R2 object key: `evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg` |
| `embedding` | `extensions.vector(1024)` | NULLABLE | 1024-dimensional semantic text embedding for cosine retrieval |
| `created_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC insertion timestamp |

##### `query_results`
Audit log and hit persistence for natural-language search queries and always-on VLM critic evaluation.
- **Primary Key:** `id` (`VARCHAR(36)`)
- **Foreign Keys:** `query_id -> queries(id) ON DELETE CASCADE`; `(incident_id, model_run_id) -> incidents(incident_id, model_run_id) ON DELETE CASCADE`.
- **Secondary Indexes:** `query_results_query_rank_idx` on `(query_id, rank)`; `query_results_incident_item_idx` on `(incident_id, model_run_id, item_type, item_id)`.
- **Row-Level Security:** RLS enabled; all permissions revoked from `anon` and `authenticated`; granted exclusively to `service_role`.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | Unique result identifier (UUID or hex) |
| `query_id` | `VARCHAR(20)` | NOT NULL, FK -> `queries.id` ON DELETE CASCADE | Associated search query identifier |
| `incident_id` | `VARCHAR(20)` | NOT NULL, composite FK -> `incidents` ON DELETE CASCADE | Target incident identifier |
| `model_run_id` | `VARCHAR(20)` | NOT NULL, composite FK -> `incidents` ON DELETE CASCADE | Target model run identifier |
| `item_type` | `VARCHAR(16)` | NOT NULL, CHECK (`item_type IN ('entity', 'instrument', 'asset')`) | Target evidence item type |
| `item_id` | `VARCHAR(20)` | NOT NULL | Target evidence item identifier |
| `rank` | `INTEGER` | NOT NULL | Retrieval rank position (1-based) |
| `similarity_score` | `DOUBLE PRECISION` | NOT NULL | Vector cosine similarity score (`1.0 - distance`) |
| `critic_verdict` | `VARCHAR(16)` | NOT NULL, CHECK (`critic_verdict IN ('confirmed', 'rejected', 'unverified')`) | VLM critic verification outcome |
| `critic_rationale` | `TEXT` | NULLABLE | Objective rationale from VLM critic justifying verdict |
| `retrieved_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Retrieval timestamp (naive UTC) |

---

### The `search_evidence_items` Postgres RPC Function

`search_evidence_items` (finals baseline) is a `SECURITY INVOKER`, `STABLE` SQL function exposed strictly to `service_role`. It executes pgvector HNSW cosine distance search over `evidence_crops.embedding`, strictly scoped to official reports (`videos.selected_model_run_id = ec.model_run_id`). Incident type, severity and description come from `effective_incidents`. When the run has a reviewer version, a crop whose AI item the reviewer removed is not returned, and the item's name (an entity's is its type), description and threat level come from the reviewer item. Ranking still uses the stored embedding of the AI text. Same signature and output columns as on midterm, so the agent's `SupabaseSearchStore` is unchanged.

- **Parameters:**
  - `p_query_embedding extensions.vector(1024)`: Normalized 1024-dimensional query vector.
  - `p_top_k INTEGER DEFAULT 10`: Maximum candidate hits to retrieve.
  - `p_min_similarity DOUBLE PRECISION DEFAULT 0.2`: Minimum similarity score threshold (`1.0 - cosine_distance`). The search route always passes its own value (default 0.0).
  - `p_item_types TEXT[] DEFAULT ARRAY['entity', 'instrument', 'asset']`: Evidence category filters.
  - `p_incident_types TEXT[] DEFAULT NULL`: Incident taxonomy filters.
  - `p_min_severity INTEGER DEFAULT NULL`: Minimum severity level (1-5).
  - `p_max_severity INTEGER DEFAULT NULL`: Maximum severity level (1-5).
- **Official Scoping:** Inner joins `videos v ON v.id = ec.incident_id AND v.selected_model_run_id = ec.model_run_id` to ensure only official reports are retrieved. Videos awaiting official report selection or re-analysis runs that are not official are excluded.
- **Permissions:** `REVOKE ALL ON FUNCTION public.search_evidence_items FROM PUBLIC, anon, authenticated; GRANT EXECUTE ON FUNCTION public.search_evidence_items TO service_role;`.

---

### Agent report writes (`report_revisions`)

PostgREST has no client-held transactions, so the agent's report write is one `INSERT` into `report_revisions` (`IncidentDB.insert_ai_revision`): `kind='ai'`, `model_run_id` (a required foreign key), `parent_id` NULL, the full contract report as `payload`, the crop list as `evidence`, and the facet columns (`incident_type`, `severity_level`, `start_seconds`, `end_seconds`) copied from the payload. `revision_no` is `max + 1` for the video; if a concurrent writer takes the number first, the unique `(video_id, revision_no)` key rejects the insert (SQLSTATE 23505) and the agent retries with the next number, five attempts at most with jittered backoff between retries. Rows are append-only (a trigger blocks updates and deletes), so a re-generation is a new row and never changes an earlier revision.

> [!IMPORTANT]
> **Cascading Deletes on Child Records:**
> Because every child table's composite foreign key `(incident_id, model_run_id)` to `incidents` is configured with `ON DELETE CASCADE`, the RPC's initial `DELETE FROM incidents` also silently cascades and deletes all related `entities`, `instruments`, `assets`, `reports`, `review_status`, `human_reports` (and its items), and `evidence_crops` rows for that `(incident_id, model_run_id)` (as it formerly did for `severity_eval_log`). Re-analyzing under the same `model_run_id` therefore wipes all child evidence and reports, which is why the RPC refuses a run that has a reviewer version. Callers must re-insert evidence rows after calling the RPC (both the agent's `_persist_incident` and `incident-console-v2`'s `/api/analysis` do so explicitly).

> [!NOTE]
> **Cascades on Deleting Videos or Model Runs:**
> Foreign keys `videos -> incidents` (and formerly `videos -> gt_incidents`) are `ON DELETE CASCADE`. Deleting a `videos` row (e.g. via `incident-console-v2/app/api/reports/[videoId]/delete/route.ts`) cascades to delete all model runs, evidence, and evaluation matches for that video. Similarly, `model_runs -> incidents` is `ON DELETE CASCADE`; deleting a `model_runs` row wipes every incident scored under it (`insert_model_run` deliberately upserts for that reason).

> **Insertion order for agent writes:**
> In console agent mode the console upserts the run (with its `notes` record) only after the agent returns, so the agent inserts a placeholder row with `ignore_duplicates` (`insert_model_run_if_absent`); the console's later upsert fills in `notes`. Search persists `query_results` against `revision_id`.

---

### Client Access Models & PostgREST/Direct-Postgres Split

Database access is split across two client implementations according to operational requirements:

1. **Tooling & Archived v1 Console (Direct Postgres):**
   The archived v1 console (`archived/incident-console/db.py`) historically used direct Postgres via SQLAlchemy Core and `psycopg2` (`INCIDENT_DB_DSN`). Active UI development in `incident-console-v2` uses Supabase PostgREST (`lib/postgrest/client.ts`). The console is database-backed only; there is no offline CSV-preview UI mode.

2. **Agent Side & Service Writers (Supabase PostgREST):**
   `services/agent/src/vss_agents/utils/incident_db.py` is the agent-side counterpart: an async Supabase
   PostgREST CRUD helper (`supabase-py`'s `AsyncClient`/`acreate_client`, not `asyncpg`/direct-Postgres) against
   the same schema, mirroring the archived v1 `archived/incident-console/db.py`'s tables and columns for the subset an agent-side caller plausibly writes
   (`model_runs`, `incidents`, `entities`, `instruments`, `assets`, `reports`, and `review_status`; the agent never writes `videos`; the `gt_*`
   tables stay eval-only; `notifications` and `*_matches` are dropped).
   - **Configuration:** `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`
     (deliberately NOT `INCIDENT_DB_DSN`, which the direct-Postgres tooling uses, as the archived v1 `archived/incident-console/db.py` did); unset means the feature is
     unavailable, no fallback.
   - **Network Constraint / DPI Blocking Rationale:** This split exists because the deployment VM (`kwanz-ws`) DPI-blocks raw Postgres wire
     protocol on port 5432, so only the HTTPS-based PostgREST route works for the agent from there — a direct-Postgres
     driver on the agent side breaks Analyze on `kwanz-ws`.
   - **Transaction Limits & RPC:** PostgREST has no client-held transactions or `SELECT ... FOR UPDATE`; all PostgREST writers
     (`services/agent/src/vss_agents/utils/incident_db.py`, `incident-console-v2/lib/postgrest/client.ts`, the archived v1 `archived/incident-console/db_postgrest.py`,
     and `eval/db_postgrest.py`) write atomically or retry on conflict: the agent appends `report_revisions` rows with a `revision_no` of `max + 1` and
     retries when the unique key rejects a concurrent writer (SQLSTATE 23505).

### Row-Level Security (RLS) & Access Control

**Finals is locked down from its first migration.** The baseline turns off Supabase's default grants before it creates any object, so nothing is ever exposed, even for a moment:
- **Default-deny:** RLS is on for all 20 tables, with no policies, so `anon` and `authenticated` cannot read, insert, update or delete rows anywhere.
- **No grants to the public roles:** every privilege on every table, view, sequence and function in `public` is revoked from `PUBLIC`, `anon` and `authenticated`. Every function is `service_role`-only, `SECURITY INVOKER`, with `SET search_path = ''`. The `effective_*` views are `security_invoker` and read-only.
- **Default privileges:** objects that `postgres` creates in `public` later get nothing for `anon`/`authenticated` and everything for `service_role`; new functions get no `EXECUTE` for `PUBLIC` in any schema. Objects created by other roles are not covered, so a new function should still be checked by `supabase/tests/security_check.sql`.
- **pgvector lives in `extensions`**, so none of its functions are REST RPCs.
- **Self-check:** the baseline fails (and rolls back) if any table has RLS off, anything is reachable by `anon`/`authenticated`, or any function is `SECURITY DEFINER` or lacks a fixed `search_path`. Run `supabase/tests/security_check.sql` after every applied migration and after the copy (expect 0 rows), and `supabase/tests/probe_api.sh` to confirm over REST that the public key is refused.
- **Role bypass:** Application services (`incident-console-v2`, `vss-agent`, `eval`, `mock-backend`) authenticate via HTTPS PostgREST using `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (`service_role`), or connect directly via Postgres wire protocol using `INCIDENT_DB_DSN` (`postgres`). Both roles hold PostgreSQL's `BYPASSRLS` attribute (`rolbypassrls = true`), preserving full access. On Supabase `postgres` is not a superuser; it skips RLS through `BYPASSRLS`, not superuser status. `FORCE ROW LEVEL SECURITY` is not applied: it only subjects table owners (here `postgres`) to RLS, and `BYPASSRLS` overrides it, so it would change nothing.
- **Signups:** create the finals project with email signups turned off; nobody uses Supabase Auth, and an open signup would let anyone with the public key mint an `authenticated` user (who could still reach nothing).

**Midterm** had RLS on only `evidence_crops` and `query_results` and gave `anon`/`authenticated` full access to the other 20 tables. `supabase/midterm/freeze_midterm.sql` closes that at the cutover and also makes midterm read-only: `service_role` keeps `SELECT` and the read RPCs, every write fails with "permission denied", and direct-DSN sessions start read-only ([`../supabase/midterm/README.md`](../supabase/midterm/README.md)).

### Fixture CSV Seed Data Quirk

Fixture data in `deploy/docker/developer-profiles/dev-profile-incident/archived/incident-console/fixtures/data/*.csv` (archived v1)
(72 rows on disk, 36 real + 36 synthetic `SYN-`-prefixed placeholders with no matching R2 video) is the seed source for the Postgres importer
(`deploy/docker/developer-profiles/dev-profile-incident/archived/incident-console/scripts/seed_supabase.py` via `scripts/seed_data.py`, both archived), which drops the `SYN-`-prefixed rows and seeds only the
36 real incidents under one shared `model_run_id`.

---

## 2. Cloudflare R2 Storage Architecture

Cloudflare R2 provides S3-compatible, permanent object storage for all video media and evidence images.
Local disks on `kwanz-ws` are treated as temporary caches only (though VST stores ingested video files locally).

### Bucket Key Tree Layout

```
anomaly-detection-dataset/            # bucket name comes from R2_BUCKET
├── anomaly/                         # classified dataset clips (seed/eval) only
│   ├── animal_attacks/  assault/  burglary/  explosion/
│   ├── fighting/  road_accidents/  shooting/
│   │   └── <clip-name>.mp4
├── normal_videos/                   # baseline non-incident clips
│   └── <clip-name>.mp4
├── uploads/                         # all new user uploads (real VST fallback and local mock)
│   └── <encodeURIComponent(sensorId)>/<uuid>.<ext>   # ext lowercased, default .mp4
├── thumbnails/                      # browser-captured report-card screenshots for new uploads
│   └── <video-key>.webp             # e.g. thumbnails/uploads/<sensor>/<uuid>.mp4.webp
├── Report/                          # empty folder marker, unused by code
└── evidence/                        # canonical R2 layout for MVP2 crop evidence (CropEvidenceService)
    └── <videoId>/<modelRunId>/{entities,instruments,assets}/<id>.jpg
```

> [!NOTE]
> The `anomaly/` subfolders are reserved for classified seed/evaluation data. New user uploads are classification-neutral and use `uploads/<sensorId>/<uuid>.<ext>` in both local-mock and real-VST flows; the VLM's later incident classification does not move or rename the object.
> In addition to the five fixture categories, live R2 storage includes `assault/` and `shooting/`.
> The `Report/` prefix is a 0-byte directory marker and is unused by code.
> The `evidence/` tree stores cropped entity/instrument/asset evidence images generated by `CropEvidenceService` (`services/agent/src/vss_agents/utils/crop_evidence.py`). Key pattern: `evidence/<videoId>/<uuid>/<itemId>.jpg` (item ids `E#`, `I#` and `A#` are unique across types; a new `<uuid>` per analysis run, so a key is never overwritten). The analyze route uploads the crops (`R2EvidenceStore`) and lists them in `report_revisions.evidence`; an item without an image carries an `image_gap` reason. `evidence_crops` rows exist only for official revisions: when a revision is made official the console calls `POST /api/v1/incidents/evidence-embeddings` for the 1024-dimension embeddings and writes the rows itself.

### Key Validation & Generation Rules

1. **Validity Rule (`isValidR2Key` in `incident-console-v2/lib/r2/key.ts`):**
   A valid R2 object key must:
   - Be a non-empty string.
   - Not start with `/` (absolute filesystem path).
   - Not start with `.` or contain `..` (relative filesystem path).
   - Guard against VST/NvStreamer `filePath` outputs (which return `./streamer/media/...` or local file paths).
2. **Upload & Evidence Key Patterns:**
   Direct uploads from `incident-console-v2/app/api/uploads/r2/route.ts` format keys as:
   `uploads/${encodeURIComponent(sensorId.trim())}/${randomUUID()}${ext}`.
   Thumbnail keys are deterministic: `thumbnailKeyForVideo(videoKey)` returns
   `thumbnails/${videoKey}.webp`; no database column is required.
   Evidence crop keys are deterministic: `evidence_key(videoId, modelRunId, collection, itemId)`
   (in `services/agent/src/vss_agents/utils/crop_evidence.py`) returns
   `evidence/${videoId}/${modelRunId}/${collection}/${itemId}.jpg` where collection is `entities`, `instruments`, or `assets`.
3. **Durability Verification:**
   `verifyR2Video` performs `HeadObject` after a direct upload (requiring the exact expected nonzero byte length)
   and again before analysis (requiring a nonempty object). A valid-looking key alone is not treated as a stored video.
4. **Presigned Media URLs:**
   Access is private by default. Video playback and up to six report-card thumbnail URLs are generated server-side using AWS SDK S3 client
   presigning (`getSignedUrl` with `GetObjectCommand`, `ResponseContentDisposition: 'inline'`, and a 1-hour
   expiration window). Agent-side evidence crops and video files are resolved via `services/agent/src/vss_agents/utils/r2.py` (`resolve_r2_url` / `get_r2_presigned_url`), generating boto3 S3 presigned URLs (1-hour expiration) or using public base URLs when configured (`INCIDENT_VIDEO_BASE_URL`).

---

For known schema issues, dual-writer architecture compromises, and technical debt, see [`status.md`](status.md).

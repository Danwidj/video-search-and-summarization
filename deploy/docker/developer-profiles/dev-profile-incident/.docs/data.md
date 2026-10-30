# Incident Search & Reporting Capstone — Data Layer & Schema

This document defines the relational database schema (Supabase PostgreSQL), the object storage layout
(Cloudflare R2), and documented data layer edge cases in the `dev-profile-incident` architecture.

> [!NOTE]
> **mvp3 schema.** On the `mvp3` branch several videos can belong to one incident, and an incident has one combined report. The schema below is the mvp3 end state, built on a **new empty database** (no back-fill; the migrations are never applied to the finals database). Console and agent code that still talks about "a video's report" is being moved over in Phases 4 and 5 of the mvp3 plan; where this file and that code disagree, this file and the migrations are the truth for the database.

---

## 1. Supabase PostgreSQL Schema

There is one Supabase project per project phase ([decision](decisions.md)): **finals** is the live database and **midterm** (`rfevukimyftzbxlehwel`) is a frozen, read-only record. mvp3 uses its own new project, kept apart from both. The schema is defined authoritatively by the baseline
[`supabase/migrations/20261020000000_finals_baseline.sql`](../supabase/migrations/20261020000000_finals_baseline.sql) and the later migrations in the same folder (applied via `supabase db push`; see [`../supabase/README.md`](../supabase/README.md)):

- `20261023000000_report_revisions_schema.sql` — drops the relational report tables and retires `videos.selected_*`; creates `report_revisions`, the revision-keyed `evidence_crops` and `query_results`.
- `20261023000100_report_revisions_functions.sql`, `20261023000200_searchable_latest_revision.sql`, `20261024090000_save_human_revision_with_crops.sql` — the revision functions of the per-video model. Every function they define is dropped or rewritten by the mvp3 migrations below.
- `20261023120000_report_revision_embeddings.sql` — adds `report_revisions.embedding` with its HNSW index (and a search function, rewritten below).
- `20261028090000_r2_rename.sql` — the one-off `apply_r2_rename` helper for the readable-names R2 migration. mvp3 drops it (`20261030100000`); mvp3 starts from real names, so there is nothing to rename.
- `20261028090100_search_evidence_items_video_id.sql` — adds `p_video_id` to `search_evidence_items` (it has its own version `20261028090100`, so it no longer shares one with the rename migration). `20261030140000` replaces the function again.

The mvp3 migrations, in order (each is a single transaction and ends with `NOTIFY pgrst, 'reload schema'`; each has a harness test in [`supabase/tests/`](../supabase/tests/)):

| Migration | Test | What it does |
|---|---|---|
| `20261030090000_incidents_core.sql` | `test_p1_1.py` | `incidents` root table; `videos.id` and `model_runs.id` become unbounded `TEXT` (with every column that refers to them); `videos.incident_id NOT NULL` and `videos.recorded_at`; the official pointer leaves `videos`; drops the per-video functions; recreates `search_report_revisions` on the `TEXT` ids |
| `20261030100000_revisions_per_incident.sql` | `test_p2_1.py` | `report_revisions` moves from video to incident (`incident_id`, `video_names`); per-incident revision numbers; the official revision must be one of the incident's own; drops `save_human_revision`, `apply_r2_rename` and the old `search_report_revisions` |
| `20261030110000_analyses_suggestions_crops.sql` | `test_p2_2.py` | `video_analyses`, `incident_match_suggestions`, and `evidence_crops.video_id` (in the primary key) |
| `20261030120000_crops_per_video.sql` | `test_crops_per_video.py` | `searchable_revision_id`, `evidence_image`, `replace_video_crops`, `set_revision_crops` per incident |
| `20261030130000_incident_summaries.sql` | `test_p3_1.py` | `list_incident_report_summaries`, `get_incident_dashboard` per incident |
| `20261030140000_incident_search.sql` | `test_incident_search.py` | `search_evidence_items`, `search_report_revisions` with incident-level hits |
| `20261030150000_human_revisions_official.sql` | `test_human_revisions_official.py` | `save_human_revision`, `save_human_revision_with_crops`, `set_official_revision` per incident |
| `20261030160000_merge_remove.sql` | `test_p3_5.py` | `merge_incidents`, `remove_video` |
| `20261030170000_ai_revision.sql` | `test_p3_6.py` | `create_ai_revision` |
| `20261030180000_matching.sql` | `test_matching.py` | `shortlist_similar_incidents`, `record_match_suggestion`, `reject_match_suggestion` |

Which of these are applied to which database is in [`status.md`](status.md#3-database-status). The midterm history is archived, never to be pushed, in [`supabase/midterm/`](../supabase/midterm/README.md). The SQL harness in `supabase/tests/` builds the schema on a throwaway local Postgres; `test_baseline.py` applies every migration in order and then runs every other `test_*.py` in that folder.

The mvp3 database holds nine tables: `incidents`, `videos`, `queries`, `model_runs`, `video_analyses`, `report_revisions`, `evidence_crops`, `incident_match_suggestions` and `query_results`. Every report is a `report_revisions` snapshot of an **incident**; there are no relational report tables (`reports`, `entities`, `instruments`, `assets`, `human_reports*`, `review_status`, `gt_*`, `severity_eval_log` are gone).

### The report model

- **An incident groups videos.** `incidents` is the root. A video belongs to exactly one incident (`videos.incident_id`, `ON DELETE CASCADE`); there is no link table. Incident ids are the identity number; video ids are the real (sanitised) file names; model-run ids are readable (`<subject>@<UTC timestamp>`, where the subject is a video name or `incident-<id>` for a synthesis run). Nothing is hashed.
- **Each video is analysed once, and the analysis is stored.** One run of the model over one video appends one `video_analyses` row (the contract-valid report for that camera, plus its evidence list and facets). The latest row per video wins. An analysis creates **no** revision.
- **A report is rebuilt from stored analyses.** `create_ai_revision` appends one `kind='ai'` revision to an incident. Its `payload` is the **envelope** below, built by the console from the agent's synthesis of the latest analyses; `video_names` records exactly which videos it covers. Merge, remove and regenerate rebuild the report this way, so the model never re-runs on every video.
- **A human edit appends a human revision.** `save_human_revision` writes `kind='human'`, `parent_id` = the revision the reviewer opened (which must be in the same incident), the full edited envelope as `payload`. It inherits the parent's `model_run_id` and **copies the parent's coverage** (`video_names`). Earlier revisions are never changed.
- **Regeneration is a new AI branch.** A new AI revision has `parent_id` NULL and copies no earlier edits.
- **One revision per incident is official.** `incidents.official_revision_id` (composite FK `(id, official_revision_id)` → `report_revisions(incident_id, id)`, so it can only name one of the incident's own revisions) names it; NULL means none. `official_since` is its mark time. Selection never rewrites a revision.
- **The searchable revision** of an incident is its official revision, otherwise its newest (`searchable_revision_id(incident_id)`). The library card, search and the crops all follow it.
- **Revisions are append-only.** A trigger rejects `UPDATE` and `DELETE`. The one exception is the `ON DELETE CASCADE` of the whole incident (trigger depth > 1): deleting an incident removes its revisions; deleting a video does **not**.
- **Coverage is immutable and the note is computed.** `video_names` never changes after insert. A reader compares it with the incident's current videos: current videos missing from `video_names` are "Does not include: <names>"; names no longer present are "Includes a removed video: <names>". The database computes this for the library (`missingVideos`, `removedVideos`); it stores no note.

#### Revision `payload` envelope

`report_revisions.payload` is an envelope, not a bare contract report. Each camera's `report` is the unchanged `incident-contract-v4` payload of that video's latest analysis ([analysis-schema.md](analysis-schema.md#4-storage)).

```json
{
  "overview": { "title": "...", "type": "...", "severity_level": 3, "description": "...", "location": "...", "confidence_score": 0.8 },
  "cameras": [ { "video": "front-door.mp4", "report": { "...": "incident-contract-v4 payload" } } ]
}
```

- `overview` uses the fields of the contract's `incident` block. Library cards, search and the dashboard read `overview.title`, `overview.description` and `overview.confidence_score`; the filter columns (`incident_type`, `severity_level`) are copied from it by the writer.
- Entities, instruments and assets are read from every camera's `report` (`cameras[].report.entities`, `.instruments`, `.assets`) for the library filters and the dashboard.
- `save_human_revision` requires `payload.overview` to be an object and `payload.cameras` to be an array; it does not validate the contract (the console does, per camera). `create_ai_revision` only requires a non-null payload.

---

### Detailed Table Specifications

#### `incidents`

The root of a group of videos and their combined report.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `BIGINT` | GENERATED ALWAYS AS IDENTITY; PRIMARY KEY | Incident id (used in URLs and by every incident-level function) |
| `official_revision_id` | `BIGINT` | NULLABLE; composite FK `(id, official_revision_id)` → `report_revisions(incident_id, id)` | The official revision. NULL = none chosen. Set/cleared only by `set_official_revision` |
| `official_since` | `TIMESTAMP` | NULLABLE | Naive UTC time the current official revision was marked. Kept when the same revision is marked again, cleared with the pointer |
| `created_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC creation time |

Deleting an incident deletes its videos, their analyses and crops, its revisions (and their crops) and its suggestions.

#### `videos`

Registry of ingested video assets. Each belongs to exactly one incident.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `TEXT` | PRIMARY KEY | The real file name after sanitising (`clip.mp4`; a taken name gets `clip-2.mp4`, see [R2](#key-validation--generation-rules)). Also the clip-name ids of fixture/eval rows (`Burglary012`, `SYN-...`). No hash. URL-encoded in routes |
| `incident_id` | `BIGINT` | NOT NULL; FK → `incidents.id` ON DELETE CASCADE | The incident the video belongs to. Merge and move change it |
| `filepath` | `VARCHAR(1024)` | NULLABLE | **Logical** R2 object key (`uploads/<name>`, `anomaly/<category>/<clip>.mp4` or `normal_videos/<clip>.mp4`), without any environment prefix. Validate with `isValidR2Key` before presigning. The console owns this column; the agent does not write `videos` |
| `recorded_at` | `TIMESTAMP WITH TIME ZONE` | NULLABLE | Recording time read from the file's metadata when present. Only a soft hint for matching, never required. The one timezone-aware timestamp in the schema |
| `uploaded_datetime` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC upload time |
| `duration` | `INTEGER` | NULLABLE | Duration in integer seconds |
| `source` | `VARCHAR(512)` | NULLABLE | Sensor ID, ingestion source, or camera stream name |

Deleting a video deletes its analyses and its crops. Revisions stay as history and keep the name in `video_names`.

#### `queries`

Tracks natural language queries submitted by users (search). Unchanged.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(20)` | PRIMARY KEY | Unique query identifier |
| `query_text` | `TEXT` | NOT NULL | Natural language query string |
| `submitted_datetime` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC timestamp when submitted |

#### `model_runs`

Tracks each execution of an AI pipeline run (over a video, or a synthesis over an incident).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `TEXT` | PRIMARY KEY | Readable run id `<subject>@<UTC timestamp>` of any length (e.g. `clip.mp4@2026-10-30T09:15:00.000Z`; subject is a video name, or `incident-<id>` for a synthesis run). Was `VARCHAR(20)` |
| `model_name` | `VARCHAR(128)` | NOT NULL | Model identifier (e.g. `nvidia/cosmos-3-nano-reasoner`, `incident_report_gen`, `vss-agent`) |
| `model_version` | `VARCHAR(128)` | NULLABLE | Optional version tag of the model |
| `prompt_version` | `VARCHAR(64)` | NULLABLE | Prompt template version tag |
| `run_datetime` | `TIMESTAMP` | DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC execution timestamp |
| `notes` | `TEXT` | NULLABLE | Free text. The console writes the **immutable analysis-attempt record** `{"incidentConsoleV2":{recordType:"analysis_attempt", status, stage, failure, contractVersion, videoId, r2Key, attemptedAt, request, response, validation, repair, report?}}` for every attempt (see [`analysis-schema.md` §4](analysis-schema.md#4-storage)); it is never modified afterwards. Failed attempts (`contract_failed` / `request_failed`) are `model_runs` rows with no analysis. `mock-backend` stores a plain-text note; agent/seed runs leave it NULL. Count runs by outcome (`run_outcome(notes)`) or via analyses and AI revisions |

`notes` is immutable. A run cannot be deleted while a revision or an analysis references it (no cascade).

#### `video_analyses`

One row per analysis run of one video. The latest row per video wins (`ORDER BY created_at DESC, id DESC LIMIT 1`). Never updated.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `BIGINT` | GENERATED ALWAYS AS IDENTITY; PRIMARY KEY | Analysis identifier |
| `video_id` | `TEXT` | NOT NULL; FK → `videos.id` ON DELETE CASCADE | The analysed video |
| `model_run_id` | `TEXT` | NOT NULL; FK → `model_runs.id` (no cascade) | The run that produced it; the run row must exist first |
| `payload` | `JSONB` | NOT NULL | The contract-valid report for this video (`incident`, `entities`, `instruments`, `assets`, `timeline`, `uncertainties`), unchanged |
| `evidence` | `JSONB` | NOT NULL, DEFAULT `'[]'` | The evidence items and R2 crop keys of this analysis |
| `incident_type` | `VARCHAR(64)` | NULLABLE | Facet copied by the writer from `payload.incident.type` |
| `severity_level` | `INTEGER` | NULLABLE | Facet from `payload.incident.severity_level` |
| `start_seconds` | `INTEGER` | NULLABLE | Facet from `payload.incident.start_timestamp` |
| `end_seconds` | `INTEGER` | NULLABLE | Facet from `payload.incident.end_timestamp` |
| `embedding` | `extensions.vector(1024)` | NULLABLE | Summary vector of the analysis. `shortlist_similar_incidents` compares these. NULL when the embedding endpoint was unavailable |
| `created_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC creation time |

Indexes: `(video_id, created_at DESC, id DESC)` and `(model_run_id)`. There is no vector index on `video_analyses.embedding` (the shortlist scans each video's latest row).

#### `report_revisions`

Append-only report snapshots of an incident. The source of truth for every AI and human report.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `BIGINT` | GENERATED ALWAYS AS IDENTITY; PRIMARY KEY | Revision identifier. Search results and `query_results` store this |
| `incident_id` | `BIGINT` | NOT NULL; FK → `incidents.id` ON DELETE CASCADE | The incident the report belongs to (was `video_id`) |
| `revision_no` | `INTEGER` | NOT NULL; UNIQUE `(incident_id, revision_no)` | 1-based sequence per incident. `save_human_revision` and `create_ai_revision` lock the incident row and assign `max + 1` |
| `kind` | `VARCHAR(8)` | NOT NULL; CHECK `IN ('ai','human')` | `ai` for a model output, `human` for a reviewer snapshot |
| `model_run_id` | `TEXT` | NULLABLE; FK → `model_runs.id`; CHECK required when `kind='ai'` | The run the revision derives from. A human revision inherits its parent's run |
| `parent_id` | `BIGINT` | NULLABLE; composite FK `(incident_id, parent_id)` → `report_revisions(incident_id, id)` | The revision this one was edited from, in the same incident. NULL for an AI branch root |
| `payload` | `JSONB` | NOT NULL | The envelope `{overview, cameras}` ([above](#revision-payload-envelope)) |
| `evidence` | `JSONB` | NOT NULL, DEFAULT `'[]'` | The evidence items and R2 image keys this revision uses |
| `video_names` | `TEXT[]` | NOT NULL, DEFAULT `'{}'` | **Coverage:** the real names of the videos this revision covers. Immutable. `create_ai_revision` stores the named videos (at least one, each a current video of the incident); a human revision copies its parent's |
| `incident_type` | `VARCHAR(64)` | NULLABLE | Facet written by the caller, from `payload.overview.type` |
| `severity_level` | `INTEGER` | NULLABLE | Facet written by the caller, from `payload.overview.severity_level` |
| `start_seconds` | `INTEGER` | NULLABLE | Single-camera only. `create_ai_revision` stores it only when exactly one video is covered; a human save writes what the caller passes |
| `end_seconds` | `INTEGER` | NULLABLE | As `start_seconds` |
| `created_by` | `VARCHAR(256)` | NULLABLE; CHECK required when `kind='human'` | Reviewer name for a human revision; NULL for AI |
| `created_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC creation time |
| `note` | `TEXT` | NULLABLE | Free-text note (empty/blank stored as NULL) |
| `embedding` | `extensions.vector(1024)` | NULLABLE | Summary vector of the overview, passed to `create_ai_revision`. NULL for human revisions and when the embedding endpoint was unavailable. Never updated |

Constraints and indexes:

- `report_revisions_pkey` on `id`; `report_revisions_incident_rev_key` unique on `(incident_id, revision_no)`; `report_revisions_incident_id_id_key` unique on `(incident_id, id)` (target of the official pointer and the parent link).
- `report_revisions_incident_id_fkey` (CASCADE), `report_revisions_model_run_id_fkey` (no cascade: a revision needs its run row first), `report_revisions_parent_fkey`.
- `report_revisions_kind_check`, `report_revisions_ai_run_check`, `report_revisions_human_by_check`.
- Indexes: `(incident_id, revision_no DESC)`, `incident_type`, `severity_level`, and `report_revisions_embedding_hnsw_idx` (HNSW cosine on `embedding`, `m = 16, ef_construction = 64`).
- Trigger `report_revisions_no_update_delete` (BEFORE UPDATE OR DELETE, `report_revisions_append_only()`): raises `report_revisions is append-only`. It permits a delete made by the incident's `ON DELETE CASCADE` (trigger depth > 1). The old `apply_r2_rename` exception no longer exists, so no `UPDATE` is possible at all.

#### `evidence_crops`

Searchable evidence of each incident's **searchable revision** (official, else newest), one row per crop, tagged with its **source video**. There is no `incident_id`/`model_run_id` here: both come through `report_revisions`.

What moves the rows (the database cannot embed, so a writer always supplies the embeddings):

| Event | Rows |
|---|---|
| `set_revision_crops(incident, rev, crops)` (`rev` must be the searchable revision) | Every crop of every video of the incident is deleted, then `crops` is stored against `rev`; each crop names its `video_id`. An empty list clears them |
| `replace_video_crops(incident, video, rev, crops)` | Only that video's crops are deleted (on any revision), then `crops` is stored against `rev`. A NULL `rev` only deletes. The incident's other videos are untouched |
| `create_ai_revision` | For each covered video, the rows of the newest revision that holds crops for that video are **copied** onto the new revision. Older rows stay, so older revisions keep their evidence |
| `save_human_revision_with_crops(..., crops)` | The crops are stored for the new revision only. Nothing is deleted, and the crop rows of older revisions stay |
| `set_official_revision` | No crop is touched. It changes which revision is searchable; the writer calls `set_revision_crops` to refresh the rows if the new official revision has none |
| A video is deleted or moved | Delete: its crops go (cascade). Move: they follow the video to the new incident, still attached to their old revision's id |

Search only returns rows of the searchable revision, so rows of other revisions are invisible but kept.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `revision_id` | `BIGINT` | PRIMARY KEY (part); FK → `report_revisions.id` ON DELETE CASCADE | The revision the crop is stored against |
| `video_id` | `TEXT` | PRIMARY KEY (part); NOT NULL; FK → `videos.id` ON DELETE CASCADE | The **source video** of the crop |
| `item_type` | `VARCHAR(16)` | PRIMARY KEY (part); CHECK `IN ('entity','instrument','asset')` | Evidence category |
| `item_id` | `VARCHAR(20)` | PRIMARY KEY (part) | Item identifier in the camera report (`E1..`, `I1..`, `A1..`); unique only within one video, which is why `video_id` is in the key |
| `item_name` | `VARCHAR(256)` | NOT NULL | Item name or detector label |
| `description` | `TEXT` | NOT NULL | Item visual description |
| `threat_level` | `INTEGER` | NULLABLE | Threat rating (1-5; instruments only) |
| `holder_entity_id` | `VARCHAR(20)` | NULLABLE | Identifier of the holding entity (instruments only) |
| `timestamp_seconds` | `INTEGER` | NOT NULL | Whole-second offset from the source video's start. An entity's first/last seen span is stored only in the payload and evidence, not here |
| `bounding_box` | `INTEGER[4]` | NOT NULL | Normalised `[ymin, xmin, ymax, xmax]` (0-1000) |
| `image` | `VARCHAR(1024)` | NOT NULL | Logical R2 object key (`evidence/<video key>/run-<N>/<itemId>.jpg` or `.../edit-<N>/<itemId>.jpg`, where `<video key>` is `videos.filepath`), without an environment prefix |
| `embedding` | `extensions.vector(1024)` | NULLABLE | 1024-dimensional embedding for cosine retrieval |
| `created_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC insertion time |

Primary key `(revision_id, video_id, item_type, item_id)`; index on `video_id`. Index `evidence_crops_embedding_hnsw_idx` is an HNSW cosine index on `embedding` (`m = 16, ef_construction = 64`). RLS is on; only `service_role` can read or write.

#### `incident_match_suggestions`

Suggested joins between two incidents. The system only suggests; the reviewer decides.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `BIGINT` | GENERATED ALWAYS AS IDENTITY; PRIMARY KEY | Suggestion identifier |
| `incident_a_id` | `BIGINT` | NOT NULL; FK → `incidents.id` ON DELETE CASCADE | One incident of the pair |
| `incident_b_id` | `BIGINT` | NOT NULL; FK → `incidents.id` ON DELETE CASCADE; CHECK `incident_a_id <> incident_b_id` | The other incident |
| `score` | `DOUBLE PRECISION` | NOT NULL; CHECK `0 <= score <= 1` | Match score from the judge |
| `reasons` | `JSONB` | NOT NULL, DEFAULT `'[]'` | Plain-language reasons |
| `status` | `VARCHAR(16)` | NOT NULL, DEFAULT `'pending'`; CHECK `IN ('pending','accepted','rejected')` | Decision state |
| `created_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Naive UTC creation time |
| `decided_at` | `TIMESTAMP` | NULLABLE | Naive UTC time of the decision |

One row per **unordered** pair: the unique index `incident_match_suggestions_pair_key` is on `(LEAST(a, b), GREATEST(a, b))`, so `(a, b)` and `(b, a)` are the same pair. A rejected row stays, so the pair is never suggested again. Other indexes: `incident_b_id` and `status`.

#### `query_results`

Audit log and hit persistence for natural-language search and critic evaluation. Unchanged by mvp3.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | Unique result identifier (UUID or hex) |
| `query_id` | `VARCHAR(20)` | NOT NULL; FK → `queries.id` ON DELETE CASCADE | Associated search query |
| `revision_id` | `BIGINT` | NOT NULL; FK → `report_revisions.id` ON DELETE CASCADE | The searchable revision the hit came from |
| `item_type` | `VARCHAR(16)` | NOT NULL; CHECK `IN ('entity','instrument','asset')` | Evidence item type |
| `item_id` | `VARCHAR(20)` | NOT NULL | Evidence item identifier |
| `rank` | `INTEGER` | NOT NULL | Retrieval rank position (1-based) |
| `similarity_score` | `DOUBLE PRECISION` | NOT NULL | Cosine similarity (`1.0 - distance`) |
| `critic_verdict` | `VARCHAR(16)` | NOT NULL; CHECK `IN ('confirmed','rejected','unverified')` | VLM critic verdict |
| `critic_rationale` | `TEXT` | NULLABLE | Critic rationale |
| `retrieved_at` | `TIMESTAMP` | NOT NULL, DEFAULT (now() AT TIME ZONE 'utc') | Retrieval time (naive UTC) |

There is **no foreign key to `evidence_crops`**: changing the official revision keeps the search audit trail. Indexes: `(revision_id, item_type, item_id)` and `(query_id, rank)`. RLS is on; only `service_role` can read or write.

### Relationships and cascades

- `videos.incident_id` → `incidents.id` (CASCADE). `report_revisions.incident_id` → `incidents.id` (CASCADE).
- `incidents.(id, official_revision_id)` → `report_revisions.(incident_id, id)`: the official revision must belong to the same incident.
- `report_revisions.(incident_id, parent_id)` → `report_revisions.(incident_id, id)` (no cascade): an edit and its parent are in one incident.
- `report_revisions.model_run_id` and `video_analyses.model_run_id` → `model_runs.id` (no cascade). The run row must exist first.
- `video_analyses.video_id` and `evidence_crops.video_id` → `videos.id` (CASCADE).
- `evidence_crops.revision_id` → `report_revisions.id` (CASCADE).
- `incident_match_suggestions.incident_a_id` / `incident_b_id` → `incidents.id` (CASCADE).
- `query_results.query_id` → `queries.id` and `query_results.revision_id` → `report_revisions.id` (both CASCADE).

| Delete | What goes with it |
|---|---|
| An incident | Its videos, their analyses and crops, its revisions (and the crops and `query_results` that name them), and every suggestion that names it |
| A video | Its analyses and crops. Its revisions stay and keep the name in `video_names`; `query_results` stay |
| A revision, directly | Refused by the append-only trigger |
| A `model_runs` row | Refused while a revision or an analysis references it |

`model_runs` and `queries` rows are never deleted by a cascade.

---

### Functions

All functions are `SECURITY INVOKER` (`STABLE` where they only read), pin `SET search_path = ''`, and are executable by `service_role` only; `supabase/tests/security_check.sql` must return 0 rows. Helpers from the baseline still exist: `canonical_incident_type`, `canonical_entity_type` (`person` → `human`), `normalized_name`, `run_outcome(notes)`, `timestamp_seconds(text)` and `try_parse_jsonb(text)`.

mvp3 dropped these per-video functions and recreated them on incidents: `list_incident_report_summaries`, `get_incident_dashboard`, `search_evidence_items`, `search_report_revisions`, `searchable_revision_id`, `replace_video_crops`, `set_revision_crops`, `evidence_image`, `save_human_revision`, `save_human_revision_with_crops` and `set_official_revision`. `apply_r2_rename` was dropped for good. New: `create_ai_revision`, `merge_incidents`, `remove_video`, `shortlist_similar_incidents`, `record_match_suggestion`, `reject_match_suggestion`.

Two error conventions: most functions raise `P0001` for a refused call (`Incident not found`, `Revision not found for this incident`, ...). `merge_incidents`, `remove_video` and the matching functions use `22023` (bad argument), `P0002` (missing row) and `23514` (the move-the-last-video refusal).

#### `save_human_revision`

```
save_human_revision(
  p_incident_id BIGINT, p_parent_id BIGINT, p_created_by TEXT, p_note TEXT,
  p_payload JSONB, p_evidence JSONB,
  p_incident_type TEXT, p_severity_level INTEGER, p_start_seconds INTEGER, p_end_seconds INTEGER
) RETURNS JSONB
```

Appends a `kind='human'` revision with `revision_no = max + 1` for the incident, while holding the incident row lock. `p_parent_id` is required and must be a revision **of this incident** (a parent from another incident is refused). The new revision inherits the parent's `model_run_id` and `video_names`. `p_payload` must be an object with an `overview` object and a `cameras` array; `p_evidence` must be an array; `p_created_by` must be 1-256 characters after trimming. The four facet arguments are written as given. Returns `{revisionId, revisionNo, incidentId, kind, parentId, modelRunId, videoNames, createdBy, createdAt, note}`.

#### `save_human_revision_with_crops`

```
save_human_revision_with_crops(<the ten save_human_revision arguments>, p_crops JSONB DEFAULT '[]') RETURNS JSONB
```

The console's Save. In one transaction it calls `save_human_revision`, then stores `p_crops` for the new revision. Each crop object is `{video_id, item_type, item_id, image, bounding_box, timestamp_seconds, item_name, description, threat_level, holder_entity_id, embedding}`. Entries without an `item_type` of `entity`/`instrument`/`asset`, an `item_id` or an `image` are skipped; a missing `bounding_box` becomes `[0,0,1000,1000]`; a missing `timestamp_seconds` becomes 0; `embedding` is a 1024-number array or null. A crop whose `video_id` is not a current video of the incident **and** in the new revision's `video_names` refuses the whole save. `p_crops` must be a list. Returns the `save_human_revision` result plus `crops`, the number of rows stored. It deletes no crop; to make the new revision the one the incident searches, the writer uses `set_revision_crops`. The console embeds the crops before the call, so a failed embedding writes nothing.

#### `set_official_revision`

```
set_official_revision(p_incident_id BIGINT, p_revision_id BIGINT) RETURNS JSONB
```

Sets `incidents.official_revision_id` and `official_since` under the incident row lock; NULL clears both. Only a revision of this incident is accepted. Marking the already-official revision again keeps the original `official_since`. It moves no crops. Returns `{incidentId, officialRevisionId, officialSince}`.

#### `create_ai_revision`

```
create_ai_revision(
  p_incident_id BIGINT, p_model_run_id TEXT, p_note TEXT, p_payload JSONB, p_evidence JSONB,
  p_video_names TEXT[], p_incident_type TEXT, p_severity_level INTEGER,
  p_start_seconds INTEGER DEFAULT NULL, p_end_seconds INTEGER DEFAULT NULL,
  p_embedding extensions.vector(1024) DEFAULT NULL
) RETURNS JSONB
```

Appends one `kind='ai'` revision (`parent_id` NULL) in one transaction: locks the incident, refuses an unknown incident, an empty name list, and any name that is not currently a video of this incident, stores the de-duplicated, sorted names as `video_names`, numbers the revision `max + 1`, and copies the covered videos' latest crops onto it (see `evidence_crops`). `start_seconds`/`end_seconds` are stored only when exactly one video is covered. The model run row must exist. It does not touch the official pointer. Returns `{revisionId, revisionNo, crops}`.

#### `set_revision_crops` and `replace_video_crops`

```
set_revision_crops(p_incident_id BIGINT, p_revision_id BIGINT, p_crops JSONB DEFAULT '[]') RETURNS JSONB
replace_video_crops(p_incident_id BIGINT, p_video_id TEXT, p_revision_id BIGINT, p_crops JSONB DEFAULT '[]') RETURNS INTEGER
```

`set_revision_crops` stores the crops of the incident's searchable revision without touching the official pointer. `p_revision_id` must equal `searchable_revision_id(p_incident_id)`, otherwise the call is refused, so a writer holding a stale revision id cannot overwrite the rows of a newer one. Every crop must name a `video_id` that is a video of the incident. All the incident's existing crops are replaced (a video missing from the list ends with none); an empty list clears them. Returns `{incidentId, revisionId, crops}`. `replace_video_crops` changes one video only and returns the row count (it checks the video and revision belong to the incident). Crop format as in `save_human_revision_with_crops`.

`searchable_revision_id(incident_id)` (official, else newest, else NULL) and `evidence_image(item)` are helpers; the console and agent have no reason to call them.

#### `merge_incidents`

```
merge_incidents(p_target_incident_id BIGINT, p_source_incident_id BIGINT) RETURNS JSONB
```

Moves the source's videos (their analyses follow by video id) into the target, marks a **pending** suggestion for the pair `accepted`, then deletes the source incident with its revisions, crops and suggestions (the accepted row goes with the source). The source's old id, human edits and official choice are not carried over; the target's revisions are not changed, so its coverage note will say "Does not include" the moved videos until the report is regenerated. Refused for the same incident twice (`22023`) or an unknown incident (`P0002`). It moves no files. Returns `{incident_id (the target), source_incident_id, moved_video_ids, orphaned_crop_images}`; `orphaned_crop_images` are the R2 keys of the crops that went with the source's revisions, for the console's sweep.

#### `remove_video`

```
remove_video(p_video_id TEXT, p_mode TEXT) RETURNS JSONB   -- p_mode: 'delete' | 'move'
```

- `'delete'`: deletes the video with its analyses and crops. The incident's revisions stay as history. If it was the incident's **last** video, the incident is deleted too, with its revisions, crops and suggestions.
- `'move'`: moves the video, its analyses and crops into a **new** incident and records the pair (old, new) as a `rejected` suggestion (score 0) so it is never suggested back. The old incident's revisions are untouched. Refused for the last video (`23514`: delete it instead).

It locks the incident, so concurrent removals run one after another. Returns `{mode, video_id, incident_id (where it was), new_incident_id (move, else null), incident_deleted, deleted_video_key (the video's logical R2 key; delete only, else null), deleted_crop_images}` so the console can clean up files. A move or merge leaves the report of the new incident to be built by `create_ai_revision`.

#### `shortlist_similar_incidents`, `record_match_suggestion`, `reject_match_suggestion`

```
shortlist_similar_incidents(p_video_id TEXT, p_limit INTEGER DEFAULT 5, p_min_similarity DOUBLE PRECISION DEFAULT 0.0)
  RETURNS TABLE (incident_id BIGINT, similarity DOUBLE PRECISION, best_video_id TEXT)
record_match_suggestion(p_incident_a_id BIGINT, p_incident_b_id BIGINT, p_score DOUBLE PRECISION, p_reasons JSONB DEFAULT '[]') RETURNS JSONB
reject_match_suggestion(p_suggestion_id BIGINT) RETURNS JSONB
```

`shortlist_similar_incidents` compares the video's **latest analysis embedding** with the latest analysis embedding of every video in other incidents (cosine similarity, `1 - distance`); an incident scores its best video. It never returns the video's own incident and never an incident whose pair has an `accepted` or `rejected` row (a `pending` pair is still returned). A video with no analysis or no embedding has an empty shortlist. The judge (agent) then scores the shortlist; this function only picks candidates.

`record_match_suggestion` inserts a pending row unless the unordered pair already has any row (an existing row of any status is kept as it is). Refuses a missing id, the same incident twice, and a score outside 0 to 1 (`22023`). Returns `{suggestionId, status, created}`.

`reject_match_suggestion` turns pending into rejected with `decided_at` set. Rejecting a rejected row changes nothing; an accepted one is refused (`22023`). Returns `{suggestionId, status}`.

#### `search_evidence_items`

```
search_evidence_items(
  p_query_embedding extensions.vector(1024), p_top_k INTEGER DEFAULT 10,
  p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
  p_item_types TEXT[] DEFAULT ARRAY['entity','instrument','asset'],
  p_incident_types TEXT[] DEFAULT NULL, p_min_severity INTEGER DEFAULT NULL,
  p_max_severity INTEGER DEFAULT NULL, p_video_id TEXT DEFAULT NULL, p_incident_id BIGINT DEFAULT NULL
)
```

pgvector cosine search over `evidence_crops.embedding`, scoped to each incident's searchable revision (official, else newest; computed inline). `p_video_id` limits the scan to one source video and `p_incident_id` to one incident, both before ranking, so the top `p_top_k` all belong to the scope. `p_query_embedding` may be NULL only with a scope: the scoped crops are then listed in video time order with `similarity_score` 0. Type and severity filters apply to the searchable revision's `incident_type` and `severity_level`. The migration drops the previous 8-argument overload first, because two overloads would make PostgREST calls ambiguous. Each hit returns `incident_id`, `revision_id`, `model_run_id`, the **source** `video_id` and `video_filepath`, `incident_title` and `incident_description` (from `payload.overview`), `incident_type`, `severity_level`, `incident_start_timestamp`/`incident_end_timestamp` (the revision's seconds as text, NULL for a multi-camera revision), the crop fields, and `similarity_score` (`1.0 - distance`). Rows whose embedding is NULL are skipped when a query embedding is given.

#### `search_report_revisions`

```
search_report_revisions(p_query_embedding extensions.vector(1024), p_top_k INTEGER DEFAULT 10, p_min_similarity DOUBLE PRECISION DEFAULT 0.0)
```

Cosine search over `report_revisions.embedding`, now **one hit per incident**: only the incident's searchable revision (official, else newest) can match, and only if it has a vector (human revisions have none, so an incident whose newest revision is a human edit with no official revision does not appear). Returns `incident_id`, `revision_id`, `revision_no`, `kind`, `model_run_id`, `video_names`, `title` and `description` (from `payload.overview`), the facets, and `similarity_score`. The agent calls it through `IncidentDB.search_revisions` for `POST /api/v1/incidents/revisions/search`. It is separate from `search_evidence_items`, which searches crops.

#### `list_incident_report_summaries`

Paginated report library, **one card per incident**: the official revision if there is one, otherwise the newest revision. An incident with no revision yet still gets a card (`revisionId` null, title from the type or "Incident report"). Facets come from the revision columns; title, description and confidence from `payload.overview`; entities, instruments and assets from every camera's `report`. Filters (all arguments unchanged from the per-video version): `p_search` (also matches the incident's video names), `p_type`, `p_severity` (`low`/`medium`/`high` or a number), `p_kind` (`ai`/`human`), date range, local time-of-day and weekday (`p_timezone`, default UTC), entity/instrument/asset text or exact-name match, `p_entity_types`, `p_sort`, and `p_scope` (`all` or `official`). Returns `{reports: [...], totalItems, incidentTypes}`. Each card carries `incidentId`, `revisionId`, `revisionNo`, `modelRunId`, `kind`, `createdBy`, `note`, `isOfficial`, `outcome`, the display fields, `officialSince`, `versionCount` (revisions of the incident), and the video fields:

- `videoCount`, `firstVideoName`, `firstVideoKey` and `thumbnail` (`thumbnails/<firstVideoKey>.webp`, null without a key) for the earliest-uploaded video (ties by name), and `sensorId` (that video's `source`);
- `coverage` (the card revision's `video_names`), `missingVideos` (current videos not in coverage) and `removedVideos` (covered names no longer present), which feed the coverage note.

It never returns `payload`, signed URLs or video content. There is no `evidenceCount` any more (it was derived from the revision's evidence list; the card now shows a video count).

#### `get_incident_dashboard`

Aggregates **official revisions only** (one per incident), filtered by the revision's `created_at` plus optional type, severity band, weekday and hour (in `p_timezone`, default UTC). Returns `total`, `incidents` (all-time counts: `total`, `withOfficial`, `awaitingSelection`, `withoutReport`), `videos` (`{uploaded}`, all-time), `previous`, severity, `revisions` (`ai`/`human`), types with per-type evidence, daily trend, heatmap, `entityTypes`, `topInstruments`, `topAssets`, `threatLevels`, a confidence histogram with `confidenceNotProvided`, and `modelCoverage` (attempts by outcome: failed attempts from `model_runs`, successful ones from AI revisions). Entities, instruments and assets are read from every camera's report.

---

### Agent writes

PostgREST has no client-held transactions, so the agent writes only single rows. `IncidentDB` (`services/agent/src/vss_agents/utils/incident_db.py`) reads `incidents`, `videos` and `report_revisions`, writes `model_runs` (`insert_model_run`, and `insert_model_run_if_absent`, the placeholder with `ignore_duplicates` and NULL `notes` so the console's later upsert fills `notes` in), and appends `video_analyses` (`insert_video_analysis`: facets copied from the payload, a summary-vector `embedding`, never updated; a re-analysis is a new row). It **no longer writes `report_revisions` or `videos`**: the console assembles the incident's revision (agent synthesis, then `create_ai_revision`), because only one place can know the coverage. Run ids come from `model_run_id(subject)`.

> **Insertion order:** the `model_runs` row first (the console upserts it with its `notes` record after the agent returns, so the agent inserts a placeholder), then the `video_analyses` row, then a revision (`create_ai_revision`). Search persists `query_results` against `revision_id`.

> **Cascades:** see the delete table above. Direct deletes/updates of `report_revisions` are rejected by the trigger; only the incident cascade can remove them.

---


### Client Access Models & PostgREST/Direct-Postgres Split

Database access is split across two client implementations according to operational requirements:

1. **Console and laptop tooling:**
   `incident-console-v2` uses Supabase PostgREST (`src/lib/postgrest/client.ts`, reached only from the adapters). Laptop tooling (the `supabase` CLI, the copy and parity scripts) uses direct Postgres (`INCIDENT_DB_DSN`). The console is database-backed only; there is no offline mode.

2. **Agent Side & Service Writers (Supabase PostgREST):**
   `services/agent/src/vss_agents/utils/incident_db.py` is the agent-side counterpart: an async
   Supabase PostgREST CRUD helper (`supabase-py`'s `AsyncClient`/`acreate_client`, not
   `asyncpg`/direct-Postgres) against the same schema. It reads `incidents`, `videos` and
   `report_revisions` (the console owns those rows), writes `model_runs` and `video_analyses`; the
   search store reads `evidence_crops` and writes `queries` and `query_results`
   ([agent writes](#agent-writes)).
   - **Configuration:** `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`
     (deliberately NOT `INCIDENT_DB_DSN`, which the direct-Postgres tooling uses); unset means the
     feature is unavailable, no fallback.
   - **Network Constraint / DPI Blocking Rationale:** This split exists because the deployment VM
     (`kwanz-ws`) DPI-blocks raw Postgres wire protocol on port 5432, so only the HTTPS-based
     PostgREST route works for the agent from there.
   - **Transaction Limits & RPC:** PostgREST has no client-held transactions or
     `SELECT ... FOR UPDATE`; the multi-row writes are server-side functions that lock the incident row
     and number revisions as `max + 1` (`create_ai_revision`, `save_human_revision`), or change several
     tables at once (`set_official_revision`, `merge_incidents`, `remove_video`). The agent no longer
     appends `report_revisions` rows.

### Row-Level Security (RLS) & Access Control

**Finals is locked down from its first migration.** The baseline turns off Supabase's default grants before it creates any object, so nothing is ever exposed, even for a moment:

- **Default-deny:** RLS is on for all nine tables, with no policies, so `anon` and `authenticated` cannot read, insert, update or delete rows anywhere.
- **No grants to the public roles:** every privilege on every table, view, sequence and function in `public` is revoked from `PUBLIC`, `anon` and `authenticated`. Every function is `service_role`-only, `SECURITY INVOKER`, with `SET search_path = ''`.
- **Default privileges:** objects that `postgres` creates in `public` later get nothing for `anon`/`authenticated` and everything for `service_role`; new functions get no `EXECUTE` for `PUBLIC` in any schema. Objects created by other roles are not covered, so a new function should still be checked by `supabase/tests/security_check.sql`.
- **pgvector lives in `extensions`**, so none of its functions are REST RPCs.
- **Self-check:** the baseline fails (and rolls back) if any table has RLS off, anything is reachable by `anon`/`authenticated`, or any function is `SECURITY DEFINER` or lacks a fixed `search_path`. Run `supabase/tests/security_check.sql` after every applied migration (expect 0 rows), and `supabase/tests/probe_api.sh` to confirm over REST that the public key is refused.
- **Role bypass:** Application services (`incident-console-v2`, `vss-agent`, `mock-backend`) authenticate via HTTPS PostgREST using `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (`service_role`), or connect directly via the Postgres wire protocol using `INCIDENT_DB_DSN` (`postgres`). Both roles hold `BYPASSRLS`. On Supabase `postgres` is not a superuser; it skips RLS through `BYPASSRLS`, not superuser status. `FORCE ROW LEVEL SECURITY` is not applied: it only subjects table owners (here `postgres`) to RLS, and `BYPASSRLS` overrides it.
- **Signups:** create the finals project with email signups turned off; nobody uses Supabase Auth, and an open signup would let anyone with the public key mint an `authenticated` user (who could still reach nothing).

**Midterm** had RLS on only `evidence_crops` and `query_results` and gave `anon`/`authenticated` full access to the other tables. `supabase/midterm/freeze_midterm.sql` closes that at the cutover and makes midterm read-only ([`../supabase/midterm/README.md`](../supabase/midterm/README.md)).

---

## 2. Cloudflare R2 Storage Architecture

Cloudflare R2 provides S3-compatible, permanent object storage for all video media and evidence images.
Local disks on `kwanz-ws` are treated as temporary caches only (though VST stores ingested video files locally).

### Bucket Key Tree Layout

```
anomaly-detection-dataset/            # bucket name comes from R2_BUCKET
├── anomaly/                         # classified dataset clips (seed/eval) only
│   ├── animal_attacks/  assault/  burglary/  explosion/
│   ├── fighting/  road_accidents/  shooting/  demo/
│   │   └── <clip-name>.mp4
├── normal_videos/                   # baseline non-incident clips
│   └── <clip-name>.mp4
├── uploads/                         # all new user uploads (real VST fallback and local mock)
│   └── <original file name>         # flat; a taken name gets -2, -3 before the extension
├── thumbnails/                      # browser-captured report-card screenshots for new uploads
│   └── <video-key>.webp             # e.g. thumbnails/uploads/Animal001_x264.mp4.webp
├── Report/                          # empty folder marker, unused by code
└── evidence/                        # evidence images: agent crops and reviewer replacements
    └── <video-key>/run-<N>/<itemId>.jpg    # AI crops, one run-<N> per analysis
        <video-key>/edit-<N>/<itemId>.jpg   # reviewer replacements, one edit-<N> per upload
```

> [!NOTE]
> The `anomaly/` subfolders are reserved for classified seed/evaluation data. New user uploads are classification-neutral and use `uploads/<original file name>` in both local-mock and real-VST flows; the VLM's later incident classification does not move or rename the object.
> In addition to the five fixture categories, live R2 storage includes `assault/` and `shooting/`.
> The `Report/` prefix is a 0-byte directory marker and is unused by code.
> The `evidence/` tree holds two writers' images, both under `evidence/<video key>/` where `<video key>` is `videos.filepath` (item ids `E#`, `I#` and `A#` are unique across types). No key holds a hash or UUID, and no key is ever overwritten: each write takes the next free number, and the put is conditional (`If-None-Match: *`):
> - the analyze route's crops (`CropEvidenceService`, `services/agent/src/vss_agents/utils/crop_evidence.py`, uploaded by `R2EvidenceStore`, `run-<N>` with N one above the highest existing run of that video), listed in `report_revisions.evidence`; an item without an image carries an `image_gap` reason;
> - reviewer replacements, uploaded by the console's `POST /api/reports/<videoId>/evidence-image` during Save, as `edit-<N>` with the smallest free N.
> - Two analyses of one video that start at the same moment can pick the same `run-<N>`; the conditional put stops the overwrite, so one of them fails instead of replacing the other.
>
> Which revision's images are searchable is decided by the `evidence_crops` table above. No writer deletes an image. `POST /api/reports/<videoId>/evidence-sweep` removes only images no revision or `evidence_crops` row of the video names and that are older than `minAgeHours` (default 24, at least 1; dry run by default). Deleting a video removes every object under `evidence/<video key>/` before the video row; if a listing or removal fails the row stays, so the delete can be repeated. Videos deleted before 2026-10-25 left their images behind ([status](status.md#7-archive)), and the sweep refuses an unknown video. In mvp3 the `<videoId>` in these routes is the video's real name and `evidence_crops` rows carry their source `video_id`; `merge_incidents` and `remove_video` return the R2 keys that went with the rows (`orphaned_crop_images`, `deleted_crop_images`, `deleted_video_key`) for the console to remove.

### Key Validation & Generation Rules

1. **Validity Rule (`isValidR2Key` in `incident-console-v2/src/lib/r2/key.ts`):**
   A valid R2 object key must:
   - Be a non-empty string.
   - Not start with `/` (absolute filesystem path).
   - Not start with `.` or contain `..` (relative filesystem path).
   - Guard against VST/NvStreamer `filePath` outputs (which return `./streamer/media/...` or local file paths).
2. **Upload & Evidence Key Patterns:**
   Direct uploads from `incident-console-v2/src/app/api/uploads/r2/route.ts` format keys as `uploads/<name>`
   (`src/lib/r2/names.ts`): the original file name is kept; a character outside letters, digits and
   `. _ - ( ) + ,` (a space included) becomes `_`; a name over 150 characters is cut (extension kept); a name that is
   already stored gets `-2`, `-3` before the extension, found with `HeadObject` and written with
   `If-None-Match: *` so a race returns 409 instead of overwriting. `POST /api/uploads/check` returns the same
   name, `unsafeChars`, `truncated` and `exists` before the upload, and the upload page warns on each.
   Thumbnail keys are deterministic: `thumbnailKeyForVideo(videoKey)` returns
   `thumbnails/${videoKey}.webp`; no database column is required.
   Agent crop keys come from `evidence_key(video_key, batch_id, item_id)` in
   `services/agent/src/vss_agents/utils/crop_evidence.py` (`batch_id` is `run-<N>`, allocated by
   `next_run_batch_id`); reviewer replacements from `uploadedEvidenceKey` in
   `incident-console-v2/src/modules/reports/domain/revision.ts` (`edit-<N>`).
   Objects written before 2026-10-28 were renamed by `supabase/r2/migrate_r2_names.py` (copy, verify, update
   the rows; the live rename has been run on finals and the old copies and orphaned objects were deleted by hand afterwards). `model_runs.notes` keeps the old key as history.
3. **Durability Verification:**
   `verifyR2Video` performs `HeadObject` after a direct upload (requiring the exact expected nonzero byte length)
   and again before analysis (requiring a nonempty object). A valid-looking key alone is not treated as a stored video.
4. **Presigned Media URLs:**
   Access is private by default. Video playback and up to six report-card thumbnail URLs are generated server-side using AWS SDK S3 client
   presigning (`getSignedUrl` with `GetObjectCommand`, `ResponseContentDisposition: 'inline'`, and a 1-hour
   expiration window). Agent-side evidence crops and video files are resolved via `services/agent/src/vss_agents/utils/r2.py` (`resolve_r2_url` / `get_r2_presigned_url`), generating boto3 S3 presigned URLs (1-hour expiration) or using public base URLs when configured (`INCIDENT_VIDEO_BASE_URL`).

---

For known schema issues and technical debt, see [`status.md`](status.md).

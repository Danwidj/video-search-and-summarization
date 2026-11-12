# Incident Search & Reporting Capstone — Data Layer & Schema

The database schema (Supabase PostgreSQL) and the object storage layout (Cloudflare R2) of `dev-profile-incident`.

## 1. Supabase PostgreSQL Schema

There is one Supabase project per project phase: **finals** is the live database and **midterm** (`rfevukimyftzbxlehwel`) is a frozen, read-only record, archived in [`archived/supabase/midterm/`](../archived/supabase/midterm/README.md). The finals schema is the baseline [`supabase/migrations/20261020000000_finals_baseline.sql`](../supabase/migrations/20261020000000_finals_baseline.sql) plus the later migrations in the same folder, listed in [Supabase README: layout](../supabase/README.md#layout); how they are applied is in the `incident-manage-database` skill. The SQL harness in `supabase/tests/` builds the schema on a throwaway local Postgres.

Finals holds seven tables: `videos`, `queries`, `model_runs`, `report_revisions`, `evidence_crops`, `query_results` and `analysis_jobs` (the console's analysis queue, not report data). Every report is a `report_revisions` snapshot; there are no relational report tables.

### The report model

- **An upload analysis appends one AI revision:** `kind='ai'`, a new `model_run_id`, the full contract report as `payload` JSONB, the evidence list as `evidence` JSONB and `parent_id` NULL. The agent writes it (`IncidentDB.insert_ai_revision`); the console never edits it.
- **A human edit appends a human revision:** `kind='human'`, `parent_id` = the revision the reviewer opened, the full edited report as `payload` and the evidence list that revision uses. It inherits the parent's `model_run_id`.
- **Re-generation is a new AI branch:** `parent_id` NULL, no earlier edits copied.
- **One revision per video is official.** `videos.official_revision_id` names it; NULL means none. `evidence_crops` rows belong to the video's **searchable revision**: the official revision when there is one, otherwise the newest (`searchable_revision_id(video_id)`).
- **Revisions are append-only.** A trigger rejects `UPDATE` and `DELETE`. The exceptions are the `ON DELETE CASCADE` of the video, `apply_r2_rename` (may change only `evidence`) and `set_revision_embedding` (may only set `embedding` while it is NULL).

Each `evidence` entry describes one item:

| Field | Meaning |
|---|---|
| `item_type`, `item_id`, `timestamp_seconds` | The report item the entry belongs to |
| `frame`, `image` | R2 keys of the whole video frame and of the crop |
| `bounding_box`, `detected_box`, `box_seconds` | The crop box in that frame, the detector's own box before the 5% crop padding, and the second the frame was read at |
| `located`, `image_gap` | `located` is false when the detector found nothing (a frame, no crop, no box); `image_gap` is the reason an item has no image |
| `box_source` | `track-time` when a person's box came from a track matched by the report's seconds; `gap-retry` when the gap retry found it; absent when the locate step found the box |
| `track`, `track_first_seen_seconds`, `track_last_seen_seconds`, `track_gap`, `track_source` | R2 key of the track JSON and its span for an item matched to a track; `track_gap` says why a person has none; `track_source` is `object-tracker` for an instrument or asset, `reviewer` for a reviewer's track |
| `zoom_checked`, `zoom_confidence`, `zoom_seen`, `zoom_gap`, `name_before`, `description_before` | The zoomed second look: whether it named the item, its 0-1 confidence, what the two looks found, why it was skipped or ignored, and the name and description before a correction |
| `source`, `image_source`, `track_partial`, `ai_proposal` | Reviewer items: `source: "reviewer"` for an item the reviewer added, `image_source: "reviewer"` for an image the reviewer set, an incomplete track, and the model's reading of the reviewer's box |

### Detailed Table Specifications

Timestamps are naive UTC (`timestamp without time zone`, default `now() AT TIME ZONE 'utc'`).

#### `videos`

Primary registry of ingested video assets.

| Column | Type | Description |
|---|---|---|
| `id` | `VARCHAR(20)` PK | `'v' + first 19 hex of sha256(random UUID)` for uploads; clip-name ids (`Burglary012`, `SYN-...`, `MOCK-...`) for fixture and eval rows |
| `filepath` | `VARCHAR(1024)` | R2 object key (`uploads/<original name>.mp4`, `anomaly/<category>/<clip>.mp4` or `normal_videos/<clip>.mp4`). Older rows may hold an absolute VST path: validate with `isValidR2Key` before presigning. The console owns this column; the agent does not write `videos` |
| `uploaded_datetime` | `TIMESTAMP` | When uploaded. Some historical rows are NULL |
| `duration` | `INTEGER` | Video duration in seconds |
| `source` | `VARCHAR(512)` | Ingestion source. NULL for console uploads |
| `official_revision_id` | `BIGINT` | Composite FK `(id, official_revision_id)` → `report_revisions(video_id, id)`. NULL = awaiting selection. Set and cleared only by `set_official_revision` |
| `official_since` | `TIMESTAMP` | When the current official revision was marked; NULL when there is none |
| `content_sha256` | `CHAR(64)` | SHA-256 of the file as uploaded, before conversion; UNIQUE where not NULL, so a repeat upload is refused before anything is stored. NULL for a seeded clip |

#### `queries`

Natural-language search queries: `id` (`VARCHAR(20)` PK), `query_text` (`TEXT` NOT NULL), `submitted_datetime`.

#### `model_runs`

One row per execution of an analysis over a video.

| Column | Type | Description |
|---|---|---|
| `id` | `VARCHAR(20)` PK | Run identifier |
| `model_name` | `VARCHAR(128)` NOT NULL | Model identifier (e.g. `nvidia/cosmos-3-nano-reasoner`) |
| `model_version`, `prompt_version` | `VARCHAR` | Optional version tags |
| `run_datetime` | `TIMESTAMP` | Execution time |
| `notes` | `TEXT` | The console's **immutable analysis-attempt record** `{"incidentConsoleV2": {...}}` for every attempt ([`analysis-schema.md` §4](analysis-schema.md#4-storage)); never modified afterwards. Failed attempts (`contract_failed` / `request_failed`) are `model_runs` rows with no revision. Count runs by outcome (`run_outcome(notes)`) or through AI revisions |

#### `report_revisions`

Append-only report snapshots: the source of truth for every AI and human report.

| Column | Type | Description |
|---|---|---|
| `id` | `BIGINT` identity PK | Revision identifier. Search results and `query_results` store this |
| `video_id` | `VARCHAR(20)` NOT NULL | FK → `videos.id` ON DELETE CASCADE |
| `revision_no` | `INTEGER` NOT NULL | 1-based sequence per video, UNIQUE `(video_id, revision_no)`. The agent uses `max + 1` and retries on a unique violation; `save_human_revision` locks the video row |
| `kind` | `VARCHAR(8)` NOT NULL | `ai` for a model output, `human` for a reviewer snapshot |
| `model_run_id` | `VARCHAR(20)` | FK → `model_runs.id` (no cascade); required when `kind='ai'`. A human revision inherits its parent's run |
| `parent_id` | `BIGINT` | Composite FK `(video_id, parent_id)` → `report_revisions(video_id, id)`: the revision this one was edited from. NULL for an AI branch root |
| `payload` | `JSONB` NOT NULL | The full contract report (`incident`, `entities`, `instruments`, `assets`, `timeline`, `uncertainties`) |
| `evidence` | `JSONB` NOT NULL | The evidence entries and R2 image keys this revision uses (default `'[]'`) |
| `incident_type`, `severity_level`, `start_seconds`, `end_seconds` | facets | Written by the caller from `payload.incident` |
| `created_by` | `VARCHAR(256)` | Reviewer name; required when `kind='human'`, NULL for AI |
| `created_at` | `TIMESTAMP` NOT NULL | Creation time |
| `note` | `TEXT` | Free-text note on a human revision |
| `embedding` | `extensions.vector(1024)` | Summary vector of the incident title and description, written with the revision. NULL when the embedding endpoint was unavailable; `set_revision_embedding` then sets it once. Never overwritten |

Indexes: `(video_id, revision_no DESC)`, `incident_type`, `severity_level`, and an HNSW cosine index on `embedding`. Trigger `report_revisions_no_update_delete` raises `report_revisions is append-only`; it permits the delete made by the video's cascade.

#### `evidence_crops`

Searchable evidence of each video's **searchable revision**. A video has rows for at most that one revision. The database cannot embed, so a writer always supplies the rows:

| Event | Searchable revision | Rows |
|---|---|---|
| `set_revision_crops(video, newest, crops)` on a video with no official revision | newest | stored for the newest revision, every other row of the video deleted |
| A human revision is saved with `save_human_revision_with_crops` and the video has **no** official revision | the new revision | replaced with the call's crop list in the same transaction |
| A newer revision is saved another way and the video has **no** official revision | the new revision | the old rows stay but are never returned by search, until the writer calls `set_revision_crops` for the new revision |
| A newer revision is saved and the video **has** an official revision | unchanged | unchanged |
| `set_official_revision(video, rev, crops)` with a crop list | `rev` | replaced with `crops` |
| `set_official_revision(video, rev)` with no crop list | `rev` | `rev` keeps the rows it has; the video's other rows are deleted |
| `set_official_revision(video, NULL, ...)` (clear) | the newest revision | the newest revision keeps its rows (or takes the crop list); other rows deleted |

| Column | Type | Description |
|---|---|---|
| `revision_id` | `BIGINT` PK (part) | FK → `report_revisions.id` ON DELETE CASCADE |
| `item_type` | `VARCHAR(16)` PK (part) | `entity`, `instrument` or `asset` |
| `item_id` | `VARCHAR(20)` PK (part) | Item identifier in the revision (`E1..`, `I1..`, `A1..`) |
| `item_name` | `VARCHAR(256)` NOT NULL | The report item's `label` as written; the evidence card title |
| `description` | `TEXT` NOT NULL | Item visual description |
| `threat_level`, `holder_entity_id` | `INTEGER`, `VARCHAR(20)` | Instruments only |
| `timestamp_seconds` | `NUMERIC(8,3)` NOT NULL | The second the box was found at, to the millisecond |
| `bounding_box` | `INTEGER[4]` NOT NULL | Normalised `[ymin, xmin, ymax, xmax]` (0-1000) |
| `slice_start_seconds`, `slice_end_seconds` | `NUMERIC(8,3)` | The evidence slice: an entity's first to last seen second, an object's confirmed track span, else the box second plus or minus 3 s. A slice is a played time range of the existing video, never a clip file |
| `frame` | `VARCHAR(1024)` | R2 key of the whole video frame with the box drawn: the search thumbnail. NULL means the console cuts the frame from the video at `timestamp_seconds` |
| `image` | `VARCHAR(1024)` NOT NULL | R2 key of the crop |
| `embedding` | `extensions.vector(1024)` | Embedding for cosine retrieval (HNSW index) |
| `created_at` | `TIMESTAMP` NOT NULL | Insertion time |

#### `query_results`

Audit log of search hits: `id` (PK), `query_id` (FK → `queries.id`, CASCADE), `revision_id` (FK → `report_revisions.id`, CASCADE), `item_type`, `item_id`, `rank` (1-based), `similarity_score` (cosine, `1.0 - distance`), `critic_verdict` (`confirmed`, `rejected` or `unverified`), `critic_rationale`, `retrieved_at`. There is **no foreign key to `evidence_crops`**: changing the official revision keeps the search audit trail.

#### `analysis_jobs`

The console's background analysis queue: one row per uploaded video waiting for, running or finished with its analysis ([console reference](console-reference.md#background-analysis-jobs)). Written only by the console, and only through the functions below apart from the insert.

| Column | Type | Description |
|---|---|---|
| `id` | `BIGINT` identity PK | Job identifier |
| `file_path`, `filename` | `TEXT` NOT NULL | The uploaded video's R2 key and its stored file name |
| `model` | `VARCHAR(128)` | The allowlisted model chosen at upload; NULL runs the console's default |
| `status` | `VARCHAR(16)` NOT NULL | `queued` (default), `running`, `done`, `failed` or `cancelled` |
| `attempts` | `INTEGER` NOT NULL | Claims since the job was queued or last retried; a stale job with 2 fails instead of queueing again |
| `error` | `TEXT` | The plain reason a job failed |
| `created_at`, `started_at`, `finished_at` | `TIMESTAMP` | Enqueue time (claims take the oldest queued job first), start of the latest claim, and when it was done, failed or cancelled |
| `heartbeat_at` | `TIMESTAMP` | The running claim's latest heartbeat (every 15 s) |
| `video_id`, `revision_id` | FKs, ON DELETE SET NULL | The analysed video and the new AI revision, once done |
| `content_sha256` | `CHAR(64)` | The uploaded file's SHA-256; UNIQUE while the job is `queued` or `running`, so two simultaneous uploads of one file cannot queue twice |

### Relationships

Deleting a `videos` row removes its `report_revisions`, their `evidence_crops` and any `query_results` that reference those revisions. `model_runs` and `queries` rows are not deleted by that cascade; upload `analysis_jobs` rows stay, with their links cleared. Deleting a `model_runs` row is refused while a revision references it.

### Functions

All functions are `SECURITY INVOKER`, pin `SET search_path = ''`, and are executable by `service_role` only. Their signatures are in the migrations.

#### `save_human_revision`

Appends a `kind='human'` revision with `revision_no = max + 1` for the video, locking the `videos` row so concurrent saves cannot take the same number. `p_parent_id` must be a revision of the same video. Returns `{revisionId, revisionNo, videoId, kind, parentId, modelRunId, createdBy, createdAt, note}`.

#### `save_human_revision_with_crops`

The console's Save: the `save_human_revision` arguments plus `p_crops`. In one transaction it calls `save_human_revision`, then, when the video has no official revision, replaces the video's `evidence_crops` with `p_crops` for the new revision. With an official revision `p_crops` is ignored and the official rows stay. The console embeds the crops before the call, so a failed embedding writes nothing.

#### `set_official_revision`

`set_official_revision(p_video_id, p_revision_id, p_crops DEFAULT '[]')`. In one transaction: sets `videos.official_revision_id` and `official_since`, then makes the new official revision (or, for NULL, the video's newest revision) the searchable one. A non-empty `p_crops` replaces all the video's `evidence_crops` rows; an empty one keeps the rows the revision already has and deletes the video's other rows.

`p_crops` is the exact row list to store, one object per crop:

```
{item_type, item_id, image, bounding_box, timestamp_seconds,
 slice_start_seconds, slice_end_seconds, frame,
 item_name, description, threat_level, holder_entity_id, embedding}
```

The console obtains the embeddings from the agent's `POST /api/v1/incidents/evidence-embeddings` and passes them in `p_crops`; it writes no table directly.

#### `set_revision_crops`

Stores `p_crops` for the video's searchable revision without touching the official pointer. `p_revision_id` must equal `searchable_revision_id(p_video_id)`, otherwise the call is refused, so a writer holding a stale revision id cannot overwrite the rows of a newer one.

#### `search_evidence_items`

```
search_evidence_items(
  p_query_embedding extensions.vector(1024), p_top_k INTEGER DEFAULT 10,
  p_min_similarity DOUBLE PRECISION DEFAULT 0.2,
  p_item_types TEXT[] DEFAULT ARRAY['entity','instrument','asset'],
  p_incident_types TEXT[] DEFAULT NULL, p_min_severity INTEGER DEFAULT NULL,
  p_max_severity INTEGER DEFAULT NULL, p_video_id VARCHAR DEFAULT NULL
)
```

pgvector HNSW cosine search over `evidence_crops.embedding`, scoped to each video's searchable revision. `p_video_id` limits the scan to one video before ranking. `p_query_embedding` may be NULL only with `p_video_id`: the video's crops are then listed in video time order with `similarity_score` 0. Returns the video id, the revision id and its facets, the crop (with its `timestamp_seconds`, slice and `frame`) and `similarity_score`. The console route passes `p_min_similarity` 0.35 for a text query.

#### `search_report_revisions`

Cosine search over `report_revisions.embedding`, restricted to each video's searchable revision, so one video returns at most one hit. The agent calls it for `POST /api/v1/incidents/revisions/search`.

#### Repair functions

`list_revisions_missing_crops`, `repair_revision_crops`, `list_revisions_missing_embeddings` and `set_revision_embedding` find and heal a searchable revision that has evidence images but no `evidence_crops` rows, or a NULL summary vector. Neither writer overwrites existing data. The console's analysis job loop runs the repair at start, every 2 minutes and after each job; with no job loop running, use `POST /api/videos/repair-crops`.

#### `list_incident_report_summaries`

Paginated report library, one card per video: the official revision if there is one, otherwise the newest. Filters: text search, type (`Unclassified` selects a NULL `incident_type`), severity, kind, date range, local time-of-day and weekday (`p_timezone`, default UTC), entity/instrument/asset text, sort and `p_scope` (`all`, `official` or `not_official`). Returns `{reports: [...], totalItems, incidentTypes}`. It never returns `payload`, notes, signed URLs or video content.

#### `get_incident_dashboard`

Counts each video once through `searchable_revision_id` (official, else newest), the same rule as the library and search. Filtered by the revision's `created_at` plus optional type, severity band, weekday and hour (in `p_timezone`, default UTC) and `p_scope`. Returns `total` (with `official` and `notOfficial`), all-time `videos` counts, `severity`, `revisions`, `versions`, `types`, daily `trend`, `heatmap`, `entityTypes`, `topInstruments`, `topAssets`, `threatLevels`, `evidence`, a confidence histogram and `modelCoverage` (attempts by outcome). Migrations `20261107110000` (`types[].evidence`, `severityEvidence`) and `20261107120000` (`threatByHolder`) extend it; on a database without them the chart views that need those fields answer "not available yet".

#### Analysis job functions

They run on the database clock, so the stale rule does not depend on the console machine's clock. `p_attempt` is the `attempts` value a claim returned, so a runner whose job was recovered and claimed again cannot overwrite the newer claim.

| Function | Does |
|---|---|
| `claim_analysis_job(p_stale_seconds DEFAULT 180)` | Recovers stale running jobs (back to `queued` when `attempts < 2`, else `failed`), then claims the oldest queued job |
| `touch_analysis_job(p_id, p_attempt)` | Heartbeat for a running claim |
| `finish_analysis_job(...)` | `done` (needs the video and revision) or `failed`, only for the running claim |
| `retry_analysis_job(p_id)` | `failed` or `cancelled` back to `queued`, attempts 0 |
| `cancel_analysis_job(p_id)` | `queued` to `cancelled` |

### Client Access Models & PostgREST/Direct-Postgres Split

- **Console:** `incident-console-v2` uses Supabase PostgREST (`src/lib/postgrest/client.ts`, reached only from the adapters). There is no offline mode.
- **Agent:** `services/agent/src/vss_agents/utils/incident_db.py` is an async Supabase PostgREST helper, configured by `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`. It reads `videos` and writes `model_runs` and `report_revisions`; the search store reads `evidence_crops` and writes `queries` and `query_results`.
- **Laptop tooling** (the `supabase` CLI) uses direct Postgres (`INCIDENT_DB_DSN`). Direct Postgres from the VM has been blocked on and off, so the agent and console stay on HTTPS.
- **No client transactions:** PostgREST has none, so the agent's report write is one `INSERT` with `revision_no = max + 1`, retried when the unique key rejects a concurrent writer (SQLSTATE 23505), five attempts at most. In agent mode the agent inserts a placeholder `model_runs` row (`insert_model_run_if_absent`) and the console's later upsert fills in `notes`.

### Row-Level Security (RLS) & Access Control

Finals is locked down from its first migration:

- **Default-deny:** RLS is on for all seven tables, with no policies, and every privilege in `public` is revoked from `PUBLIC`, `anon` and `authenticated`. Every function is `service_role`-only.
- **Self-check:** the baseline fails (and rolls back) if any table has RLS off, anything is reachable by `anon`/`authenticated`, or any function is `SECURITY DEFINER` or lacks a fixed `search_path`. Run `supabase/tests/security_check.sql` after every applied migration (expect 0 rows), and `supabase/tests/probe_api.sh` to confirm over REST that the public key is refused.
- **Service access:** `incident-console-v2`, `vss-agent` and `mock-backend` authenticate over HTTPS PostgREST with `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (`service_role`), which bypasses RLS.

## 2. Cloudflare R2 Storage Architecture

Cloudflare R2 is the permanent object storage for all video media and evidence images. Local disks on the VM are temporary caches only.

### Bucket Key Tree Layout

```
anomaly-detection-dataset/            # bucket name comes from R2_BUCKET
├── anomaly/<category>/<clip-name>.mp4   # classified dataset clips (seed/eval) only
├── normal_videos/<clip-name>.mp4        # baseline non-incident clips
├── uploads/<original name>.mp4          # all user uploads; flat; always an H.264 MP4; a taken name gets -2, -3 before .mp4
├── thumbnails/<video-key>.webp          # browser-captured report-card screenshots
├── scratch/analyze/<video-key>/         # agent scratch (caption windows, set-of-marks copy), deleted when the step ends
└── evidence/<video-key>/
    ├── run-<N>/<itemId>.jpg             # AI crop, one run-<N> per analysis
    ├── run-<N>/<itemId>-frame.jpg       # the whole video frame the box was found in
    ├── run-<N>/<itemId>-track.json      # person or object track
    └── edit-<N>/<itemId>.jpg            # reviewer items cut at Save (-frame.jpg and -track.json beside), one edit-<N> per Save
```

- **Uploads are classification-neutral:** the VLM's later incident classification does not move or rename the object.
- **No key is ever overwritten:** each write takes the next free number, and the put is conditional (`If-None-Match: *`). No key holds a hash or UUID.
- **Shared images:** items on one box share one stored `image` and `frame` key; every item keeps its own evidence entry.
- **No writer deletes an image.** `POST /api/reports/<videoId>/evidence-sweep` removes only images no revision or `evidence_crops` row of the video names and that are older than `minAgeHours` (default 24; dry run by default). Deleting a video removes its video and thumbnail objects, then every object under `evidence/<video key>/`, then the video row.

### Track files

`<itemId>-track.json` under `run-<N>/` is an array of `{t, box, score}`: `t` in video seconds, `box` `[ymin, xmin, ymax, xmax]` on 0-1000, `score` 1.0 for a confirmed box and -0.1 for one carried by a tracker and not confirmed. A person's track comes from the perception stack; an instrument's or asset's from the object tracker. A reviewer's track file is `{source, samples:[{t, box, conf}], span, partial, lost_at, reason}`. The console reads a track on the server through `GET /api/reports/[videoId]/track`.

### Key Validation & Generation Rules

1. **Validity (`isValidR2Key` in `incident-console-v2/src/lib/r2/key.ts`):** a non-empty string that does not start with `/` or `.` and does not contain `..`. This rejects the VST file paths that old rows may hold.
2. **Upload keys (`src/lib/r2/names.ts`):** the original file name with its extension replaced by `.mp4`; a character outside letters, digits and `. _ - ( ) + ,` becomes `_`; a name over 150 characters is cut; a name already stored gets `-2`, `-3` before the extension.
3. **Durability:** `verifyR2Video` performs `HeadObject` after a direct upload (requiring the exact expected nonzero byte length) and again before analysis. A valid-looking key alone is not treated as a stored video.
4. **Presigned URLs:** access is private. Video playback and thumbnail URLs are presigned server-side with a 1-hour expiry.

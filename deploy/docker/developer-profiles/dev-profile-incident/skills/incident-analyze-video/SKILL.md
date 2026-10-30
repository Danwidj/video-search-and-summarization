---
name: incident-analyze-video
description: Use to upload a video clip, analyse it, group videos into incidents (suggestions, merge, remove) and build, edit, version or mark official an incident's combined report through incident-console-v2 against the VM agent (mvp3). Not for batch scoring against ground truth - use incident-run-eval.
license: Apache-2.0
metadata:
  version: "0.2.0"
  profile: "dev-profile-incident"
  tags: "incident analysis vlm report review merge"
---
# Incident Analyze Video

**Identity rules (mvp3).** A video belongs to exactly one incident. Analysing a video stores an analysis and creates **no** report version. A version is built only by Regenerate, from the latest analysis of each current video, and versions are append-only. Merge and remove never rebuild a version.

Canonical facts:
- Flow, deployment and the console API table: [`.docs/architecture.md` §5](../../.docs/architecture.md#5-mvp3-incidents-with-several-videos)
- Agent endpoints: [`.docs/vm-api-contracts.md`](../../.docs/vm-api-contracts.md)
- Report fields: [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md)
- Tables and database functions: [`.docs/data.md`](../../.docs/data.md)
- Why: [`.docs/decisions.md`](../../.docs/decisions.md) (entries dated 2026-10-30)

## Prerequisites

The stack is running via [`incident-start`](../incident-start/SKILL.md) in `--mode vm` (the mvp3 agent on `localhost:8001`), and `curl -s localhost:3200/api/health` is ready. Analysis is **agent mode only**; there is no gateway path for `POST /api/analysis`. Keep clips short: analyse must finish inside 360 s.

Check the synthesise route first, because Regenerate needs it:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8001/api/v1/incidents/synthesize -H 'Content-Type: application/json' -d '{}'
```

`422` means it is mounted. `404` means the agent was started before PR #320 (which mounts it); restart it, or Regenerate fails with 502.

## Instructions

The Phase 6 UI is merged ([screens](../../.docs/architecture.md#screens-phase-6)); the same steps are available through the console API below, which the screens call.

### 0. In the UI

- **Upload a batch:** on `/` pick or drop several clips. Each file runs Upload and Analyse (two at a time); once all are analysed, Check matches runs for every file, then Build report. A file whose best match scores 0.5 or more is joined to that incident automatically (checks run one file at a time; the card says where it went). A file with no pending suggestion shows "Checked, waiting to build" until its report is built; one with a pending suggestion waits ("Awaiting your decision"), and only then does the amber banner show and the page link to the Matches tab. Each file shows its own bar and error; "Retry this video" resumes at the stage that failed. The batch bar is the average of the files' own progress (a file awaiting a decision counts as finished); the running step shows its elapsed time and analysis is about a minute per video. "Cancel unfinished uploads" appears only while a file is uploading, and the final button opens the library's Matches tab while a suggestion awaits a decision, the library otherwise.
- **Automatic joins:** the report page shows a note on a camera the system joined (score and reason chips). To undo it, Remove video, then Move to its own incident: the video leaves, the pair is rejected and it is not joined again. Rebuild with Regenerate afterwards.
- **Review matches:** the report page shows an amber banner per pending match; the library's **Matches** tab (`/library?tab=matches`) lists them all. Accept opens the same confirm dialog as a manual merge (both sides' video names, a warning when the kept incident has an official version), then merges and rebuilds the kept incident's report once, and shows a notice on it; Reject is remembered and builds the report of each side that has no other pending match. An incident still waiting shows "Waiting for match decision" in the library, and its page offers the suggestion or "Build report now".
- **Report page** (`/reports/<incidentId>?revision=&camera=`): the overview card, then the camera bar (removed, invalid and not-in-this-version cameras are disabled; Remove video sits at its end; counts and the Remove dialog follow the incident's videos, not the open version), then the usual panes for that camera. **Regenerate** (above the version list) builds a new version from the stored analyses and selects it; **Remove video** offers "Move to its own incident" or "Delete entirely" (only delete for the last video); **Merge into another incident** picks a target and confirms; **Edit from vN** edits the selected camera or the overview.
- **Library:** one card per incident with a video-count chip; "Delete incident..." names what goes. An incident with no videos opens a "has no videos" page with the same Delete action and is not offered as a merge target.

### 1. Upload

1. `POST /api/uploads/check` with `{"filename"}` (a video name is its real, sanitised file name; a name already stored is not refused but gets `-2`, `-3`, ... before the extension, and the answer's `name` is the one the file will be stored under, `exists: true` when it differs from the file's own).
2. `POST /api/uploads` with `{"filename": "<name>.mp4"}` returns the VST upload URL; chunked upload to it (the browser does this in `modules/videos/infrastructure/vst/chunked-upload.ts`).
3. `POST /api/uploads/r2` puts the file in R2 (VST returns no R2 key). With `R2_KEY_PREFIX=mvp3/` the console adds the prefix itself.
4. `POST /api/uploads/complete` with `{"sensorId", "filename"}`.

### 2. Analyse

`POST /api/analysis`:

- New upload: `{"sensorId", "filepath": "<R2 key>", "filename", "model"?, "additionalInstruction"?}`. This creates the incident and the video.
- Re-analysis of a stored video: `{"videoName", "model"?, "additionalInstruction"?}`. It adds an analysis; earlier ones are kept and the latest wins.

Returns `{incidentId, videoName, analysisId, modelRunId, model, promptVersion, outcome}`. The model run id reads `<video name>@<UTC timestamp>`. If a new upload fails, the video and incident rows and the upload's VST camera are removed again and the R2 object stays, so retry without re-uploading (analysis reads R2, not VST). No version exists yet.

### 3. Group videos (optional)

- `POST /api/suggestions/evaluate` with `{"incidentId"}` compares every video of the incident with similar incidents (shortlist of 5, similarity at least 0.3, score at least 0.5; decided pairs are skipped), then joins the best pending match scoring at least 0.5 and answers `joined` (or `joinError`, leaving it pending); the evaluated incident id may be merged away, so use `joined.keptIncidentId`; after a join the kept incident is checked again (no second join) and its other matches at 0.5 or more come back in `suggestions` as pending rows. Needs the agent's `match-judge`. Time is only a hint. Each suggestion carries `reasons` (text) and, from an agent that returns `structured_reasons`, `structuredReasons` chips (`kind`, `label`, `detail`); the report-page banner and the library Matches tab show the chips and fall back to the text.
- `GET /api/suggestions?incidentId=<id>` lists pending suggestions, best first.
- `POST /api/suggestions/<id>/accept` (body `{"incidentId"?}`) merges; the kept incident defaults to the lower id. `POST /api/suggestions/<id>/reject` is remembered for good.
- `POST /api/reports/<targetId>/merge` with `{"sourceIncidentId"}` merges directly. The source incident, its versions and its official choice are deleted; no files move. The console then calls `POST /api/reports/<targetId>/build` once; the official version is not moved. A refusal shows in the dialog (404: an incident no longer exists; 422: cannot be merged). `GET /api/reports/<id>/videos` returns `{videoNames, hasOfficial}` for the picker.
- `POST /api/videos/<name>/remove` with `{"choice": "delete" | "move"}`. `delete` also removes the video's VST camera; `move` makes the video a new incident (then build its first report), removes nothing, and is refused for the last video of an incident.

### 4. Build a version (Regenerate)

`POST /api/reports/<incidentId>/build` with `{"note"?}` returns `{built: {incidentId, revisionId, revisionNo, modelRunId, videoNames, crops}}`. Statuses: `422` no videos, `409 {videos}` some video has no analysis yet, `503` agent not configured, `502` or `504` agent failed. The synthesis run is `incident-<id>@<UTC timestamp>`.

The version's `video_names` is its coverage and never changes. After a merge or a removal the coverage note says "Does not include: ..." or "Includes a removed video: ..." until you regenerate (merge and Accept rebuild by themselves; Remove video leaves its notice and Regenerate, primary while the version is stale, clears it).

### Direct agent calls (debugging the agent)

```bash
curl -s -X POST localhost:8001/api/v1/incidents/<video_name>/analyze \
  -H 'Content-Type: application/json' \
  -d '{"video_url": "<signed R2 URL>", "model_run_id": "<video_name>@2026-10-30T06:00:00Z", "skip_rp1": true}'
```

The `videos` row must already exist; the agent does not write `videos`. The response carries `analysis_id`, `model_run_id` and `outcome` (`stored` or `not_stored`) and no `revision_id`. Request fields and error table: [`vm-api-contracts.md`](../../.docs/vm-api-contracts.md#post-apiv1incidentsvideo_nameanalyze). Synthesise and match-judge are stateless, so they are safe to call by hand with a body copied from the contract.

| Status | Meaning |
|---|---|
| 422 | P1 output failed `core-scored-v1`. Nothing is stored; `detail` carries `message`, `raw_output`, `finish_reason`, `model`, `contract_version`. |
| 504 | Analysis timed out |
| 501 | `incident_report_gen` is not configured on this agent. |
| 502 | The video model returned no answer. The video is probably in an unsupported format (10-bit H.264) or unreadable; nothing is stored. In a batch only that file fails. |
| 500 | Any other failure. See `./.scripts/logs.sh vss-agent` on the VM. |

## Version lifecycle

There is no verify step and no review status. A report is its list of versions; `GET /api/reports/<incidentId>/revisions` lists them newest first, each with its coverage verdict.

- **Read:** `GET /api/reports/<incidentId>?revision=<id>&camera=<video>` returns the version (given, else official, else newest), its overview and cameras, and that camera's report.
- **Edit:** `PATCH /api/reports/<incidentId>/edit` with `{parentId, editedBy, note?, camera?, edit?}`, or an overview edit (title, type, severity_level, description, location), writes a new human version. Re-generation copies no edits.
- **Evidence images:** `POST /api/reports/<incidentId>/evidence-image` (multipart `file`, `itemId`, `video`; JPEG, PNG or WebP, up to 5 MB) uploads to a new key `evidence/<video key>/edit-<n>/<itemId>.jpg` and never overwrites. `GET .../frame?t=<s>&video=<name>` returns a JPEG (needs `ffmpeg`). `POST .../evidence-crop` with `{video, timestampSeconds, region}` returns a crop and writes nothing. `POST .../evidence-sweep` with `{video, dryRun?, minAgeHours?}` removes unreferenced images (dry run by default).
- **Official:** `PUT`/`DELETE /api/videos/<incidentId>/official` with `{"revisionId"}` (the old path name takes an incident id). Only the incident's own versions are accepted.
- **Delete:** `DELETE /api/reports/<incidentId>/delete` removes every video's objects and its VST camera (VST holds at most 100; an upload past that fails with "Maximum number of sensors limit reached"), then the rows, and the videos' unused `model_runs`; an incident with no videos is deleted by its row alone.

## Verify

Minimum checks after one analyse and one build, in the finals-free mvp3 database:

- `POST /api/analysis` returned 200 with `outcome: "stored"`, and `video_analyses` has a row for the video.
- No `report_revisions` row exists until `build` runs; after it, the new version's `video_names` lists the incident's videos.
- Objects in R2 sit under `R2_KEY_PREFIX`, and database keys have no prefix.
- The model run ids are readable (`<video name>@<timestamp>`).

## Known quirks

- The report page's **Re-analyse** dialog still posts to the stale `POST /api/videos/<id>/runs` route and does not work on mvp3. Re-analyse with `POST /api/analysis` and `{"videoName"}`.
- The agent's analysis payload carries a derived `incident.duration` that `incident-contract-v4` forbids, so the report API can mark a freshly analysed camera invalid and the page shows "No camera of this version can be shown". Synthesise (Regenerate) accepts the shape. The console fix had not merged when this was written; check [`architecture §5`](../../.docs/architecture.md#known-leftovers-on-originmvp3).
- A model can run away into invalid JSON for one clip (422 for that file only); retry or change the model.
- `GET /api/videos`, `POST /api/videos/<id>/runs` and `ANALYSIS_MODE` still exist in the console from before mvp3 and use the old video-keyed run code. They do not match the mvp3 schema; do not use them.
- Every attempt, valid or not, is recorded in `model_runs.notes` with its outcome under validation policy `core-scored-v1`; see [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md).
- `anomaly/<category>` is reserved for classified seed/evaluation media. VLM output such as `incident_type: none` does not change the uploaded object's key.

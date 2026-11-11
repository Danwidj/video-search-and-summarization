# incident-console-v2 Reference

Pages, routes, behaviour and configuration of `incident-console-v2`, the reviewer console of `dev-profile-incident`. Companions: [`architecture.md`](architecture.md) (containers, runtime and deployment views), [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md) (code layout and import rules), [`vm-api-contracts.md`](vm-api-contracts.md) (the agent's HTTP contracts) and [`data.md`](data.md) (the tables and object keys the routes write).

## Console configuration

Server-only variables, read from `incident-console-v2/.env.local` (a symlink to the profile's shared `.env.local`); none may be exposed through `NEXT_PUBLIC_`:

| Variable | Use |
|---|---|
| `ANALYSIS_MODE` | `gateway` (default) or `agent` |
| `VLM_GATEWAY_URL` | the gateway, required in gateway mode |
| `INCIDENT_AGENT_BASE_URL` | the agent or the mock (chat, search, embeddings, and analysis in agent mode); uploads do not use it |
| `VLM_MODEL` | default model in the picker, one of `contracts/inference.json` (default `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`) |
| `CONTRACTS_DIR` | the shared `contracts/` directory (default `../contracts`) |
| `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | PostgREST |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` | video and evidence storage |
| `FFMPEG_PATH`, `FFPROBE_PATH` | override the npm-bundled `ffmpeg` / `ffprobe`; unset uses the bundled copy, then PATH |
| `ANALYSIS_JOB_LOOP` | `off` keeps this console's [background analysis loop](#background-analysis-jobs) stopped (its queued jobs then wait for another console); unset runs it |
| `INCIDENT_ANALYSIS_TIMEOUT_SECONDS` | the limit of an agent-mode analysis (default 600) |

## Console routes

| Route | Does |
|---|---|
| `GET /api/health` | `status` (`ready` or `degraded`) and per-service booleans only; the `gateway` row is omitted in agent mode |
| `GET /api/models` | The allowlisted models and the default |
| `POST /api/uploads/check` | The name an upload will be stored under, with `unsafeChars`, `truncated` and `exists` |
| `POST /api/uploads/r2` | Stores an upload in R2 as an H.264 MP4 ([upload](#upload)) |
| `POST /api/uploads/thumbnail` | Stores the browser-captured thumbnail |
| `POST /api/jobs`, `GET /api/jobs`, `POST /api/jobs/<id>/retry`, `POST /api/jobs/<id>/cancel` | The [background analysis jobs](#background-analysis-jobs) |
| `POST /api/analysis` | Runs one analysis inside its request, for scripts and tools; the upload page does not call it |
| `GET /api/reports` | Library summaries, six per page, with signed thumbnail URLs and no video URL |
| `GET /api/reports/[videoId]?revision=` | One report version with its playback URL |
| `GET /api/reports/[videoId]/revisions` | The History list |
| `GET /api/reports/[videoId]/preview` | A signed video link for the Library card's hover preview |
| `PATCH /api/reports/[videoId]/edit` | Save as new version ([edit](#saving-an-edit)) |
| `DELETE /api/reports/[videoId]/delete` | Deletes the whole video, every revision of it and its objects in R2 |
| `GET /api/reports/[videoId]/track?revision=&type=&item=` | An item's track samples, read from R2 on the server: `{samples: [{t, box}]}`, 404 without a track |
| `GET /api/reports/[videoId]/frame?t=` | One video frame as a JPEG |
| `POST /api/reports/[videoId]/evidence-crop` | Cuts a rectangle from a frame and returns it as a JPEG, writing nothing |
| `POST /api/reports/[videoId]/evidence-image` | Stores a reviewer image under a new R2 key; the console itself no longer calls it |
| `POST /api/reports/[videoId]/evidence-sweep` | Removes images a failed save left behind ([`data.md`](data.md#2-cloudflare-r2-storage-architecture)) |
| `POST /api/reports/[videoId]/box/describe`, `.../box/track` | Proxies of the agent's [box tool routes](vm-api-contracts.md#reviewer-box-tool-console-proxy) |
| `POST /api/search` | Find evidence, through the agent's [incident search](vm-api-contracts.md#post-apiv1incidentssearch) |
| `POST /api/chat`, `POST /api/chat/video-check`, `POST` and `GET /api/chat/gap-retry` | The [report chat](#report-chat) |
| `GET /api/dashboard`, `POST /api/dashboard/chart` | The [dashboard](#dashboard-analytics-and-cross-filtering) and its chart requests |
| `GET /api/videos`, `GET /api/videos/[videoId]/runs` | Videos and a video's analysis history |
| `POST /api/videos/[videoId]/runs`, `PUT` and `DELETE /api/videos/[videoId]/official` | [Re-generation and the official version](#re-generation-and-the-official-version) |
| `POST /api/videos/repair-crops` | The [repair step](#search-rows-and-repair) |

A refusal by a database write function becomes a `StoreRejection`, which the route returns as 422 with the database's reason.

## Console pages

- **`/` (upload):** the model picker, a drop zone that takes one file or several, and the **Analysis jobs** list. The browser uploads each file, uploads a WebP thumbnail, then queues its analysis as a [background job](#background-analysis-jobs), so closing the tab does not stop a queued file. One file shows the four stages (**Uploading videos**, understanding, saving, report ready) and redirects to its report. Several files form a **batch**: a row per file shows Queued, Uploading, Analysing, Done with an **Open report** link, Failed with the reason, or Cancelled. Uploads run strictly one at a time, and a failure never stops the next file. **Retry** re-sends a failed upload or queues a failed job again.
- **`/library`:** two tabs, Find incidents and Find evidence ([library](#report-library-pagination-and-deferred-report-loading)).
- **`/reports/<videoId>`:** the report workspace. A resizable left pane stacks the video, the timeline and the version graph; the right pane scrolls the report fields and one horizontal evidence-card carousel. Re-analyse, Ask about this incident and the View / Edit tabs sit in the app header ([report versions](#report-versions-view-edit-and-history)).
- **`/reports/<videoId>/compare?left=&right=`:** two AI revisions of one video side by side. Nothing in the console links to it; it opens only from a typed URL.
- **`/dashboard`:** see [Dashboard analytics](#dashboard-analytics-and-cross-filtering).

### Upload

`POST /api/uploads/r2` (multipart `file`, `filename`):

1. Hashes the file (SHA-256) and answers 409 `{error, duplicate}` when a video or an active job already has that content, storing nothing. The page then links to the existing report.
2. Probes the file with `ffprobe`. An ISO MP4 whose video is already 8-bit yuv420p H.264 is stored byte for byte; anything else (phone HEVC `.MOV`, 10-bit H.264, MKV, WebM) is converted with `ffmpeg` to H.264 at the same width, height and frame rate, with no audio.
3. Stores it in R2 as `uploads/<name>.mp4` and answers with `contentSha256`, which the page passes to `POST /api/jobs`.

A file `ffprobe` or `ffmpeg` rejects is 422; a missing binary is 503; a file over 5 GB is 413. The conversion may take 25 minutes.

## Background analysis jobs

An upload's analysis runs as a row in `analysis_jobs` ([`data.md`](data.md#analysis_jobs)), not inside the browser's request, so it survives a closed tab.

- **Routes:** `POST /api/jobs {filepath, filename, model?, contentSha256?}` checks the model against the allowlist (400) and the hash against existing videos and active jobs (409) and queues a job -> 201 `{job}`. `GET /api/jobs` -> `{jobs}`: every running and queued job, then the latest 10 finished. `POST /api/jobs/<id>/retry` (failed or cancelled -> queued) and `POST /api/jobs/<id>/cancel` (queued -> cancelled) -> `{job}`, or 422 for a job in any other state.
- **The loop:** `src/instrumentation.ts` starts `src/lib/jobs/loop.ts` once per console process. Every 3 s it calls `claim_analysis_job`, which takes the oldest queued job, then runs `analyseUpload`, the same code `POST /api/analysis` runs, heartbeats the job every 15 s, and stores done with the new video and AI revision, or failed with the plain reason. One job at a time per console.
- **Time limit:** in agent mode an analysis is limited to 600 s (`INCIDENT_ANALYSIS_TIMEOUT_SECONDS`); gateway mode keeps each model's `timeout_seconds` in `contracts/inference.json`.
- **One video per job:** every attempt of a job analyses into the same video id, so a retry adds revisions to one video instead of leaving a second video row on the same R2 object.
- **Recovery:** a running job with no heartbeat for 180 s lost its console. The next claim, by any console, sends it back to the queue after its first stale run and fails it ("The console stopped twice while analysing this video") after the second.
- **Shared queue:** every console pointed at finals with the loop on claims from the same table, and a job runs against the agent or gateway of whichever console claims it. Set `ANALYSIS_JOB_LOOP=off` on a console that must not take other people's jobs.

## Report library pagination and deferred report loading

```mermaid
sequenceDiagram
    actor User as Reviewer
    participant UI as /library
    participant API as Next.js /api/reports
    participant DB as Supabase RPC
    participant R2 as Cloudflare R2

    User->>UI: Open library or change metadata/evidence filter
    UI->>API: GET summaries (page size 6; entity/instrument/asset terms)
    API->>DB: list_incident_report_summaries(...) (IncidentRepository.listReports)
    DB-->>API: 6 summaries + total count
    API->>R2: Sign up to 6 derived thumbnail keys
    API-->>UI: Metadata + small thumbnail URLs (no video URL)
    UI-->>User: Lazy screenshot images or skeleton fallback
    User->>UI: Open one report
    UI->>API: GET /api/reports/videoId?revision=revisionId
    API->>DB: Read one report_revisions row (IncidentRepository.getReport)
    API->>R2: Create selected object's signed URL
    API-->>UI: Full report + playback URL
```

- **Find incidents** shows six cards per page, one per video (official revision, else newest). A card shows the incident type, its official status, the title, a one-line summary, the severity badge, the version pill and the video's length. Filters are text, type, report status, severity band and added date, shown as chips and kept in the URL.
- **Text search** runs two matches on every query: the agent's meaning match (revisions scoring 0.25 or better) and the library's plain word match. The cards are listed found-by-both first, then word-only matches, then meaning-only matches. When the agent fails the word matches alone are listed, with a note.
- **Without search text** the list is always official reports first, then the rest, each by upload date oldest first.
- **Find evidence** posts `{query, videoId?}` to `POST /api/search`, which asks the agent for matches of 35% or better (`min_similarity` 0.35), and shows the top 20 hits; kind, threat and type filters, Sort and "Group by incident" work on the returned hits in the browser. A hit card shows the whole frame with its box and opens the report at the box second (`?t=`). "See evidence" on a card scopes Find evidence to that incident: it then returns 50 hits, and an empty query lists the incident's evidence in video time order.
- **Hover preview:** resting the mouse on a Library card for 300 ms plays the incident's video muted and looping over the screenshot.

## Dashboard analytics and cross-filtering

`GET /api/dashboard` calls the service-role-only `get_incident_dashboard` RPC. It counts **one report per video: the official revision, else the newest**, the Library's rule, and reports how many are official and how many are not yet official. Nothing is marked official by being counted.

- **Filter bar:** period presets (7d / 30d / 90d / All) or a Custom calendar range, Status, Severity and Type. Every active filter is a removable chip, and **Reset** clears them all (back to 30d). Period sends `days` plus the window (`after`/`before`), Status sends `scope` (`all`, `official`, `not_official`), Type sends `type`, Severity and a heatmap cell send `severity`, `day`, `hour`.
- **Cards:** Total reports, Activity by day and hour (a heatmap; select a cell to filter), Severity breakdown (a donut), Incidents by type, Top assets (a treemap), Instruments by threat level, Evidence by kind and Entity types.
- **Drill-down:** the total, its official and not-yet-official counts, and the type and asset rows link to `/library?scope=...` with the same period and filters, so the Library total equals the clicked number.
- **Time zone:** the heatmap and the weekday and hour filters use the viewer's local time; the browser's detected `timezone` is forwarded to `p_timezone`.
- **Loading:** before the first load the panels show skeletons, and a failed first load shows an error with Try again: the page never shows a 0 it has not loaded. A field the RPC does not return is read as not loaded, never as 0.

### Ask for a chart

`POST /api/dashboard/chart {request, chartType, timezone}` takes one request and the user's chart kind (Bar, Stacked bar, Ranking, Pie, Line or Area), and answers `{kind: 'chart', chart}`, `{kind: 'unsupported'}`, `{kind: 'needs_bar'}` or `{kind: 'not_available'}`.

1. The console posts its prompt and the request to the agent's [`chart-requests`](vm-api-contracts.md#post-apiv1incidentschart-requests) route, where the agent's own LLM picks a `ChartSpec`. The console validates it against the allowlist in `modules/dashboard/domain/chart-spec.ts`. A period is a preset or a calendar period (`{month}`, `{day}` or `{from, to}`), read against today in the viewer's time zone.
2. `generateChart` runs `getDashboard`, builds the rows, title and labels itself, and sends the figures and the palette colours to the agent's [`charts`](vm-api-contracts.md#post-apiv1incidentscharts) route.
3. The agent returns a Chart.js configuration; the console checks every label and figure against its rows and answers a 502 on a mismatch, so no altered figure is shown. The browser draws it with `chart.js`, and the Table tab gives every row.

- **`needs_bar`:** a kind that does not suit the dimension: a stacked bar needs the official split, a donut needs a whole, a line or area needs a day, week or month trend. A bar always suits.
- **Chart views:** four requests draw a view in its own kind, whatever the picker says: reports and evidence per report by incident type (a dual-axis combo), incident type by severity (a stacked bar), severity against evidence (a bubble chart) and instrument threat by holder type (a stacked bar). The first, third and fourth answer `not_available` on a database without migrations `20261107110000` and `20261107120000`.
- **Errors:** invalid input is 400, a missing `INCIDENT_AGENT_BASE_URL` 503, and a failed model or drawing call a plain 502.

## Report versions: View, Edit and History

The report page has two modes.

- **View** shows the version on screen: the report fields, the version graph, the official star and the evidence cards. A click on another version's row opens it; the star only toggles official. When no revision is official the page says so once.
- **Edit** (**Edit from vN**) shows the saved version read-only beside an editable draft, and the evidence as two rows of cards, saved and draft. **Undo** walks backward through changes and **Revert all** restores the opened version; neither writes a revision. Choosing another revision starts a fresh draft from that version. Unsaved edits exist only in the form: a refresh reloads the stored revision.
- **Version pill:** one shared pill shows the version type (Model, Human, or the starred Official) on Library cards, in each version row and beside the title.
- **What a reviewer may edit:** the structured (Class A) fields and each item's image; model output and provenance are read-only ([field classes](analysis-schema.md#three-classes-of-report-fields)). An entity keeps its canonical `E<n>` id from View through Edit and Save. Deleting an entity deletes the instruments it holds.

### Saving an edit

**Save as new version** always appends a `human` revision and needs a note. There is no Restore: copying an older version back is an Edit from that version.

`PATCH /api/reports/[videoId]/edit {parentId, editedBy, edit, note?}`:

1. Rejects Class B/C keys (400) and validates the edit against the contract's own sub-schemas and ID/holder/window rules (422).
2. Cuts each reviewer item's crop and frame on the server from the stored video.
3. On a video with no official revision, asks the agent to embed the new evidence; an embedding failure answers 502 and saves nothing.
4. Calls `save_human_revision_with_crops` ([`data.md`](data.md#save_human_revision_with_crops)), which appends a `human` revision whose parent is the revision that was opened.

No route changes a revision, `model_runs.notes` or an existing R2 object.

### Evidence cards and tracks

- **Evidence display:** cards show each item's whole video frame with its box drawn on it, never a cut-out crop. `located: false` shows the frame with no box and an "Object not located" note. The crop (`image`) is kept only for evidence search.
- **Tracks:** when an item's evidence entry carries a track, View mode draws a box that follows the item over the report video (`TrackOverlay`), in one stable colour per tracked item, and its card shows a presence bar that seeks on click. An item with no track shows its stored box on the player around `box_seconds`, and its card reads "Not tracked: <reason>" when the agent recorded `track_gap`. A person whose box came from a track matched by time carries a **Matched by time** badge. In Edit mode the overlay and the timeline draw the draft, so a change shows before Save.
- **Add evidence (box tool):** in Edit mode, **+ Add evidence** opens the box tool: pick a second, draw a box, **Analyse this box** (the describe route names it, the track route follows it), check the AI-filled card and **Add to draft**. Save cuts the evidence image on the server.
- **Edit track:** opens the keyframe editor (`TrackEditor`) on an item's track without changing its image or text. No new route or schema.
- **Set image:** clicking a card's image in Edit mode opens a picker: choose a frame, drag a rectangle, **Use this image**. The draft item carries `image_pick: {seconds, box}`, and Save cuts the crop and frame at that second; the entry gets `image_source: "reviewer"`, so a later re-track keeps this image.
- **Evidence proposals:** a re-track or set-image change proposed by the chat editor or a gap retry is not applied at once. The card shows it with **Confirm**, **Adjust** and **Dismiss**, and Save is blocked while any proposal is open.

### Report chat

`POST /api/chat` sends `version_id` (the version on screen in View, or the version an Edit draft came from) and, in Edit, `draft_report`. Each answer is tagged with the version it came from. Agent contract and chat modes: [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentschat).

- **The panel** is a non-modal side sheet, so the player stays usable beside it. Each version keeps its own conversation.
- **Answers** come from the stored report for the open version, not from a new look at the video. Every video time in an answer's text is a button that seeks the player, and a citation shows as a card with the item's crop, its name and the second it was found at.
- **Editing by chat:** in Edit, the route queries the report editor on the agent ([investigate](vm-api-contracts.md#post-apiv1incidentsvideo_idinvestigate)); its proposed changes are applied to the draft, and the reviewer saves. If no tool ran, the question falls through to standard chat. The editor sees each draft item's label and name and the last six chat turns.
- **Draw a box:** asked to add new evidence or to redraw an item, the editor opens the box tool at a second with the name filled in, or on the existing item, and the reviewer draws the box.
- **Gap retry:** asked to "retry the gaps" or to "look for E2 in the clip", the console starts a job with `POST /api/chat/gap-retry`, which proxies the agent's [gap-retries](vm-api-contracts.md#post-apiv1incidentsvideo_idgap-retries-and-get-apiv1incidentsvideo_idgap-retriesjob_id) route, and polls it. A found box becomes a set-image evidence proposal on the item; a miss gives its reason and offers the box tool. A retry takes about a minute an item.
- **"What I did"** (flag `INCIDENT_CHAT_STEPS_ENABLED`, off by default): each reply shows the tools executed and the changes applied to the draft.
- **Video check:** with routed answers and video checks on at the agent, **Check original video** appears under an offer and runs only on the click, through `POST /api/chat/video-check`.
- **Errors:** a failed request shows a plain message with **Try again**: the agent's `detail` for a 4xx, a fixed sentence for anything else.

### Analysis stages behind the page

Agent mode only. Settings and response fields: [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentsincident_idanalyze).

| Stage | Flag | Effect |
|---|---|---|
| Person tracking | `INCIDENT_TRACKING_ENABLED` (on for the VM agent) | Each located person is matched to a person track; the page draws a box that follows them, and a presence bar |
| Set-of-marks | `INCIDENT_SOM_ENABLED` (off by default, needs tracking) | P1 sees numbered person boxes, and entities are matched to tracks by that number first and by box overlap for the rest |
| Object tracking | `INCIDENT_OBJECT_TRACKING_ENABLED` (on for the VM agent) | Each located instrument and asset gets a track in the person-track shape, so the overlay and presence bar read it unchanged |
| Caption pass | `INCIDENT_CHUNKING_ENABLED` (on for the VM agent) | A clip over 30 s is cut into 20 s windows with 2 s overlap and captioned before P1, as context |
| Gap retry | none (on) | An item the locate step left without a box may get one (`box_source: "gap-retry"`); the console draws it like any located box, with no badge |
| Zoomed second look | `INCIDENT_ZOOM_NAMES_ENABLED` (default on) | A located item may be renamed at a confidence of at least 0.7; the previous name and description stay on the evidence entry |

### Search rows and repair

- **Searchable crops:** an analysis or re-run of a video with no official revision also writes the new revision's crops (`set_revision_crops`), and a Save writes them in the same call as the revision, so `/library` can find the video ([`data.md`](data.md#evidence_crops)). Each Find evidence card is titled with `evidence_crops.item_name`, the report item's `label`.
- **Repair step:** `POST /api/videos/repair-crops {videoId?, dryRun?}` (dry run unless `dryRun: false`) lists the searchable revisions with an evidence list but no crop rows, or with a NULL summary vector, embeds them through the agent and stores them without overwriting anything. The same repair runs automatically in the analysis job loop: at loop start, every 2 minutes and after each job. It is off with `ANALYSIS_JOB_LOOP=off`.

## Re-generation and the official version

- **Re-generation.** `POST /api/videos/[videoId]/runs {model, additionalInstruction?}` re-analyses the stored R2 object (the console's "reviewer prompt" box is `additionalInstruction`), from `ReanalysisDialog` in the report page's top bar:
  - the same canonical request, strict validation and ID-only recovery as an upload;
  - always a new run and a new AI revision, which starts from the model's output (earlier edits are not carried across);
  - it never writes the `videos` row and never changes the official version.
- **Official version.** `PUT /api/videos/[videoId]/official {revisionId}` and `DELETE` call `setOfficialRevision`: for a mark, the console asks the agent for the revision's evidence embeddings and passes them to `set_official_revision`, which sets `videos.official_revision_id` and rebuilds the incident's `evidence_crops`; for a clear it passes none and the rows go. If the agent is unreachable the mark fails and nothing changes.
- **Model choice:** both modes send the chosen allowlisted model. The run records the model the agent reports.

## Colour meanings

`incident-console-v2/src/app/styles.css` is the one source: semantic tokens exposed as Tailwind theme colours, with a comment table saying what each means (version model, human and official; not yet official; severity and threat high, medium and low). Use the token (`bg-version-model`, `text-sev-high`, `var(--color-not-official)`), never the hex. `levelBand` in `lib/ui/severity.ts` is the one number-to-band mapping for severity and threat level (5 and 4 high, 3 medium, 2 and 1 low). `tests/colour-tokens.test.mjs` fails if a meaning hex appears elsewhere in `src/`.

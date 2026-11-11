# Incident Profile Decision Log

Decisions that still shape `dev-profile-incident`, newest first. Each entry: decision, why, alternatives rejected, links. Superseded decisions move to [`archive/decisions-superseded.md`](archive/decisions-superseded.md).

### 2026-11-11: A template-built VM file must start the agent, and a test keeps it so

**Decision:** `native-services.sh` loads the env file through `vm_env_load` (`.scripts/env-file.sh`): a blank `HOST_IP` gets the VM's address (`vm_host_ip`, the same detection as `vm-ensure-docker.sh`) before the file is read, so `VST_INTERNAL_URL` and `PHOENIX_ENDPOINT` are built from it; a typed value wins; no address stops the script. `rebuild-svc.sh` and `tracking-stack.sh` use the same default. The template gains non-secret defaults in section 2 for `EVAL_LLM_JUDGE_NAME`, `EVAL_LLM_JUDGE_BASE_URL`, `EVAL_DIR`, `DATASET_FILE_NAME` and `RTVI_VLM_BASE_URL` (the values NVIDIA's `dev-profile-base/.env` uses) and an optional blank `WEAVE_WORKFLOW_ALIAS`; they left `compose.unused.env`. `test-env-template.sh` fails when the agent config refers to a setting a template-built file leaves unset or blank.

**Why:** The agent refused to start on a file copied from the template (`llms` and `workflow` invalid): nat rejects an unset or blank `${NAME}` that is a whole value, and `HOST_IP` and the eval judge name were exactly that. `HOST_IP` is a script default (it changes with DHCP), so only the script knows it; the rest are constants.

**Alternatives rejected:** Defaulting the eval settings in the start script (they never vary, so the template is the one place to read them); editing NVIDIA's config to add `:-` defaults (upstream drift); sourcing the file first and setting `HOST_IP` after (settings built from it would keep a blank host).

**Links:** [README §2](../README.md), `.scripts/env-file.sh`, `.scripts/test-env-template.sh`.

### 2026-11-11: Remove dead files, the VM shell dotfiles, the gateway's Compose files and the v1 console

**Decision:** five removals, each with no remaining reader outside docs: (1) the dangling `scripts/backfill_official_timestamps.py` symlink, four unreferenced `.docs/screenshots/` folders and `contracts/test-schema.mjs` (a search-contract test nothing ran); (2) `.dotfiles/`, the personal VM shell setup, and the stale `dotfiles/aliases.sh` comments in `.scripts/`; (3) `vlm-gateway/compose.yml` and `vlm-gateway/Dockerfile`, because the gateway only ever runs through `uv` from `start.sh`, plus the `include:` in the profile `compose.yml`, which now holds an empty `services: {}`; (4) `archived/incident-console/`, the retired v1 console, plus the mentions of it in `.gitignore`, `AGENTS.md`, `README.md`, `archived/README.md` and two skills. `archived/supabase/` stays. (5) All of `.docs/screenshots/` and every link to it from `status.md` and `decisions.md` (the entries keep their text); screenshots are evidence for the PR description and are never committed. `.docs/figures/` stays.

**Why:** Each item was unused, and a file that nothing reads still has to be kept accurate or misleads the next reader. Git history keeps everything removed. The profile `compose.yml` stays, with no services, so the `developer-profiles/compose.yml` include of it still loads.

**Alternatives rejected:** Deleting the profile `compose.yml` and its include in `developer-profiles/compose.yml` (a wider change than the gateway's include); keeping `.dotfiles/` as optional tooling (it is one person's shell aliases, not part of the profile); leaving the v1 console as read-only history (88 files, including `.env`-named ones, that nothing launches or tests).

**Links:** [`archived/README.md`](../archived/README.md), [`vlm-gateway/README.md`](../vlm-gateway/README.md), [`contracts/README.md`](../contracts/README.md). The 2026-10-22 entry on archiving the v1 console records why it was kept until now.

### 2026-11-11: Midterm, copy and R2 history move to `archived/supabase/`; a script builds a new database from the migrations

**Decision:** the `midterm/`, `copy/` and `r2/` folders of `supabase/` move, with their layout, to `archived/supabase/`; `supabase/migrations/` and `supabase/tests/` stay. `.scripts/setup-database.sh --env-file <file>` builds every table and function on an empty database from `supabase/migrations/`, and `.scripts/test-setup-database.sh` tests it on a throwaway local Postgres.

**Why:** A new user needs only the migrations; the rest is history that people should not read or run. `eval/` loads `supabase/migrations/` and `supabase/tests/` by path, so those stay. The script applies the files itself, because two migrations share the version `20261028090000` (applied migrations cannot be renamed), so `supabase db push` fails on an empty database with a duplicate `schema_migrations` key. It records each version, keeping the first of a shared one as finals' history does, so a later `db push` works on the new database. It refuses a target that already has tables or recorded migrations.

**Alternatives rejected:** Archiving all of `supabase/` (breaks `eval/` and the console tests); renaming or merging migrations (finals records them by file name); `supabase db push` for the build (fails on the shared version).

**Links:** [`supabase/README.md`](../supabase/README.md), [`archived/README.md`](../archived/README.md), `.scripts/setup-database.sh`. The 2026-10-20 entry below records the original folder layout.

### 2026-11-11: Section 1 is grouped by machine, the scripts supply three settings, the VM file is `.env.remote`

**Decision:** Section 1 of `.env` has one short heading per group: both machines (Supabase, R2), laptop only (`VSS_SSH_HOST`), VM only (keys, model endpoint); a setting sits in a machine group only when the other machine has no reader. `HOST_IP`, `VSS_APPS_DIR` and `VSS_DATA_DIR` moved to section 2 as blanks that the VM scripts fill in (`env-file.sh` for `native-services.sh`, `rebuild-svc.sh` and `tracking-stack.sh`; the same logic inline in the piped `vm-ensure-docker.sh`): `HOST_IP` is written into the file after a backup, the two directories are exported for the run only, and a typed value always wins. The default `VSS_DATA_DIR` is `<checkout>/.data` (git-ignored). `HF_TOKEN` and `VLM_GATEWAY_URL` were deleted (no reader). `VLM_MODEL`, `VLM_GATEWAY_BASE_URL` and `VLM_GATEWAY_API_KEY` are optional blanks in section 2: the profile `compose.yml` no longer includes the gateway's compose file (PR 556), so the VM's Compose needs neither; the laptop needs the pair only for mock mode and `eval/`, and the VM agent reads it only as an optional override of `VLM_BASE_URL` and `OPENAI_API_KEY`. The VM file is now `.env.remote`; `generated.env.remote` is still read when it is the only one, and `.env.remote` wins when both exist.

**Also in this change:** the two flows are named Midterm flow (`--mode mock`) and Final flow (`--mode vm`) on the diagrams (figures 2, 3, 5) and in the live docs; flags, scripts and folder names such as `mock-backend` keep their names, figure 5 is renamed `figure-5-analysis-midterm-flow`, and `*.bkp` is git-ignored.

**Why:** A fill-in list should hold only what a person must know. The scripts can derive the address and paths, so asking for them invited stale values. The checkout is shared by all VM users, so a checkout-relative data folder does not fork per user as `$HOME/.local/share` would. The file is no longer "generated", so the old name misled; the profile `.gitignore` already ignores `.env.remote`.

**Alternatives rejected:** Per-machine template files (two files to keep in step); a `$HOME`-based data default (forks per user); changing the data folder of an existing deployment (it would orphan data, so a set value always wins); dropping the old file name at once (breaks the VM's existing file).

**Links:** [`README.md`](../README.md), [operations §5](incident-profile-operations.md#5-vm-deployment-configuration-principles-envremote), `.scripts/env-file.sh`.

### 2026-11-10: One commented-down `.env` template, copied to `.env.local` and `.env.remote`

**Decision:** `.env` is the only copy-me template: section 1 blanks to fill in, section 2 defaults, one short heading per group, each value typed once (later settings refer to earlier ones). Dead and empty optional settings are deleted, and the long behaviour comments moved to [operations §5](incident-profile-operations.md#5-vm-deployment-configuration-principles-envremote). `native-services.sh` and `rebuild-svc.sh` no longer fall back to `.env`; they stop and name `cp .env .env.remote`. A committed `compose.unused.env` (names only) is passed before the real env file to every `docker compose` call of the profile, so Compose stops warning "variable is not set" about services this profile never starts. `LLM_ENDPOINT_URL` and `VLM_ENDPOINT_URL` were deleted: nothing in the started services reads them.

**Why:** Three overlapping files and a silent fallback to the committed template hid a missing real file. The warnings buried real ones.

**Alternatives rejected:** Editing the stock compose files to default the names (upstream drift); `--no-warn`-style filtering (hides real warnings); keeping the fallback (it can start the agent on blank keys).

**Links:** [README §2](../README.md), `compose.unused.env`, `.scripts/test-env-template.sh`.

### 2026-11-09: Ask for a chart shows three example chips, each sending its own chart kind

- **Decision:** the panel offers exactly three example chips, in `chart-examples.ts`: "Break down each incident type by severity throughout October" (a stacked bar by severity per incident type, the captain's chip), "Share of each incident type throughout October" (a donut) and "Severity mix of assault incidents in the last 90 days" (a donut). The captain asked for specific full-sentence prompts after the first version ("Incident distribution" and "Severity breakdown") and the first two candidates were chosen from seven tried. Each chip submits with the kind it reads best in; a donut chip also sets the picker to Pie, so the picker shows what is drawn (the October view leaves the picker alone, since a view ignores it). The bar and line examples, and the bubble chart, are gone from the chips; the picker's options and typed requests are unchanged.
- **Why:** the captain found the example list cluttered and the plain bar and line charts ugly. A donut suits a whole, and both donut dimensions (incident type, severity) are pie-capable in `chart-spec.ts`.
- **Alternatives rejected:**
  - *Short labels such as "Incident distribution":* the captain wants specific prompts that read like the first chip.
  - *Keep the picker's kind for chips:* a chip would draw a bar unless the reviewer changed the picker first, which is the ugly default.
  - *Donut for "Official vs not yet" or "Reports by version":* two slices, which reads poorly.
  - *Keep the bubble chip:* the captain found the bubble chart ugly.
- **Links:** [`chart-examples.ts`](../incident-console-v2/src/sections/dashboard/components/ChartRequest/chart-examples.ts), [console reference](console-reference.md#dashboard-analytics-and-cross-filtering), [`chart-examples.test.mjs`](../incident-console-v2/tests/chart-examples.test.mjs)

### 2026-11-09: New evidence opens the box tool at once; the editor asks no question first
- **Decision:** the report editor no longer asks the reviewer anything about new evidence. `propose_ask_reviewer` is removed (tool, `report_editor` `tool_names` entry, prompt text, and the `ask_reviewer` check in `utils/evidence_asks.py`). When the reviewer asks to add evidence, the editor calls `propose_open_box_tool` once, straight away, from the reviewer's message and the chat so far (`history`): the second it is best seen at (from the message or the draft, else the incident's start second) and a short name (a generic one when the message gives none). The console's `evidence` exchange is gone: no question count, no transcript, no question rows under "What I did". `POST /api/chat` sends the draft and the chat history only. The `evidence-asks` route no longer takes `questions_asked`. `propose_open_box_tool`, its window and item-key checks are unchanged.
- **Why:** a teammate asked (2026-11-09) that the reviewer's first message be enough, with no two-step question round. Removing the tool is the only way to guarantee that no question comes before the box tool opens; a tool that is kept but told not to ask could still be called.
- **Alternatives rejected:** keeping `propose_ask_reviewer` with the prompt saying "ask nothing" (the model could still call it, and the check would need the same rejection as removal, so the tool would still be dead code with a live prompt); keeping the question count and sending it with the request (it would serve nothing once no question is asked).
- **Amends:** the 2026-11-07 entry below. Its at-most-two-questions rule, the `evidence` payload and the question rows no longer exist; the box tool rules (one opening, inside the incident, `item_key` redraws) stand.
- **Links:** [console-reference](console-reference.md#report-chat), [vm-api-contracts](vm-api-contracts.md#post-apiv1incidentsvideo_idinvestigate), [`evidence_asks.py`](../../../../services/agent/src/vss_agents/utils/evidence_asks.py), [`evidence-ask.ts`](../incident-console-v2/src/lib/chat/evidence-ask.ts).

### 2026-11-08: Architecture figures follow the deck diagram standards and export with the local drawio command
- **Decision:** figures 2, 4 and 8 are the finals-deck draw.io diagrams (stock, built and external colours; 1800x830 page; Helvetica), exported with `drawio -x -f svg -e --theme light --embed-svg-fonts false` so each `.drawio.svg` stays small and opens for editing.
- **Why:** one source per diagram keeps the docs and the deck from drifting; the default export embeds PNG text fallbacks and grows the file about twentyfold.
- **Alternatives rejected:**
  - *Keeping the older repo-only C4:* it lacked gap retry and the stock/built key.
  - *Hosted draw.io tools:* diagram content must not leave the machine.
- **Links:** [`architecture.md`](architecture.md)

### 2026-11-08: Chat gap retry is in scope, and it returns proposals the reviewer confirms
- **Decision:** the reviewer can ask the report chat to retry the gaps of an existing report: every item with no box, or one named item. The editor calls `propose_retry_gaps`; the console starts a job on the agent (`POST /api/v1/incidents/{video_id}/gap-retries`) and polls it. The job runs the analysis's gap-retry stage (`retry_gap_crops`, the same video-model check and per-item caps) on the saved revision, with a request time cap of 300 s and 40 detector calls for all its items. Each box it finds becomes a set-image evidence proposal on its item, which the reviewer confirms or adjusts before Save. The agent writes nothing.
- **Why:** a gap retry is useful after the analysis, and a reviewer should not have to re-run an analysis to get it. A retry takes 30 to 120 s an item, longer than the chat's 90 s step cap, so it runs as a job with progress. Proposals keep the reviewer in charge of what is saved; the video model's box is never kept on its own.
- **Alternatives rejected:**
  - *Running the retry inside the editor's tool call:* the chat's 90 s wall clock would end it, and the reply would hang for the whole retry.
  - *Writing the found boxes straight into the draft:* a video-model box would be saved with no reviewer look.
  - *A new feature flag for the chat path:* features are on by default on this branch (#526).
  - *Keeping jobs in a database table:* a restart loses an in-flight job; the reviewer re-asks. A table is a schema change for a rare case.
- **Links:** [`api/incident_gap_retry.py`](../../../../../services/agent/src/vss_agents/api/incident_gap_retry.py), [`utils/gap_retry_jobs.py`](../../../../../services/agent/src/vss_agents/utils/gap_retry_jobs.py), [`src/lib/chat/gap-retry.ts`](../incident-console-v2/src/lib/chat/gap-retry.ts), [console reference](console-reference.md#report-versions-view-edit-and-history).
### 2026-11-08: A Library card's duration comes from the run's recorded video length
- **Decision:** `list_incident_report_summaries` returns `durationSeconds`, read from `model_runs.notes` at `incidentConsoleV2.request.videoDurationSeconds` (the length the analysis read before validation). The card shows it as an `m:ss` or `h:mm:ss` badge, bottom-right on the thumbnail, and no badge when it is null. Migration `20261108000000_library_card_duration.sql`.
- **Why:** `videos.duration` exists but the console never writes it (the upload row is inserted without it), so reading it would always show nothing. The run notes already hold the length and the list query already joins them, so the change is one field in the existing RPC with no per-card probe or download.
- **Alternatives rejected:**
  - *Reading `videos.duration`:* always null today; would need a writer and a backfill first.
  - *Probing each video in the browser or on the server per card:* the brief forbids it and it costs a download per card.
- **Links:** [`supabase/migrations/20261108000000_library_card_duration.sql`](../supabase/migrations/20261108000000_library_card_duration.sql); [`thumbnail.ts`](../incident-console-v2/src/lib/ui/thumbnail.ts)

### 2026-11-08: The report chat is a docked panel that narrows the page, not an overlay
- **Decision:** on the report page the chat is a docked `aside` beside the article, `sm:w-[28rem]` (the old sheet's width), and the article takes the rest (`min-w-0 flex-1`). Closing it (close button, Escape or the toggle) restores the full width. It is no longer a Radix sheet, so no overlay, portal or focus trap; `ReportChat` takes an `onClose` prop instead of `SheetClose`. Below `sm` it takes the full width, as the sheet did.
- **Why:** with the sheet open it covered the right side of the page, hiding the edit column and the evidence cards. Docking keeps every field and card usable while the chat is open.
- **Alternatives rejected:**
  - *Keeping the overlay and padding the page:* the page would need to know the sheet's state in every pane; a flex sibling does it with no extra state.
  - *Portalled sheet with `static` overrides:* the portal leaves the page's flex row, so the content would not narrow.
- **Amends:** [2026-11-06](#2026-11-06-the-report-chat-panel-is-not-modal-and-its-conversation-lives-on-the-report-page), where the panel was a non-modal sheet beside the player. Its conversation and non-modal behaviour still hold.
- **Links:** [`ReportPage.tsx`](../incident-console-v2/src/sections/reports/components/ReportPage/ReportPage.tsx), [`ReportChat.tsx`](../incident-console-v2/src/sections/reports/components/ReportChat/ReportChat.tsx)

### 2026-11-07: Instrument threat by holder type is a stacked bar per holder type, drawn in the stacked kind the agent already has
- **Decision:** a fourth chart view, `threat_by_holder` (metric `instruments`). One bar per holder type of the counted reports' instruments (Human, Animal, Unknown; "No holder" only when some instrument has no holder), each split into high, medium and low threat (low 1-2, medium 3, high 4-5, the severity bands), in the severity colours (`THREAT_SERIES`). Its figures are a new top-level `threatByHolder` from `20261107120000_dashboard_threat_by_holder.sql`, a read-only extension of `get_incident_dashboard`: four rows always, each with `high`, `medium`, `low`, `official` and `notOfficial`. The kind is `stacked_by_severity`, auto-selected like the other views.
- **Why:** the captain asked "among entity, what is the distribution of their instrument being high threat". The dashboard had instrument threat levels and entity types, but no link between them; each report records the holder of every instrument (`entity_id`), so the link is computed from the payload in SQL, and the figures stay counted from the database.
- **Holder and threat rules (in the migration):** an instrument's holder is the entity of its report with the same `entity_id`; an instrument with no holder (null or unknown id) is "none", so every instrument is in a holder row. An instrument counts once per counted report for each distinct (normalised name, holder type, threat level), the rule the existing instrument counts use. An instrument with no name, no threat level or a level outside 1-5 is in no band. Summed over the holder types, a band can exceed the same reports' `threatLevels` count when one name is held by two holder types; the holder view is not meant to match that count exactly.
- **Alternatives rejected:**
  - *A new threat-stack kind in `chart_generator`:* the live agent already accepts `stacked_by_severity` with three series under any labels and colours, so the shared agent needs no change and no restart (probed on 2026-11-07).
  - *Counting every instrument entry:* a report that names the same instrument twice would count twice, unlike the threat levels and the top instruments.
  - *Dropping instruments with no holder:* they would vanish from the bands, which would then disagree with "Instrument threat levels" for the same reports.
  - *Reading "high threat" as the report severity filter:* severity is a report property; threat is an instrument's. The prompt says so.
- **Deploy:** (1) the migration is a finals change and goes after `20261107110000` (ask-first; not applied). Until it is applied the view answers "Not available yet" and no figure is shown. (2) No agent change and no restart.
- **Evaluation (development only):** the SQL harness checks the holder rows on a constructed report (a holder with no entity, a blank type, a duplicate name, an out-of-range level), and the bands equal the `threatLevels` totals on the fixtures. The eval recount matches the SQL on seeded snapshots 1 and 2 (it also gained the `versions` figure of `20261107090000`, which it lacked), and the console's own code replays every spec the same way. No live model run. The allowlist grew to 2,170 specs (1,690 + 4 x 120).
- **Live check (2026-11-07):** the console at `:3210` against the live database answered "Not available yet" for "distribution of high-threat instruments among entities" (the migration is not applied). A chart from SQL-harness figures (TEST DATA) was drawn from the console's chart code through the shared agent's `stacked_by_severity` configuration, with the four holder rows of the seeded snapshot 2; the figures match the harness rows.
- **Links:** [`chart-spec.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-spec.ts), [`generate-chart`](../incident-console-v2/src/modules/dashboard/application/generate-chart/index.ts), [`chart-palette.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-palette.ts), [`20261107120000_dashboard_threat_by_holder.sql`](../supabase/migrations/20261107120000_dashboard_threat_by_holder.sql), [console reference](console-reference.md#dashboard-analytics-and-cross-filtering), [data.md](data.md#get_incident_dashboard), amends [2026-11-07 chart views](#2026-11-07-dashboard-chart-views-a-dual-axis-combo-a-stacked-bar-by-severity-and-a-bubble-chart-drawn-in-their-own-kind) only by adding a fourth view.

### 2026-11-07: Dashboard chart views: a dual-axis combo, a stacked bar by severity and a bubble chart, drawn in their own kind
- **Decision:** the captain chose three views from the options (B, C and E). Each is a closed allowlisted dimension in `chart-spec.ts` with its own metric, and each is drawn in its own kind whatever the picker says (`viewKind`):
  - `incident_type_evidence` (metric `evidence_per_report`): **combo_dual_axis**. Bars are the reports per incident type (left axis, "Reports"); a line is evidence items per report (right axis, "Evidence items per report"). Per report is items over reports, rounded to two decimals in code; a type with no reports is left out.
  - `incident_type_severity` (metric `incidents`): **stacked_by_severity**, one bar per type split into high, medium and low.
  - `severity_evidence` (metric `evidence_items`): **bubble**, x = severity level (1 to 5), y = evidence items, one bubble per pair, radius from the report count by code (`chartjs_config.bubble_radius`, area proportional to the count, 4 to 24 px).
  - The picker is not refused for a view and does not change it; the chart says "Drawn as ..." under its title. Auto-selecting the kind was chosen over offering the new kinds in the picker, because each view has exactly one kind that fits, so a picker choice would only ever be refused or ignored.
  - Figures: B and C come from `types[]` (`count`, `severity`, and the new `evidence`); E comes from a new `severityEvidence` list. Both need `supabase/migrations/20261107110000_dashboard_chart_evidence.sql`, a read-only extension of `get_incident_dashboard`. **That migration is not applied to finals** (ask-first). Until it is, B and E answer `not_available` ("Not available yet") and no figure is invented. C needs no new figure and works now.
  - Severity colours now also go to severity series (a severity stack and a bubble's band), not only donuts; status colours still go only to status series.
- **Why:** the captain wanted "nicer charts with a certain level of complexity", from the evidence and the severity, with two y axes. Every figure is still counted from the database and checked against the rows, and the model still only picks the view from the allowlist.
- **Correction to the drafting brief:** `types[]` had no per-type evidence count, and the top-level `evidence` is per kind, not per type. So B could not come from data already returned, and its per-type evidence is part of the migration.
- **Alternatives rejected:**
  - *Offer the three kinds in the picker where they fit:* each view has one kind that fits, so the picker would be refused or ignored for it. Auto-selecting is simpler to explain.
  - *Approximate B from the top-three ranked entities per type:* those are distinct-incident counts, not evidence items, so the figure would be wrong.
  - *Derive E on the client from report payloads:* it would download every counted payload to the browser; the database aggregate returns only the cells.
  - *Send the bubble radius from the model or the console:* the captain's rule is that code scales what is drawn; the agent scales it from the counts it is given.
  - *Changing the RB2 sealed allowlist:* RB2 keeps the allowlist from before these views (`fixtures/chart-allowlist-rb2.json`), so its plan and pinned counts do not change.
- **Amends:** the 2026-11-06 Chart.js decision (the picker's six kinds are unchanged; three view kinds are added, and the rule that severity colours go only to donuts widens to severity series). The 2026-10-31 spec allowlist gains three dimensions and two metrics.
- **Deploy:** (1) the migration is a finals change, applied only with approval; (2) the shared agent must pull and restart `vss-agent` before the stacked bar by severity and the two other kinds draw as Chart.js (until then they draw as a PNG bar picture, not an error).
- **Evaluation (development only):** `all_specs` enumerates 2,050 specs (1,690 ordinary, plus 360 for the three views). The eval replay (`dashboard_figures.py`) and its recount now compute the views and the new fields, and the recount matches the SQL harness on the seeded snapshots. Dashboard figures were also replayed through the console's own code in Node. No live model run.
- **Links:** [`chart-spec.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-spec.ts), [`generate-chart`](../incident-console-v2/src/modules/dashboard/application/generate-chart/index.ts), [`chart-kinds.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-kinds.ts), [`chart-palette.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-palette.ts), [`chartjs_config.py`](../../../../../services/agent/src/vss_agents/tools/chartjs_config.py), [`20261107110000_dashboard_chart_evidence.sql`](../supabase/migrations/20261107110000_dashboard_chart_evidence.sql), [console reference](console-reference.md#dashboard-analytics-and-cross-filtering), [vm-api-contracts.md](vm-api-contracts.md#post-apiv1incidentschart-requests), [data.md](data.md#get_incident_dashboard).

### 2026-11-07: The report chat redraws an existing item through the box tool, and the reviewer's redraw is a proposal
- **Decision:** when the reviewer asks the report chat to re-track an item or set its image, `report_editor` calls `propose_open_box_tool` with that item's draft key alone. The agent checks the key against the draft, and the item must have a seen second; the box tool opens on the item at that second, in re-track mode (switching to Edit when asked in View). The reviewer's redraw is a `retrack` proposal (a track) or a `set_image` proposal (a still box) beside the item, confirmed through the existing Confirm, Adjust and Save block. Cancel changes nothing. Each shows as a "Redraw" row under "What I did". The agent never draws or locates a box, and takes no second or name from the model. An item the draft does not have is refused with the fixed prefix, so the chat shows it instead of falling through to the report Q&A.
- **Why:** the reviewer draws every box, so a box is seen before it is cut. Taking the second from the item means the model cannot invent one.
- **Alternatives rejected:** the agent locating the box itself (a detector guess applied unseen); opening new evidence with a name at the item's second (the item is not new evidence, and the add path would make a duplicate); applying the redraw straight into the draft (an unseen box could be saved).
- **Amends:** the refusal below no longer covers re-track or set image; only unsupported incident types are refused.
- **Links:** [console-reference](console-reference.md#report-chat), [vm-api-contracts](vm-api-contracts.md#post-apiv1incidentsvideo_idinvestigate), [`evidence_asks.py`](../../../../services/agent/src/vss_agents/utils/evidence_asks.py), `ReportEditPane.tsx`.

### 2026-11-07: New evidence is asked and opened by the report editor's tools
- **Superseded in part (2026-11-09, see above):** the question step is gone. Everything below about `propose_ask_reviewer`, at most two questions and the `evidence` exchange no longer applies; the box tool rules still do.
- **Decision:** `propose_ask_reviewer` and `propose_open_box_tool` are `report_editor` tools (`tools/incident_editor.py`), checked by `utils/evidence_asks.py` against the incident window, the questions asked and the run's earlier calls: at most two questions, no question after the box tool, and one box tool opening inside the incident. The console sends the open exchange with each question (`evidence`: `questions_asked` and the transcript, `lib/chat/evidence-ask.ts`), and the editor's input carries it. An ask is the chat's reply; an opening sets the page's `evidenceOpening`, switching to Edit when asked in View. Neither is a draft change, and each shows as a "New evidence" row under "What I did". The route `evidence-asks` stays as the same check on its own, and `INCIDENT_EVIDENCE_ASKS_ENABLED` is removed: the features are on, as in #526.
- **Why:** the reviewer asks in the chat, so the editor that reads the answer must be the one that checks the count. The agent loop is stateless between replies, so the count and the exchange come with each request, and the run's own calls are checked from its step log.
- **Alternatives rejected:** a console-side counter with the route alone (the console would repeat the rules, and the editor could not see the exchange); a per-process counter in a registered tool (shared across requests, so it would leak between videos and reviewers); keeping the flag (features are on without one, #526).
- **Links:** [vm-api-contracts](vm-api-contracts.md#post-apiv1incidentsvideo_idinvestigate), [console-reference](console-reference.md#report-chat), [archive](archive/decisions-superseded.md) (the route-only decision this replaces).

### 2026-11-07: The chat report editor refuses evidence manipulations and unsupported incident types with a fixed prefix
- **Decision:** the `report_editor` prompt refuses requests to re-track, change a box, or set an item's image (amended 2026-11-07: those now open the box tool on the item, see the entry above), as well as incident types outside the allowed list (`road accident`, `burglary`, `explosion`, `assault`, `animal attack`), calling no tool and replying with a fixed prefix ("I can't do that in chat:"). The console's chat route returns the editor's reply directly when no tool ran and the answer begins with this prefix (`CHAT_EDITOR_REFUSAL_PREFIX`), while other no-tool replies (such as "This is not an edit.") continue falling through to the standard chat route.
- **Why:** stops the chat editor from improvising evidence changes (such as swapping entity descriptions and names when asked to re-track) or silently substituting invalid incident types (such as mapping "robbery" to Burglary) before dedicated evidence workflows are built.
- **Alternatives rejected:** building the ask flow or re-track within this fix (too large for a single bugfix round; deferred to dedicated task); silently falling through to general QA (causes general QA to try answering evidence edit requests or confusing the reviewer).
- **Links:** [console-reference](console-reference.md#report-chat), `config.yml`, `src/app/api/chat/route.ts`, `src/lib/chat/report-chat.ts`.

### 2026-11-07: Chat steps view ("What I did") renders the tool step log and applied/skipped draft changes under each chat reply
- **Decision:** an expandable "What I did" disclosure is rendered directly under each assistant chat reply whenever steps or draft actions are present. It renders the step log from PR 517's investigator route (`POST /api/v1/incidents/{video_id}/investigate`) showing tools executed in order with status (ok/failed), duration (ms), parameters, and error message, plus changes applied and skipped against the draft (from 1B applier). Gated behind `INCIDENT_CHAT_STEPS_ENABLED`, checked per request in `src/app/api/chat/route.ts` and overridable per request via `x-chat-steps` header or `steps: true`.
- **Why:** reviewers need visible proof of what the tool-calling agent did, which tools were chosen, and which proposed draft actions were applied or skipped. Phoenix traces require administrative access and cannot be inspected inline by reviewers in the console; rendering the step log directly in the conversation provides immediate, verifiable proof.
- **Alternatives rejected:** putting the step log in the chat bubble text (muddies the conversation and disrupts plain reading); separate modal dialog (breaks conversational context); unconditional display (Plan B requires all new features to sit behind off-by-default flags).
- **Links:** [console-reference](console-reference.md#report-chat), `ChatStepsView.tsx`, `chat-steps.ts`, `agent-chat.ts`, `src/app/api/chat/route.ts`.

### 2026-11-07: Documentation corrections for analysis zoom order, Phoenix telemetry claims, video-check route, and deployment container status
- **Decision:** (1) Align `architecture.md` Figure 4 text and diagram with code: the zoomed second look runs before storing (dropping crops called a different object), not after. (2) Correct Phoenix telemetry claims in `architecture.md`: Phoenix traces NAT tool and workflow spans when run via SessionManager, not incident model calls (which are direct remote calls). (3) Add `video-check` route to the agent extension routes table in `architecture.md` and mention it in `status.md`. (4) Correct the stale `.env` budget comment to reflect the 600 s console limit and 540 s agent default. (5) Clarify in `architecture.md`, `status.md`, `incident-operate-vm`, and `decisions.md` that while the launcher does not start stock VIOS/VST (except NvStreamer for tracking), HAProxy, or Redis, leftover containers remain on the VM until deleted.
- **Why:** Scout reports and diagram reviews found these five factual discrepancies between code/runtime state and documentation.
- **Alternatives rejected:** leaving discrepancies in place or deferring them.
- **Links:** [architecture.md](architecture.md), [status.md](status.md), [skills/incident-operate-vm/SKILL.md](../skills/incident-operate-vm/SKILL.md), [figures/figure-4-analysis.drawio.svg](figures/figure-4-analysis.drawio.svg).

### 2026-11-07: An evidence change the chat proposes is held beside the item until the reviewer confirms it
- **Decision:** a re-track or set-image change for an existing item is stored as `proposal` on the draft item, not as `reviewer` or `imagePick`. Confirm runs `retrackDraftItem` or `setImagePick`; Adjust reuses the Edit track or Set image dialog and its Done confirms; `draftProblems` blocks Save while any proposal is open. Behind `INCIDENT_EVIDENCE_PROPOSALS_ENABLED`, read by the report page on each request.
- **Why:** the detector cannot signal doubt (a car was boxed as "person near billboard"), so a box the chat chose must be seen by the reviewer; a rule in `draftProblems` makes "cannot be saved unconfirmed" a code fact. Confirm reusing the hand-edit functions means Save cuts crops exactly as before.
- **Alternatives rejected:** applying the change straight into `reviewer` (an unseen box could be saved); a confirm dialog only (Save would not be blocked); a flag in the agent (the agent only proposes, the console applies).
- **Links:** [console-reference](console-reference.md#report-versions-view-edit-and-history), `evidence-proposals.ts`.

### 2026-11-07: A gap retry in plain code with a video-model check
- **Decision (amended 2026-11-08: the flag is no longer in the code, and the stage is on by default; features are on by default on this branch, #526):** behind `INCIDENT_GAP_RETRY_ENABLED` (off in code, read per request at the time), `CropEvidenceService.process_incident_report` runs `retry_gap_item` for each item the locate step left without a box (not found, a box too small or too large, a detector error), after locate and before tracking so a retried person or object is tracked like the rest. The steps are plain code: the seconds 3 and 4 either side, the item's description as the label, and four overlapping tiles (a too-small box tries tiles first; an error gap gets one same-second retry). It uses only what is left: its own 24-call counter (10 per item) over the shared experiment cap and the stopped-detector breaker, and nothing starts within 90 s of the deadline. A new box is kept only when `DefaultDetector.verify_box` (prompt `zoom/verify-box`) answers a confident yes (0.7) and, for an instrument or asset, names the same kind of thing (`refines_name`); at most two checks per item. Anything else leaves the original gap text. Without a second-look client nothing runs. The entry gets `box_source: "gap-retry"`; the console ignores unknown values.
- **Why:** an item with no box has no crop, no track and no searchable image. The scout run on six items cost 52 calls and 126.5 s in plain code against 63 model calls plus 37 tool calls and 202.4 s for a tool-calling agent, with the same outcomes. The video-model check is there because a detector given a second chance will box something: one retry boxed the wrong object (E1) and only a look at the box catches that.
- **Alternatives rejected:** a tool-calling agent for the retry (dearer, slower and its path is harder to cap); accepting any box that passes the size rule (false boxes); changing the gap text of a failed retry (hides why the first try failed); a new provenance stage (detector retries count under `grounding`, checks under `zoom`).
- **Needs:** a restart of the shared agent on port 8000 (Firstmate restarts it after merge); nothing is live until then. New analyses only; stored reports are not changed.
- **Links:** `utils/crop_evidence.py` (`retry_gap_item`, `locate_in_tiles`), [analysis-schema](analysis-schema.md), [prompt registry](../contracts/prompts/README.md).

### 2026-11-07: Fixed edit and clip request test set and offline scorer under services/agent/tests
- **Decision:** Plan B Phase 1 Item 1D provides the canonical 20-case test set (`cases.json`) and an offline scorer (`scorer.py`, `cases.py`) under `services/agent/tests/edit_test_set/`, unit-tested by `services/agent/tests/unit_test/test_edit_test_set.py`.
- **Why:** enables offline verification of tool selection, arguments, and refusal behavior for both investigator (clip QA) and editor (report edits) agents without calling hosted models or spending model tokens.
- **Alternatives rejected:** placing under `eval/` (forbidden by Plan B worker rules); using live LLM judges (slow, expensive, non-deterministic; rule-based matching with numeric tolerances and regexes gives immediate, repeatable evaluation).
- **Links:** `services/agent/tests/edit_test_set/`, `services/agent/tests/unit_test/test_edit_test_set.py`.

### 2026-11-07: The investigator is the toolkit's `tool_calling_agent`, run through `SessionManager`, with limits added around it
- **Decision:** `investigator` is a `tool_calling_agent` under `functions:` in the agent config, with its tools in `tool_names`. The route runs it through `FastApiFrontEndPluginWorker._create_session_manager` and wraps the run in `utils/agent_loop.py`: a step log written by the tools, a 5-step budget, a 90 s wall clock, and detection of the toolkit's give-up string (`cap_reached`). The model-call timeout (30 s) and retries (2) sit on the `investigator_llm` entry. The video id is bound by the route in a per-request context, not filled in by the model. A tool error that is not a `ValueError` stops the run. The route is behind `INCIDENT_INVESTIGATE_ENABLED`, checked per request.
- **Why:** `SessionManager` is the only path that writes Phoenix tool spans (measured: spans appear in the project). The agent returns one string and no steps, and at its iteration cap it returns a normal-looking sentence and runs one tool more, so the route has to log steps itself and detect the cap. The toolkit defaults (10 retries, no timeout) would let one slow model call run past the wall clock.
- **Alternatives rejected:** a hand-written loop (duplicates the toolkit and loses its spans); the stock top agent's tool list (video search tools, not this task); letting the model pass `video_id` (it could read another video).
- **Links:** [vm-api-contracts](vm-api-contracts.md#post-apiv1incidentsvideo_idinvestigate), `agent_loop.py`, `incident_investigate.py`.

### 2026-11-07: Every Dashboard chart enters with the same timing, by CSS where Recharts does not draw it
- **Decision:** the treemap, waffle, icon array, risk ladder, heatmap and Total bar use `.chart-enter` / `.chart-grow` (transform and opacity, staggered by `--enter-delay`) with `useChartEntrance`, which gives 1500 ms on first data and 400 ms after a data change and replays by keying on an epoch. Off under `prefers-reduced-motion`.
- **Why:** only the Recharts bars and donut animated; the captain asked for all charts. Recharts' treemap animation does not suit the custom cell, and `backwards` fill keeps hover transforms working.
- **Alternatives rejected:** a motion library (new dependency); animating width or layout properties (reflow).
- **Links:** [console-reference](console-reference.md), `Dashboard.tsx`, `styles.css`.

### 2026-11-07: The report controls live in the shared app header, which centres the nav
- **Decision:** the app header is a `1fr auto 1fr` grid, so the pill nav is centred on every page. The report page portals its controls into two header slots (left of the brand, far right) and has no toolbar row. State and handlers stay in `ReportPage`; the View / Edit `Tabs` markup is unchanged from main.
- **Why:** the captain wanted one navbar row with the nav truly centred; a portal keeps behaviour with the page that owns it.
- **Alternatives rejected:** lifting report state into a layout context (more moving parts); a second header component for reports (two navs to keep in step).
- **Links:** [console-reference](console-reference.md), `AppHeader.tsx`, `ReportPage.tsx`.

### 2026-11-07: Dashboard charts draw slowly once, then quickly on a filter change
- **Decision:** 1500 ms (`CHART_ANIMATION_MS`) the first time a chart has data, 400 ms (`CHART_FILTER_ANIMATION_MS`) when a filter changes its data; reduced motion stays off.
- **Why:** the slow draw is a pleasant first impression but made every filter click feel laggy.
- **Alternatives rejected:** one shorter duration for both; no animation on filter changes (the change is harder to follow).
- **Links:** [console-reference](console-reference.md#dashboard-analytics-and-cross-filtering), `useChartMotion` in `Dashboard.tsx`.

### 2026-11-07: The Dashboard takes the approved mockup: treemap, donut, waffle, risk ladder and icon array
- **Decision:** built the approved mockup (round 26) into the console with no RPC change: Top assets as a slate treemap, Severity donut with the legend beneath, Evidence by kind as a 10x10 waffle, Entity types as an icon array, Instruments by threat level as a risk ladder, "Total: N" on cards, tilted two-line labels on Incidents by type, the legend in the top row, no Ask button and chips only while filtering. Colours come from the tokens; the asset size scale got its own token, `--color-asset-size`, and threat level uses `levelBand`. The mock's fake data and no-op links were left out.
- **Why:** the captain approved the mockup; the shared tokens keep one meaning per colour.
- **Alternatives rejected:** copying the mockup's hex values (they broke the colour guard); keeping the Ask button (the card is on the same screen at 1440x900).
- **Links:** [console-reference](console-reference.md#dashboard-analytics-and-cross-filtering), `Dashboard.tsx`.

### 2026-11-07: Not yet official is solid grey in charts, a dashed grey pill elsewhere; the Official pill glows
- **Decision:** `--color-not-official` is a plain solid mid grey `#aeb5bb` for every chart bar, heatmap ramp and legend swatch, with no outline. The "No official version" pill and the report notice keep a light grey fill (`--color-not-official-pill` `#e9ece4`) with a dashed outline (`--color-not-official-line` `#7b8794`), as on main. The shared Official pill (`VersionPill`, `.official-glow` in `styles.css`) has a teal halo on a pseudo-element that breathes by opacity over 4 s; under reduced motion the glow stays steady.
- **Why:** the captain asked for grey (replacing pale teal `#8cc5cf`); a dashed outline on chart bars looked busy, so charts "stick to the colour"; the glow makes official obvious.
- **Alternatives rejected:** pale teal (too close to official teal); dashed chart bars (tried, removed on the captain's word); animating box-shadow (repaints; opacity is composited).
- **Links:** [console-reference](console-reference.md#colour), `styles.css`, `version-pill.tsx`.

### 2026-11-07: Colour meanings are tokens in styles.css, with one band mapping for severity and threat
- **Decision:** version model/human/official, not yet official (`#8cc5cf`, replacing the orange in charts, legends and split bars), the severity bands and card hover are semantic CSS variables in `styles.css` with a comment table. One helper (`levelBand`) maps 5 and 4 to high, 3 to medium, 2 and 1 to low for severity and threat; severity pills derive tint and border from the band token with `color-mix`. The official star in History uses the official token. A test fails if a meaning hex appears outside `styles.css` and the two canvas mirrors. Severity 4 is now the high band (it was a separate orange).
- **Why:** the same meaning had several hexes across pages; the Dashboard redesign will use this one set.
- **Alternatives rejected:** a generated tokens file (more machinery than one CSS file and a test); recolouring the destructive orange and amber notices (they carry no one of these meanings).
- **Links:** [console-reference](console-reference.md#colour-meanings), `tests/colour-tokens.test.mjs`.

### 2026-11-07: Reviewers cannot save an unknown entity
- **Decision:** the edit row dropdown offers only Human and Animal, the box tool's add dialog asks for Human or Animal, and an entity still `unknown` (an older version) must be set before Save. `validateStructuredEdit` refuses an entity of type `unknown` (422), so no human version holds one. Stored older reports still display and filter as they were.
- **Why:** a reviewer always knows whether an entity is a person or an animal; no AI version has ever produced `unknown` (0 of 942).
- **Alternatives rejected:** removing `unknown` from the contract enum, schema or prompt (shared with eval; no contract bump for a reviewer-side rule).
- **Links:** `src/modules/contract/domain/structured-edit.ts`, `src/modules/reports/domain/edit-draft.ts`.

### 2026-11-07: The Library header is the app nav plus Chrome-style tabs and one filter row
- **Decision:** the approved Library header redesign, console only (no database change). The shared app header is a white bar with a bottom border and the three links in one rounded pill track (shadcn `NavigationMenu`; the current page is a solid dark-green pill); it serves Analyze, Library, Dashboard and the report pages. The Library drops its title, "Incident console" label, info icon and Analyze button (Analyze stays one click away in the nav). Find incidents and Find evidence are real shadcn `Tabs`, centred in a full-width strip, drawn Chrome-style (selected tab on the page colour with curved feet, 150 ms colour transition, none under reduced motion). The search field and every filter sit on one row on both tabs (`InputGroup` for the search; Find evidence has the kind as a joined `ToggleGroup`); there is no Search button, Enter submits. A set filter is drawn in the theme green. Chips and "Clear all" appear only when a filter is set, and the search-order note only while searching. Cards are unchanged.
- **Why:** the header and controls took 309 px above the first card; it is now about 153 px at 1440x900 (mockup 154 px).
- **Alternatives rejected:** keeping the Search button (Enter is enough); a sticky filter bar in the Library (the cards are sized to the viewport, so the page does not scroll at desktop).
- **Links:** [console-reference](console-reference.md#console-pages), `AppHeader.tsx`, `LibraryScreen.tsx`, `EvidenceTab.tsx`, `components/ui/input-group.tsx` (added from shadcn).

### 2026-11-07: The Dashboard is one sticky filter bar over a tight 12-column grid
- **Decision:** the approved redesign: one sticky bar (period presets with a new 90d, Custom, Status, Severity, Type, Ask for a chart) with removable chips, the explanation and card subtitles as tooltips, the legend once, a floating Reset in a reserved right rail, and the Activity card's own toggle removed because Status replaces it. Status sends the existing `scope`, Type the existing `type`; the route accepts `days=90`. No asset, instrument or entity filter, no RPC change, no migration (the captain does not want RPC filters).
- **Why:** the header and per-card text took 249 px before the first chart and the filters were scattered; the mockup's measured height was about 890 px against 2335 px.
- **Alternatives rejected:** a More menu with asset, instrument and entity filters (needs RPC parameters); keeping the Activity toggle beside Status (two controls for one thing).
- **Links:** [console-reference](console-reference.md#dashboard-analytics-and-cross-filtering).

### 2026-11-07: Chat answers people, place and moments from the whole report, never picks a role, and a failed model is not an error
- **Decision:**
  - Code reads `incident.location`, a time in the question, and the people the report's text describes, not only its typed items. An entity of type `unknown` is a person when its label or description says so.
  - Nobody is called the attacker or the victim unless the report's wording does. Names, injuries and causes work the same way.
  - In routed mode a failed chat model gives a `200`: what the report settles, or a request to try again. Motives, disputes and video requests always get the request.
  - The routed prompt changes, and allows partial answers. Grounded mode's prompt and contract stay as evaluated. Template stays the default.
- **Why:** on 7 Nov the running agent answered "who are involved" with "This report records no people" and "where the incident take place" with a theft reply, both on version 151. The first was two people of type `unknown`; the second was "take" matching the theft words, with no location branch at all, though all 256 stored revisions hold a location. Model failures reached the panel as raw JSON.
- **Alternatives rejected:** *making routed the default* (the next restart would turn on model calls for everyone before the frozen re-run; the owner chose to keep the setting); *counting people found in text* ("a man ... the man" cannot be counted); *a code check of location against description* (it flagged 40 of 256 stored revisions, and the flags read were all false); *general typo correction* (14 false fixes on frozen questions); *the composed answer on every model failure* (it can state something false).
- **Limits:** until routed mode is enabled, live answers come from rules, so unexpected wording may still miss. The 6 Nov pilot's figures describe the earlier prompt.
- **Needs:** a restart of the shared agent and the console. Existing reports do not change.
- **Links:** [routes, failures and results](mvp2/chat-routing.md), [`chat_questions.py`](../../../../../services/agent/src/vss_agents/utils/chat_questions.py), [`chat_followups.py`](../../../../../services/agent/src/vss_agents/utils/chat_followups.py)

### 2026-11-07: A calendar range that ends after today is charted up to today, and titled "(to date)"
- **Decision:** a chart's calendar period (`{"month"}`, or `{"from", "to"}`) that starts on or before today in the viewer's time zone but ends after it is accepted and clamped to end today. Its title and scope say so: both name the days charted, "Reports per day, 1 to 7 November 2026 (to date)" for a running month and "Reports per day, 1 October to 7 November 2026 (to date)" for a range, so the last day charted is always visible; a completed month keeps its name ("October 2026"). A period that starts after today (for example "next month") is still refused, and so is a `{"day"}` after today. The real-date, `from <= to` and 366-day rules are unchanged, and the 366-day limit is measured on the days charted (up to today). The prompt tells the model to write the end the request names, and that in a range given without years the start is the most recent such date not after today and the end is in the start's year, or in the following year when the end's month comes before the start's month, so "December to February" on 7 November 2026 is 2025-12-01 to 2026-02-28, "October to December" on 6 November 2026 is 2026-10-01 to 2026-12-31 and a reversed range such as "20 to 10 October" stays reversed and is refused (a rule that put the end on the first such date on or after the start would turn it into 2026-10-20 to 2027-10-10 and chart it). The development requests gain "October to December" and "next month" and move to `dashboard-calendar-development-v1` (eleven requests). Figures still come only from `getDashboard`, and the spec keeps no new field.
- **Why:** the captain asked for "evidences collected from october to december" on 6 November and got "Can't chart that", because the range ran past today. The captain chose this fix on 2026-11-07 among the options offered (the separate "evidence by kind" fix was not chosen).
- **Alternatives rejected:** *refusing* any range past today (the captain's case stays unanswered); *a new `toDate` field in the spec* (the allowlist and golden would change for one flag that the title already carries); *clamping a range that starts in the future* (it would chart a period with no days in it).
- **Amends:** the 2026-11-06 calendar-period decision, where "a day or range that reaches past today is refused" no longer holds for ranges. A day after today is still refused.
- **Evaluation:** `dashboard_calendar.py` mirrors the clamp; its tests and development requests changed with it (no live run).
- **Links:** [`chart-period.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-period.ts), [`chart-prompt.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-prompt.ts), [`generate-chart/index.ts`](../incident-console-v2/src/modules/dashboard/application/generate-chart/index.ts)

### 2026-11-07: Every model the Brev endpoint serves is in the allowlist
- **Decision:** `contracts/inference.json` (and the agent's vendored copy) lists all 10 models of the endpoint, with readable labels; the models not expected to take video say "(text only)". The list is static, not fetched live. No contract version change.
- **Why:** the captain asked for the Re-analyse dialog and the upload dropdown to show every endpoint model.
- **Probed 2026-11-07** (one 64x64 image, 16 tokens, per model, through the gateway; no video, no analysis): `cosmos-3-auto` answered (takes images). `nemotron-3-nano-30b-a3b`, `nemotron-3-super-120b-a12b` and `nemotron-3.5-lightning-30b-a3b` were refused as not multimodal. `nemotron-3-ultra`, `nemotron-3-ultra-nvfp4` and `nemotron-3-auto` returned 400 "an internal error occurred" (the reason is not stated), so they are labelled text only as agreed; `nemotron-3-auto` gained that label. Retest if the endpoint changes.
- **Needs:** the agent restarted to see its copy. `eval/tests/test_contract_fixtures.py` compares this list to `eval_vlm_client.MODELS`, so it fails until eval (off limits here) adds them.

### 2026-11-07: Version type is a coloured pill, one shared component
- **Decision:** `VersionPill` shows a version's type everywhere: Model slate blue, Human plum, official teal #0B7A8F with a star (green looked like the Generate and Reset buttons) and the text "Official · Type". Colours are `--color-version-*` theme tokens.
- **Why:** type and official status were separate badges in different places; the captain chose colour by type with the text kept as a label.
- **Alternatives rejected:** colour only (not accessible); changing Dashboard chart or severity colours (out of scope).

### 2026-11-07: The Library is always ordered official first, then oldest upload first
- **Decision:** the Find incidents list has no sort control. The console always asks for `p_sort = 'official-first'`: official reports first, then the rest, each by `videos.uploaded_datetime` oldest first, with the old tie-break (newest report time, revision id), sorted in the RPC so it holds across pages (migration `20261107100000_library_official_first_sort.sql`; the older sort values stay for other callers). With search text the existing ranking (both matches, then words only, then meaning only) is kept; words-only matches follow the new order.
- **Why:** the captain asked for one fixed order that puts official reports first.
- **Needs:** the migration applied to finals; before that the RPC falls back to newest first.

### 2026-11-07: Total reports counts every version, split AI and human
- **Decision:** the Total reports card shows the number of all versions (every `report_revisions` row of the counted reports' videos) as its big number, split AI against human, with a small line for the incident count (one per video). It no longer splits official against not yet official, and the "Multiple versions" stat is gone from the card. The RPC gains `versions` (migration `20261107090000_dashboard_all_versions.sql`); every other field is unchanged because evaluation reads them.
- **Why:** the card counted one revision per video, so a video with an AI and two human versions showed 1. The captain wanted all versions and the AI and human mix.
- **Alternatives rejected:** reusing `revisions` (it counts only the one revision per video that `total` counts); changing `total` (the other displays and evaluation count incidents).
- **Needs:** the migration applied to finals; until then the card shows the incident count alone.
- **Links:** [`Dashboard.tsx`](../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx)

### 2026-11-07: The stream check reads the nested get-stream-info by this run's sensor id, and an animal is never time-matched to a person track
- **Decision:** (1) `PerceptionClient.has_stream(sensor_id)` replaces `stream_count()`. It reads `stream-info.stream-info[].camera_id` (the live reply is `{"stream-info":{"stream-count":1,"stream-info":[{"camera_id":...,"source_id":4}]}}`); a missing key, an empty list or an unreadable reply reads as gone. `_stream_alive` asks for this run's own id, so a quiet-start clip now waits to its length plus `INCIDENT_TRACKING_END_MARGIN_SECONDS` instead of giving up at 40 s. (2) An entity whose `item_name` is `animal` is never given to a person track by seconds alone (`match_by_time`); box overlap still applies, and an animal left without a track gets `track_gap` "person tracking does not follow animals". `human` and `unknown` entities are unchanged.
- **Why:** the old read of top-level `stream-count` was always 0 on the VM, so the 3 Nov wait never held and a clip with no object for 40 s lost its people. A count would not do now either: a dead registration (`incident-5131dd96-m5786bf85c5ac7d3096c`) stays listed on the VM, so only this run's id tells that its stream is alive. Animals went to the person tracker and, with no match, were told a person-worded reason.
- **Alternatives rejected:** a count above 0 (the dead registration keeps it above 0); sending only `human` entities to tracking (an upright black bear, `vafbef7916847d4c97c7`, has a trace that looks right from a Person-labelled track).
- **Needs:** a restart of the shared agent on port 8000. Existing reports do not change.
- **Links:** [`perception_client.py`](../../../../../services/agent/src/vss_agents/utils/perception_client.py), [`track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py)

### 2026-11-07: The evidence detector, zoom and object tracker run on Nano, not on `VLM_NAME`
- **Decision:** `DefaultDetector` uses `DEFAULT_GROUNDING_MODEL`, now `nvidia/cosmos-3-nano-reasoner`, unless its constructor names a model. It no longer reads `VLM_NAME`, which stays Super for search and the chat's video check. Captions and the main call already use the job's model. There is no fallback model. New analyses only.
- **Why:** on 7 Nov Super stalled the detector: 2 of 10 calls answered (36 s and 46 s; the agent's request limit is 20 s), with 5 timeouts at 60 s and 3 `429`s. Stored runs show the stage going from 18 s for 7 calls on 3 Nov to 242 s for 3 calls on 6 Nov. Of the 27 items without a trace on reports since 5 Nov, 23 were never reached before the old 240 s limit. Nano returned a box on 27 of 28 stored frames, median 1.3 s.
- **Known cost:** Nano missed the 80% target: its box overlapped Super's stored box (IoU of 0.5 or more) on 18 of 28 frames (64%). A frame review put about 22 of 28 on the labelled thing, and 6 on the wrong one (cash register, SUV, backpack, hatchback, two people). The comparison is about 30 frames, not a full evaluation.
- **Not fixed by this:** items with an image but no trace, mainly person tracking returning no frames or no tracks, or its tracks not matching the person.
- **Alternatives rejected:** changing `VLM_NAME` on the VM (also moves search and the chat's video check); Omni as a backup (12 of 28 overlapped, with 5 empty replies); keeping Super.
- **Needs:** a restart of the shared agent on port 8000.
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py)

### 2026-11-07: An analysis may take 10 minutes: the console waits 600 s, the agent spends at most 540 s, and a report is never written after the console gives up
- **Decision:** (1) In agent mode the console limit is `DEFAULT_AGENT_ANALYSIS_TIMEOUT_SECONDS = 600` (`run-contract-analysis.ts`; `INCIDENT_ANALYSIS_TIMEOUT_SECONDS` overrides it, optional, no `.env.local` change). Gateway mode and `eval/` keep `model.timeout_seconds` from `contracts/inference.json` (300 s; the file and the contract version do not change). (2) `DEFAULT_ANALYSIS_BUDGET_SECONDS` in the agent goes from 240 to 540 (`INCIDENT_ANALYSIS_BUDGET_SECONDS` still overrides it), leaving 60 s for the main call's last moments, the save and the response. (3) Once the budget is spent the evidence stages are skipped at once with the existing gap wording (`analysis time budget exhausted`) and the report is saved; person tracking is not started with 30 s or less left and its wait for tracks ends at the deadline. (4) A main call still running at 600 s fails the run as before, and the console now says so plainly ("the model's main call was still running, so no report was saved"). (5) The agent call uses `node:http`, not fetch. (6) `POST /analyze` watches `request.receive()` for the hang-up instead of polling `request.is_disconnected()`.
- **Why:** on 7 Nov 00:43 SGT `Assault012` on the Super model spent 256 s on the main call, which used up the 240 s budget before evidence began, and the console gave up at 300 s about 2 s before the agent finished; the retry took 393 s and failed the same way. Node's fetch (undici) also abandons a response with no headers after 300 s whatever the abort signal says (checked: `UND_ERR_HEADERS_TIMEOUT` at 301.1 s), and the agent sends nothing until it has saved, so a 600 s limit needed `node:http` (checked: a silent server answered after 330 s). The job loop needs no change: the heartbeat is every 15 s on its own timer and a job is stale only after 180 s without one.
- **Correction to PR 503 (cancel on abort):** it said the agent stops when the console aborts and writes no report. On the real server it did not: NAT installs a `BaseHTTPMiddleware` on its app, and behind it `request.is_disconnected()` (which cancels its own `receive()` before it can yield) never turns true. Job 59 (9-clip live test): abort 16:48:38 UTC, revision 155 saved 16:48:40; retry abort 16:53:42, revision 156 saved 16:56:02; no cancel line and no 499 in the agent log. A watcher task awaiting `request.receive()` until `http.disconnect` works with and without the middleware. A regression test starts a real uvicorn server (with and without such a middleware) and hangs up a raw socket; it also pins that the old poll fails behind the middleware.
- **Alternatives rejected:** raising only the console limit (the 240 s budget would still be spent by a slow main call, and the evidence then stalls); a 540 s budget with no skip (a long main call plus 300 s of evidence would pass 600 s); an undici dispatcher for fetch (needs a new dependency whose version must match Node's bundled undici); moving the timeout into `contracts/inference.json` (eval reads it and the contract version would change).
- **Not tested live:** the shared agent and the SSH tunnel were off limits for this change. The disconnect was reproduced on a local uvicorn server with the same package versions (a disconnect is cancelled 3.0 s after the hang-up); the budget is covered by unit tests with a fake clock (a 256 s main call under the old 240 s limit and a 545 s call at the new budget both save with gaps). The first real check is the next live analysis after both restarts.
- **Needs:** a restart of the shared agent on port 8000 (Firstmate does it after the running test) and a restart of the console (the new limit, `node:http` and the 660 s `maxDuration` load at start). Nothing is live until both.
- **Links:** [`incident_report_gen.py`](../../../../../services/agent/src/vss_agents/tools/incident_report_gen.py), [`run_cancel.py`](../../../../../services/agent/src/vss_agents/utils/run_cancel.py), [`run-contract-analysis.ts`](../incident-console-v2/src/modules/analysis/application/run-contract-analysis.ts), [`incident-agent.ts`](../incident-console-v2/src/modules/analysis/infrastructure/agent/incident-agent.ts), [vm-api-contracts](vm-api-contracts.md), [console reference](console-reference.md)

### 2026-11-06: The report title is a reviewer-editable field
- **Decision:** `title` joins the edit's incident fields (`EDITABLE_INCIDENT_FIELDS`), required and not blank. Save stores it on the new human revision's `payload.incident.title`. The report page and the version compare read the version's own title (`structured.incident.title`, through `reportHeading`); before this they read `modelOutput.title`, from the run notes, so a stored change would not have shown. Severity rationale and location stay read-only. No contract version changes: the report schema already has `incident.title`, and only the edit's allowed fields grow.
- **Why:** captain, 6 Nov: a reviewer could correct every report field except the headline.
- **Who reads it:** the library card, incident search text and the Find incidents summary vector (`revision_summary_text`, and `summaryEmbedding` on Save when the video has no official version) already read `payload.incident.title`, so they follow the saved version. The model's title stays in `model_runs.notes`, earlier revisions keep theirs, and View names the model's beside a reviewer's. The library card and the search vector show the video's searchable version (official, else newest), so a saved title reaches them only when that version is it.
- **Limits:** the chat reads a saved version's stored title, but a draft sent to the chat (`draftReport`) carries no title, so the chat does not see an unsaved one. An older report with no title at all has to be given one before its next Save.
- **Alternatives rejected:** a separate reviewer-title column (every reader would need to choose between two); an optional title in the edit (an omitted title could not be told from a blanked one).
- **Links:** [`structured-edit.ts`](../incident-console-v2/src/modules/contract/domain/structured-edit.ts), [`edit-draft.ts`](../incident-console-v2/src/modules/reports/domain/edit-draft.ts), [`report-view.ts`](../incident-console-v2/src/modules/reports/domain/report-view.ts), [`ReportEditPane.tsx`](../incident-console-v2/src/sections/reports/components/ReportEditPane/ReportEditPane.tsx)

### 2026-11-06: The report video shows the Edit draft before Save, and an untracked item's box for 2 s in playback
- **Decision:** in Edit mode `TrackOverlay` draws the draft (`draftOverlay`), not the opened version: unchanged items through their source id, re-tracked and added items from samples held in the browser, deleted items not at all (Undo brings them back), and the item whose Edit track dialog is open hidden until Done. In View and Edit an untracked item's stored box shows dashed amber from 0.25 s before its second to 2 s after it, during playback as well as paused; overlapping boxes are all drawn, with the selected card's emphasised. Every card's box carries the item's name and its video colour (`STILL_BOX_COLOUR` for an untracked item).
- **Why:** captain, 6 Nov: track and box changes should show on the video at once, and an untracked item should be visible in playback. The 2 s, the deletion, the dialog and the card colour are the captain's answers to the plan's open choices. A stored box is a pin-point, so it stays short rather than pretending to follow.
- **Timeline:** in Edit mode the Timeline panel draws the same draft from the same source (`draftToStructured` with `draftOverlay`'s frames), so it and the video cannot disagree; it now returns to the saved version whenever the mode is View, even while a draft is kept. Lanes keep their kind colours, in the order Save stores.
- **Colours:** draft items take colours by position in the order Save stores them, so draft and saved colours agree. A new item joins the end of its kind, so items before it keep their colours; a new tracked entity or instrument shifts the tracked items of later kinds, because they will have those colours once saved.
- **Alternatives rejected:** a box until the next item's box, or for the item's whole span (a still box would sit still while the person moves); a faint ghost for a deleted item (the draft is what Save stores); green card boxes (card and video would disagree); keeping the draft's colours fixed after a new item (they would change at Save instead).
- **Supersedes:** the hold rule in "An untracked item holds its stored box on the paused player" below; Play from here still seeks and pauses, but the box now follows the 2 s window.
- **Links:** [`track.ts`](../incident-console-v2/src/modules/reports/domain/track.ts), [`TrackOverlay.tsx`](../incident-console-v2/src/sections/reports/components/TrackOverlay/TrackOverlay.tsx), [`ReportPage.tsx`](../incident-console-v2/src/sections/reports/components/ReportPage/ReportPage.tsx), [`EvidenceFrame.tsx`](../incident-console-v2/src/sections/evidence/components/EvidenceFrame/EvidenceFrame.tsx)


### 2026-11-06: A tracked item's image is always the first frame of its track unless a reviewer set one; small crops get context; the agent waits out 429s on its other calls and stops when the console aborts
- **Decision:** (1) a reviewer's own image (Set image, `image_pick`) wins; otherwise an item with a track always shows the first frame of that track (`track_evidence.first_seen_sample`), whatever its score. Items with no track keep the located second. The agent now closes the paths where a tracked item stayed on another image: a re-cut that fails drops the track with a `track_gap` ("the first frame of the track could not be cut, so the track was not kept") instead of leaving it on another frame. The "first confirmed sample" idea is not built. On Save, a re-track with no reviewer image takes the new track's first frame; an entry whose image a reviewer set carries `image_source: "reviewer"`, and a re-track in a later Save keeps that image, frame, box and second (a pick in the same Save still wins over the re-track's first sample). The console shows a tracked item with no stored image or frame as the frame at the track's first second (`GET /api/reports/[videoId]/frame`), in View, Edit and the detail dialog, instead of "Image unavailable". (2) A crop under 96 px on its short side is cut with a 40% context margin and enlarged to at least 192 px on the short side, by the agent and by Save's cut; `bounding_box` stays the exact box the console draws. (3) The caption pass and the zoomed second look wait out a 429 like the main P1 call (the service's `retry-after`, else a jittered doubling backoff from 5 s capped at 30 s), only when the wait fits the run's deadline (`utils/rate_limit.py`); the 240 s budget and the console's 300 s limit are unchanged. (4) `POST /analyze` stops when its caller disconnects: the route polls `request.is_disconnected()`, cancels the run, and sets a flag every worker thread checks before each hosted call and in each retry wait (`utils/run_cancel.py`); the answer is 499 and no report revision is written.
- **Why:** the audit (2026-11-06) found tracked items whose image sat on another object, 1-px-wide crops, caption and second-look calls that gave up on the first 429, and job 51 spending calls 10 s and 77 s past the console's abort.
- **Limits:** new analyses and new Saves only; nothing is re-analysed and no stored report is rewritten. On abort, work already finished stays: crops uploaded to R2 stay as unreferenced objects (nothing is deleted), the scratch prefix is deleted, no `report_revisions` row is written, and a hosted call already in flight finishes on its own and is dropped. `model_runs.notes` is not touched (the console records its own attempt). Grounding's own retry wait is unchanged (it only checks for the abort). The shared agent needs a restart to run this code.
- **Alternatives rejected:** moving an object's image to its first confirmed sample (the captain wants the first frame of the track, always); keeping a track on a frame it could not be re-cut to (the image would not be the track's first frame); a new endpoint to cancel by run id (the disconnect already says it); killing worker threads (not safe; the flag stops the next call).
- **Links:** [data](data.md), [analysis-schema](analysis-schema.md), [vm-api-contracts](vm-api-contracts.md), [console reference](console-reference.md)

### 2026-11-06: A stalled detector call no longer eats the budget, and a person with no box can still get a track
- **Decision:** (1) The locate step's hosted-detector request times out at **20 s** (`GROUNDING_TIMEOUT_SECONDS`, was 120 s; healthy calls take 2-4 s) and is tried once more on a timeout (`GROUNDING_TIMEOUT_RETRIES`, inside the existing four attempts), and no request waits past the run's deadline (the timeout is clamped to the time left; none left stops the item with `analysis time budget exhausted`). (2) `DetectorBreaker` now **pauses** instead of ending detection for the run: three consecutive errors stop calls for 10 s (`DETECTOR_COOLDOWN_SECONDS`), a call after the pause is a probe, one more error pauses again straight away, a reply resets everything, and the **third pause is a hard stop** (`DETECTOR_MAX_TRIPS`) with `image_gap` `detector stopped after 3 consecutive errors, 3 times`. A dead service therefore costs at most about 140 s of the 240 s budget (3 trips of 20 s x 2 tries, 2 pauses of 10 s, plus the first streak), not all of it. (3) A person the detector gave **no box** (`located` false) is matched to a **solid** person track by the report's `first_seen_seconds` and `last_seen_seconds` (`track_evidence.match_by_time`); the entry gets the track, an image cut from the track's first sample (no hosted call, so it works when the breaker has tripped or the budget stopped the detector) and `box_source: "track-time"`. The zoomed second look still runs on that image and a "different object" verdict drops the match.
- **How "clearly fits" was decided:** score = overlap of the two spans (intersection over union, the entity's end taken as `last_seen_seconds + 1` because the report's seconds are whole). A match needs a score of at least **0.5** and a lead of at least **0.2** over the runner-up; a track that is the clear pick of two or more people goes to **none** of them, and a track already taken by a box match is never offered. Chosen on five revisions' real tracks (Assault001 had 22 solid tracks of 28): the 0.5 floor drops the 0.14 to 0.26 scores of people seen for a few seconds among many tracks, and the 0.2 lead drops IMG_4569 rev 138 E1 (0.55 vs 0.47). Everything unmatched keeps `track_gap` with the reason ("none clearly fits (best 55%, next 47%)", "N people fit the same person track, so it was not given to any").
- **Result:** with every detector call failing (simulated), people with a track went from 0 to 2 (Assault001, rev 145), 0 to 1 (IMG_4569 rev 142) and 0 to 1 (IMG_4569 rev 138). Only people with no box are eligible, so a located person whose box no track overlapped keeps `no person track overlapped this person's box`.
- **Why:** 58 of 94 library evidence items had no moving box; the last 7 analyses tracked 4 of 34 items. One stalled call took about 2 minutes of the 240 s, the breaker counted 3 quick timeouts across concurrent items and ended detection for good, and `associate_tracks` matched on box overlap only, so no box meant no track.
- **Alternatives rejected:** raising the 240 s budget or the console's 300 s limit (hides the stall); a local detector model (out of scope); also matching located people whose box overlapped no track (their box says the detector saw a different person); time matching for instruments and assets (people only).
- **Needs:** a restart of the shared agent on port 8000 (Firstmate restarts it after merge); nothing is live until then. `box_source` is new on the evidence entry and the console reads it (a "Matched by time" badge); no contract version changes.
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [vm-api-contracts](vm-api-contracts.md), [data](data.md), building on [the failing detector and time budget](#2026-11-05-a-detector-stops-after-three-errors-in-a-row-and-an-analysis-has-a-240-s-time-budget).

### 2026-11-06: A repeat upload is blocked by file content, and the reviewer is sent to the existing report
- **Decision:** every video and every queued or running analysis job carries `content_sha256`, the SHA-256 of the file as the reviewer uploaded it, before any conversion. `POST /api/uploads/r2` hashes the file (streamed) before it stores anything and, when a video (or an active job) already has that hash, answers 409 with the existing video. The upload page then shows "This video is already in the library as <name>" with a link to its report, starts nothing, and offers no override; re-analysing stays on that report. A batch with a repeated file queues it once. The database enforces it: a unique partial index on `videos.content_sha256` (settled state) and one on `analysis_jobs.content_sha256` where the job is queued or running (the window before the video row exists, because the video row is created when the job starts). `POST /api/jobs` turns a unique violation into the same 409. A new file with an existing name still gets the `-2` key.
- **Why:** on 6 Nov `Assault018_x264_demo.mp4` was uploaded twice about 1 s apart and two jobs were queued 60 ms apart, so the library held 19 video rows for 15 clips and the reviewer saw one clip under different reports. Two uploads of one file in the same second must end with one video and one job, which only a database rule guarantees.
- **Limits:** a re-encoded copy of the same clip has different bytes and is not caught. A converted upload keeps the hash of the original, but a converted video backfilled from R2 was hashed from its stored (converted) bytes, so a re-upload of the original file is not caught for it. A video whose analysis failed keeps its hash, so a re-upload opens a video that may have no report; retrying a failed job while another active job holds its hash hits the job index. A race loser's `-2` R2 object and thumbnail are left in place, unreferenced: nothing is deleted.
- **Alternatives rejected:** an override ("upload anyway") on the page (the captain wants repeats blocked); comparing file name and size (a renamed copy slips through, a different clip with a colliding name is refused); a perceptual hash (catches re-encodes but is fuzzy, slow and not enforceable by a unique index); a check in the console only (two simultaneous requests both pass it); hashing in the browser (extra work on every file and a client the server must not trust); deleting a race loser's R2 object (a rule that deletes data on a lost race is riskier than an orphan).
- **Links:** [migration](../supabase/migrations/20261106160000_video_content_hash.sql), [backfill](../archived/supabase/r2/backfill_content_hash.py), [`duplicate.ts`](../incident-console-v2/src/modules/uploads/domain/duplicate.ts), [`route.ts`](../incident-console-v2/src/app/api/uploads/r2/route.ts), [data](data.md#videos), [console reference](console-reference.md#background-analysis-jobs)

### 2026-11-06: Clicking an Edit card's image sets that item's evidence image from a picked frame and a mouse crop
- **Decision:** in Edit mode the image area of every evidence card (entity, instrument, asset, with or without an image or box today) is a button, and only the image: a click elsewhere on the card does nothing. It opens `EvidenceImagePicker`: pick a frame of the report's video with the slider or the step buttons (the exact second, to 0.1 s), drag a rectangle on it, check the crop it cuts, **Use this image**. The result is `image_pick: {seconds, box}` on the draft item (`ImagePick`); the card shows the picked frame and box with an "Image set by you" badge and **Revert to A** undoes it. Hover and keyboard focus show "Click to set the image". Nothing else on the item changes: the text, the track and `timestampSeconds` ("most visible at") stay.
- **Save:** `PATCH .../edit` accepts `image_pick` (Ajv `additionalProperties: false`, `seconds >= 0`, a valid box) and `storeReviewerItems` cuts the crop and frame server-side at that second, through the same ffmpeg and R2 path as a reviewer box item (`edit-<N>/<id>.jpg`, `-frame.jpg`). The entry gets `image`, `frame`, `bounding_box`, `box_seconds` = the picked second, `timestamp_seconds` = it rounded, `located: true`, and drops the old crop's detector, zoom and `image_gap` fields (`IMAGE_REPLACED_FIELDS`, the 3 Nov rule). A track file, `track_*` fields, `track_gap` and `base.source` are kept. When the item also has a re-tracked `reviewer` object, the pick wins over the track's first sample for the image only; the track is still stored.
- **Stored facts after Save (checked live on revision 147):** the revision's evidence entry, the item's `evidence_crops` row (image, frame, box, `timestamp_seconds`) and the R2 objects all come from the one cut. The rows exist only when the video has no official revision at save time, or when a revision is marked official, as for any human edit. A tracked entity's evidence slice stays its track span; an instrument, asset or untracked entity uses 3 s either side of `box_seconds`.
- **Why:** an item the detector missed (E2 in revision 142 of `IMG_4569_480-2.mp4`: `located: false`, no image) had no way to get an image except re-tracking, and a tracked item's first-seen image could be the wrong moment. The captain wants to choose the frame and crop by hand, and only from the image itself so the card stays uncluttered.
- **Alternatives rejected:** a button beside **Edit track** on every card (the captain wants the image to be the control); reusing `image_timestamp_seconds` and the upload path (integer seconds only, and the old path drops the frame, `box_seconds`, `located` and track); a browser canvas crop (R2 has no CORS rule, so a signed video taints the canvas); file upload from disk, new tracking or an AI describe call from this control (out of scope).
- **Supersedes in part:** "Replace image and the frame picker are removed from Edit mode" and the "two ways to set an image" rejection in "Edit mode adds and re-tracks evidence with a box tool" (both 3 Nov), amended below. **+ Add evidence** and **Edit track** are unchanged, and a box-tool item still takes its image from its track's first second.
- **Links:** [`EvidenceImagePicker.tsx`](../incident-console-v2/src/sections/evidence/components/EvidenceImagePicker/EvidenceImagePicker.tsx), [`image-pick.ts`](../incident-console-v2/src/lib/evidence/image-pick.ts), [`store-reviewer-items/index.ts`](../incident-console-v2/src/modules/reports/application/store-reviewer-items/index.ts), [console reference](console-reference.md#report-versions-view-edit-and-history)

### 2026-11-06: Dashboard chart requests take calendar periods: a month, a day or a range, read against today in the viewer's time zone
- **Decision:** besides the presets, a chart's `period` takes a calendar period: `{"month": "YYYY-MM"}` (one month), `{"day": "YYYY-MM-DD"}` (one day) or `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}` (both days included). The model picks the period; the console counts it. A reply counts only if every date is real, the period does not start after today in the viewer's time zone, `from` is not after `to`, and a range covers at most 366 days (`CALENDAR_MAX_DAYS`). A month or range that ends after today counts up to today, so "November" on 6 November is 1 to 6 November; a day after today is refused. (The range clause was amended on 2026-11-07, see above.) The presets keep their exact shape, so old answers still parse. The chart covers local midnight of the first day to local midnight after the last, in the viewer's zone, sent as zoneless UTC as the fixed ranges are. Its title names the range ("Reports per day, 1 to 15 October 2026") and its scope the same.
- **Today's date:** the console adds one line to the user message before the request, `Today is 2026-11-06 (time zone Asia/Singapore).`, so "October" resolves to the most recent October that is not in the future. The system prompt stays a fixed contract text. The request still answers to 300 characters, and the line is not counted in it. The agent route passes the messages through unchanged, so the shared agent needs no change.
- **Why:** the captain typed "number of different category of incident throughout october" and got "Can't chart that", because the presets cannot name a month. Asked whether to add custom ranges (and so to update the evaluation set), the captain said yes. The standing rules hold: the model picks only the spec, every figure comes from `getDashboard` for the range, one request makes one chart, and nothing is marked official.
- **Alternatives rejected:**
  - *A from and to pair only:* the model would have to find the last day of a month, which is the mistake the captain would see first.
  - *Clamping a future range to today:* it would change the period the user typed without saying so. Amended 2026-11-07: a range that ends after today is now clamped and titled "(to date)"; one that starts after today is still refused.
  - *Today's date in the system prompt:* the prompt is a hash-pinned contract file, so a date would change it every day.
- **Evaluation (no live run):** `parse_spec` takes the calendar forms against the pinned reference day 2026-11-06 in UTC (`dashboard_calendar.py`). `all_specs` still enumerates only the 1,690 presets. Nine hand-written development requests (`dashboard-calendar-development-v0`; eleven in `-v1` since 2026-11-07, `ai_proposed`, not reviewed, `split: development`) cover a month, a day, a range, the most recent December, a running month and refusals. They are not a held-out set. The request shape `agent-route-v4` carries the date line and is the golden's shape; v1 to v3 are unchanged, so the sealed pilots reproduce. **A capped C1c re-run that measures calendar requests needs the eval owner's approval.** RB2's hints and `references/dry_run.py` still call a named month, a year and a date range unsupported; RB2 is sealed, so they describe the earlier allowlist and must be reworded before any new RB2 run.
- **Deploy:** no migration. The console change ships with the console. The shared agent needs no change or restart for calendar periods.
- **Links:** [`chart-period.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-period.ts), [`chart-spec.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-spec.ts), [`chart-prompt.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-prompt.ts), [`generate-chart`](../incident-console-v2/src/modules/dashboard/application/generate-chart/index.ts), [`dashboard_calendar.py`](../eval/evalv2/references/dashboard_calendar.py), [`requests/chart.py`](../eval/evalv2/requests/chart.py), [console reference](console-reference.md#dashboard-analytics-and-cross-filtering), [vm-api-contracts.md](vm-api-contracts.md#post-apiv1incidentschart-requests), amends [2026-10-31](#2026-10-31-dashboard-chart-requests-a-model-picks-an-allowlisted-spec-our-code-fetches-the-figures-and-vss-chart_generator-draws-them) only by widening `period`.

### 2026-11-06: The default analysis model is Nemotron 3 Nano Omni Reasoning
- **Decision:** the `VLM_MODEL` fallback in `incident-console-v2/src/lib/env.ts` is `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (it was `nvidia/cosmos-3-nano-reasoner`). `/api/models` serves it as `defaultModel`, so the upload page and the Re-analyse card preselect it. The picker still offers all three allowlisted models, audio stays off, and no contract version changes.
- **Why:** the captain asked for the omni reasoning model to be the default for analysis.
- **Note:** an untracked `.env.local` that sets `VLM_MODEL` overrides the code default; it is not edited here and has to be changed (or the line removed) on each machine.
- **Alternatives rejected:** removing the other models from the picker (the captain asked to change the default only).
- **Links:** [`env.ts`](../incident-console-v2/src/lib/env.ts), [`inference.json`](../contracts/inference.json), [console reference](console-reference.md)

### 2026-11-06: Dashboard drops the previous-period comparison, adds an Ask for a chart jump, and restyles the several-versions stat
- **Decision:** the header's "vs. previous period" checkbox and the "+N% vs. previous" line on Total reports are removed, with the console code that only served them (`delta`). In their place is an **Ask for a chart** button that scrolls to the section at the foot of the page and focuses its request box (smooth, instant under reduced motion). The several-versions figure becomes a labelled **Multiple versions** stat (layers icon, neutral tone, hidden when not loaded) below the official split, not a sentence and not coloured like official or not yet official.
- **Amended 2026-11-06 (later):** the stat is replaced by a neutral **N revised** chip (history icon) beside the total, with a tooltip that is also its accessible label, hidden when not loaded or 0; the captain chose it over a two-column split and a share bar, which could confuse readers.
- **Amended 2026-11-06 (later, the captain):** Activity by day and hour takes the wide slot beside Total reports, and **Reports generated over time** is removed from the page (no migration: the RPC keeps its `trend` output and Ask for a chart keeps its trend charts).
- **Why:** the captain found the comparison unwanted and the sentence untidy, and the chart request is the page's main action, so it should be one click from the header.
- **Alternatives rejected:** keeping the comparison behind a toggle (the captain asked for it gone); removing the RPC's `previous` output (the RPC and its output stay untouched, so there is no migration and other callers are unaffected); linking the stat to the Library (it has no version filter).
- **Links:** [`Dashboard.tsx`](../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx), [`ChartRequest.tsx`](../incident-console-v2/src/sections/dashboard/components/ChartRequest/ChartRequest.tsx), [console reference](console-reference.md#dashboard-analytics-and-cross-filtering), amending [2026-11-06 calendar range](#2026-11-06-dashboard-calendar-range-several-versions-line-and-evidence-displays-the-trend-is-titled-by-report-time) for the line and the comparison.

### 2026-11-06: Dashboard calendar range, several-versions line and evidence displays; the trend is titled by report time
- **Decision:** the fixed displays take a calendar range as well as the presets: **Choose dates** opens a shadcn `Calendar` in a `Popover` (range mode, days after today disabled, Apply commits, Cancel keeps the period), sent as zoneless UTC from local midnight of the first day to local midnight after the last. A third row of three displays shows the evidence (**Evidence by kind**, **Top instruments**, **Entity types**), each split by official. The RPC (migration `20261106140000_dashboard_versions_and_evidence.sql`, applied to finals on 2026-11-06) adds `multipleVersions`, `evidence` (items per kind, split) and the split on `entityTypes` and `topInstruments`; the bar axes get headroom so a total label is not clipped; the top-instrument panel shows five rows. The trend is titled **Reports generated over time** and still counts each report by its own time (the official revision's, else the newest's), as before; the title and the count were the captain's choice on 2026-11-06.
- **Several versions:** Total reports gains a line, "N with more than one version": the counted reports whose video has more than one `report_revisions` row (AI and human alike), following the same period and filters. It is not a third part of the split and is not linked, because the Library has no version filter. It was held on 2026-11-06 and put back on the captain's word on 2026-11-07. The six videos with a duplicated AI revision 2 ([status, known issue 11](status.md#5-action-items)) count as multiple versions.
- **Why:** the captain wants any period picked on the fixed charts, and evidence diagrams filling the row of three where the panels left whitespace. The RPC returned no item totals per kind (its ranked lists are top-N), so the evidence figures need the migration.
- **Alternatives rejected:** keeping the period in the URL (the dashboard never kept its period there, and the Library links already carry the window); a second RPC for evidence (one snapshot keeps every figure on one count); a free-text date field (the captain asked for a calendar).
- **Dependencies:** `react-day-picker` (the engine under the shadcn `Calendar`) is the only new package. The shadcn CLI also added `date-fns`; nothing imports it, so it was removed.
- **Links:** [`Dashboard.tsx`](../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx), [`charts.ts`](../incident-console-v2/src/modules/dashboard/domain/charts.ts), [`calendar.tsx`](../incident-console-v2/src/components/ui/calendar.tsx), [`route.ts`](../incident-console-v2/src/app/api/dashboard/route.ts), [migration](../supabase/migrations/20261106140000_dashboard_versions_and_evidence.sql), [console reference](console-reference.md#dashboard-analytics-and-cross-filtering).

### 2026-11-06: A time in a routed answer must belong to the event beside it, and code adds missing ones
- **Decision:** `utils/chat_attribution.py` ties each written time to the timeline event its clause describes; one that does not fit stays plain text, and the wording is never changed. Code adds an event's time to a clause that plainly describes that event and gives none. Items only denied in an answer get no card.
- **Why:** the check only asked whether a second was in the report, so "exploding at 1:31", the end of an event starting at 1:12, became a link to the wrong moment. Omitting a jump is safer than a wrong one.
- **Rejected:** rewriting the model's times (changes its wording, and "by 0:03" has no safe rewrite); event markers in the model's output (needs a new prompt and paid checks, and still needs this check for a model that ignores them).
- **Limit:** matching is on words, so paraphrase loses a link, and one time string is unlinked everywhere in an answer if any use of it fails.
- **Links:** [`chat_attribution.py`](../../../../../services/agent/src/vss_agents/utils/chat_attribution.py), [routes](mvp2/chat-routing.md)

### 2026-11-06: Chat routes by question behind `INCIDENT_CHAT_MODE=routed`, and a video check needs a click
- **Status:** built and off. The default stays template. The text-model pilot ran on 6 Nov ([results](mvp2/chat-routing.md#text-model-pilot-2026-11-06-paid-owner-approved)); turning either setting on still needs approval ([plan](mvp2/chat-routing.md#before-switching-on)).
- **Decision:**
  - A third mode, `routed`, answers report-field questions by code with no model call and sends the rest to the chat model, which reads the report only ([routes](mvp2/chat-routing.md#routes)).
  - It has its own prompt (`chat/incident-routed`) and contract (`chat-contract-v3`), so template stays v1 and grounded stays exactly as evaluated.
  - A video check is offered, never automatic, and sits behind `INCIDENT_VIDEO_CHECK_ENABLED`. The look is blind to the report, a text call compares the two, and nothing is stored.
- **Why:** template mode answers reasoning and follow-up questions badly ("Why was this classified as high severity?" gave "It is an assault."), while grounded mode spends a model call on what code answers as well. On the frozen C3 questions code matched the model on the questions routed to it, the model won every unanswerable and false-premise question, and routing keeps that for about a quarter of the tokens ([results](mvp2/chat-routing.md#evaluation-2026-11-06-no-model-calls)).
- **Rejected:** editing `chat/incident-answer` (it would separate grounded mode from its results); showing the VLM the report's claim (the 2026-11-01 finding: the model agrees with a name it is shown); running a check automatically on a missing detail (slow, paid and unasked); saving a look's result (a schema decision, and not needed to review a conflict).
- **Links:** [`chat_routing.py`](../../../../../services/agent/src/vss_agents/utils/chat_routing.py), [`video_check.py`](../../../../../services/agent/src/vss_agents/utils/video_check.py), [`chat-contract-v3`](../contracts/chat-contract-v3/README.md)

### 2026-11-06: A template chat answer cites the items its report text names, matched by id or by name
- **Decision:** a chronology, a description fallback and a taking cite the items their report text refers to, each once, in order of first mention. An id in the text counts. Otherwise an item counts when its name or label stands whole in the text (articles and plurals aside), or when a person's or animal's head word does ("the dog") and no other entity shares it. The longest phrase wins a stretch of text. Items tied on it are one object if they share a name and label, else the text does not say which it means and none is cited. Descriptions are not matched. With nothing named there are no citations. A card keeps its stored second, and an item with none gets no card.
- **Why:** the fallback cited every person when the text held no ids. 54 of 57 stored events hold none, so an animal attack with a dog and three assets had no cards, while other reports listed bystanders the events never mention, and objects were never cited. On the 16 default-opened reports on 6 Nov the rule cites what each timeline names: the dog, coffee table and vase but not the sofa, and not rev 129's pedestrian.
- **Rejected:** word overlap (the first version's "on ground", from "backpack on ground", matched "remains on the ground"); matching descriptions (they mention neighbouring things); a model call to choose cards (not worth a call, and grounded mode stays off).
- **Known limit:** text that names an item differently gets no card: "the vehicle" for a car, or "the man" with two men in the report. A one-word name can also match the same word used another way.
- **Links:** [`report_answers.py`](../../../../../services/agent/src/vss_agents/utils/report_answers.py)

### 2026-11-06: The report chat offers one suggested question, Show the timeline of events
- **Decision:** the panel keeps PR 491's single suggestion and its header, and the owner chose the wording **Show the timeline of events**. Who, what was taken and weapons are still answered when typed.
- **Why:** PR 491 cut the list to one and recorded that in the docs, so the panel stays short. It kept the old text, "What happened, in order?", without a stated reason. The new wording says what the answer is: a timed list. Typing the old question still gives the same answer.
- **Rejected:** the four chips first built for this work (they would have undone PR 491).
- **Links:** [`ReportChat.tsx`](../incident-console-v2/src/sections/reports/components/ReportChat/ReportChat.tsx)

### 2026-11-06: Template chat answers the official version from its report, and citations use the crop's second
- **Status:** approved by the owner on 2026-11-06. Replaces [2026-10-24](archive/decisions-superseded.md#2026-10-24-chat-about-the-official-version-uses-the-in-memory-chat-search-client-for-mvp2-superseded-2026-11-06) for template mode; grounded mode already answered it. Grounded mode stays off.
- **Decision:** in template mode the official version is answered from its own report, like any other version, so the search client no longer takes part in a question that names a version. A template citation seeks to the evidence entry's `box_seconds`, else its `timestamp_seconds`, else the item's second.
- **Why:** marking a report official replaced its chat answers with "This chat mode doesn't answer questions about the official version yet". No video had an official version on 6 Nov (0 of 15), so nobody had met it, but the first star would have. For the second: the evidence card and grounded mode use `box_seconds`, and the two differ by 1 s or more on 29 of 66 evidence entries, so a card could jump away from the moment its image shows.
- **Rejected:** keeping the official version on the search client (it finds nothing for a finals video); turning on grounded mode to fix this (not validated against template mode yet).
- **Links:** [`incident_chat.py`](../../../../../services/agent/src/vss_agents/api/incident_chat.py), [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentschat)

### 2026-11-06: The report chat panel is not modal and its conversation lives on the report page
- **Decision:** the report page's chat panel (since 2026-11-08 docked, see that entry) is non-modal, has no overlay and stays open when the page behind it is used; only its close button, Escape or the toggle closes it. Each version's conversation (and its draft's) is held by `ReportPage`, so closing the panel keeps it; a new Edit draft starts a new conversation. `seek` uses the player on screen, which below the `lg` breakpoint is the compact one. The library chat sheet is unchanged.
- **Why:** checked in a browser on 6 Nov against the VM agent. While the panel was open the overlay took the clicks and the player was `aria-hidden`, so a jump could not be paused or scrubbed. Closing the panel to watch unmounted the chat and lost the conversation. Below `lg`, seeks went to the hidden player, so a jump did nothing visible.
- **Amends:** [2026-11-03](#2026-11-03-every-console-video-is-silent-play-clip-is-removed-and-the-chat-sheet-does-not-blur-the-page), where the shared overlay "still dims the page": that now applies to the library chat only.
- **Rejected:** closing the panel on every jump (loses the place in a long answer); keeping the panel mounted while closed (a hidden sheet in the page's focus order).
- **Links:** [`ReportPage.tsx`](../incident-console-v2/src/sections/reports/components/ReportPage/ReportPage.tsx), [`ReportChat.tsx`](../incident-console-v2/src/sections/reports/components/ReportChat/ReportChat.tsx)

### 2026-11-06: The chat keeps the report timeline and relevant uncertainties, and the report page stays without them
- **Status:** an exception to [2026-10-28: The report timeline is being removed](#2026-10-28-the-report-timeline-is-being-removed), approved by the owner on 2026-11-06 for the chatbot work, and by the captain the same day, whose 28 Oct direction it changes. The captain's approval, which also covers merging PRs 492 and 494, was given outside GitHub and passed on by the owner, so neither PR holds a review or comment from the captain. [2026-11-01](#2026-11-01-the-console-no-longer-shows-the-model-event-timeline-or-the-model-reported-uncertainties) stands: nothing returns to the report page.
- **Decision:**
  - `timeline` stays in `incident-contract-v4` as the chat's source for a what-happened answer, and is not restored to the report UI.
  - Uncertainties reach a chat answer only in a chronology, and only those that relate to the events shown.
  - Removing `timeline` from the contract (action item 5) is on hold, and would first need another source for the chronology.
- **Why:** the timeline is the only ordered, timed account of an incident the system stores. Without it a what-happened answer falls back to one description paragraph. Audit on 6 Nov of the 15 reports the library opens by default: all 15 have a timeline, with 2 to 7 events each.
- **The 28 Oct concern still applies:** the timeline is unscored and can disagree with the incident window (6 of 57 events fell outside it). Such an event may be real lead-up or aftermath, so the answer labels it as context around the incident rather than dropping it or treating it as wrong.
- **Rejected:** deleting the timeline as planned (the chat loses its chronology); restoring it to the report page (the 1 Nov decision stands); building a chronology from first-seen and last-seen times (they place items, not events).
- **Links:** [`report_answers.py`](../../../../../services/agent/src/vss_agents/utils/report_answers.py), [`status.md`](status.md#5-action-items).

### 2026-11-06: Dashboard charts are Chart.js configurations that VSS `chart_generator` builds, and the browser draws them
- **Decision:** `chart_generator` returns a Chart.js configuration (`type`, `data`, `options`) as plain JSON for each `"output": "chartjs"` item, with the figures the console sent placed exactly as sent and no callbacks. The PNG output stays as the fallback. The console draws the configuration with `chart.js` 4 and `react-chartjs-2` 5 in a client component, loaded only when a chart comes back. The user picks one of six kinds: bar, stacked bar (official and not yet official in one bar, for dimensions with the split), horizontal bar, donut (for dimensions that are a whole, in place of the pie), and line or area (for day, week and month trends). No heatmap. The model is unchanged: it still picks only the dimension, period and filters.
- **Figures:** the console checks every label and figure in the returned configuration against the rows it computed (`configMatchesChart`). A mismatch is a 502 and is never shown. The Table tab lists the same rows.
- **Colours:** one palette in `src/lib/ui/chart-colors.ts`. Official and not yet official equal the `--chart-1` and `--chart-3` tokens (a test keeps them equal). Every colour passes 3:1 against white. `--chart-2` (`#76b900`, 2.41:1) and `--chart-4` (`#f59e0b`, 2.15:1) are not used for data. Status colours go only to status series and severity colours only to severity donuts, so no chart mixes the two sets. **Not changed:** the severity "low" fill (`#174f3b`) is the same green as official. Across the page's separate charts the two still coincide; recolouring severity low would break the badge match of 2026-11-01, so it is left for the captain.
- **Why:** a PNG cannot be read, hovered, resized or themed. Drawing in the browser gives tooltips, the console's own tokens and responsive sizing, and the captain asked that VSS still build the chart. Here VSS reads the request and builds the chart description; the browser shows it.
- **Alternatives rejected:**
  - *The console builds the chart itself:* VSS would drop out of the chart path, which the captain ruled out.
  - *Recharts (already in the console) as the drawer:* the agent would have to name React components; a plain JSON configuration is simpler to check.
  - *Vega-Lite:* about 297 KB gzipped against about 67 KB for Chart.js, measured on a minimal chart; its specs would need validating before use.
  - *A heatmap kind:* not required; the dashboard keeps its own heatmap.
- **Amends:** the 2026-10-31 decision (`chart_generator` now returns a configuration, with the PNG as fallback; bar or pie becomes the six kinds). The route in the 2026-11-02 decision now also takes Chart.js items. `pie` is still accepted and read as donut.
- **Deploy:** the shared agent must pull this change and restart `vss-agent` before charts are drawn in the browser. Until then chart requests still answer with the PNG chart, not an error: when the agent cannot supply a configuration (it answers `422`, `404` or `501` for the Chart.js item, as the old agent does with `422`, or `200` with `chart_config: null`), the console asks it for the PNG instead. Any other failure (a `5xx`, a timeout, figures that do not match) is still an error.
- **Links:** [`chart-renderer.ts`](../incident-console-v2/src/modules/dashboard/infrastructure/agent/chart-renderer.ts), [`chartjs_config.py`](../../../../../services/agent/src/vss_agents/tools/chartjs_config.py), [`chart-config.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-config.ts), [`chart-colors.ts`](../incident-console-v2/src/lib/ui/chart-colors.ts), [vm-api-contracts.md](vm-api-contracts.md#post-apiv1incidentscharts).

### 2026-11-06: The P1 call streams its reply and waits out HTTP 429 inside the existing worker
- **Decision:** `run_p1` sends `stream: true` with `stream_options: {include_usage: true}` (without it the service sends no token counts) for the main analysis call (the contract's request builder still says `stream: false`, which eval and the golden fixtures use) and joins the server-sent events into the same `content`, `finish_reason` and `usage` the validator reads; a plain JSON answer is still read as before. A stream that drops, carries an error event or ends with no finish reason is a failed attempt (`P1StreamError`, not retried). `run_p1_with_retry` waits and calls again after an HTTP 429 (`retry-after`, else 5 s doubling to 30 s with jitter), at most 4 calls, and only when the wait plus 60 s of call fits the analysis deadline (`P1_RATE_LIMIT_*` in `incident_report_gen.py`); other 4xx and 5xx errors are not retried, and the runaway retry is unchanged. Each wait is one log line. The logic lives in the existing agent call path, with no new worker or queue.
- **Why:** the dog-yard clip failed on 5 Nov with `Priority-based rate limit exceeded` (429) and with HTTP 524, which Cloudflare returns when the service sends no byte for 125 s; a streamed reply keeps bytes flowing, and a wait inside the 240 s budget cannot push an analysis past the console's 300 s limit. It adds no capacity.
- **Checked live (2026-11-06, on the VM, a scratch script on the hosted model, 3 calls, no analysis):** the service streams with `response_format`; a normal call finished `stop` in 8.5 s with usage, a 300-token cap finished `length` in 6.8 s; no 429 came back, so the wait itself is covered by unit tests only.
- **Rejected:** retrying inside the console (a second worker for the same call); waiting past the budget; retrying a dropped stream (the partial text cannot be reused and the budget is short); changing the caption and zoom calls here (follow-up).
- **Follow-up:** the same 429 wait for the caption pass and the zoomed second look.
- **Links:** [`incident_report_gen.py`](../../../../../services/agent/src/vss_agents/tools/incident_report_gen.py), [`test_p1_retry_stream.py`](../../../../../services/agent/tests/unit_test/tools/test_p1_retry_stream.py)

### 2026-11-06: Evidence making - wrong renames are blocked, a detector error keeps the frame, implausible boxes show the frame, twins share one image
- **Decision:** (1) The second look renames an instrument or asset only when the new name refines the old (one name's words inside the other's, or both in one label group in `_NAME_GROUPS`) and is English; otherwise the report's name and description stay and `zoom_gap` is "looks like a different object". (2) `crop_evidence_item` catches a detector error per attempt, tries the remaining seconds and returns the frame already read as a `located=false` result with a gap; a stopped detector (`DetectorStoppedError`: the breaker or the 240 s deadline) ends the tries at once. (3) An instrument or asset box over 50% or under 0.3% of the frame counts as a miss, and a crop the second look calls a different object is dropped before it is stored: the item shows the frame with an `image_gap`. People are unchanged. (4) Items in one report with box IoU above 0.8 at the same second share one stored image and frame (first item's keys), each keeping its own entry; an instrument is never merged with its holder.
- **Why:** the audit of 18 analyses found "cash register" renamed "high heel shoe", a club renamed "handgun" and "elevator interior" boxed at 100% and renamed "cabinet"; a single detector error returned no frame at all; rev 131 stored three identical crops. The docs also overstated three things (the track score is a flag, optional stages can leave gaps, the zoom pass renames only on a refinement); they are corrected.
- **Rejected:** asking the model to judge the rename again (another call on a rate-limited service); a new report field for sharing (the keys already say it); merging by name (names differ for the same box); checking people's boxes by area (people legitimately fill frames).
- **Limit:** "aisle display rack" to "toy display" passes only because both are in the display group; the groups are small and deliberate, so a good rename outside them is missed rather than a wrong one let through. Existing reports are not re-analysed.
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [architecture](architecture.md), [data](data.md)

### 2026-11-06: Find incidents matches words and meaning, the summary text leads with the incident type, and the floor is 0.25
- **Decision:** (1) The summary vector embeds "type: title", a newline, then the description, built in one place (`revision_summary_text`) for AI versions, human saves and the repair step. (2) Every Find incidents text search runs the plain word match and the meaning match and merges them: both (best meaning score first), then word-only (sort order), then meaning-only (best score first). Word-only ranks above meaning-only because a word match is exact. (3) `REVISION_MIN_SIMILARITY` is 0.25. (4) `refresh_revision_embedding` may replace a stored vector on the searchable version, behind its own transaction-local flag; nothing else in a revision can change. (5) The 13 searchable versions were re-embedded once.
- **Why:** "burglary" scored 0.203 against a burglary report, under any sensible floor, because the type was not in the text. After the re-embed it scores 0.463. Scores over 18 searches (top hit per query, before to after): burglary 0.203 to 0.463; robbery at a shop 0.351 to 0.455; explosion 0.378 to 0.400; dog attack 0.403 to 0.431; bear attack 0.279 to 0.444; fight between two people 0.448 to 0.461; man with a knife 0.298 to 0.284; theft from a counter 0.298 to 0.401. Unrelated queries after: helicopter 0.144, birthday cake 0.137, spaceship landing 0.172, weather forecast 0.109. The weakest true match is 0.284 and the strongest nonsense 0.172, so 0.25 keeps every true match and drops all the nonsense; 0.35 had cut "man with a knife".
- **Rejected:** a floor above 0.28 (drops true matches); a new column or table for the type text; meaning-only search (misses exact words); re-embedding through the hosted model service (rate limited).
- **Links:** migration `20261106120000_refresh_revision_embedding.sql`, [`route.ts`](../incident-console-v2/src/app/api/reports/route.ts), [`incident_db.py`](../../../../../services/agent/src/vss_agents/utils/incident_db.py), [`refresh_revision_embeddings.py`](../scripts/refresh_revision_embeddings.py).

### 2026-11-06: One searchable version per incident, human versions get a vector, and the repair runs by itself
- **Decision:** (1) `search_report_revisions` matches only `r.id = searchable_revision_id(r.video_id)`, so a video returns at most one hit and marking official, clearing it and saving a new version each leave exactly one version searchable for both searches (`search_evidence_items` already filtered the same way); the id is derived, never stored. (2) A human Save stores a summary vector (the console asks the agent's new `revision-embedding` route, same text and model as AI versions); a failed embedding saves with NULL. `report_revisions_append_only()` gets a second narrow exception (`app.revision_embedding`: `embedding` only, NULL to a value, as `app.r2_rename` does for evidence). (3) The repair of missing crops and vectors runs in the console's job loop (start, every 2 minutes, after each job), bounded to 5 versions per kind per pass, using `repair_revision_crops` (insert-only, searchable version only) so several consoles can run it; failures cool down 10 minutes. (4) An instrument or asset slice always contains its box second (item 137 A1: box at 0.07 s, confirmed from 2.4 s).
- **Why:** older versions of a video kept appearing beside the current one; a human version had no vector so it dropped out of text search; job 51's agent saved its revision 77 s after the console gave up, leaving a video with no crops until someone called the route.
- **Rejected:** a stored "searchable" flag or column (a copy to keep in step); a new table; embedding calls to the hosted model service (rate limited); a scheduler outside the console (one more thing to run).
- **Limit:** the automatic repair runs only while a console with the job loop is up.
- **Links:** migration `20261106090000_one_searchable_version.sql`, [`data.md`](data.md), [`console-reference.md`](console-reference.md), [`repair.ts`](../incident-console-v2/src/lib/jobs/repair.ts).

### 2026-11-05: A detector stops after three errors in a row, and an analysis has a 240 s time budget
- **Decision:** object tracking and the evidence locate step each count detector errors (HTTP error or timeout) in a run and stop calling the detector after three in a row (a reply resets the count); tracking carries on with tracker-only samples and logs one line, the locate step leaves the remaining items an `image_gap`. A production `incident_report_gen` also records a start time and a budget (`INCIDENT_ANALYSIS_BUDGET_SECONDS`, default 240 s). Past it, items not yet located get `image_gap`, an unchecked second look gets `zoom_gap` (both `analysis time budget exhausted`), and object tracking is skipped or capped to the time left minus 30 s. `timeout_seconds` in `contracts/inference.json` stays 300, and the report contract and schema do not change. Experiments have no budget.
- **Why:** job 51 (Animal013, 5 Nov) ran 312 s and 383 s inside the agent because the hosted model service answered this key with 429s or stalls and nothing summed the per-stage timeouts (grounding 120 s, tracking 15 s a call with a 120 s cap, second look 60 s). The console had given up at 300 s, so the run failed `AGENT_TIMEOUT` while the agent kept working. The scout report measured tracking at 103 s and 55 s of pure detector failure.
- **Amended 2026-11-07:** the budget is now 540 s and the console waits 600 s (see [the 7 Nov decision](#2026-11-07-an-analysis-may-take-10-minutes-the-console-waits-600-s-the-agent-spends-at-most-540-s-and-a-report-is-never-written-after-the-console-gives-up)); the rejection of raising the limit below no longer holds, because a slow main call, not a stalled stage, is what used the old budget (Assault012: 256 s). The stall defences (three errors in a row, 20 s detector timeout) stay.
- **Rejected:** raising the console timeout (hides the failure, a throttled run would take 5-7 minutes); a new "degraded" field (the existing gap wording is already read by the console); cancelling the stages mid-call (a thread cannot be cancelled, so the wait is abandoned and the call ends on its own timeout).
- **Follow-up (not done):** cancel the agent request when the console aborts, so no work or tokens are spent after the abort (status action item 18). Raising the key's priority on the hosted service is an account matter outside this repository.
- **Links:** [`object_tracking.py`](../../../../../services/agent/src/vss_agents/utils/object_tracking.py), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`incident_report_gen.py`](../../../../../services/agent/src/vss_agents/tools/incident_report_gen.py), [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-11-05: Evidence search keeps the exact second, adds a 0.35 score floor and plays a slice
- **Decision:** (1) `evidence_crops.timestamp_seconds` is `NUMERIC(8,3)` and the agent, contract and console pass it as a number, so a hit at 15.333 s links to 15.333 s (`?t=`), not 15. (2) The console's text search sends `min_similarity` 0.35, one named constant (`MIN_SIMILARITY`, `lib/search/min-similarity.ts`, no environment override); a listing (empty query) sends 0. When nothing passes, the tab says "No evidence found" and names the floor. (3) Each crop stores a slice (`slice_start_seconds`, `slice_end_seconds`): first to last seen where the entity has a track, else the box second plus or minus 3 s (instruments and assets follow the object rule in the paragraph "Object slices and Find incidents" below). A hit has a "Play slice" button that plays that range of the existing video through a media fragment (`#t=start,end`); no clip file is made. (4) Each crop stores `frame`, the R2 key of the whole frame with the box, and the search card shows it; a row without one falls back to the frame cut from the video. (5) `list_revisions_missing_crops` and `POST /api/videos/repair-crops` find and refill videos whose searchable revision has no crop rows; two videos (Assault036, vafbef7916847d4c97c7) were in that state and were repaired on 5 Nov. Unofficial versions keep their searchable crops.
- **Why:** the audit (15.33 became 18, 2.27 became 22 in the link and the cut frame) showed the integer second moved hits off their moment; two videos were absent from search; weak matches filled the grid. Measured on finals with the floor at 0.35: the five check queries scored 0.356 to 0.591 at the top, "people fighting" found nothing at or above 0.35 and shows "No evidence found", and "a dog on a leash" kept one hit at 0.356. Only a hit under 0.35 is dropped.
- **Object slices and Find incidents (same day):** (a) an instrument or asset slice is no longer the tracker's whole window (seed plus or minus 12 s; only 8.7% of object samples are detector-confirmed, audit `vss-evidence-making-audit` finding 3). It runs from the first to the last confirmed sample of its track (`score` above 0); a confirmed span under 2 s is widened to 2 s around its middle; with no confirmed sample, or no track, it is the box second plus or minus 3 s. People keep first to last seen. The track file is read from R2 on save, mark official and repair (`application/confirmed-spans`, `lib/r2/stored-json.ts`); an unreadable track gives the box-second fallback and never stops a save. The stored image (re-cut rule) is not changed, so an object's frame can sit outside its slice. The video length is not known to those callers, so only the start is clamped (at 0). 25 of 32 existing instrument and asset rows were rewritten by `scripts/backfill_object_slices.py`. (b) The Find incidents text search sends `min_similarity` 0.35 (`REVISION_MIN_SIMILARITY`, a separate named setting because report scores compare the query with title and description) and lists cards in the agent's match order, a video ranked by its best revision; paging follows that order. Without text the sort applies. During a text search the sort control stays but does not apply (a note says so). When the agent returns nothing (including everything under the floor) or fails, the console falls back to the plain ILIKE match, as before; a nonsense search such as "helicopter" then shows the ILIKE result, normally none.
- **Rejected:** a 0.7 floor (it would hide every hit seen in the sample, whose best score was 0.593); clip files for slices (the removed Play clip feature, 3 Nov, wrote and orphaned files; a time range of the stored video needs none); cutting the thumbnail at request time (slow and wrong second on the old agent); raising the floor through an environment variable (a second place to drift).
- **Card name (same day):** `evidence_crops.item_name` holds the report item's `label` (fallback: name, then type), so a card is titled "black bear" or "cash register" instead of "animal" or "high heel shoe". Chosen over changing the report format or prompt (rejected by the captain): the label is already in every revision's `evidence`, so only the crop writer and a one-off row rewrite (54 of 62 rows, no re-embedding) change.
- **Links:** [`data.md`](data.md#evidence_crops), [`console-reference.md`](console-reference.md), migration `20261105090000_evidence_crop_seconds_slices_frames.sql`, [`repair-missing-crops`](../incident-console-v2/src/modules/reports/application/repair-missing-crops/index.ts)

### 2026-11-05: The Videos surface and analysis-history UI are removed completely
- **Decision:** Remove the report-card **History** action, the `/videos/[videoId]` route, `VideoHistoryScreen`, `RunHistoryList` and its browser hook. Re-analysis stays in the report page's `ReanalysisDialog`. `POST /api/videos/[videoId]/runs` remains because it is the re-analysis command endpoint; its GET response and server-side history model remain available to tests and integrations but have no console page.
- **Why:** the Library and each report's version graph are the console's incident navigation. A separate video-history page duplicated those surfaces and contradicted the earlier removal of the Videos page.
- **Alternatives rejected:** retaining a hidden deep link (still a supported page); redirecting `/videos/[id]` to a report (there may be no chosen report revision, and the link is no longer emitted); deleting the entire runs route (would remove report-page re-analysis).
- **Links:** [`IncidentCard.tsx`](../incident-console-v2/src/sections/library/components/IncidentCard/IncidentCard.tsx), [`ReportPage.tsx`](../incident-console-v2/src/sections/reports/components/ReportPage/ReportPage.tsx), [`console-reference.md`](console-reference.md).

### 2026-11-03: Architecture documentation follows C4 and arc42 views in NVIDIA's blueprint style and carries no deployment values
- **Decision:** `.docs/architecture.md` is an explanation page in arc42's section order (introduction and goals, constraints, context and scope, solution strategy, building block view, runtime view, deployment view, crosscutting concepts, decisions, quality requirements, risks and technical debt, glossary) with C4 context, container, component and deployment views drawn as draw.io figures (`.drawio.svg` files in `.docs/figures/`, which GitHub renders as images), and with NVIDIA's names for the stock components. It describes roles and interactions only: no ports, hosts, addresses, user or machine names, GPU indices, paths, bucket names, private URLs, secrets or environment-file references; those stay in [`incident-profile-operations.md`](incident-profile-operations.md), the skills, [`vm-api-contracts.md`](vm-api-contracts.md) and [`status.md`](status.md). Page-level console behaviour, routes and configuration moved unchanged to [`console-reference.md`](console-reference.md) under their old headings, so existing links still resolve. A stock-versus-added table, derived from the git history since the profile's first commit, records the boundary with the upstream blueprint.
- **Why:** the previous page mixed four kinds of documentation (architecture, console reference, deployment values, procedures), repeated values the runbook and the skills already hold, and had no explicit boundary, constraints or quality scenarios. NVIDIA's own VSS pages keep architecture sections free of deployment values and list ports in a separate section.
- **Rejected:** Mermaid for the architecture figures (its C4 syntax has unfinished legends and links, and its layout cannot be controlled; draw.io figures render as plain images on GitHub); one page per view (more files to keep current than one architecture page plus one reference page); keeping the console behaviour inside the architecture page (reference material that changes with every UI change and buried the architecture).
- **Links:** [`architecture.md`](architecture.md), [`console-reference.md`](console-reference.md); the research record with its sources is kept outside the repository.

### 2026-11-03: Edit track is a keyframe editor; Done densifies, and a track has no gaps
- **Decision:** an Edit mode card has **Edit track** (`TrackEditor`): the saved AI track (read from its track route) is thinned to keyframes (Ramer-Douglas-Peucker, tolerance 8 on the 0-1000 grid), the reviewer moves, adds and deletes keyframes on a frame and timeline, and drags start and stop grips. Between keyframes the box slides in a straight line. **Done** re-expands to 4 samples per second with the exact start and stop (cap 2000) and goes through `retrackDraftItem` as a reviewer track, so Save, the viewer and the `-track.json` file are unchanged. Pure model: `modules/reports/domain/track-editor.ts`. A saved gap loads as continuous, and there is no cut, remove or restore stretch (dropped by the captain in board round 4).
- **Why:** the viewer and the stored file take dense samples, and a reviewer edits intent, not samples; one start and one stop is all the viewer and Save need.
- **Rejected:** editing the dense samples directly (hundreds of handles); a removed-stretch model (dropped by the captain); a canvas stand-in for the video (the frame uses the real clip).
- **Links:** [`track-editor.ts`](../incident-console-v2/src/modules/reports/domain/track-editor.ts), [`TrackEditor.tsx`](../incident-console-v2/src/sections/evidence/components/TrackEditor/TrackEditor.tsx)

### 2026-11-03: A replaced reviewer image drops the old crop's detector and second-look fields; the edit preview uses the exact second
- **Decision:** `storeReviewerItems` no longer carries `detected_box`, `zoom_checked`, `zoom_confidence`, `zoom_seen`, `zoom_gap`, `name_before` or `description_before` from the source entry onto the entry of an item whose image Save replaced (added to `REPLACED_FIELDS` beside `image_gap` and the track fields). `videoFrameUrl` sends the second with up to three decimals instead of rounding to a whole second; the frame route and ffmpeg already accept decimals.
- **Why:** the old fields described a crop that is no longer the entry's image, and Save cuts the crop and frame at the first sample's exact second, so a rounded preview could show a different frame from the one stored.
- **Rejected:** keeping `name_before`/`description_before` (they record a correction of the old crop's name; the payload keeps the corrected name, the history belongs to the old revision).
- **Links:** [`store-reviewer-items/index.ts`](../incident-console-v2/src/modules/reports/application/store-reviewer-items/index.ts), [`evidence-view.ts`](../incident-console-v2/src/lib/evidence/evidence-view.ts)

### 2026-11-03: An untracked item holds its stored box on the paused player
- **Superseded in part (2026-11-06):** the box now shows for 2 s from its second, also during playback and in Edit mode, not only until the user plays. See "The report video shows the Edit draft before Save" above.
- **Decision:** the View-mode overlay (`TrackOverlay`) also draws a still box. In the evidence pop-up, Play from here on an item with no track, a located box and a `box_seconds` seeks to `box_seconds`, pauses the video and holds the item's `bounding_box` (dashed amber, labelled) until the user plays or the playhead leaves that second by more than 0.25 s. An item with a track still seeks and plays.
- **Why:** only tracked items had an overlay, so seeking from an untracked card showed a bare frame (the `evidence-box-findings` note). The box exists, so it is shown where it is true: at the frame it was found in.
- **Rejected:** playing from the second with the box (it would sit still while the person moves, which reads as a bad track); a synthetic one-sample track (needs the 0.5 s tolerance, so the box would vanish after half a second).
- **Links:** [`TrackOverlay.tsx`](../incident-console-v2/src/sections/reports/components/TrackOverlay/TrackOverlay.tsx), [`track.ts`](../incident-console-v2/src/modules/reports/domain/track.ts)

### 2026-11-03: A person left without a track records why (`track_gap`)
- **Decision:** when person tracking was requested, each person (entity) entry without a track gets `track_gap`: the run's `tracking.skipped` reason, else `no person track overlapped this person's box`, else `this person was not located, so no track could be matched`. The console reads it as `ItemEvidence.trackGap` and prints a quiet "Not tracked: <reason>" line on the card and the pop-up. A reviewer Save that replaces an item's image clears it (`REPLACED_FIELDS`).
- **Why:** an untracked person was indistinguishable from "tracking off" or a tracker miss; the scout reports needed the run notes to tell. Mirrors `image_gap`.
- **Rejected:** a badge (louder than a missing track deserves); deriving the reason in the console from run notes (the notes are per run, the entry is per item).
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`evidence-detail.ts`](../incident-console-v2/src/modules/reports/domain/evidence-detail.ts)

### 2026-11-03: Person tracking waits for a quiet-start clip while its stream is registered
- **Decision:** `run_tracking` no longer gives up 40 s after the stream add when no frames have appeared. At that point it reads `get-stream-info` (`stream_count`); a stream still registered keeps the run waiting up to the existing deadline (clip duration plus `INCIDENT_TRACKING_END_MARGIN_SECONDS`), and a count of 0 or an unreadable count skips as before (`no frames from perception`). The frame-poll failure log is now a warning.
- **Why:** perception publishes only frames with an object, so a clip whose first person appears late is silent for a long time; the 40 s exit made every person in such a clip untracked (the `vss-tracker-miss` scout report).
- **Rejected:** raising the timeout to the deadline for every run (a dead stream would hold the run to the deadline); a longer fixed timeout (still a guess).
- **Follow-up (7 Nov 2026):** the check never worked on the VM, because it read `stream-count` at the top level and the live reply nests it; see [the 7 Nov entry](#2026-11-07-the-stream-check-reads-the-nested-get-stream-info-by-this-runs-sensor-id-and-an-animal-is-never-time-matched-to-a-person-track). It now looks for this run's sensor id.
- **Links:** [`track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [`test_track_evidence.py`](../../../../../services/agent/tests/unit_test/utils/test_track_evidence.py)

### 2026-11-03: Every console video is silent, Play clip is removed and the chat sheet does not blur the page
- **Decision:** every `<video>` in `incident-console-v2` is a `MutedVideo` (`src/components/muted-video.tsx`): muted, volume 0, re-muted on `volumechange` and `loadedmetadata`, with the native mute and volume controls hidden in `styles.css`. The detail pop-up's **Play clip** and everything only it used are removed: `POST /api/reports/[videoId]/evidence-clip`, `get-evidence-clip`, `evidence-clip.ts`, `ffmpeg-clip.ts`, the R2 clip store, `ItemEvidence.clipUrl` and `tests/evidence-clip.test.mjs`. **Play from here** stays. The shared sheet overlay (`components/ui/sheet.tsx`, used only by the "Ask about this incident" and library chat panels) drops `backdrop-blur`; it still dims the page.
- **Why:** the captain asked (3 Nov 2026, minor fixes for the finals demo) that sound never plays, that the ask panel never blurs the background, and that Play clip goes entirely.
- **Rejected:** only `muted` on each element (a user could unmute it from the native controls); a custom player (a larger change for no gain); keeping the clip route unused (dead code and an ffmpeg cut path nobody calls).
- **Existing data:** clips already cached in R2 stay until the orphan sweep or the video's delete removes them; nothing reads them.
- **Links:** [`muted-video.tsx`](../incident-console-v2/src/components/muted-video.tsx), [`sheet.tsx`](../incident-console-v2/src/components/ui/sheet.tsx), [`muted-video.test.mjs`](../incident-console-v2/tests/muted-video.test.mjs)

### 2026-11-03: Evaluation V2 C2 freeze (owner D1-D4)
- **Decision (owner):**
  - The pre-registration is approved (D1), with its amendments and the owner's eight checks.
  - Option B, the 55 previously exposed clips, is the C3 set (D2).
  - Track B uses the historical C1b profile at `acbf892ba`, reproduced exactly or stopped (D3).
  - C2 is frozen, then C3 runs under a $2.00 hard cap (D4).
- **Freeze manifest:** `eval/methodology/v2-c2-freeze-manifest.json`. It pins code, prompts, datasets, the pre-registration, the content of the five C3 configs, the judge, the historical agent and the budgets. The configs pin its SHA-256, and `scripts/v2_freeze_manifest.py verify` rebuilds and compares it.
- **Why:** the primary metrics and the analysis are fixed before any C3 output exists.
- **Rejected:**
  - A fresh test set now (it needs human labelling time).
  - A current-production Track B (it needs the VM tracking stack and a new dev check).
- **Links:** [`v2-c2-freeze-manifest.json`](../eval/methodology/v2-c2-freeze-manifest.json), [`evaluation-v2-preregistration.md`](../eval/methodology/evaluation-v2-preregistration.md), [`v2-c2-freeze-readiness.md`](../eval/methodology/v2-c2-freeze-readiness.md)

### 2026-11-03: C3 scope: evidence boxes out of the critical path, Track B on the historical C1b profile, deterministic held-out dashboard set
- **Decision (owner):** evidence-box localisation is removed from the C3 critical path. RA1 continues separately, and no IoU is claimed.
- **Proposed for the owner's approval in the pre-registration:**
  - C3 Track B runs the historical C1b profile (agent `acbf892ba`, tracking off), labelled as such and never combined with current production.
  - The held-out dashboard set `dashboard-references-test-v1` is deterministic (code-planned specs, template wording, recount figures).
- **Why:**
  - The RA1 Claude passes (about 17,000 frame judgements for dev alone) are unscoped.
  - A current-production Track B needs the VM tracking stack.
  - Held-out reference answers must not reach external models, so they cannot be AI-reviewed and are made correct by construction instead.
- **Rejected:**
  - Mixing current agent code with historical flags.
  - Claude-written held-out dashboard requests (they would need an external review to validate).
  - Sampling RA1 seconds without a methodology version.
- **Links:** [`v2-c2-freeze-readiness.md`](../eval/methodology/v2-c2-freeze-readiness.md), [`evaluation-v2-preregistration.md`](../eval/methodology/evaluation-v2-preregistration.md)

### 2026-11-03: Caption-pass provenance names the per-run outcome and the agent setting separately
- **Decision:** `response.provenance.flags.chunking` keeps `enabled` as is (this run captioned) and gains `ran` (the same per-run value, named plainly), `setting_enabled` (`INCIDENT_CHUNKING_ENABLED` for the agent at the time of the run) and `skipped` (the pass's skip reason, `null` when it ran or was not attempted). Contract: [`vm-api-contracts.md`](vm-api-contracts.md).
- **Why:** a 2 Nov report read `enabled: false` on a short clip as "the pass is off". `enabled` is per-run, so a clip under `INCIDENT_CHUNK_MIN_CLIP_SECONDS` reads false while the pass is on. The additive keys make both questions answerable without changing any consumer.
- **Rejected:** renaming `enabled` or making it the agent setting, because the evaluation package pins it as the per-run outcome (`eval/evalv2/adapters/base.py`, `PER_RUN_FLAGS`).
- **Links:** [`run_provenance.py`](../../../../../services/agent/src/vss_agents/utils/run_provenance.py), [`incident_report_gen.py`](../../../../../services/agent/src/vss_agents/tools/incident_report_gen.py)

### 2026-11-03: Dashboard chart requests normalise canonical severity words in code
- **Decision:** `generateChart` rewrites severity words to their dashboard band before the chart model reads the request (`domain/severity-words.ts`, `chart-severity-words-v2`).
- **Rule:** a word maps to a band only when every severity level the project's definitions tie it to lies in that one band. The definitions:
  - the severity rubric, shared by the P1 prompt and the ground-truth Severity Guide;
  - the importer's `mapSeverity`;
  - the dashboard bands (low 1–2, medium 3, high 4–5).
- **Mapped:**
  - minimal and very low → low;
  - minor → low (the rubric uses it only at levels 1–2);
  - moderate → medium;
  - severe and critical → high.
- **Where it applies:** only where the word qualifies "severity" or an incident noun. Breakdowns and "how severe…" stay as typed.
- **Limits:** the chart prompt bytes are unchanged, and the typed request is kept if the result would pass 300 characters.
- **Why:** Ultra read the prompt's "exactly these values" rule literally and refused synonym requests. On development requests the change raised correctness from 0.88 to 0.92 (RB2) and from 0.75 to 1.00 (supplement, valid requests), with no new false acceptance. The gain is **not statistically significant** (RB2 paired difference +0.04, 95% CI −0.03 to +0.11; McNemar p = 0.45), and **one changed request regressed** (correct to refused); one byte-identical request also flipped in the same run, so the cause is not established ([evaluation](../eval/methodology/v2-dashboard-change-assessment.md)). Merged by owner approval on 2026-11-03.
- **Rejected:**
  - Mapping serious or significant (they span bands).
  - Mapping major, extreme or catastrophic: one-band under the rule, but outside the owner-approved scope.
  - Treating AI reviewers' agreement as justification for "minor".
  - A prompt-only synonym list.
  - Changing the scale or the bands.
- **Links:** [`severity-words.ts`](../incident-console-v2/src/modules/dashboard/domain/severity-words.ts), [`chart-severity-words.json`](../contracts/fixtures/chart-severity-words.json), [`v2-dashboard-change-assessment.md`](../eval/methodology/v2-dashboard-change-assessment.md)

### 2026-11-03: Evaluation V2 reference review is AI-only; no record is human-verified
- **Decision (owner):** an AI-only independent review replaces the planned human reviews: the 80 judge-calibration pairs, RA2 chat (64), RB2 dashboard (30) and the RA1 boxes.
  - Two blind reviewers from families outside the subjects, judges and generator (DeepSeek, Zhipu GLM), with a MiniMax adjudicator for disputed records.
  - Fixed, versioned prompts; κ between reviewers.
  - Statuses AI-consensus / AI-disputed; every record stays Human-unverified, and the human calibration threshold is not claimed.
- **Why:** the owner has no time for human review, and AI review is the strongest independent check available without it.
- **Rejected:**
  - Claude as a reviewer (it generated the references).
  - A subject or judge family as a reviewer.
  - Reporting AI agreement as verification.
  - Waiting for reviewers (no date).
- **Links:** [`v2-ai-only-reference-review.md`](../eval/methodology/v2-ai-only-reference-review.md), [`evaluation-methodology-v2.0.md`](../eval/methodology/evaluation-methodology-v2.0.md)

### 2026-11-03: Box describe sends one enlarged close-up and asks the Nano model first
- **Decision:** `describe_box` no longer sends the whole frame. `crop_evidence.describe_box_close_up` cuts the box plus a 20 % margin (at least 16 px), upscales it (Lanczos, short side at least 512 px, long side at most 1024 px) and outlines the box in red; that is the only image. The `zoom/describe-box` prompt names ONE object, says what the picture is, and forbids naming floor, tiles, walls, doors, handrails or a person only partly inside the box. `DefaultDetector.describe_box` asks `nvidia/cosmos-3-nano-reasoner` first (25 s, one try, reasoning off); on a failure or a "cannot tell" answer it asks the detector's own model (150 s, one retry on a timeout). Worst case 25 + 2 x 150 = 325 s, under the console's 330 s. The response contract is unchanged.
- **Why:** a reviewer boxed a small white bottle held low and got "floor tile", "elevator floor" and "elevator door": beside the whole frame the model names the most prominent thing, not the boxed one. Measured on the shared VLM, the enlarged close-up with the new prompt names the object correctly on cars, vans, bins, bags and people; the motion-blurred bottle is named a bottle on some boxes and a bag or other hand-held item on others, so it is better but not reliable. The main model often took 60-125 s or returned a 524 on the shared VLM; Nano takes 1-3 s.
- **Rejected:** keeping the whole frame as a second image (made it worse: "white shoe", "white plastic bag"); a crop without the outline (the model named the wrong thing or said "too blurry"); the omni model (named a knife); a tighter or larger upscale (no better).
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`incident_box_describe.py`](../../../../../services/agent/src/vss_agents/api/incident_box_describe.py), [prompt](../contracts/prompts/zoom/describe-box.txt), [vm-api-contracts](vm-api-contracts.md).

### 2026-11-03: Box describe runs with reasoning off, retries a timeout once, and the console waits longer than the agent
- **Decision:** `DefaultDetector.describe_box` sends `chat_template_kwargs.enable_thinking=false`, times out at 150 s per try (was 40 s; raised 3 Nov 2026 so a slow model can give its final answer) and tries a timeout once more (`_chat_json(timeout_seconds, thinking, retry_timeout)`). The console's describe proxy waits 330 s (route `maxDuration` 330), shows the agent's own `detail` text instead of the raw HTTP body, and the box tool says "The AI is still looking..." after 6 s, with the seconds waited. `box/track` is unchanged: it uses the grounding detector's own 15 s, one-attempt limits, and its 90 s console wait already exceeds them.
- **Why:** on the shared VLM the same call took about 30 s with reasoning on (and hit the 60 s timeout, so the console's equal 60 s wait aborted first and showed "could not reach the agent"); with reasoning off it takes about 3 s. The answer is a short JSON, so it needs no reasoning.
- **Rejected:** the Nano model as the only model (superseded 3 Nov 2026 by the entry above: it is now tried first, with the main model as the fallback); a longer single timeout without a retry (a stalled request would still cost the full wait).
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`box-tools.ts`](../incident-console-v2/src/modules/reports/infrastructure/agent/box-tools.ts), [vm-api-contracts](vm-api-contracts.md).

### 2026-11-03: Person tracks are read at frame id / fps, and a located box is never replaced by a sample from another moment
- **Decision:** `build_tracks` stamps a sample at `frame_id / fps` with no start loss, and keeps one sample per track per 200 ms bucket, preferring a real detection over a tracker-only box. `run_tracking` reads until the stream reaches the end of the file (last frame id within 3 frames of the clip's, or the frame ids fall back because DeepStream replays the file) or the deadline (clip duration + 20 s). The confirmation fallback of the entry below replaces an unconfirmed box with a track sample only when the sample is within 0.5 s of the box's own second; otherwise the located box stays. `/analyze` `tracking` gains `time_base` (`clip_frames`, `frames`, `last_frame_id`, `end_reached`) and `boxes` (`confirmed`, `moved`, `kept`).
- **Why:** the earlier time base added a "start loss" to every sample (`clip frames - last frame id` or 2.85 s), which was the unread tail of the stream, not frames DeepStream dropped. Measured against the video on revisions 116, 118, 119 and 120 the best shift of frame ids to seconds was 0.0 s, with the first frame id 2, while the agent had applied 0.6 to 3.3 s. Tracks were therefore up to 3 s late, the confirmation fallback then replaced located boxes with samples from the wrong moment (5 of the 6 wrong person boxes in revisions 115 to 124), and the first-seen evidence image (the entry above) cut the wrong frame. A tracker-only box first in a bucket made `is_solid` depend on the frame parity.
- **Rejected:** keeping the loss inference but fixing the margin (the premise is wrong, the first frame is not lost); dropping the fallback entirely (it still helps when the track and the box agree on the second); reading to the end only when the last frame is exactly the clip's (DeepStream publishes only frames with objects, so the last id often falls short, and the deadline covers that case).
- **Cost:** a clip whose last person leaves well before its end is read until the deadline (duration + 20 s), where the old 100-frame margin could stop it up to about 3 s earlier; a replay of the file ends the read sooner.
- **Links:** [`track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [recorded frames](../../../../../services/agent/tests/unit_test/utils/fixtures/perception/), [vm-api-contracts](vm-api-contracts.md).

### 2026-11-03: Edit mode adds and re-tracks evidence with a box tool, not a crop picker
- **Decision:** the frame picker and **Replace image** are gone. **+ Add evidence** and one **Edit** per card (assets included) open `BoxTool`: draw a box, the AI describes it, the tracker follows it, the reviewer checks the card and adds it to the draft. The draft item carries a `reviewer` object (reviewer track, AI proposal, still second/box) that Save sends; a partial track must be kept as incomplete, redrawn or kept as a still image before it is added. Edit re-tracks without touching the item's text. Track labels use item names.
- **Why:** a reviewer can add what the model missed and fix a bad track in one flow, and the evidence image is always the first second the item is seen. The proxy calls sit in one module (`box-tool-client.ts`) so the routes unit can change them without touching the dialog.
- **Rejected:** keeping the crop picker beside it (two ways to set an image); editing text on Edit (it only re-tracks).
- **Amended 2026-11-06:** the rejection of "two ways to set an image" no longer holds: the box tool still adds and re-tracks, and clicking a card's image now sets only that item's image by hand ([decision](#2026-11-06-clicking-an-edit-cards-image-sets-that-items-evidence-image-from-a-picked-frame-and-a-mouse-crop)). A box-tool item's image is still its track's first second unless the reviewer picks one.
- **Links:** [`BoxTool.tsx`](../incident-console-v2/src/sections/evidence/components/BoxTool/BoxTool.tsx), [`box-tool.ts`](../incident-console-v2/src/lib/evidence/box-tool.ts)

### 2026-11-03: A reviewer's box item is cut and stored on the server at Save
- **Decision:** the box tool's draft item reaches Save as a new optional `reviewer` object on its `StructuredEdit` item (`ai_proposal`, `track`, `still_seconds`, `still_box`). `PATCH /api/reports/[videoId]/edit` then cuts the crop and the whole frame at the first-seen second (the track's first sample, or `still_seconds`) with ffmpeg over a signed R2 URL, and stores `<itemId>.jpg`, `<itemId>-frame.jpg` and `<itemId>-track.json` under the first free `edit-<N>/`. The evidence entry gets `source: "reviewer"`, `box_seconds`, `track`, `track_first_seen_seconds`, `track_last_seen_seconds`, `track_source: "reviewer"`, `track_partial` and `ai_proposal`. The console proxies the agent through `POST /api/reports/[videoId]/box/describe` and `.../box/track`.
- **Why:** the final item ids (E#, I#, A#) exist only when the edit is validated, so the server is the one place that can name the keys; the evidence image is then always the first-seen second, whatever the browser had on screen. A re-tracked existing item keeps its source entry (and its `source`), so only boxes the reviewer drew read "Added by reviewer".
- **Rejected:** the browser cuts and uploads the crop (it cannot cut the whole frame the same way, and it needs ids before Save); storing the track only in the browser (lost on reload).
- **Links:** [data](data.md), [vm-api-contracts](vm-api-contracts.md)

### 2026-11-03: Reviewer box describe is one new prompt on the second look's machinery
- **Decision:** `POST /api/v1/incidents/{video_id}/box/describe` reuses the zoomed second look's crop (`zoom_crop`), marked frame (`zoom_context_frame`), `DefaultDetector._chat_json` client and strict-parser style, and adds one registered prompt, `zoom/describe-box` (one call; the frame with the box was dropped on 3 Nov 2026, see the entry above). `holder` is plain words, not an entity id.
- **Why:** the existing look prompts return only name, description and confidence and are split by person versus object, so none gives the item type, holder or threat level the draft item needs, and the merge step needs report text a new item does not have. One call keeps the box tool fast. A reviewer's item is not in any report yet, so there is no entity id to hold it.
- **Rejected:** chaining the two looks and a merge (three calls, no type); asking the model for an entity id (none exists).
- **Links:** [`incident_box_describe.py`](../../../../../services/agent/src/vss_agents/api/incident_box_describe.py), [prompt registry](../contracts/prompts/README.md), [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-11-03: A reviewer's box is tracked by the analysis tracker, with the name and description as the detector prompt
- **Decision:** `POST /api/v1/incidents/{video_id}/box/track` calls `object_tracking.track_item` with the reviewer's box as the seed and `"<name>: <description>"` as the label, asymmetric back and forward windows (`spans`) and a 50 s cap. A track that cannot reach the end of the window is returned as `partial` with `lost_at`, never as an error. The video comes from `videos.filepath`, so the body stays as the shared contract has it.
- **Why:** no new model or service; the failure modes are the ones the team already knows. Samples carry `conf` (contract) and `score` (stored track files, console reader).
- **Rejected:** a second tracker for reviewer boxes; SAM 3 (needs a GPU service and a licence check); a `video_url` in the body.
- **Links:** [vm-api-contracts](vm-api-contracts.md#post-apiv1incidentsvideo_idboxtrack)

### 2026-11-03: An item's evidence image is the first second its track sees it
- **Decision:** for an item with a person or object track, `frame`, `image`, `bounding_box` and `box_seconds` come from the track's first sample (`track_evidence.first_seen_sample`, replacing `best_moment`, which took the largest confident box). Items without a track keep the located second. `track_first_seen_seconds` and the stored track file are unchanged.
- **Why:** the captain asked that the first instance of seen evidence is always the evidence image (add/track evidence mockup, message 007), so AI items and reviewer items (contract `vss-evidence-box-contract`) behave the same and there is no crop picker.
- **Limit (audit 2026-11-06, settled the same day):** the captain chose the first frame of the track, always, whatever its score, unless a reviewer set the image; the "first confirmed sample" idea is not built ([decision](decisions.md#2026-11-06-a-tracked-items-image-is-always-the-first-frame-of-its-track-unless-a-reviewer-set-one-small-crops-get-context-the-agent-waits-out-429s-on-its-other-calls-and-stops-when-the-console-aborts)).
- **Rejected:** keeping the largest-box moment for AI items (two rules for one image); skipping tracker-only first samples (the first sample is by definition when the tracker first saw it).
- **Links:** [data](data.md), [vm-api-contracts](vm-api-contracts.md)

### 2026-11-03: Replace image and the frame picker are removed from Edit mode
- **Decision:** Edit mode no longer has **Replace image** or the frame picker dialog (`EvidenceFramePicker`), including its track scrubber. The server pieces stay: `GET /api/reports/[videoId]/frame`, `POST .../evidence-crop` and `POST .../evidence-image` (uploads under `edit-<N>/`), plus the pure rectangle rules in `lib/evidence/frame-picker.ts` and `lib/evidence/track.ts`, because the reviewer box tool reuses them. A saved reviewer image keeps displaying; the draft's `pendingImage`, `imageBox` and `imageTimestampSeconds` fields stay for that tool.
- **Why:** the reviewer now draws a box and the AI tracks it; the evidence image is always the first second the item is seen, so a separate crop picker is redundant.
- **Rejected:** deleting the crop and upload routes (the box tool needs them); keeping the picker for existing items (two ways to set an image).
- **Amended 2026-11-06:** the picker is back in a new form, `EvidenceImagePicker`, opened only by clicking an Edit card's image; there is still no **Replace image** button and no file upload. It uses `GET .../frame` and `POST .../evidence-crop` and Save cuts the image on the server from `image_pick`, so `pendingImage` and `POST .../evidence-image` stay unused by it ([decision](#2026-11-06-clicking-an-edit-cards-image-sets-that-items-evidence-image-from-a-picked-frame-and-a-mouse-crop)).
- **Links:** [architecture](console-reference.md#report-versions-view-edit-and-history)

### 2026-11-03: Track labels show the item's name, never its id
- **Decision:** the player overlay box, the presence bars' accessible names and the pop-up label a track with the item's name (`TrackedReportItem.label`: entity label or type, instrument or asset name; the id only when a name is empty). Ids (`E1`, `T-1`, `N-1`) stay internal keys (`data-track-item`, selection, routes) and the id badge on cards and the pop-up title is unchanged.
- **Why:** captain, 2 Nov: tracking reads by the names of evidence, not codes; part of the add/track evidence build.
- **Links:** [`TrackOverlay.tsx`](../incident-console-v2/src/sections/reports/components/TrackOverlay/TrackOverlay.tsx), [`track.ts`](../incident-console-v2/src/modules/reports/domain/track.ts).

### 2026-11-02: The chat evaluation runs the agent's real chat router in-process over frozen corpus snapshots
- **Status:** built and tested offline (Evaluation V2 J2/J3); the C1c-chat pilot itself is a proposal awaiting the owner's marker.
- **Decision:** the chat task calls the route function of `create_incident_chat_router` (grounded mode) directly, with snapshot ports for `RevisionStore` and `LibraryIndex` and an injected chat model, over two frozen corpora (oracle = the ground truth's reports; system = a sealed Track B run's final reports). It runs in two interpreters: `prepare`, `score` and `readiness` in the eval venv (ground truth, scoring), and `estimate` and `run` in the agent venv (`vss_agents`), joined by hashed files in the run directory (`plan.json`, `corpora/`, `answers.jsonl`). Every model call is reserved on the budget ledger first; a live run needs `--live`, `EVALV2_ALLOW_LIVE=1` and the owner's marker.
- **Why:** the answers must come from the same code the console calls (parity), and must never read or write the finals database. The eval venv cannot install the agent package without a new dependency, and the agent venv lacks the ground-truth workbook reader.
- **Alternatives rejected:** an HTTP call to a running agent (needs a server and a database with the corpora loaded); re-implementing the router's planning and counting in `evalv2` (no parity); adding `vss_agents` to the eval environment (a heavy new dependency); routing chat through the generic executor (its adapters speak model APIs, not the router).
- **Links:** [`eval/methodology/v2-run-readiness.md` §10](../eval/methodology/v2-run-readiness.md#10-chat-evaluation-c1c-chat), `eval/evalv2/tasks/chat/harness.py`.

### 2026-11-02: Dashboard chart requests are read by the VSS agent's own LLM, not the local vlm-gateway
- **Decision:** the console posts its chart prompt (`modules/dashboard/domain/chart-prompt.ts`) and the one request to the agent's `POST /api/v1/incidents/chart-requests`. The agent calls the `llms:` entry named by `chart_generator.llm_name` (`${LLM_MODEL_TYPE:-nim}_llm`, the same text model as the workflow; `nvidia/nemotron-3-ultra` on the VM) and returns the JSON object the model wrote, or null. `AgentChartInterpreter` replaces `GatewayChartInterpreter` behind the unchanged `ChartInterpreter` port. Charts no longer use `CHART_MODEL` or `VLM_GATEWAY_URL`, and `start.sh --mode vm` starts no local gateway. Mock mode is unchanged.
- **Why:** the captain wants the chart model to come from the VSS agent on the VM, not from the laptop. The agent already holds the model URL and key, so charts reuse an existing entry and add no key, no gateway process and no laptop secret.
- **What stays the same:** the reply counts only if `parseChartSpec` (strict zod, the allowlist in `chart-spec.ts`) accepts it, and the console validates it, not the agent. The agent never validates, so the allowlist lives in one place. The model never sees a figure, and its text never reaches the database or the screen.
- **Alternatives rejected:**
  - *Sending the allowlist to the agent and validating there:* the spec would be duplicated in Python, and the console must validate anyway because it owns the query.
  - *Running vlm-gateway on the VM:* a second gateway and key on the VM for one call, when the agent already has the model.
  - *A new `llms:` entry or a new key for charts:* not needed, since the workflow's entry is the same model.
  - *Naming the LLM in code:* the model would be invisible in config.
- **Links:** [`../incident-console-v2/src/modules/dashboard/infrastructure/agent/chart-interpreter.ts`](../incident-console-v2/src/modules/dashboard/infrastructure/agent/chart-interpreter.ts), [`../../../../../services/agent/src/vss_agents/api/incident_charts.py`](../../../../../services/agent/src/vss_agents/api/incident_charts.py), [`dev-profile-base` agent config](../../dev-profile-base/vss-agent/configs/config.yml), [vm-api-contracts.md](vm-api-contracts.md#post-apiv1incidentschart-requests).

### 2026-11-02: Object tracking is on for the VM agent
- **Decision:** `native-services.sh` exports `INCIDENT_OBJECT_TRACKING_ENABLED=1` unless the env file or the caller sets it, like `INCIDENT_CHUNKING_ENABLED`. `=0` in `.env.remote` turns it off and a restart applies it.
- **Why:** the four fixes it waited for are merged: the 15 s one-attempt detector timeout, the whole-frame seed skip with the anchor guard, NanoTrack ahead of MIL, and the pinned model fetch at agent start. The scout measurements (Nano tracked 6 of 6 seeds at 0.4-0.8 s each against MIL's 3 of 8) are the reason. It is a native-services default and not a `.env.remote` line so that it survives a regenerated env file.
- **Rejected:** leaving it off until another end-to-end run (the captain asked to see it on); setting it only in the env file.
- **Rollback:** `INCIDENT_OBJECT_TRACKING_ENABLED=0` in `.env.remote`, restart `vss-agent`.
- **Links:** [status](status.md), [`native-services.sh`](../.scripts/native-services.sh)

### 2026-11-02: Object tracking's detector calls get a 15 s timeout and one attempt
- **Decision:** object tracking sends each detector request once, with a 15 s timeout (`INCIDENT_OBJECT_TRACKING_DETECTOR_TIMEOUT_SECONDS`), through `DefaultDetector.with_request_limits` applied in `run_object_tracking`. A timeout or a 429 is a `detector_errors` and not a miss, so a failed call never ends a segment. Each item reports `detector_ms` and `detector_max_ms`.
- **Why:** the 10-65 s per item came from the detector's stall tail, not the tracker. In the speed scout, 11% of 320 calls took 60-130 s and made up 77% of detector time (median 2.3 s); a 429 cost 62 s with one retry and 122 s with two. Tracker and decode cost 1-3 s per item.
- **Checked on the VM (live detector, 4569 and 8206, once, 26 calls):** slowest call 8.6 s, no errors, wall time 47 s for five items.
- **Rejected:** a shorter budget for the shared detector (grounding, zoom and evidence calls need the long timeout); fewer re-anchor checks (the reanchor scout found no gain).
- **Links:** [`object_tracking.py`](../../../../../services/agent/src/vss_agents/utils/object_tracking.py), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py).

### 2026-11-02: Whole-frame seeds are not tracked; a failed anchor keeps the previous tracker
- **Decision:** `track_item` skips an item whose seed box covers more than `ObjectTrackingSettings.max_seed_area` (0.5, a field, no env var) of the frame, with `skipped: "seed box covers <n>% of the frame"` and no detector call. `_Tracker.anchor` builds and initialises the new OpenCV tracker before replacing the old one. `follow` catches a refused seed anchor (no track, `anchor_errors: 1`, the other direction is not tried) and a refused re-anchor (`anchor_errors += 1`, the detector-confirmed sample is kept and the previous tracker keeps running).
- **Why:** in the end-to-end test OpenCV's MIL `init` raised on whole-frame and edge-touching boxes; run_object_tracking turned that into `error` and a re-anchor crash discarded the item's whole track (4569 A3 failed in 11 of 14 runs). A track of a whole-frame box carries no information. The seeds scout found items track on target up to about 44% of the frame, so the limit is 0.5, not 0.4.
- **Rejected:** padding or shrinking seeds (hurts tracking); an env var for the limit (no case for tuning per deployment yet).
- **Links:** [`object_tracking.py`](../../../../../services/agent/src/vss_agents/utils/object_tracking.py), plan `vss-objtrack-plan` unit U2.

### 2026-11-02: Object tracking prefers NanoTrack v2 over MIL
- **Decision:** `select_tracker(model_dir)` returns NanoTrack when `nanotrack_backbone_sim.onnx` and `nanotrack_head_sim.onnx` are in `INCIDENT_OBJECT_TRACKING_MODEL_DIR`, else Vit (`object_tracking_vittrack_2023sep.onnx`), else CSRT, KCF, MIL as before. A model that fails to load is skipped. The files are fetched at deploy time (U4), pinned by SHA-256, and never committed.
- **Why:** MIL never reports failure and drifts off small objects (9170 ball: 0 of 13 reference points). On the three test clips Nano tracked 6 of 6 seeds (414 samples, 0.4-0.8 s per item) where MIL gave 4 of 6 with an `error`; 74% of reference points on target against MIL's 60%, 3.9 ms per update against 24, and it initialises on whole-frame and edge-touching boxes that crash MIL. Vit is close (70%, 409 samples).
- **Rejected:** CSRT (needs `opencv-contrib-python-headless` in place of the headless wheel for no accuracy gain, and 60-140 ms per update on large boxes); committing the models (the NanoTrack weights have no licence file, so they are not redistributed; Vit is Apache-2.0 and a drop-in if the licence matters).
- **Links:** [`object_tracking.py`](../../../../../services/agent/src/vss_agents/utils/object_tracking.py).

### 2026-11-02: The privacy blur is removed entirely
- **Decision:** every form of face blur is gone. The agent no longer detects heads or pixelates evidence frames and crops (`privacy_blur.py`, `EvidenceBlur`, the `every-match` head query and `INCIDENT_BLUR_DETECTOR_CALL_CAP` are deleted), `/analyze` ignores `blur_faces` (the console no longer sends it), `POST /api/v1/incidents/{id}/reblur` and `<itemId>-heads.json` are deleted, and the console has no **Blur faces** switch, no `PUT /api/videos/<id>/privacy`, no blurred clips (`-clip-blur.mp4`) and no re-analysis job. Migration `20261102090000_drop_blur_faces.sql` drops `videos.blur_faces`, `analysis_jobs.blur_faces`, `analysis_jobs.reanalyse_video_id` and `claim_queued_analysis_job`, and restores the standalone `claim_analysis_job(p_stale_seconds)`; it cancels any queued or running re-analysis job first.
- **Why:** the blur added processing time (a whole-frame head search per frame and per clip second, and a 2.5 minute re-blur for a four-item report) without enough benefit.
- **Existing data:** revisions keep the images they already have, and nothing in R2 is deleted. Old evidence entries may still carry `blur_regions`, `heads` and run notes may carry `privacy` or `blurFaces`; readers ignore unknown fields.
- **Consequence:** a console built before this change calls `claim_queued_analysis_job`, which the migration drops, so it must be updated and restarted once the migration is applied.
- **Rejected:** keeping the switch off by default (dead code and a column nobody sets); keeping `claim_queued_analysis_job` as a wrapper (it only existed for re-analysis jobs).
- **Supersedes:** the privacy-blur entries of 2026-11-01 and the 2026-11-02 re-blur entry, which are removed; git history has them.
- **Links:** [migration](../supabase/migrations/20261102090000_drop_blur_faces.sql), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py).

### 2026-11-02: A person pictured on a screen is not the entity, and tracks confirm a person's box
- **Decision:**
  - The grounding prompt (`grounding/best-match`) says that only a real, physically present person or object counts, and that one shown on a screen, TV, monitor, poster, sign, picture, painting or reflection gets `{"bbox_2d": null}`.
  - With solid person tracks, the evidence step treats a located person's box as unconfirmed when no track sample within 0.5 s of its second overlaps it (the association's own test, IoU of at least 0.3). It then tries the locate seconds not yet tried (+1, -1, +2, -2 s after the one found) and keeps the first box a track confirms. With none, the box becomes the nearest track sample inside the entity's first to last seen span and within 0.5 s of the box's own second (a sample from another moment keeps the located box, [decision](#2026-11-03-person-tracks-are-read-at-frame-id--fps-and-a-located-box-is-never-replaced-by-a-sample-from-another-moment)), each fallback taking a track of its own. A confirmed first box costs no extra detector call. Persons only; instruments and assets keep the first box.
  - Nothing changes without solid person tracks (tracking off, skipped, or only ghost tracks). The confirmation runs once tracking has finished; locate and tracking still start together.
- **Why:** on IMG_8206 the report model put both men one second before they walk in, and the detector boxed the person shown on the hallway TV with a fixed score of 1.0. The retry never ran, the association found no track, and the TV frame was stored as located. The prompt removes the cause; the track check catches the same failure when the model is fooled by something else, independently of its judgement.
- **Checked on the VM (2 Nov 2026, targeted, not a full run):** the new prompt on the stored IMG_8206 frames returns no box for "man in blue shirt" and "man in white shirt" at 80 s (the TV frame; the old prompt boxed the TV at [115, 488, 229, 523]), still boxes the white robot (control), and boxes the men at 82 s and 84 s. Against the run's six stored DeepStream person tracks the old TV box is unconfirmed (IoU 0) and the boxes at 81, 82 and 84 s overlap tracks 2 and 3 (IoU 0.24 to 0.52, one below the 0.3 bar). The shared model gateway key was throttled by parallel runs, so the full console flow was not run.
- **Rejected:** set-of-marks as the fix (its own open issue, X13); raising the zoom threshold (the second look cannot say "this is not the entity"); a plausibility score from the detector (it has none).
- **Links:** [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [`best-match.txt`](../contracts/prompts/grounding/best-match.txt)

### 2026-11-02: Library questions are answered by a planned search with exact counts (Gate M2 approved by the chatbot feature owner)
- **Status:** approved on 2026-11-02 by the authorised chatbot feature owner (Gate M2), with grounded report chat (P5) and console report chat (P7). Only in grounded mode (`INCIDENT_CHAT_MODE=grounded`); template mode stays the default until Evaluation V2 validates grounded answers, and nothing is deployed by the merge. First proposed 2026-11-01.
- **Decision:** a chat question with no incident is answered in steps:
  1. The model turns the question into a checked plan: type, severity band, instrument, asset, a breakdown (by type or severity), a count flag, and a search phrase holding only what the filters leave.
  2. Code filters every incident's searchable version (official, else newest) exactly and ranks the matches. An instrument or asset filter matches whole words (or a compound's head: "gun" in "handgun") in the name, label or description of any instrument or asset of the report.
  3. **Counts and breakdowns are composed by code**, never by the model. When the filters do not capture the whole question (a condition left in the search phrase, or a type, severity or breakdown the library does not use), the count is refused with the reason, never estimated.
  4. Any other question is answered by the model from the best eight, with incident and item citations; its context carries the code counts and whether they are exact.
  - **Prose:** the answer names incidents by type and title and items by name, never by id unless asked. An id still written is replaced and listed in `grounding.ids_resolved`; an item id that names different items in two incidents reads neutrally ("an object") rather than as the wrong one.
- **Why:**
  - Counts must be exact. A model counting the reports it was shown gets them wrong past a few, and a filter that silently drops a condition ("at night") widens the count while it still looks exact.
  - Retrieval must cover the whole library.
- **Rejected:**
  - Model-written counts from a code total: the model still states the total for a question the filters only partly capture.
  - Substring matching of objects: "bat" matched "bathroom".
  - Semantic revision search alone: there is no summary embedding for human revisions, and it has no type or severity filter (X25). A migration for that waits for approval.
  - One model call over every report: it does not scale past a few dozen reports and cannot count exactly.
- **Links:** [contract](vm-api-contracts.md#post-apiv1incidentschat), [`grounded_chat.py`](../../../../../services/agent/src/vss_agents/utils/grounded_chat.py)

### 2026-11-02: Grounded chat answers from one report version with a chat model, behind a mode switch (Gate M2 approved by the chatbot feature owner)
- **Status:** approved on 2026-11-02 by the authorised chatbot feature owner (Gate M2). The decision covers implementing and integrating grounded report chat (P5), library chat (P6) and console report chat (P7), and it supersedes [2026-10-24: Chat about the official version uses the in-memory chat search client](archive/decisions-superseded.md#2026-10-24-chat-about-the-official-version-uses-the-in-memory-chat-search-client-for-mvp2-superseded-2026-11-06) for grounded mode. **The production default does not change:** template mode stays the default (`INCIDENT_CHAT_MODE` unset) until Evaluation V2 validates grounded mode, and nothing is deployed to the shared agent by this merge. First proposed 2026-11-01.
- **Decision:** with `INCIDENT_CHAT_MODE=grounded`, an incident question is answered by a chat model from one report version: the asked one, else the official one, or the reviewer's draft.
  - The model is `INCIDENT_CHAT_MODEL`, default Nemotron 3 Ultra, which the endpoint check (RB1) must confirm.
  - It sees the registered prompt `chat/incident-answer`, the version as JSON (incident, items with ids, timeline) and the last eight turns.
  - It answers in a strict schema: `answer`, cited item ids, `insufficient_evidence`.
  - Every cited id is checked against the version, and unknown ones are dropped and counted.
  - The answer follows `chat-contract-v2`: v1 plus `insufficient_evidence` and `grounding`.
  - The model client and its clock are injectable, and the request has a golden (`contracts/golden/chat.json`).
  - **Prose and ids (revised 2026-11-01, after the item-list answer on localhost):** the prompt names people and objects by their descriptions, keeps item ids out of the answer unless the question asks for them, and tells a what-happened question as the timeline in order with `m:ss` times; the context sorts the timeline and adds the clock times. The first prompt said to refer to people "by their description as well as their id". A known id still written in the prose is resolved to the item's description by the same function the template mode uses, and listed in `grounding.ids_resolved`, so prompt compliance can be measured.
- **Why:** today's chat makes no model call. It keyword-ranks saved evidence into a template sentence, and for the official version with no draft it asks a canned in-memory search client that knows no finals video. The brief asks for a working chatbot first, and Evaluation V2 measures answers: fact recall, citations, refusals.
- **Rejected:**
  - Retrieval over `evidence_crops` alone: it holds one version per video and no incident-level facts.
  - Free-text answers with citations parsed from prose: they cannot be checked reliably.
  - Changing the default mode now: it waits for Evaluation V2 to validate grounded answers (chat references RA2 and the judge).
  - Library-wide questions in this step: they need a planner over SQL facets and revision search, which is P6.
- **Links:** [contract](vm-api-contracts.md#post-apiv1incidentschat), [`grounded_chat.py`](../../../../../services/agent/src/vss_agents/utils/grounded_chat.py), [`chat-contract-v2`](../contracts/chat-contract-v2/README.md)

### 2026-11-02: Evaluation V2 proposes Gemma 4 31B as its independent open-weight Track A baseline (pending a capped dev pilot)
- **Decision (proposed by the evaluation agent, pending the owner and the C2 freeze):** Track A adds `google/gemma-4-31b-it` on the NVIDIA API catalog as the external open-weight baseline, after four probes and a 50-run dev pilot (C1e, ≤ 1.5 M tokens). `moonshotai/kimi-k2.6` is an optional second only if its probes show real video input.
- **Why:** Switchyard serves only NVIDIA models (RB1). On the catalog (re-listed 2026-11-02, unchanged), Gemma 4 31B is the only independent-family model with documented video input and a practical size. It is Google-built, Apache-2.0, 31B dense, and documents video up to 60 s at 1 fps. The pilots so far compare NVIDIA models only.
- **Alternatives rejected:** Qwen3-VL-8B (not served by either endpoint; it needs a GPU host and a weight download, both gated, which would delay C2); Cosmos Reason 2 8B (open weights, but NVIDIA's post-training of Qwen3-VL-8B, so not independent; it can be added as an NVIDIA arm); image-only catalog VLMs (Llama 3.2 Vision, Phi-3 Vision, GLM-5.3 Flash, Step-5, Muse Glimmer).
- **Update (2026-11-02):** the profile has no NVIDIA catalog key, so the proposed route is OpenRouter (prepaid; exposure is the top-up). It adds Qwen3.5-9B as a Qwen-family video arm, because Qwen3-VL-8B is not served there with video. Routing is pinned per subject (providers, no fallback, no data retention).
- **Links:** [methodology v2.0 §2](../eval/methodology/evaluation-methodology-v2.0.md), [C1e config](../eval/experiments/v2/c1e-external-baseline-pilot.json), [OpenRouter configs](../eval/experiments/v2/c1e-openrouter-gemma4-31b.json).

### 2026-11-02: Evaluation V2 scores severity by MAE (primary), with exact accuracy and QWK secondary, over one denominator
- **Decision (evaluation owner, 2026-11-02; proposed primary metric for the C2 freeze, final with the freeze package):** severity_level is ordinal, so V2's primary severity metric is the mean absolute error on the canonical 1–5 scale (`severity-v2-mae`). Exact accuracy and quadratic-weighted κ stay as secondary metrics. All three are computed over the same valid pairs, with the denominator, coverage and every excluded status (invalid output, invalid label, missing prediction, no model output) reported beside them. Score stage `evalv2-score-stage-v2` (v3 also keeps failed Track B runs in later stages' severity) writes to a new versioned directory and records the eval commit and scorer-file hashes.
- **Why:** exact accuracy counts a one-level miss the same as a four-level miss. The pilots show it: Super's QWK is well above Nano's while their exact accuracy is close. Mixing denominators (V1's field accuracy counts invalid outputs as misses; QWK skipped them) hid reliability inside a quality metric.
- **Alternatives rejected:** QWK as primary (unstable on small, skewed subsets, and harder to read than a level error); a composite incident score (it would mix error and accuracy directions); changing V1's scorer (V1 is frozen; its own v1.3 MAE stays for continuity).
- **Links:** [methodology v2.0 §4](../eval/methodology/evaluation-methodology-v2.0.md), [pre-registration §4 and §8](../eval/methodology/evaluation-v2-preregistration.md).

### 2026-11-02: `compose up --yes` in every start path
- **Decision:** Every `docker compose up` that start.sh reaches (`vm-ensure-docker.sh`, `tracking-stack.sh`, `rebuild-svc.sh`) passes `--yes`.
- **Why:** Compose 2.35.1 asks "Volume exists but doesn't match configuration. Recreate?" and waits on stdin, which hung start.sh for 13 minutes over no-tty ssh. With stdin closed and no `--yes` it does not abort, it silently keeps the old container. `--yes` recreates both. Verified on the VM with a throwaway project.
- **Rejected:** piping `yes` (undocumented, masks other prompts); `down -v` first (destroys unrelated state).

### 2026-11-02: Closing `start.sh` leaves the VM backend running
- **Decision:** No exit path of `start.sh` (last session or not, Ctrl-C, SIGTERM, SIGHUP, error) stops anything on the VM. `cleanup()` stops only laptop-side things: the console, the local mock and gateway, the SSH tunnel and temp files. The VM active-run flock (`.run/active-runs.lock`, held by `ssh -tt ... sleep infinity`), `VSS_LOCK_FILE`, `.scripts/vm-stop-backend.sh` and `test-vm-stop-backend.sh` are removed, since the lock only existed to find the last session. The start path is unchanged and still starts whatever is missing. To stop the backend on purpose, run `native-services.sh stop` and `tracking-stack.sh stop` on the VM.
- **Why:** The backend (shared vss-agent, Phoenix, the tracking stack) is shared by several people and workers. The last-exit stop killed it under others' runs on 2026-11-02, while workers were using it. Leaving a shared service up costs idle memory; stopping it costs other people's work.
- **Rejected:** keeping the stop behind an opt-in flag (nothing needs it; the manual scripts already exist); keeping the lock for registration only (no reader).
- **Links:** [`../start.sh`](../start.sh); [`incident-profile-operations.md`](incident-profile-operations.md); [`../skills/incident-start/SKILL.md`](../skills/incident-start/SKILL.md).

### 2026-11-02: Tracker model files are fetched at agent start, pinned by hash, not committed
- **Decision:** `.scripts/tracker-models.sh` (run by `native-services.sh` before it starts `vss-agent`, non-fatal) downloads the two NanoTrack v2 `.onnx` files (about 1.8 MB) into `<repo>/.tools/tracker-models` and checks each SHA-256 before renaming it into place. `native-services.sh` exports that dir as `INCIDENT_OBJECT_TRACKING_MODEL_DIR` unless the env file sets it.
- **Source:** `HonglinChu/SiamTrackers` at commit `8fe6791fecf13b95e6f19770af8963a9fc98759b` (2022-12-13), `NanoTrack/models/nanotrackv2/`: `https://raw.githubusercontent.com/HonglinChu/SiamTrackers/8fe6791fecf13b95e6f19770af8963a9fc98759b/NanoTrack/models/nanotrackv2/<file>`. `nanotrack_backbone_sim.onnx`: 1,056,849 bytes, SHA-256 `530bdd0cd00f19afab79a863e71ba71e3312395a5dc9151af675082bdaaa2fc4`. `nanotrack_head_sim.onnx`: 726,198 bytes, SHA-256 `0d8c0637be849f092cc7236cae02e55c8b9455ebe37ba50601d6115db4247cd9`.
- **Licence (unclear):** the repository has no licence file (`gh api repos/HonglinChu/SiamTrackers/license` returns 404), and it is the only published source of these weights (OpenCV's `opencv_extra` download script points to it). The captain chose Nano on 2026-11-02 knowing this. Because the licence is unclear, the files are fetched at deploy time and never redistributed through this repository. The Apache-2.0 alternative is `opencv_zoo`'s `object_tracking_vittrack_2023sep.onnx` (about 4 points less accurate in the tracker scout); switching needs only a new pinned file here.
- **Why:** the shared VM has no manual step, matches how `media-tools.sh` handles ffmpeg, and a mismatching download is refused rather than loaded.
- **Rejected:** committing the binaries (licence); an unpinned download (a moved upstream file would change tracking silently).
- **Links:** [`../.scripts/tracker-models.sh`](../.scripts/tracker-models.sh), [`../.scripts/native-services.sh`](../.scripts/native-services.sh), [`../.scripts/test-native-services.sh`](../.scripts/test-native-services.sh).

### 2026-11-02: Library cards trade info lines for a bigger thumbnail
- **Decision:** `IncidentCard` shows only the incident type, official status, title and one-line summary under the thumbnail. The file name and "Added" date are in the title tooltip; evidence and version counts are only in the "..." menu.
- **Why:** the earlier cards led with a larger thumbnail. Card height is fixed by the viewport grid (PR 264), so every info line removed gives the thumbnail height (93 to 137 px at 1440x900). The pre-shadcn card (before PR 255) had a 16:9 thumbnail; PR 255 cut it to 96 px, PR 260 to 80 px and PR 264 made it fill what the info left.
- **Rejected:** shrinking the summary or title (the title and type are what people scan for).

### 2026-11-01: Evaluation V2 runs on main with incident-contract-v4, in a layered eval/v2 package beside the frozen V1 code
- **Decision (evaluation owner, 2026-11-01):** Evaluation V2 measures several models and the whole application.
  - **Scope:** incident fields, objects, evidence boxes, chatbot (incident and library scope), AI dashboard, tokens and cost, latency and reliability.
  - **Contract:** `main` with `incident-contract-v4`, pinned to one SHA at the freeze.
  - **Code:** a new layered package under `eval/` (core, adapters, datasets, tasks with scorers, statistics, reporting). It sits beside V1's flat modules, which stay as they are, so V1 results remain reproducible.
  - **Workflow:** a dedicated worktree, one short-lived branch per PR from the latest `main`, and draft PRs.
  - **Production-side parity work** goes in separate PRs: a prompt registry for every production prompt family, per-stage provenance on analysis runs, and experimental production profiles. Agent restarts and shared-service changes are still asked for each time.
  - **No default-model change.** The console default (Cosmos 3 Nano) and the agent default (Cosmos 3 Super) are both evaluated before any recommendation.
- **Why:**
  - Main already holds everything V2 measures: the production pipeline, the chatbot and the dashboard with "Ask for a chart".
  - `origin/mvp3` adds contract v5's optional `last_handled_by`, naming rules and multi-video incidents, which the 80-clip ground truth cannot score. It has been idle since 30 Oct, with no merge PR.
  - A separate package keeps every dimension runnable, testable and reportable on its own without touching V1.
- **Contingency:** if mvp3 merges, V2 results stay valid for their frozen SHA, and a v5 run is a separate version. Eval is already forward-compatible ([analysis-schema](analysis-schema.md#3-validation-id-only-repair-and-outcomes)).
- **Alternatives rejected:**
  - waiting for mvp3 (unknown date, and main keeps diverging);
  - extending V1's P1-shaped runner in place (it would grow into a monolith);
  - adopting an external harness such as NAT `nat eval`, Inspect or promptfoo as the runner (weak fit for direct-model arms, offline re-scoring and retry-proof caps; individual metric formulas can still be reused as scorers).
- **Links:** [methodology v2.0 (proposed)](../eval/methodology/evaluation-methodology-v2.0.md), [pre-registration skeleton](../eval/methodology/evaluation-v2-preregistration.md).

### 2026-11-01: Evaluation V2 keeps model and pipeline comparisons apart, and its new references are AI-first with tiered human verification
- **Decision (evaluation owner, 2026-11-01):**
  - **Track A** sends the same P1 request to every video-capable model. It runs first and is the only cross-model ranking.
  - **Track B** runs the production profile (caption pass, P1, grounding, zoom) for Nano and Super. It is compared with Track A within each model only. Every record names the model of every stage.
  - **Person tracking** is off in Track B. A tracking-on crop condition is added only if the shared perception stack is approved.
  - **New references** for evidence boxes, chatbot questions and dashboard requests are generated by Claude (in Claude Code) and, for boxes, an offline open-vocabulary detector. Deterministic code checks and a separate blind validation pass follow.
  - **Every record carries a tier:** `ai_proposed`, `ai_validated` or `human_verified`.
  - **People review** about 20% stratified, including a random sample of AI-validated records, plus every flagged record. **Primary metrics use human-verified records only.**
- **Why:**
  - A cross-model ranking is only fair when every model gets the same request. Production adds steps (captions, zoom) that change the stored report, and that is a separate question.
  - V1 showed that AI-assisted labels are workable when they are traceable and never presented as human-verified.
  - Neither generator is a model under test.
- **Alternatives rejected:**
  - full human annotation (not feasible for the team);
  - the production grounding model (Cosmos 3 Super) as the box generator (it would grade itself);
  - unverified AI references counted as ground truth.
- **Open:**
  - the judge family;
  - the repeat count;
  - reviewers;
  - whether chat questions derived from the ground truth are accepted, given they break the MVP2 blind-authoring rule;
  - where reference text is stored;
  - an R2 scratch prefix for the experiment agent's caption pass;
  - an embedding key for the evaluation host.

  See [methodology v2.0 §10](../eval/methodology/evaluation-methodology-v2.0.md#10-open-decisions).
- **Links:** [methodology v2.0](../eval/methodology/evaluation-methodology-v2.0.md).

### 2026-11-01 (proposed): Caption windows go through a scratch-store port; experiments run captions inline or under an approved R2 prefix (X16)
- **Decision:**
  - **Port:** the caption pass keeps its window clips behind `ScratchStorage` (`put_video`, `signed_url`, `release` once a window's call is over, `delete_prefix`). The R2 store (`ScratchStore`) is confined to a root, default `scratch/analyze`, which production uses unchanged: it refuses a key outside the root, and a delete of the root or of one level under it.
  - **Experiments:** `experiment_captions` runs production's caption pass in an experiment (same settings, prompts, model, retries and P1 context message), and `max_caption_calls` (required) caps its HTTP attempts, retries included. There is no default store.
    - **`inline`** sends each window as a base64 data URL and stores nothing, so it needs no shared storage and works with cropping on. Its feasibility depends on the endpoints accepting a base64 video, and up to what size: unverified, it needs a gated live probe (one approved model call). A window over 8 MiB is not sent.
    - **`r2`** needs the owner-approved prefix in `INCIDENT_EXPERIMENT_SCRATCH_PREFIX` (a folder under `scratch/` other than `scratch/analyze`), and is refused (409) without it. Each window is deleted as soon as its call is over. Experimental crops still refuse an agent holding R2 settings, so `r2` needs `skip_crops`.
  - **A pass that cannot run or finish** (short clip, a window over the inline limit, the cap, ...) is skipped as in production: P1 runs without context, the flags say `chunking.enabled: false`, and `experiment.caption.skipped` says why.
  - **Every window finishes before the scratch delete:** a failed window no longer leaves the others uploading or calling (before, a late upload could land after the delete, and late calls could miss the run provenance). Production's successful pass is unchanged.
- **Why:** Track B could not measure the caption effect, because experiments skipped the caption pass: the remote model must fetch each window, and the experiment agent has no R2 settings (blocker X16).
- **Open (owner decision, X16):**
  - **(a) `r2`:** approve the prefix (for example `scratch/eval`), add a bucket lifecycle rule on it, and give the experiment agent R2 credentials, ideally limited to that prefix.
  - **(b) `inline`:** approve the live probe of a base64 video on each endpoint Track B uses.
  - **(c) Keep captions out of Track B.**
  - **Track B** then needs a profile that declares the caption stage and its cap (the eval adapter, separate).
- **Rejected:**
  - a local HTTP server for the windows (Switchyard cannot reach the laptop);
  - writing to `scratch/analyze` from experiments (that prefix belongs to production);
  - refusing a window over the inline limit with a 400: its size is known only after the cut, and the eval adapter stops a whole run on a refusal;
  - an uncapped experimental pass: the eval needs a worst case for every stage;
  - letting experimental crops run on an agent with R2 settings: the scratch prefix stays the single exception.
- **Links:** [`chunk_captions.py`](../../../../../services/agent/src/vss_agents/utils/chunk_captions.py), [caption pass](vm-api-contracts.md#caption-pass-chunked-captioning-incident_chunking_enabled), [experimental captions](vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b)

### 2026-11-01: Experimental requests can cap the zoom look, track objects and return the pre-zoom P1 report; captions wait for a scratch store
- **Decision:** an experimental crops-on request may set:
  - `max_zoom_calls`: a per-request cap on the zoomed second look's HTTP attempts, applied to a capped copy of the shared namer. Items beyond it keep a `zoom_gap`. The refusal is also counted in the run provenance;
  - `experiment_object_tracking`: the object tracker under its own detector budget.
- **Response:** every experimental response carries `experiment.p1_report`, the validated P1 report before zoom corrections. Every located evidence entry, production included, records the detector's unpadded `detected_box`.
- **Why:** Evaluation V2's production track (Track B) measures the production pipeline in experiment agents.
  - Each step needs its own cap, because zoom calls were uncapped (X17).
  - Object tracking must be switchable there.
  - The zoom effect must be measurable without extra calls: compare `p1_report` with the final report.
  - Crop scoring needs the unpadded box. The stored box is padded by 5%, so scorers had to estimate.
- **Rejected:** counting zoom calls in `max_crop_calls`, which would change the meaning of an existing cap that V1's end-to-end profile used; requiring a zoom cap on every experiment, which would break V1's configs; running the caption pass in experiments now. That pass sends window clips to the model by signed URL, an experiment agent holds no R2 settings by design, and a dedicated scratch prefix is a shared-storage change that needs the owner's approval (X16). Captions in experiments are now wired behind `experiment_captions` (the X16 entry above).
- **Links:** [contract](vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b), [data](data.md), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py)

### 2026-11-01: Every analysis returns its run provenance, and the console keeps it in the run's notes
- **Decision:** `/analyze` returns `provenance` (`incident-run-provenance-v1`) on every response and in the `422` detail. It holds:
  - the agent's commit (`git rev-parse` once at startup, or `VSS_AGENT_GIT_SHA`) and whether the tree was dirty;
  - the analysis flags: what this request ran (experiment, caption pass, person tracking, set-of-marks, object tracking, zoom), over the agent's settings. An experiment never runs tracking or marks, and runs the caption pass only when it asks for it (`experiment_captions`), so flags read from the environment alone would describe a run that never happened;
  - for each stage used (caption, P1, RP1, grounding, zoom, object tracking, revision embedding): its model, its prompt hashes from `contracts/prompts/`, and every HTTP attempt, with failed and cap-refused attempts, tokens and time. An attempt that returns no usable answer (a P1 reply the contract rejects, a runaway, a zoom reply its strict check rejects, any status other than 2xx) is failed.
  - The console writes it into `model_runs.notes.response.provenance` with the attempt, once.
- **How calls are counted:** a per-request context variable (`run_provenance.collecting`). It reaches the evidence step's tasks and `asyncio.to_thread` workers, so the detector, zoom, caption, P1 and RP1 calls record themselves without threading a meter through the pipeline. The object tracker and the head search set their stage with `stage_scope`.
- **Why:** Evaluation V2's production track needs to know, per run, exactly which models, prompts and flags produced a report, and what it cost. Before this:
  - P1 and RP1 usage left production responses;
  - caption telemetry was only logged;
  - production grounding was not counted;
  - zoom calls were never counted (X17);
  - nothing named the agent's code.
- **Rejected:**
  - Explicit meters passed through `collect_evidence` and every detector copy: far more plumbing, and a copy missed is a silent gap.
  - Reading the version from package metadata: the VM's editable install keeps the install-time version across `git pull`.
  - Storing provenance only in the agent's logs: not tied to the run row, and not kept.
- **Open:** requests that fail outright (`502`/`504`/`500`) still return no provenance. Gateway mode records its P1 usage in `response.usage` as before.
- **Links:** [`run_provenance.py`](../../../../../services/agent/src/vss_agents/utils/run_provenance.py), [contract](vm-api-contracts.md), [notes](analysis-schema.md#immutable-notes-model_runsnotes)

### 2026-11-01: Every model prompt besides P1 and RP1 lives in one registry, contracts/prompts/
- **Decision:** the prompts below move byte for byte from code literals into `contracts/prompts/` (one file each, with a `registry.json` that pins each SHA-256 and names who uses it):
  - the caption pass's system, window and time-range prompts;
  - the caption context and set-of-marks preambles;
  - the reviewer-instruction preamble;
  - the grounding and head-search prompts;
  - the zoomed second look's blind-look and merge prompts.
- **Agent:** reads its prompts from the copy `sync.py` vendors, through `incident_contract.prompt()`, `render_prompt()` and `prompt_sha256()`. All three check the hash; placeholders are `{{name}}` and render in one pass.
- **Console:** reads the reviewer preamble from the registry at runtime, so both analysis modes share one file. Its chart prompt stays built from the TypeScript allowlist, and `npm run export:prompts` exports it (and the allowlist) to `chart/`, with a drift test.
- **Proof the move is exact:** the request goldens (`contracts/golden/`) pass unchanged.
- **Why:** Evaluation V2 records each stage's prompt version. Prompts that were literals scattered across four agent modules and two console files had no version to record, and could change unseen.
  - One registry gives each prompt a sha256 to record (run provenance, next).
  - It gives a single place to read for a review.
  - It makes one copy of the preamble shared by the console and the agent, which were two copies kept equal by hand.
- **Rejected:**
  - Extending the experiment registry (`contracts/experiments/`): that one is append-only P1 variants under test, not production prompts.
  - Moving the chart prompt into a file the console reads: it is generated from the allowlist the parser enforces, so the TypeScript must stay its source.
  - Keeping literals with only a hash check: two sources of truth.
- **Links:** [`contracts/prompts/`](../contracts/prompts/README.md), [`contracts/golden/`](../contracts/golden/README.md), [`sync.py`](../contracts/sync.py)

### 2026-11-01: Request goldens pin every model request, checked by each producer
- **Decision:** `contracts/golden/` holds the exact request bodies the profile sends to models, one JSON file per kind with named cases:
  - P1 (base, reviewer instruction, caption context, set-of-marks, both);
  - RP1;
  - the caption pass;
  - grounding;
  - the zoomed second look;
  - the dashboard chart request.
- **How it is checked:**
  - Every producer (console, eval, agent) has a test that builds its requests with its own code and compares them with the cases naming it, and asserts it covers all of them.
  - P1 and RP1 are therefore equal across producers.
  - The other prompts are pinned before Evaluation V2 records them as a run's provenance.
- **Comparison and references:**
  - Bodies compare as JSON values. The agent may add `"stream": false`; inline images compare as a placeholder.
  - The P1 prompt and `response_format` are referenced by path and sha256 rather than copied.
- **Why:** Evaluation V2 compares models through the production pipeline. Its results mean something only if the requests it measures are the ones production sends.
  - Before this, only P1 had a parity check (eval against the console, and Stage 3's preflight against the agent).
  - The caption, grounding, zoom and chart prompts were unversioned literals that could drift unnoticed.
  - A golden makes every change to them a visible diff, and the planned move of those prompts into a registry must leave the goldens unchanged.
- **Rejected:**
  - Copying the full P1 prompt and schema into each case: 27 KB per case, and every contract bump would show the same diff several times.
  - Snapshot tests per producer: they prove nothing about two producers agreeing.
  - Comparing serialized bytes: Python and JavaScript serialize whitespace and `0.0` differently, while the server parses JSON.
- **Links:** [`contracts/golden/`](../contracts/golden/README.md), [analysis request](analysis-schema.md#2-the-analysis-request-identical-to-eval-p1)

### 2026-11-01: Template chat answers from the report version in prose, and the default chat search client searches nothing
- **Decision:**
  - **Composed answers:** in the chat route's template mode (no model), a question about a version that is not official, or about a draft, is answered by `utils/report_answers.py` from that version's report:
    - the timeline in time order for a what-happened question;
    - otherwise the people, the objects with their holders, what was taken (the timeline's takings, or that the report doesn't say), what could cause harm (the instruments with their threat levels), the incident window or an item's time, the severity or the type. A compound question gets each part answered;
    - otherwise the matching timeline events;
    - otherwise "This report doesn't mention ...", with no citations.
  - **Names and ids:** items are named by their labels or descriptions. The ids the P1 timeline uses as references ("E1 strikes E2 with I1") are resolved to those descriptions and kept only in the structured citations. An id is written in the prose only when the question asks for ids. The console's citation chips under an answer show the item's name ("Person in light shirt"), never its id.
  - **Default search client:** the route's default (`DisabledSearchClient`) searches nothing. A question about the official version (decision 2026-10-24, unchanged) and a library question get an answer saying that this chat mode does not search that scope.
- **Why:** on 2026-11-01 the localhost console (vm mode, the VM agent on `main`) answered "What happened, in order?" with "5 relevant item(s) were identified: human (E1) in vc8328cb9cdcdfa99fa8 (incident at 134s); ...". The template ranked evidence items by keyword: a question with no item words got the first five items. It never read the timeline or the description, and its formatter wrote the ids into the prose. The default in-memory client also served its demo incidents (`Assault007`, `Burglary005`) as if they were real for every library question.
- **Rejected:**
  - removing the ids from the old sentence: it would still list items for every question;
  - answering the official version from its saved report as well: that supersedes the 2026-10-24 decision (Gate M2);
  - wiring the real search store or a model into this mode: that is grounded chat (P5 and P6), behind the same gate.
- **Links:** [`report_answers.py`](../../../../../services/agent/src/vss_agents/utils/report_answers.py), [`incident_chat.py`](../../../../../services/agent/src/vss_agents/api/incident_chat.py), [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentschat), [2026-10-24 decision](archive/decisions-superseded.md#2026-10-24-chat-about-the-official-version-uses-the-in-memory-chat-search-client-for-mvp2-superseded-2026-11-06).

### 2026-11-01: The dashboard breaks ties in byte order (COLLATE "C"), whatever the database collation
- **Decision:** every text tie-break in `get_incident_dashboard` (types, entity, instrument and asset labels, model names) says `COLLATE "C"`. The function is otherwise unchanged (migration `20261101120000_dashboard_byte_order_ties.sql`).
- **Why:** ties followed the database's default collation. en_US ignores spaces, hyphens and case at the first level and C does not, so two databases with the same rows could rank ties differently ("car-door" and "carbon"; "Unknown model" and "nvidia/..."). The order also decided which tied labels made a top-3 or top-8 cut. Evaluation V2 checks dashboard figures three ways (the SQL in a C.UTF-8 harness, a Python recount in byte order, and the console's chart code), and those checks only hold for finals if finals breaks ties the same way.
- **Rejected:**
  - making the recount follow en_US: glibc and ICU versions differ, and finals' collation was not checked;
  - leaving ties to the database: it is not deterministic across databases.
- **Links:** [migration](../supabase/migrations/20261101120000_dashboard_byte_order_ties.sql), [`data.md`](data.md#get_incident_dashboard).

### 2026-11-01: Instruments and assets are followed by a seeded OpenCV tracker corrected by the detector (flag, off by default)
- **Decision:** behind a new agent flag `INCIDENT_OBJECT_TRACKING_ENABLED` (off unless `1`, `true`, `yes` or `on`; production requests only; independent of `INCIDENT_TRACKING_ENABLED`), the evidence step follows every located instrument and asset through the clip. The seed is the item's own unpadded detector box at its `timestamp_seconds` (`CropResult.detected_box`). `utils/object_tracking.py` decodes the clip with OpenCV at about 4 fps, scaled to at most 960 px, and runs a single-object OpenCV tracker forwards and then backwards from the seed, up to 12 s each way. Every 2.5 s, and at once when the tracker fails, it asks the existing open-vocabulary detector (`DefaultDetector.detect`, on the whole frame) for the item's label and takes the detection that overlaps the tracked box most; at IoU 0.3 or more the box is re-anchored (the tracker is re-initialised on it) and the sample scores as detected. Two misses in a row, or a tracker failure with no agreeing detection, end the segment. The track has the shape of a person track (`utils/track_evidence.py` `Track`: `{t, box, score}` samples, score -0.1 for tracked and not detected), is stored as `<itemId>-track.json`, and sets `track_first_seen_seconds`, `track_last_seen_seconds` and the best-moment frame and crop exactly as a person track does; the entry also carries `track_source: "object-tracker"` (person tracks have none). The console reads it unchanged (overlay, presence bar, scrubber). Every detector call goes through the request's `CropCallBudget` (default 80, `INCIDENT_OBJECT_TRACKING_MAX_DETECTOR_CALLS`) and the whole run stops at 120 s (`INCIDENT_OBJECT_TRACKING_MAX_SECONDS`), keeping what it has. The `/analyze` response carries `object_tracking` (`{enabled, seeds, tracked, tracker, elapsed_ms, time_cap_reached, skipped, detector, items}`, per-item samples, detector calls, re-anchors, lost, time) and the console copies it into `model_runs.notes.response.object_tracking`. The report's own `first_seen`/`last_seen` are never rewritten; contract v4 is unchanged.
- **Why a seeded tracker plus the detector, not the alternatives:** the person path (DeepStream RT-DETR warehouse, NvDCF) is closed-vocabulary and would need a new open-vocabulary DeepStream model for arbitrary crowbars and cash registers (a new model, a new deployment, GPU memory). Calling the open-vocabulary detector on every sampled frame costs a VLM call per frame (about 5 a second of clip); a cheap tracker carries the box between calls, so a clip costs one call per 2.5 s and item, bounded by the budget. The detector still corrects drift and says when the item has gone. OpenCV is already an agent dependency, and the existing decoding, locate and budget code is reused.
- **Why the installed OpenCV decides the tracker:** the agent's `opencv-python-headless` 4.13.0 has no contrib modules, so CSRT, KCF, MOSSE and `cv2.legacy` do not exist; only `TrackerMIL` does, and it never reports failure (it keeps returning a drifting box). `select_tracker()` therefore prefers CSRT, then KCF, then MIL where the build has them, and the loss test does not rely on the tracker's own flag: a segment also ends when the box leaves the frame (under 25 % visible), shrinks under 4 units, or changes area by more than 6 times, and when the detector misses twice in a row, in which case the samples after the last detector agreement are dropped (the tracker may have drifted). `object_tracking.tracker` records which tracker ran. Switching the dependency to `opencv-contrib-python-headless` for CSRT is a follow-up for the end-to-end test to justify.
- **Concurrency:** the tracker runs as a task beside person tracking (it needs only the locate step), not after it, so it adds no wall time when the person path is slower. Object tracks are deliberately exempt from the person rules (`is_solid`, `visible_samples`, the tracker-only grace): they feed no association, and a tracker-only box between two detector checks (up to 2.5 s) is how an object track works, while drift is bounded by the detector misses, the geometry limits and dropping the samples after the last agreement. An object's evidence frame is its track's first sample ([decision](#2026-11-03-an-items-evidence-image-is-the-first-second-its-track-sees-it)).
- **Alternatives rejected:** an open-vocabulary DeepStream model (above); per-frame detection (above); an optical-flow-only follower (no appearance model, loses the item on any occlusion); changing the report's `first_seen`/`last_seen` from the track (a contract change, and the model's reading stays the audited fact); a console change for the overlay (none was needed).
- **Open:** the live check waits for the end-to-end test (captain, 1 Nov): IMG_9170_480, IMG_4569_480 and IMG_8206_480 with the flag on and off, to see which objects get tracks, whether the box stays on the item, the presence bars and clips, the extra detector calls and the added time. The flag stays off until then.
- **Links:** [`object_tracking.py`](../../../../../services/agent/src/vss_agents/utils/object_tracking.py), [`track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [`crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [contract](vm-api-contracts.md#post-apiv1incidentsincident_idanalyze), [data](data.md)

### 2026-11-01: The console no longer shows the model event timeline or the model-reported uncertainties
- **Decision:** the report page drops the "Model event timeline" section (with its "not consistent with the detected incident window" notice) and the "Model-reported uncertainties" section; Compare drops its timeline rows. `ReportView.modelOutput` no longer carries `timeline`, `timelineCheck` or `uncertainties`. Contract v4, the agent, eval and stored payloads keep `timeline` and `uncertainties`, so an edit saves them as the parent had them and the run details still show the stored report.
- **Why:** the roadmap's purpose (captain, 1 Nov) is better evidence; model-written narrative that disagrees with the detected window and is not scored does not contribute to that. The incident window, first and last seen, evidence, tracking overlay, presence bars and clips stay.
- **Alternatives rejected:** removing the fields from the contract (a version bump across agent, eval and fixtures, and the model still returns them); hiding the sections behind a flag (dead code).
- **Links:** [`ReportPane.tsx`](../incident-console-v2/src/sections/reports/components/ReportPane/ReportPane.tsx), [earlier timeline removal](#2026-10-28-the-report-timeline-is-being-removed), [`analysis-schema.md`](analysis-schema.md#three-classes-of-report-fields).

### 2026-11-01: Run history and run details no longer list unscored model output
- **Decision:** run history drops its "Unscored model output" line (and `RunHistoryEntry.enrichmentIssues`), and the run-details panel drops its "Issues in unscored model fields" alert; the repair panel's first-pass list shows only the ID violations that were repaired. Validation still runs and `model_runs.notes` still stores every violation code, so the stored record, contract v4, `validate.ts`, the agent and eval are unchanged. Real failures (contract violations that fail a run) still show, with their labels.
- **Why:** follows [the timeline removal](#2026-11-01-the-console-no-longer-shows-the-model-event-timeline-or-the-model-reported-uncertainties) (captain: "yes remove"): the `TIMELINE_*` codes are the main content of that list, and unscored output does not improve evidence.
- **Alternatives rejected:** dropping the stored codes (loses the record and changes the notes shape); removing the `describeCode` labels (failed runs still list them).
- **Links:** [`RunHistory.tsx`](../incident-console-v2/src/sections/analysis/components/RunHistory/RunHistory.tsx), [`ReportRunDetails.tsx`](../incident-console-v2/src/sections/reports/components/ReportRunDetails/ReportRunDetails.tsx).

### 2026-11-01: Set-of-marks prompting draws numbered person tracks on the clip P1 sees (flag, off by default)
- **Decision:** behind a new agent flag `INCIDENT_SOM_ENABLED` (off unless `1`, `true`, `yes` or `on`; effective only with `INCIDENT_TRACKING_ENABLED` on, production requests only), `/analyze` runs the perception stack **before** P1 instead of after it (beside the caption pass), numbers the person tracks 1, 2, ... in order of first appearance, and renders a marked copy of the clip with OpenCV (a box per track per frame, one colour per number, the number in a filled tag kept inside the frame; encoded H.264 by `ffmpeg`, no audio). The copy goes to the caption pass's R2 scratch area (`scratch/analyze/<video key>/<run id>-marks/marked.mp4`, through `chunk_captions.ScratchStore`), its one-hour signed URL is the P1 `video_url`, and the prefix is deleted right after P1 whether P1 succeeded or not. One more user message, added the way the caption pass adds its context (`p1_request_body`), says the boxes are overlays not to be described, lists each number's on-screen span, and asks for the box number in square brackets at the end of each human entity's `label`. After P1 the agent reads the number, keeps it only when it names a track with a sample within 1 s of the entity's `timestamp_seconds` and no earlier entity took it, strips every bracketed number from the labels (before RP1, the evidence step and the stored revision; `raw_output` keeps the model's text), and the evidence step takes those entity-track pairs as they are and associates the other entities by box overlap with the tracks no mark took. The tracking run is reused, so perception runs once. Crops, the zoomed look and stored frames are cut from the original clip. `tracking.marks` records `{rendered, parsed, fallback, invalid, skipped, elapsed_ms}`.
- **Why:** on IMG_4569 the IoU association matched neither man to any of six tracks (31 Oct, PR 397), because the locate step's box and the tracker's box disagreed. If the model sees the tracker's own boxes, its entity ids can name tracks directly and the association stops depending on a second detector agreeing with the first.
- **Why the label:** contract v4 entities have no name field; `label` is the short free-text field, and it is stripped before anything reads it, so the prompt file, `inference.json` and the schema stay untouched and contract v4 holds.
- **Why soft:** no tracks, no `ffmpeg`, no R2, or a render or upload failure leaves `marks.rendered` false with a reason, and P1 runs on the original clip exactly as with the flag off; a missing or invalid number falls back to box overlap.
- **Rejected:** drawing marks on still frames for a separate call (a second VLM call and a second notion of time); passing the track boxes as text coordinates (the model cannot ground numbers it does not see); adding a `track` field to the schema (a contract change and a bump for every consumer); keeping DeepStream's object ids as the numbers (long, sparse numbers the model copies less reliably).
- **Open:** the live check is deferred to the end-to-end test after all PRs land (captain, 1 Nov). One run before the deferral (IMG_4569, Cosmos 3 Nano, 31 Oct): 4 of 4 person entities matched by mark (0 fallback, 0 invalid), and no description mentioned a box or number, but the tracker had split the two men into four tracks and the model reported **four** person entities, one per mark, so people were duplicated. The flag stays off until the end-to-end test shows association improves without inflating the entity count.
- **Links:** [`set_of_marks.py`](../../../../../services/agent/src/vss_agents/utils/set_of_marks.py), [`incident_report_gen.py`](../../../../../services/agent/src/vss_agents/tools/incident_report_gen.py), [contract](vm-api-contracts.md#post-apiv1incidentsincident_idanalyze)

### 2026-11-01: The console's ffmpeg and ffprobe come from npm; the system copy is only a fallback
- **Decision:** `incident-console-v2` depends on `ffmpeg-static` (5.3.0, a native arm64 ffmpeg 6.0 on macOS) and `@ffprobe-installer/ffprobe` (2.1.2, native arm64 ffprobe 4.4.1 on macOS), both pinned exactly. `src/lib/video/host-binaries.ts` picks each binary in this order: `FFMPEG_PATH` or `FFPROBE_PATH` when set, the bundled file when it exists, else the bare name on PATH. Every console spawn of ffmpeg or ffprobe goes through it. Both packages are in `serverExternalPackages`, so Next.js leaves the binaries in `node_modules`. `ffmpeg-static` downloads its binary from GitHub during `npm install`; a machine without GitHub access falls back to PATH.
- **Why:** the captain asked that the console run without anyone installing ffmpeg by hand; a laptop without ffmpeg failed on upload, frame and clip.
- **Why `@ffprobe-installer/ffprobe` and not `ffprobe-static`:** `ffprobe-static@3.1.0` (last published 2022) ships `bin/darwin/arm64/ffprobe`, but that file is an x86_64 Mach-O and fails with "bad CPU type" on Apple Silicon. `@ffprobe-installer/ffprobe` picks a native binary per platform through `optionalDependencies`. Chosen on firstmate's steering instruction (1 Nov 2026).
- **Licence:** `ffmpeg-static` is published under GPL-3.0-or-later and its binaries come from third-party builds; the console is private and does not redistribute them, but a public release would need that reviewed.
- **Alternatives rejected:** keeping PATH only (the failure the captain wanted removed); `ffmpeg.wasm` (slower, a larger change to the frame and clip routes); `apt-get install` or Homebrew in the setup steps (a system change on each laptop); `ffprobe-static` (broken on arm64, above).
- **Links:** [`host-binaries.ts`](../incident-console-v2/src/lib/video/host-binaries.ts), [console README](../incident-console-v2/README.md#run-it), [`incident-start`](../skills/incident-start/SKILL.md)

### 2026-11-01: Alert rules and the caption display are removed; the caption pass stays as report context
- **Decision:** the alert rules feature (agent `utils/chunk_alerts.py`, its rules file, `INCIDENT_ALERTS_ENABLED`, the `chunk_alerts` and `alerting` response fields, the console's Alerts box and timeline flags) and the report page's caption list (`ChunkTimeline`, `chunkTimelineFrom`, `chunk-seek`) are deleted. The agent's `/analyze` response no longer returns `chunk_timeline` or `chunking`, and the console no longer copies `chunkTimeline`, `chunking`, `chunkAlerts` or `alerting` into `model_runs.notes`. The caption pass itself (`INCIDENT_CHUNKING_ENABLED`) is unchanged: its timed captions still go to P1 as one context message, and its telemetry or skip reason is logged. The unused finals tables behind an earlier chunk search (`chunk_embeddings`, `search_chunks`), created outside any migration, were dropped.
- **Why:** the captain (1 Nov 2026): "ok i dont want both features on ui. Remove them and the db storing them. They are not used for report or anything." The plan's aim is better evidence; neither the alerts nor the caption list feed the report, while the captions as P1 context do (they are what lets P1 catch the fall at about 82 s in the demo clip).
- **Rejected:** hiding the UI but keeping the fields and notes (stored data nothing reads, and the captain asked for the storage to go); removing the caption pass too (it improves the report). Existing run notes that already hold the old keys are left as they are; nothing reads them.
- **Links:** [vm-api-contracts.md](vm-api-contracts.md#caption-pass-chunked-captioning-incident_chunking_enabled), [chunked captioning decision](#2026-10-31-chunked-captioning-before-p1-the-gateways-fixed-2-fps-and-ignored-num_frames)

### 2026-11-01: The caption pass is on by default in vm mode; ffmpeg comes from a repo-local static build
- **Decision:** `native-services.sh` exports `INCIDENT_CHUNKING_ENABLED=1` for `vss-agent` unless the env file (or the caller) sets it, the same way as `INCIDENT_TRACKING_ENABLED`; `0` turns it off. The profile `.env` says `1` and documents the window (20 s) and overlap (2 s) beside it. Before it starts the agent, `native-services.sh` runs `.scripts/media-tools.sh install`, which puts `ffmpeg` and `ffprobe` from the BtbN static build `ffmpeg-n8.1-latest-linux64-gpl-8.1` (SHA-256 checked against the release's `checksums.sha256`) into `<repo>/.tools/ffmpeg/bin`, gitignored, unless both are already on `PATH`; that directory is first on the agent's `PATH`, and `status` prints both tools with their versions or `MISSING`. The agent code keeps the flag off by default.
- **Why the caption pass:** it improves the evidence a report is built from: a whole-clip P1 pass samples 64 frames, so a short event in a long clip can fall between them, and the window captions hand P1 those events as context.
- **Why the repo-local `.tools/`, not `~/.local/bin` or the agent venv:** the shared agent is started by whichever team member runs `start.sh`, so a per-user prefix would make `ffmpeg` depend on who restarted it last; the venv is rebuilt by hand and a rebuild would silently drop the binaries. `.tools/` sits beside `.run/` in the shared, group-writable checkout, so one install serves everyone and survives a venv rebuild. No system-wide install, so nothing on the shared VM changes outside the checkout.
- **Why BtbN:** a GitHub release with a published SHA-256 list per asset (johnvansickle publishes only MD5 and is a single personal host), a release-branch build (n8.1) rather than master, and binaries that need only the base glibc libraries (`ldd` finds every library on the VM). The `latest` tag is rebuilt daily, so the checksum proves the download is intact and matches the release, not a fixed build; `VSS_FFMPEG_BUILD` and `VSS_FFMPEG_BASE_URL` override it. The download is about 150 MB and took 20 s on the VM, inside `start.sh`'s 300 s native start budget (the archive fetch is capped at 180 s); a failed install only warns, and the agent then skips the caption pass and tracking as before.
- **Open:** the live check (time and model calls per clip with tracking and the caption pass on) is deferred to the end-to-end test after the current PRs land; the console `/api/analysis` `maxDuration` (360 s) is unchanged until it shows a need.
- **Rejected:** `apt-get install ffmpeg` (a system-wide change on a shared VM); flipping the default in `chunk_captions.py` (every caller of the package, including tests and eval, would change); writing the flags into `.env.remote` (a secrets file that needs asking first, and the script default does the same job).
- **Links:** [`../.scripts/media-tools.sh`](../.scripts/media-tools.sh), [`../.scripts/native-services.sh`](../.scripts/native-services.sh), [operations](incident-profile-operations.md), [contract](vm-api-contracts.md#caption-pass-chunked-captioning-incident_chunking_enabled)

### 2026-11-01: Dashboard displays take the form their data suits
- **Decision:** the six fixed displays keep their numbers and split, but change form. Total reports stays a number with its official and not-yet-official bar. Incidents over time is a stacked area (was stacked bars): a daily series reads as a trend. Incidents by type and Top targeted assets stay ranked bars, because they compare named categories. Severity breakdown is a donut, with the centre showing the reports that have a severity and a list beside it giving each band's exact official and not-yet-official counts; each list row is a button that filters the page, so the list is the keyboard and screen-reader control. `severity_level` is nullable and the bands drop NULLs, so reports with no severity appear as a "No severity" line under the list and the centre then reads "rated"; with no rated reports the panel shows its empty state. The donut stacks above its list at `xl`, where the panel is a third of the row. The heatmap stays custom.
- **Colours:** the severity fills are the severity badges' text colours (`severityChartColor` in `src/lib/ui/severity.ts`: high `#991b1b`, medium `#765300`, low `#174f3b`), each at least 4.5:1 against white, so the donut matches the badges. The split keeps `--chart-1` (official) and `--chart-3` (not yet official). The five `--chart-*` tokens are not used as a categorical set; the split only ever has two series.
- **Why:** the captain found the page too one-sided, all bars. A pie has no second series, so the split sits in the list beside it, and no slice is needed to read a count. Colour is never the only cue: every band is named with its counts.
- **Alternatives rejected:** a pie for the split inside Total reports (that is two series, which a pie cannot show); a donut for incident types (too many categories for a legend that also has to show the split); a line for the trend (the daily series is mostly zero, and a stacked area keeps the split visible).
- **Links:** [`../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx`](../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx), [`../incident-console-v2/src/lib/ui/severity.ts`](../incident-console-v2/src/lib/ui/severity.ts), [architecture](console-reference.md#dashboard-analytics-and-cross-filtering).

### 2026-10-31: Person tracking is on by default in vm mode
- **Decision:** `start.sh` defaults `ENABLE_TRACKING` to `true` in vm mode, so the stock perception stack comes up with the backend, and `native-services.sh` exports `INCIDENT_TRACKING_ENABLED=true` for `vss-agent` unless the env file (or the caller) sets it. The profile `.env` says `true` too. The agent code keeps its own default off, so tests, eval and any other caller of `vss_agents` are unchanged.
- **Why `native-services.sh`, not `.env` alone:** on the VM `native-services.sh` loads `.env.remote` when it exists and never reads `.env`, and that file has no `INCIDENT_TRACKING_ENABLED`; a default in the script reaches the shared agent at its next restart without editing the secrets file. An explicit `false` there still wins.
- **Why it is safe with the stack down:** the agent's tracking step never fails an analysis; with the stack absent (`ENABLE_TRACKING=false`, or a stopped container) it reports `tracking.skipped` and the report is the same as with the flag off. The cost with the stack down is one extra download of the clip.
- **Measured (31 Oct 2026, console path, own agent copy):** 24 s clip 56 s, 49 s clip 79 s, 94 s clip 132 s; GPU 0 peaked at 7744 MiB and 29% (7645 MiB idle with perception up) and returned to 7673 MiB. The console's `maxDuration` (360 s) was not raised: the slowest run took 132 s, and an agent run is bounded by the model's 300 s timeout first.
- **Rejected:** flipping the default in `track_evidence.tracking_enabled()` (it would switch tracking on for every caller of the package, including tests and eval); writing the flag into `.env.remote` (a secrets file that needs asking first, and the script default does the same job).
- **`ffmpeg` and `ffprobe`:** without them every run is skipped with `ffprobe not found`; since 1 Nov 2026 `native-services.sh` installs them ([decision](#2026-11-01-the-caption-pass-is-on-by-default-in-vm-mode-ffmpeg-comes-from-a-repo-local-static-build)).
- **Links:** [`../start.sh`](../start.sh), [`../.scripts/native-services.sh`](../.scripts/native-services.sh), [operations](incident-profile-operations.md#person-tracking-stack-scriptstracking-stacksh-enable_trackingtrue)

### 2026-10-31: The report player draws person tracks, read through a console route
- **Decision:** View mode draws each tracked person's box over the report video from the agent's `<itemId>-track.json` (`TrackOverlay`, one colour per item, interpolated between samples at most 1 s apart, held 0.5 s past the span ends, hidden outside the span and in longer gaps), adds a presence bar to each tracked card and the detail pop-up, and selects a box from a card click. The browser reads the samples from `GET /api/reports/[videoId]/track?revision=&type=&item=`, which looks the key up in the stored revision's evidence entry and reads R2 on the server. `ItemEvidence` gains `track`, `trackUrl` (that route), `trackFirstSeenSeconds` and `trackLastSeenSeconds`; an entry without a key and both span ends has no track. The console copies the agent's `tracking` summary into `response.tracking` of the run's notes. The report's own `first_seen`/`last_seen` (contract v4) stay as they are; the tracked span is shown beside them.
- **Why:** R2 has no CORS rule for the console origin (a preflight from `127.0.0.1:3262` answers 403 without `Access-Control-Allow-Origin`), so a browser `fetch` of a signed track URL fails, unlike `<img>` and `<video>`. Taking the key from the revision, not the query, means the route can read only a track the report names. Interpolating only across short gaps keeps a box from sliding across the frame while the tracker had lost the person. A bar click outside a short span seeks to its start, because most of the bar is clip where the person is not on screen.
- **Rejected:** a signed track URL fetched by the browser (needs an R2 CORS change); inlining every track into `GET /api/reports/[videoId]` (slows every report load by an R2 round trip per person and bloats the view); a route taking the R2 key from the browser (any `evidence/` object would be readable); drawing in Edit mode (the draft's evidence may differ from the stored track; the edit-mode scrubber is separate work).
- **Links:** [`TrackOverlay.tsx`](../incident-console-v2/src/sections/reports/components/TrackOverlay/TrackOverlay.tsx), [`track.ts`](../incident-console-v2/src/modules/reports/domain/track.ts), [`get-evidence-track`](../incident-console-v2/src/modules/reports/application/get-evidence-track/index.ts), [architecture](console-reference.md#report-versions-view-edit-and-history)

### 2026-10-31: Background analysis jobs: a Supabase table and one in-process loop per console
- **Decision:** an upload's analysis is a row in a new `analysis_jobs` table (migration `20261031120000_analysis_jobs.sql`), not a browser request. The browser still uploads and converts each file, then queues its job (`POST /api/jobs`) and polls `GET /api/jobs` every 3 s. A loop inside the console's Node process, started once by `src/instrumentation.ts` (`src/lib/jobs/loop.ts`), claims one queued job at a time with `claim_analysis_job` (oldest first, `FOR UPDATE SKIP LOCKED`), runs `analyseUpload`, the same application code as `POST /api/analysis`, heartbeats every 15 s and stores done (video and revision) or failed (the plain reason). A running job with no heartbeat for 180 s goes back to the queue once and fails on a second stale run. Every attempt of a job uses one video id derived from the job. Retry (failed or cancelled to queued) and cancel (queued only) are conditional updates in the database. All state changes are functions on the database clock.
- **Why:** the merged batch upload ran its queue inside the tab, so closing it lost every file not yet analysed and a long analysis tied the page to a 360 s request. The database already holds every other piece of state and the console already reaches it with the service key, so a table needs no new service, dependency or credential and its progress is visible from any tab. An in-process loop is the smallest runner: the console is a long-lived `next dev`/`next start` process on the laptop, not a serverless function. One job at a time matches the batch upload's load and the Switchyard rate limits. The heartbeat plus stale rule recovers a console restarted mid-job without anyone acting, and the second-stale-run failure stops a job that kills its console from looping forever. A fixed video id per job came out of the live check: a run cut short by a restart had already written its `videos` row, and the re-run under a fresh id left a second row on the same R2 object.
- **Rejected:** a queue service (Redis, BullMQ, pg-boss: a new dependency or service for one console's handful of jobs); a separate worker process (another thing to start, stop and forget on the laptop; the loop lives and dies with the console that serves the page); running the analysis on the VM (the agent does P1 only and does not own `videos` or `model_runs`, so the console's verification and run record would move too); calling the console's own `POST /api/analysis` from the loop (an HTTP hop back into the same process and its 360 s limit); several jobs at once (the agent's single model host and the provider's rate limits make it slower per video, not faster); uploading in the background (the browser holds the file; a tab closed mid-upload loses only that file, and the page says so).
- **Open:** the queue is shared by every console pointed at finals with the loop on, and a job runs against whichever console claims it (its agent or gateway, its code version). `ANALYSIS_JOB_LOOP=off` opts a console out; jobs carry no owner. The jobs list shows the latest 10 finished jobs and there is no pruning; delete old rows by hand if the table grows. A job's R2 object is not checked at enqueue, only when the job runs.
- **Links:** [`../supabase/migrations/20261031120000_analysis_jobs.sql`](../supabase/migrations/20261031120000_analysis_jobs.sql), [`../incident-console-v2/src/modules/jobs/`](../incident-console-v2/src/modules/jobs/), [`../incident-console-v2/src/lib/jobs/loop.ts`](../incident-console-v2/src/lib/jobs/loop.ts), [console-reference.md](console-reference.md#background-analysis-jobs), [data.md](data.md#analysis_jobs).

### 2026-10-31: Dashboard chart requests: a model picks an allowlisted spec, our code fetches the figures, and VSS `chart_generator` draws them
- **Research (what NVIDIA VSS offers):** no natural-language analytics over a relational database, but a drawing service worth reusing.
  - `chart_generator` draws bar and pie images with matplotlib from numbers its caller passes in. It reads no data, so whoever calls it supplies the figures.
  - `get_fov_counts_with_chart` charts one sensor's object counts from the video-analytics API.
  - `multi_report_agent` with `multi_incident_formatter` charts incidents fetched from video analytics, and is enabled only in the `warehouse-operations` and `smartcities` industry configs.
  - `va_retrieval` (`tools/incidents.py`) runs a model-written SQL string on an in-process DuckDB `incidents` table loaded from a bucket.
  - `top_agent` is a conversational loop with `max_history`, the opposite of one input and one output.
  - NVIDIA's overview and agent pages describe no text-to-SQL and no charting over a user's own database.
- **Decision (captain, 2026-10-31):** one request, one static image at the bottom of the dashboard (`POST /api/dashboard/chart {request, chartType, timezone}`; a new request replaces the result, and no history exists to send).
  - **The user** picks bar or pie.
  - **The model** (`CHART_MODEL`, through `vlm-gateway`; superseded on 2026-11-02, see above: the agent's own LLM reads the request) sees only a prompt built from the allowlist plus that request. Its reply counts only if it parses as a strict Zod `ChartSpec` (`modules/dashboard/domain/chart-spec.ts`): metric, dimension, period, incident type and severity, each from a fixed list. Anything else, including an extra key, is a plain "Can't chart that".
  - **Our code** runs `DashboardRepository.getDashboard` and builds the rows, title and labels from the allowlist. No model text reaches the database, the image or the screen, and the model never sees a figure.
  - **`chart_generator`** draws those figures through a new agent route, `POST /api/v1/incidents/charts`. The console reads the PNG from `/static/`, deletes it from the agent's in-memory store and returns it inside its response, so the browser never talks to the agent, and a per-request name means two people cannot swap images. The tool now closes each figure; it used to keep one in memory per chart.
  - **Official and not official:** the counting rule and `DashboardQuery.scope` come from the dashboard fix. A bar chart shows both beside each other, from one `getDashboard` per scope (assets from the per-asset figures the query already returns). A pie has no second series, so it carries the totals in a caption, and `report_status` is a chart of its own. Top instruments stay one series, because the query cuts that list to eight per scope, so a name could read as a false 0; analysis attempts are not reports.
  - **Pie only for a true whole:** type, severity, status, report version and analysis outcome. Anything else answers "that one needs a bar chart". The severity split is gone: `chart_generator` groups bars rather than stacking them, so two splits would crowd the chart.
  - **Time** is the report date, as on the dashboard. The weekday and hour charts say they show when reports were generated; a question about when incidents happened is refused. A trend past 31 bars moves to weeks, then months, and says so, because the tool labels every bar.
  - **`start.sh --mode vm` starts the local gateway too,** only for this. Superseded on 2026-11-02: vm mode starts no gateway, and charts need no `VLM_GATEWAY_API_KEY` on the laptop.
- **Why:** the requirement is real figures only, and a spec from a closed list makes that structural rather than a prompt instruction. The captain chose the VSS service for drawing and accepted static images and its default colours.
- **Alternatives rejected:**
  - *`top_agent` or `va_retrieval`:* see above.
  - *Text-to-SQL:* the model would write what reaches the database.
  - *NAT's `front_end.endpoints` for `chart_generator`:* NAT checks the result with `isinstance(result, list[...])`, which Python refuses, after the tool has drawn. So a small route calls the unchanged tool, as `/analyze` does.
  - *Allowlist and prompt in the agent:* they would live in both TypeScript and Python.
  - *The console calling Switchyard itself:* the console would hold a model key, which the gateway owns.
  - *Recharts in the console (the first version of this feature):* the captain chose the VSS service.
  - *`LLM_NAME` for the model:* laptop settings can hold the template placeholder `<your-model-id>`.
- **Open:** see [status action item 12](status.md#5-action-items).
- **Links:** [`../incident-console-v2/src/modules/dashboard/domain/chart-spec.ts`](../incident-console-v2/src/modules/dashboard/domain/chart-spec.ts), [`../incident-console-v2/src/modules/dashboard/application/generate-chart/index.ts`](../incident-console-v2/src/modules/dashboard/application/generate-chart/index.ts), [`../../../../services/agent/src/vss_agents/api/incident_charts.py`](../../../../../services/agent/src/vss_agents/api/incident_charts.py), [vm-api-contracts.md](vm-api-contracts.md#post-apiv1incidentscharts).
- **Amended 2026-11-06:** `chart_generator` returns a Chart.js configuration that the browser draws, with the PNG as fallback, and the chart kinds are bar, stacked bar, horizontal bar, donut, line and area. See the 2026-11-06 entry above.

### 2026-10-31: The dashboard counts official, else newest, and shows six fixed displays with the official split
- **Decision:** `get_incident_dashboard` counts each video once through `searchable_revision_id` (official, else newest) and returns the official and not-yet-official split. This replaces decision D6 (official reports only; others never put in a category). Counting a report never marks it official: `videos.official_revision_id` is only read. The fixed page is Total reports, Incidents over time, Incidents by type, Severity breakdown, Top targeted assets, and Activity by day and hour, each showing the split. `DashboardRepository` takes a `scope` (`all`, `official`, `not_official`) so natural-language charts reuse the rule. The RPC's `p_scope` defaults to `official`, so a console from before this change, which labels its numbers official, keeps showing only official reports; the current console always sends it.
- **Why:** finals has 0 official revisions, so official-only counting left the dashboard empty. A read-only test changing only that join matched `/library` on total, severity, kind and period. The captain chose the rule, the split and the six displays.
- **Rejected:** marking AI reports official (they are not reviewed); counting in the console from the Library RPC (it would duplicate the SQL aggregates); keeping every panel (the captain picked six; the RPC keeps the other sections).
- **Links:** [`../supabase/migrations/20261031090000_dashboard_official_else_newest.sql`](../supabase/migrations/20261031090000_dashboard_official_else_newest.sql), [`../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx`](../incident-console-v2/src/sections/dashboard/components/Dashboard/Dashboard.tsx), [`architecture.md`](console-reference.md#dashboard-analytics-and-cross-filtering).

### 2026-10-31: Person tracks give matched evidence its best moment and a track file
- **Decision:** behind `INCIDENT_TRACKING_ENABLED` (off in code; on for the VM agent since 31 Oct 2026, [decision](#2026-10-31-person-tracking-is-on-by-default-in-vm-mode)), `/analyze` pushes the clip through NVIDIA's stock perception stack, builds person tracks (stock warehouse detector, people only), and matches each located entity to a track by IoU between the locate box and the track's box nearest the locate second (at least 0.3, within 0.5 s; greedy, one track per entity and one entity per track). A matched entity's frame and crop are re-cut at the track's first sample (since 3 Nov 2026; until then the largest box among samples scoring at least 0.85, see [decision](#2026-11-03-an-items-evidence-image-is-the-first-second-its-track-sees-it)), the track is stored as `<itemId>-track.json`, and the entry gains `track`, `track_first_seen_seconds` and `track_last_seen_seconds`. Unmatched entities, instruments and assets keep today's result. The association time is the locate step's `box_seconds` (where its box was actually found), not the report's `timestamp_seconds`.
- **Why:** one VLM-timestamped frame can show the person small, cut off or hidden, and nothing tells a reviewer how long they were on screen. A tracker follows the same person through the clip, so the evidence shows them at their clearest and the span is measured, not guessed. The stock stack already runs on the VM, so no new service or Python dependency is added.
- **Time base:** frame timestamps from the stack are NTP times, not clip times, so video second = frame_id / fps (the first decoded frame is id 2; nothing is lost at the start, [decision](#2026-11-03-person-tracks-are-read-at-frame-id--fps-and-a-located-box-is-never-replaced-by-a-sample-from-another-moment)). The file replays at end of file with frame ids restarting, so the agent removes the stream itself at duration + 20 s and cuts at the first frame-id decrease; frames are de-duplicated on (id, timestamp) so the replay never shadows the real pass.
- **HDR:** BT.2020 or HLG/PQ clips crash DeepStream, so they are transcoded to BT.709 SDR before the push (never skipped). `ffmpeg` and `ffprobe` must be on the agent host's PATH; a missing one skips tracking, as does any perception failure, which never fails the analysis.
- **Rejected:** associating on the report timestamp alone (the box moves between it and the locate second); replacing the locate step with tracks (instruments and assets need it, and tracks are people only); a Python tracker in the agent (a new dependency and GPU work the stack already does); restarting perception containers from the agent (shared infrastructure); keeping per-sample embeddings (about 4 KB each, unused).
- **Open:** the console does not yet store the `tracking` summary in `model_runs.notes` or draw the track; the live-VM check is recorded in the PR.
- **Links:** [`services/agent/src/vss_agents/utils/track_evidence.py`](../../../../../services/agent/src/vss_agents/utils/track_evidence.py), [`perception_client.py`](../../../../../services/agent/src/vss_agents/utils/perception_client.py), [`vm-api-contracts.md`](vm-api-contracts.md)

### 2026-10-31: Person tracking runs the stock perception stack from its own script, behind ENABLE_TRACKING
- **Decision:** `ENABLE_TRACKING=true` makes `start.sh` run `.scripts/tracking-stack.sh start` on the VM after Phoenix: Kafka, Elasticsearch, Logstash, NvStreamer, the perception init and DeepStream containers, and the video-analytics API, from the stock compose plus `compose.override.yml` plus `compose.tracking.yml`, under the compose project Phoenix already uses (`mdx`). `start.sh` leaves them running on exit ([decision](#2026-11-02-closing-startsh-leaves-the-vm-backend-running)); `tracking-stack.sh stop` stops them by hand. The script stages the RT-DETR warehouse model with `ngc` first, because no container downloads it.
- **Why a separate script:** the tracking stack has its own lifecycle (a 10 minute first start that builds TensorRT engines, a perception container that must be restarted on its own when the pipeline dies while `/ready` still says YES, a 40 GB image set, 7.6 GB of GPU 0), so it must not ride on `vm-ensure-docker.sh`'s 600 s bounded `compose up` or be pulled in by a partial-heal of Phoenix. It also needs `status` and `restart-perception`, which `native-services.sh` does not have.
- **Why Logstash:** `/frames` reads `mdx-raw-*`, and Logstash is the only thing that writes it (Kafka `mdx-raw`, protobuf, to Elasticsearch). `vss-search-analytics-2d-fusion` is out: it writes `mdx-behavior`, which tracks do not use.
- **Why sensor-ms and centralizedb are out:** streams are provisioned over REST (`/api/v1/stream/add`), which never talks to sensor-ms. Its only link is a `service_started` dependency of perception, reset in `compose.tracking.yml`. Two fewer containers and no Postgres.
- **Other choices:** `HOST_IP` is the VM's current address, exported for the run (Kafka advertises it), and the secrets file is not rewritten. NvStreamer loop playback is off through a copied config mounted over the container's.
- **Rejected:** folding it into `vm-ensure-docker.sh` (bounded timeout, heals Phoenix too); a second compose project (the stock fixed container names collide anyway); keeping sensor-ms for NVIDIA's SEI sensor-id path (not needed now).
- **Links:** [`../.scripts/tracking-stack.sh`](../.scripts/tracking-stack.sh); [`../compose.tracking.yml`](../compose.tracking.yml); [operations §2](incident-profile-operations.md).

### 2026-10-31: Chunked captioning before P1: the gateway's fixed 2 fps and ignored `num_frames`
- **Decision:** with `INCIDENT_CHUNKING_ENABLED=1` on the agent, a production `/analyze` request runs a caption pass before P1 (`services/agent/src/vss_agents/utils/chunk_captions.py`): the clip is cut with `ffmpeg` into 20 s windows overlapping by 2 s (a tail under 3 s merged into the previous window; clips of 30 s or less are not chunked), each window is uploaded to `scratch/analyze/<video key>/<run id>/<index>.mp4`, captioned by the P1 model with NVIDIA's stock caption prompt and system prompt plus `CHUNK_TIMESTAMP_PROMPT` (copied from `video_report_gen.py`, with its stamp helpers; those tools are bound to VST and the NAT object store), at most 4 calls in flight with 429 retried, stamps offset to whole-video seconds, and the scratch prefix deleted in a `finally`. The captions go to P1 as one more user message (`CONTEXT FROM A FIRST PASS OVER THE SAME VIDEO`) that tells the model to trust the video over the captions and to take timeline seconds from the video, not the window bounds; windows the model described as a static view with no activity are left out. `incident_extraction_prompt.txt`, `inference.json` and the v4 schema are untouched. The captions are P1 context only: since 2026-11-01 the response no longer returns them and nothing stores or shows them ([removal](#2026-11-01-alert-rules-and-the-caption-display-are-removed-the-caption-pass-stays-as-report-context)); the pass's telemetry or skip reason is logged, and a caption failure never fails the analysis (P1 runs without context). Experimental requests (`experiment_prompt_id`, `skip_crops`, `max_crop_calls`) never run the pass, so eval runs behave exactly as before. The flag is off in code; the VM env turns it on.
- **Why:** the vss-chunk-scout runs (2026-10-31) showed that through the Switchyard gateway the Nano model ignores `media_io_kwargs.video.num_frames` outright (4 to 256 frames gave identical prompt tokens and byte-identical reports) and samples a fixed 2 fps capped at about 60 frames, so a 94 s clip is seen once every 1.5 s and the fall at 82 s in the demo clip (upright at 81.8 s, on the floor at 82.2 s) was read as "two people kneel to interact with a small object", severity 1. Every chunked run saw each window at the full 2 fps and caught the fall, the second man arriving and the woman in the background; feeding those captions to P1 gave "man falls and is assisted" with a correct 80 to 85 s timeline for about 1.2 to 2k extra prompt tokens. 20 s is the longest window that keeps the full 2 fps with margin; 10 s doubled the calls for no better recall. Captions sometimes invent detail (a second man "also trips", a "robot vacuum cleaner", clock readings) and the extraction copies it unless told to trust the video, so the context block says so. The pass roughly triples VLM tokens per analysis (about 28k prompt tokens and 3.3 calls per minute of 480p video, 5 to 8 s of wall time), accepted for clips over 30 s. NVIDIA's summariser drops caption lines under 2 s; here only lines under 0.5 s are dropped, because a fall lasts under 2 s.
- **Rejected:** asking for more frames (`num_frames` is ignored; the Super model finds the fall but takes 31 s per call and invented a third faller); stream-copy cuts (10x faster but keyframe-aligned, seconds off on phone clips); calling `video_understanding` or `video_report_gen` (VST, NAT object store and a LangChain VLM); changing the prompt file or `inference.json` (shared with eval and the console); de-duplicating the overlap; failing the analysis when a window call fails (P1 alone is still today's behaviour).
- **Open:** the empty-window filter is a wording heuristic (`static`, `no activity`, `unchanged`, ...); a static window the model describes in other words still reaches P1. An R2 lifecycle rule on `scratch/` (1 day) is the backstop for a crashed agent and is not set up by this change.
- **Links:** [`../../../../../services/agent/src/vss_agents/utils/chunk_captions.py`](../../../../../services/agent/src/vss_agents/utils/chunk_captions.py), [vm-api-contracts.md](vm-api-contracts.md#caption-pass-chunked-captioning-incident_chunking_enabled), [architecture.md](architecture.md#analysis-run-in-agent-mode).

### 2026-10-31: Zoomed second look renames a located item from its close-up
- **Decision:** after the grounding detector locates an entity, instrument or asset, the agent cuts the item from the frame at native resolution with a 25% margin (upscaled to a 256 px short side for the model only), draws the box on a copy of the frame, and asks the same VLM for two blind looks that never see the report's text (the marked frame; the marked frame plus the close-up), then, only when the looks agree (equal content words or one name inside the other, decided in code), a text-only merge of what they found against the report's current name and description, as strict JSON `{name, description, confidence, changed}` (confidence = the lowest of the calls; the looks are kept as `zoom_seen`; disagreeing looks keep the report's text and are named in `zoom_gap`). A correction is applied only when `changed` is true and `confidence` >= 0.7, and then to both the evidence entry (`item_name`, `description`, with `name_before`, `description_before`, `zoom_confidence`) and the matching report payload item, so the cards and the report text agree. Never changed: the item id, the detector `label`, timestamps, images and boxes, and an entity's `type` (only its description may change). Flag `INCIDENT_ZOOM_NAMES_ENABLED`, default on; a failed or slow call leaves `zoom_checked: false` with a `zoom_gap` and never fails the analysis. The calls are outside `CropCallBudget` (`max_crop_calls` counts grounding attempts only) and run inside the existing crop concurrency slot. No contract bump, no migration (evidence is JSONB).
- **Why:** P1 names items from a whole-clip pass at thumbnail resolution, so a crumpled plastic bag seen at 25 px became "soccer ball" on the 480p test clips (mvp3 evidence, reproduced on main), and the wrong name flowed into the title and the evidence card. A sharp crop is the direct fix: the model names what it can actually see. The 0.7 threshold keeps a hesitant second guess from overriding the first pass; the first name is kept on the entry so a reviewer can see what changed.
- **Rejected:** one vision call carrying the report's current name (the brief's shape: on IMG_9170 at 480p the model confirmed "soccer ball" at 0.7, and at 0.9 even when asked to judge before reading the name; blind, the marked frame said "black bag"); the close-up as the only blind look (it named the shoe beside the object; the code-side agreement rule keeps such an item unchanged and records both looks); letting the merge model judge whether the looks agree (on IMG_8206 both looks said "plastic bag" and it still kept "white cylindrical object" at 0.4); re-running P1 at higher resolution (the whole clip is the problem, not one frame, and it costs a full pass); correcting the title or RP1 prose too (RP1 runs before the crops and a title rewrite is a semantic repair the contract rules forbid); applying every `changed` reply (low-confidence flips on blurry crops); changing an entity's type (the enum drives the timeline and holder rules); counting zoom calls against `max_crop_calls` (the cap documents grounding cost for experiments and its tests pin it).
- **Links:** [`../../../../services/agent/src/vss_agents/utils/crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [console-reference.md](console-reference.md#report-versions-view-edit-and-history), [vm-api-contracts.md](vm-api-contracts.md).

### 2026-10-31: Batch upload runs files strictly one at a time, each as a single upload
- **Decision:** the upload page takes several files at once and runs them sequentially, in the order added: each file goes through the unchanged single-upload engine (`uploadVideo`: upload, conversion, thumbnail) and its analysis, so each becomes its own `videos` row and AI revision. Since the background-jobs change (entry above) the analysis is a queued job the console's server runs, and only the uploads run in the tab. The queue is pure functions (`batch-upload.ts`: `nextToRun`, `runBatchItem`, `drainQueue`, `removeQueued`, `cancelQueued`) with a thin React hook around them. A failed file is recorded on its row and the next file starts. Cancel drops queued files and aborts the running one only while its bytes upload. One file on an empty page keeps the single-upload flow (name warning, preview, redirect to the report). Ported by hand from mvp3's batch upload (P6.7, polish and the refused-upload reason) without its match, join and multi-video incident steps, which main does not have.
- **Why:** sequential keeps the laptop's ffmpeg and the agent's single model host doing one job at a time, the same load as one reviewer uploading by hand, so a batch never slows the shared agent for other users or makes two conversions fight for the CPU; the order on screen is the order of work, and a failure is easy to place. Throughput is bounded by the analysis anyway, so a pool would mostly queue on the model host. Reusing the single-upload engine means a batch file is stored, converted, named and cleaned up exactly as a single upload is: a file the console refuses (ffprobe cannot read it) stores nothing, because the route probes before it writes R2 and the `videos` row is only written by the analysis.
- **Rejected:** mvp3's pool of two (it overlapped uploads with analyses for multi-video incidents; here it would double the agent and ffmpeg load for little gain); a server-side job queue (that is P3, background jobs, which builds on this; done, entry above, which also added Retry on a failed row); deleting the video when its analysis fails (the single upload keeps it, failed attempts are `model_runs` rows by design, and the report page can re-analyse it).
- **Open:** a file whose analysis fails keeps its `videos` row and R2 object, as a single upload does today. A cancel or page close after the bytes are sent leaves the conversion running on the server, which may still store the object without a `videos` row (also true of a single upload). The batch lives in the page: leaving or refreshing the page drops the files not yet started.
- **Links:** [`../incident-console-v2/src/sections/analysis/batch-upload.ts`](../incident-console-v2/src/sections/analysis/batch-upload.ts), [`../incident-console-v2/src/sections/analysis/hooks/use-batch-upload.ts`](../incident-console-v2/src/sections/analysis/hooks/use-batch-upload.ts), [console-reference.md](console-reference.md#console-pages).

### 2026-10-31: Every upload is stored as an H.264 MP4 at the original resolution, converted by the console with ffmpeg
- **Decision:** `POST /api/uploads/r2` writes the file to a temporary directory, probes it with `ffprobe` and, unless it is an ISO MP4 whose first video stream is already 8-bit yuv420p H.264, converts it with `ffmpeg -map 0:v:0 -an -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -movflags +faststart` (same width, height and frame rate; the phone's rotation is applied, so a portrait clip is stored portrait) into a temporary MP4 that is streamed to R2 and deleted. The stored name always ends in `.mp4` (`clip.MOV` becomes `uploads/clip.mp4`; `inspectUploadName`, so the pre-upload check reports the final name), the `videos` row and the duration read by `lib/video/mp4-duration.ts` come from the stored file, and the answer carries `converted`. The upload page shows the conversion's elapsed time inside its **Uploading videos** step (upload and conversion are one step) and then says whether the file was converted; a file `ffmpeg` rejects is a 422 with its last lines. The route allows 5 GB and 1800 s (ffmpeg 25 minutes), sized for a 10-minute 4K phone recording and documented in the profile `.env`. `ffmpeg` and `ffprobe` are host binaries on PATH, as the frame route already assumed; no npm dependency. The file picker is unchanged. The thumbnail is still captured in the browser from the chosen file, which has the same frames as the stored copy, because Homebrew's `ffmpeg` is built without `libwebp`, so a server-side WebP thumbnail would fail on the very laptops that run the console.
- **Why:** since uploads go straight to R2 (2026-10-31, below), the agent analyses the uploaded bytes as they are, and the video model host cannot decode phone HEVC `.MOV` files or 10-bit H.264 (a clear 502, but still a failure). The captain's test uploads were 480p proxies made by hand to get round this, which gave 25-pixel crops and wrong object names; the 4K test showed that an H.264 MP4 at the original resolution analyses fine and gives sharp evidence. Converting once, on the way in, fixes both and keeps one stored format for the frame route, the duration reader and the agent. Audio is never kept: the captain does not want audio in analysis, and nothing downstream reads it. Pass-through keeps the common case (an H.264 MP4 from a camera or an earlier export) byte-for-byte and instant.
- **Rejected:** converting on the VM in the agent (the console already needs `ffmpeg`, the laptop has the file and spare CPU, and the agent would then have to write R2 and the `videos` row it no longer owns); a browser-side conversion (WebCodecs cannot mux MP4 without a library, and a new dependency is out); always re-encoding, pass-through included (slow for files that are already right, and a needless generation loss); remuxing a pass-through MP4 to strip its audio (the spec is byte-for-byte pass-through; an extra ffmpeg run on every upload for a track nothing reads); a server-side thumbnail from the converted file (`libwebp` missing from Homebrew's `ffmpeg`); stricter pass-through on profile or level (the host decodes 8-bit 4:2:0 H.264 of every profile seen so far).
- **Open:** Next.js's `request.formData()` holds the whole upload in memory before it is written to disk, so a multi-gigabyte file costs that much RAM on the laptop; a streaming multipart parser would need a dependency. The 25-minute ffmpeg budget is about 20 minutes of 4K on an M-series laptop; longer or slower hosts hit the clear "took longer than" error.
- **Links:** [`../incident-console-v2/src/lib/video/transcode.ts`](../incident-console-v2/src/lib/video/transcode.ts), [`../incident-console-v2/src/app/api/uploads/r2/route.ts`](../incident-console-v2/src/app/api/uploads/r2/route.ts), [console-reference.md](console-reference.md#console-pages).

### 2026-10-31: VST is dropped from the console's upload path; uploads go to R2 only
- **Decision:** the console uploads each video once, straight to R2 through its own server-side `/api/uploads/r2` route (key `uploads/<original name>.mp4` after the H.264 conversion, then the thumbnail), as mock mode already did. It no longer calls the agent's `POST /api/v1/videos` or `.../complete`, never sends the file to VST, and needs no sensor id: `/api/analysis` takes `{filepath, filename, model?}`, a new upload's video id is `'v' + 19 hex of sha256(random UUID)`, and `videos.source` stays null for new rows (existing rows keep their old sensor ids). The VST camera delete added on 2026-10-31 (https://github.com/Danwidj/video-search-and-summarization/pull/379) is removed with it, since no camera is created; the delete is objects then row again. `INCIDENT_VST_BASE_URL` is gone, and `start.sh --mode vm` forwards and checks only `:8000`. With VST gone, the VM deployment keeps only the native `vss-agent` and Phoenix: `start.sh --mode vm` expects and starts only `phoenix` in Docker (plus `elasticsearch` and the native analytics services under `ENABLE_ANALYTICS=true`, as before), and no longer names VIOS/VST, `vss-haproxy-ingress`, Redis or Kafka anywhere; `.scripts/tunnel.sh` forwards only `:8000` too. Firstmate deletes those containers on the VM after this merges; this change does not touch the VM, the agent, its config or the `.env` VST lines. *(Note: superseded in part by the person-tracking stack, which runs Kafka and NvStreamer `vss-vios-nvstreamer` via `tracking-stack.sh`; leftover VIOS/VST ingress/sensor/streamprocessing/postgres containers remain on the VM pending deletion).*
- **Why:** nothing after the upload used VST: analysis, evidence frames and crops read the R2 copy through a signed URL, the agent computes embeddings and stores them in Supabase, and search is a Supabase vector query. VST cost us its 100-camera cap shared by every console (cameras of deleted videos filled it and had to be pruned by hand) and HTTP 415 refusals of phone `.MOV`/HEVC files, and every file was uploaded twice. VST was also the reason for Redis and HAProxy (HAProxy only fronted VST and the agent). Kafka stays only because the person-tracking stack needs it (2026-10-31 tracking entries). Phoenix is kept because eval uses it as its trace viewer.
- **Rejected:** keeping VST and deleting cameras on video delete (the 2026-10-31 approach: still a second upload, the shared cap and the 415s); keeping VIOS/VST, HAProxy and Redis running on the VM for the stock VSS UI (nothing in the incident profile uses them, and they only add start-up time and failure points to `start.sh`). An undecodable file now surfaces at analysis time as the agent's clear 502 instead of a 415 at upload; the file picker is unchanged.
- **Open:** `behavior-analytics` (only with `ENABLE_ANALYTICS=true`) is a Kafka consumer; Kafka now runs only with the tracking stack, so that optional path works only while `ENABLE_TRACKING` is on.
- **Links:** [`../incident-console-v2/src/sections/analysis/hooks/use-video-upload.ts`](../incident-console-v2/src/sections/analysis/hooks/use-video-upload.ts), [vm-api-contracts.md](vm-api-contracts.md#tunnel).

### 2026-10-31: Evidence shows the whole frame with a box, not a crop
- **Decision:** the agent stores each evidence item's whole video frame (`evidence/<video key>/run-<n>/<itemId>-frame.jpg`, native size) beside the crop, plus `box_seconds` and `located` in the evidence entry. The console draws the box on the frame (report cards, Edit cards, evidence search tiles and viewer; object-contain, never object-cover); the crop is kept only for evidence search. When the detector finds nothing the agent retries at +1, -1, +2 and -2 s and keeps the first hit with the second it used (each second is one call against the unchanged `max_crop_calls` budget); with no hit it stores the frame with no box, `located: false` and an `image_gap`, never `[0,0,1000,1000]`. Items analysed before this have no stored frame: the console cuts it from the stored video through the existing frame route and reads a stored whole-frame box as not located. No contract bump, no migration (evidence is JSONB).
- **Why:** crops were cut at the video's native size (25 to 117 px on a 480p clip) and shown object-cover in a 2:1 tile, so a tall crop became a magnified slice, and the whole-frame fallback was stored as a real box, so a card showed a hallway with no object. Context tells a reviewer more than a cut-out does.
- **Rejected:** returning the frame key from evidence search (the hit rows come from `evidence_crops`, which has no frame column and no migration is allowed: search tiles cut the frame from the video instead); upscaling the crop (still no context); regenerating old reports (their data stays as analysed); a new column or migration; Edit's picker writing a frame instead of a crop (search needs the crop; the picked frame and box are shown from the stored video instead); cherry-picking mvp3's #375 (it removed the crop-call cap and targets another schema).
- **Links:** [`../../../../services/agent/src/vss_agents/utils/crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`../incident-console-v2/src/lib/evidence/evidence-view.ts`](../incident-console-v2/src/lib/evidence/evidence-view.ts).

### 2026-10-31: Agent hygiene: a clear 502 for a null VLM body, a redacting URL type, one retry for runaway P1 output, and no `nvdataset` in the fork
- **Decision:** A P1 response of HTTP 200 whose body is not a dict or has no `choices` raises `VlmNoAnswerError`, which `/analyze` maps to 502 with a plain message. `IncidentReportGenInput.video_url` is a `SignedUrl` (`str` whose `repr` drops query and credentials). A P1 output cut off by length (`finish_reason=length`) or over 30,000 characters is retried once with the identical request; `p1_attempts` lists every call in the 200 and in the 422 detail. `nvdataset`, its index and its source entry are removed from `services/agent/pyproject.toml` and the lock is regenerated, so `uv lock --check` and `uv sync --group dev` pass off NVIDIA's network. Ported from mvp3 (#326, #346) into main's one-video-one-incident shape; the route, `report_revisions`, crop budget and experiment settings are unchanged.
- **Why:** The video host answers HTTP 200 with a null body for a video it cannot decode (10-bit H.264), which used to surface as an obscure 500. NAT logs a failed tool call's input as the kwargs dict, so only the value's own `repr` keeps a signed URL out of the log. A runaway output is rare and a second attempt costs one P1 call. Nothing imports `nvdataset` in this repo.
- **Alternatives rejected:**
  - *Repair or truncate the runaway output:* a repair step that changes semantic content breaks the strict-contract rule.
  - *Add a repetition penalty or change `max_tokens`:* the P1 request in `inference.json` is shared with eval and the console, and eval pins it in tests. The cap is already 16384 tokens.
  - *Relock against NVIDIA's index:* not possible from outside the NVIDIA network; the package is unused here.
- **Open:** at temperature 0 the retry may repeat the same output; this is unmeasured. The console does not read `p1_attempts` yet, so a retried first attempt is in the agent log only until it does.
- **Links:** [vm-api-contracts](vm-api-contracts.md#post-apiv1incidentsincident_idanalyze).

### 2026-10-30: Planning documents and spreadsheets are local only, never in Git; O3 closed as a documented limitation
- **Decision (owner, 2026-10-30):**
  - **Removed from Git tracking** (`git rm --cached`; local files kept unchanged; merged history not rewritten):
    - `.docs/mvp2/ground-truth-and-prompt-experiments-plan.md`;
    - `.docs/mvp2/ground-truth-planning-instructions.md`;
    - `.docs/mvp2/resolve-ground-truth-proposals.md`.
  - **Ignore rules:** the root `.gitignore` now ignores those names and every spreadsheet (`*.xlsx`, `*.xls`, `*.xlsm`, `*.xlsb`, `*.xltx`, `*.xltm`). **One exception:** NVIDIA's upstream `services/vios/test/vios_dev_sanity.xlsx` stays tracked, because `services/vios`'s `vios-dev-sanity` agent reads it (owner's choice).
  - **Links:** living docs now name the plan as a local document. The approved annotation guidelines, methodology v1.0, the adjudication prompt and earlier decision entries are unchanged, so their references point to a file that exists only locally.
  - **O3:** closed as a documented limitation.
    - The AI drafting sessions for V1-V7 read no per-video test results in the verified drafting window.
    - Earlier aggregate benchmark exposure and access to test ground-truth labels are disclosed.
    - **Full test-set quarantine cannot be established from the available evidence.**
    - The owner's personal attestation remains unprovided unless the owner supplies one.
    - No rerun is required ([quarantine audit](../eval/docs/experiments/stage2-quarantine-attestation.md)).
- **Why:** the owner keeps planning material and workbooks out of the repository.
- **Links:** [plan audit](../eval/docs/experiments/plan-audit.md).

### 2026-10-30: End-to-end profile executed; O1, O2 and O4 accepted; O3 attested only for the AI author
- **Decision (owner, 2026-10-30):**
  - **O1, O2 and O4:** the judge-drift check, matching sensitivity below τ and an annotator review of the guidelines are **accepted as omitted**. Owner approval of the guidelines is disclosed as **not equivalent to an annotator review**.
  - **O3:** a retrospective quarantine attestation, recording only what can be verified ([attestation](../eval/docs/experiments/stage2-quarantine-attestation.md)).
    - **AI author, from the session transcripts:** no per-video test result was read while V1-V7 were drafted. Aggregate 2026-10-02 benchmark figures and test ground-truth labels were in context, and no prompt contains clip-specific text.
    - **Owner, who adjusted V1-V7:** not obtained, and not written on the owner's behalf.
  - **End-to-end profile:** approved and run once under the prepared design and caps ([results](../eval/docs/experiments/e2e-profile-results.md)).
    - **Runs:** 30 video-runs. One gateway outage paused the stage, which resumed once from its checkpoint after 15 minutes; 26 runs produced output.
    - **Usage:** 40 of 90 P1 attempts, 0.25 M of 3.15 M tokens, 185 of 1,440 grounding calls (at most 40 per request), 61 k of 8.64 M grounding tokens, 0 judge calls.
- **Findings:**
  - cropping took about a third of a typical request: median end to end 28-29 s, of which inference 19-20 s and cropping 8.5-9.6 s;
  - the cap truncated one C3 report (61 of 101 items).
- **Accounting notes (disclosed; no cap affected; code left as it ran, to match the pinned manifest):**
  - the runner's crop bound over-counts timed-out attempts that got an agent response;
  - the agent's token telemetry does not count grounding calls that raised. Upper bound: C2 ≤ 48,448 tokens.
- **Links:** [profile results](../eval/docs/experiments/e2e-profile-results.md), [plan audit](../eval/docs/experiments/plan-audit.md), [final report](../eval/docs/experiments/final-report.md).

### 2026-10-30: Evaluation plan audit: deviations recorded; ground truth and matching calibration are AI-assisted, not human-validated
- **Decision:** the original plan's requirements, and how each was met, replaced, omitted or deferred, are recorded in one place ([plan audit and deviation record](../eval/docs/experiments/plan-audit.md)).
  - **Replaced, by earlier owner decisions (R1-R7):**
    - human ground-truth review and κ by AI-assisted adjudication;
    - τ 0.75 by the AI-calibrated 0.40;
    - D9 (c) by D9 v2;
    - few-shot E6 by V6 boundaries;
    - test N = 2 by 1;
    - the crop pilot by the capped profile;
    - the Stage 1 baseline as Stage 2's reference by concurrent baselines.
  - **Deferred by the owner:** the Stage 1 recovery and the R2 workbook copy.
  - **Not done, recorded for the owner's acceptance (O1-O4):**
    - the judge-drift description-cosine check;
    - matching sensitivity below τ (both need new embedding calls);
    - the Stage 2 quarantine attestation;
    - a recorded annotator review of the guidelines.
- **Acknowledgement:** `ground-truth-v1.0` and the τ = 0.40 calibration are **AI-assisted and not human-validated**. No inter-rater agreement exists, and 8 calibration pairs await human review. Every result is accuracy against an AI-assisted reference approved at the dataset level.
- **Offline checks added (no model, embedding, judge or cropping call; nothing frozen changed):**
  - **Near-duplicates:** `scripts/eval_near_duplicates.py` (pHash, agent-venv OpenCV) found none across the 80 clips. The one flagged pair was visually confirmed as different scenes matched only through letterbox borders.
  - **Secondary metrics:** `secondary_metrics.py` / `scripts/eval_secondary_metrics.py` add macro accuracy, per-video mean F1, instrument threat and holder accuracy, and stricter-threshold sensitivity (lower bounds) for Stage 3. These are reporting only; D9 v2, the primary metrics and the conclusions are unchanged.
- **Why:** the final report must state which plan requirements were actually met, and which claims (human validation above all) the evaluation cannot make.
- **Alternatives rejected:**
  - computing the sub-τ sensitivity and the judge-drift check with the local embedder (new model calls, excluded by the owner);
  - re-scoring or re-matching any stage.
- **Links:** [plan audit](../eval/docs/experiments/plan-audit.md), [final report](../eval/docs/experiments/final-report.md).

### 2026-10-30: End-to-end VSS profile prepared with a per-request crop-call cap and its own budget (not approved to run)
- **Decision:** the plan §F.2 profile runs C2 and C3 through the local experiment agent with cropping on, on 15 test clips (3 per category, `random.Random(20261027)`), 1 repeat, never scored (`purpose: profile`, `scoring: none`).
  - **Agent:** a new experimental `/analyze` field `max_crop_calls` (1-200, gated by `INCIDENT_EXPERIMENTS_ENABLED=1`). One counter per request is checked before every grounding HTTP attempt, retries included. An experimental crops-on request without it is 400. Production requests are unchanged and uncapped. The response's `experiment.crop` reports crop wall time, calls, tokens, images and gaps.
  - **Runner:** separate `budget.max_crop_calls` and `max_crop_tokens`, reserved before each video-run at the cap × (1 + retries) and 6,000 tokens per call. An attempt that may have cropped unseen counts at the cap.
  - **Isolation:** `e2e-` ids and their own results. The preflight and the report re-hash every Stage 3 result file against its passed audit.
- **Status:** configs, manifest, preflight (passing) and report tooling are ready. **No profile request has been sent; execution needs the owner's budget approval** ([plan](../eval/docs/experiments/e2e-profile-plan.md)).
- **Why:** the box-call count is only known after P1, so the spend needs a bound the runner can enforce before each call (the reason the Stage 0 crop pilot was dropped). A cap of 40 covers the p95 of predicted items in Stage 3 (28); the one outlier (101 items) is truncated and counted.
- **Alternatives rejected:** counting predicted items × 4 attempts as the bound (no hard stop inside a request); scoring the profile (its outputs are not accuracy results, and the judge adds cost); running it on the shared VM agent (ask-first, and it writes to shared storage).
- **Links:** [profile plan](../eval/docs/experiments/e2e-profile-plan.md), [vm-api-contracts](vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b), [final report](../eval/docs/experiments/final-report.md).

### 2026-10-30: Stage 3 executed once under the frozen design, by an automated supervisor
- **Decision:** the owner approved Stage 3 execution on 2026-10-29 under the frozen plan and caps, with end-to-end automation. `eval_stage3.py supervise` (`eval/stage3_automation.py`) ran it: preflight before every session, checkpointed 4-hour sessions, a progress log, then recovery-v1, both report views and an integrity audit. The 220 video-runs ran once (stage `20261029T124321Z-0953f2d3`); the audit passed.
- **Outcome:** no ΔI comparison excludes zero. V1 minus base is +0.019 [-0.015, +0.055] in VSS and -0.011 [-0.045, +0.024] direct; VSS minus direct is -0.007 [-0.036, +0.024] (base) and +0.023 [-0.003, +0.050] (V1). Usage: 247 + 12 recovery P1 attempts, 2.01 M tokens, 865 judge calls, far within the caps. One attempt discarded after a judge `ReadTimeout` is not in the cost log and is disclosed ([results](../eval/docs/experiments/stage3-results.md)).
- **Why:** unattended execution needed resume, integrity checks and fixed stop rules so that no run is duplicated and nothing frozen changes; the supervisor only applies the approved mechanical steps.
- **Not done in response to results:** no prompt revision, rerun, new experiment or methodology change. Adopting V1 in production would be a separate decision with a contract bump.
- **Alternatives rejected:** a manual run (laptop closures needed checkpointed stops and resumes); rerunning to narrow the intervals (run-once design).
- **Links:** [Stage 3 results](../eval/docs/experiments/stage3-results.md), [plan](../eval/docs/experiments/stage3-plan.md).

### 2026-10-30: Dark theme removed from the console
- **Decision:** Remove the `.dark` token block and `dark` custom variant from `src/app/styles.css`, all `dark:` utilities from `src/components` and `src/sections`, and the `next-themes` dependency. The console is light only.
- **Why:** Nothing in the UI could switch to dark mode, so the code was dead weight that every shadcn component add would grow.
- **Alternatives rejected:** *Wiring a theme toggle:* large change touching most files, and no requirement for it.
- **Links:** `src/app/styles.css`, `src/components/ui/sonner.tsx`, `src/components/ui/chart.tsx`.

### 2026-10-29: AnalysisWorkspace upload target uses a composed shadcn dropzone
- **Decision:** The hand-written drag-and-drop `<button>` in `AnalysisWorkspace.tsx` is replaced with a dropzone composed of shadcn/ui components (`Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `Button`, `Badge`, and `lucide-react`'s `Upload` icon) over the native hidden file input. The dropzone Card is keyboard-accessible (`role="button"`, `tabIndex={0}`, with Enter and Space handlers dispatching to the hidden file input), displays a visual `Upload` orbit icon, a "New analysis" badge, title, description, and an outline "Browse video files" button. Drag-and-drop states (`border-primary bg-primary/10`) provide responsive feedback, and pre-upload validation behaviours are preserved: name checks, duplicate-name warning, unsafe-character replacement notice, progress, and error alert states.
- **Why:** The previous upload target was a custom uncomposed HTML button with hardcoded inline SVG and ad-hoc styling that did not align with shadcn design system conventions.
- **Alternatives rejected:**
  - *Adding `react-dropzone`:* Unnecessary third-party dependency; composition from existing shadcn primitives (`Card`, `Button`, `Badge`) and standard HTML5 Drag and Drop API fully satisfies requirements with zero extra bundle weight.
  - *Unwrapping Card/Button into raw divs:* Violates shadcn composition and accessibility rules.
- **Links:** `src/sections/analysis/components/AnalysisWorkspace/AnalysisWorkspace.tsx`.

### 2026-10-29: Report band panels swap hand-written resize handles for shadcn Resizable
- **Decision:** The report page (`ReportPage.tsx`) replaces the hand-written `<hr>` horizontal panel resize handle (`ReportBandResizeHandle`) with shadcn's `ResizablePanelGroup`, `ResizablePanel`, and `ResizableHandle withHandle` (`src/components/ui/resizable.tsx`). Default panel proportions (70% video, 30% version history) and minimum bounds (15% min, 85% max) are preserved. On mobile viewports (< 1024px / 390px), the panels stack vertically with `hidden lg:flex` on the separator handle and responsive CSS overrides. The vertical report band height handle (`ReportBandHeightHandle`) is retained for height adjustments (190px to 600px, default 270px) to preserve sticky bar behavior and scrolling ergonomics.
- **Why:** The hand-written panel handle relied on manual pointer capture, clientX calculations, and bespoke keyboard handlers. Swapping to shadcn `Resizable` (backed by `react-resizable-panels`) leverages standard ARIA separator semantics, built-in keyboard navigation, fine/coarse cursor ergonomics, and component consistency across the console.
- **Alternatives rejected:**
  - *Wrapping the entire page in a vertical `ResizablePanelGroup`:* Rejected because `react-resizable-panels` groups require rigid container bounds with `overflow: hidden`, which would break the outer document's `position: sticky` top bar and native window scrolling.
- **Links:** `src/sections/reports/components/ReportPage/ReportPage.tsx`, `src/components/ui/resizable.tsx`.

### 2026-10-29: Analysis progress uses the shadcn Progress component with accessible announcements
- **Decision:** the upload page shows progress with the shadcn `Progress` component (`@/components/ui/progress.tsx`): one batch bar with `aria-valuenow` and `aria-valuetext`, and a polite live region (`role="status" aria-live="polite"`) that announces the batch headline. Each video has four steps, Uploading videos (this includes the H.264 conversion), Understanding the incident, Structuring and saving report and Report ready (`stage-progress.ts`); a failed step keeps the progress value it had reached.
- **Why:** a single bar with real ARIA values and announcements tells a reviewer, and a screen reader, how far the whole analysis has got; static stage cards and an upload-only bar did not.
- **Alternatives rejected:**
  - *Separate disconnected Progress bars per stage:* Radix UI Progress represents a single value range; fragmented mini-bars clutter the UI and impair screen reader parsing.
  - *Hiding stage labels entirely:* operators need visual and semantic confirmation of each pipeline stage.
- **Links:** `src/sections/analysis/components/AnalysisWorkspace/AnalysisWorkspace.tsx`, `src/sections/analysis/stage-progress.ts`, `tests/analysis-progress-bar.test.mjs`.

### 2026-10-29: Stage 3 design: C1-C4 on the 55 test clips, 1 repeat, run once (approved 2026-10-29; executed, see above)
- **Decision (owner's design, 2026-10-29):**
  - **Configurations:** C1 direct + `p1-v4-base`, C2 VSS + base, C3 VSS + V1, C4 direct + V1.
  - **Runs:** the 55 `split-v2` test clips, **1 repeat** (this replaces D10's 2 for Stage 3), interleaved by the D10 order, so 220 video-runs.
  - **Unchanged settings:** Cosmos 3 Super, `ground-truth-v1.0`, methodology v1.2 (τ = 0.40), D9 v2 differences, severity MAE under v1.3 (reporting only), retry-v2, recovery-v1.
  - **Pinned inputs:** `eval/experiments/stage3/manifest.json` pins configs, prompts, ground truth, methodology, clips, seeds, policies and caps.
  - **Preflight:** `eval_stage3.py preflight` refuses any drift and checks C1/C2 and C3/C4 request parity. The only difference is `stream: false`, which the agent sends.
  - **Run once:** each config is `final` and `frozen_baseline`.
  - **Caps:** 660 P1 attempts, 23.1 M reserved tokens and 6,720 judge calls, plus recovery at most 180 / 6.3 M / 2,740.
- **Status:** approved by the owner on 2026-10-29 and executed 2026-10-29/30 ([plan](../eval/docs/experiments/stage3-plan.md), [results](../eval/docs/experiments/stage3-results.md)).
- **Why:**
  - All four configurations run on the same clips under the same conditions, so every comparison is paired by video. The prompt effect is measured in both arms, and the VSS-minus-direct effect at each prompt.
  - One repeat keeps the test run single and within one or two sessions.
  - D9 is used as a measurement on test, never a selection.
- **Rejected:**
  - Reusing Stage 1 or 2 runs, which are dev clips under other protocols.
  - Two repeats, which the owner chose against.
  - Selecting or tuning anything on test results.
- **Links:** [stage3-plan.md](../eval/docs/experiments/stage3-plan.md); [D15 exposure](mvp2/experiment-decision-record.md#d15-held-out-exposure-approved).

### 2026-10-29: Stage 2 selection (D9 v2): p1-v4-e01-severity
- **Decision:** the pre-registered D9 v2 rule (`select_d9` over every version that ran, each against its own interleaved baseline, merged `original+recovery-v1` records) selects **V1 `p1-v4-e01-severity`** (SHA-256 `004746ea7d19…`) as the Stage 3 prompt.
  - **V1:** ΔI +0.051 [+0.013, +0.089].
  - **Next best:** V4 +0.029. **V8:** `p1-v4-e08-combined`, +0.022 [−0.025, +0.071] against `s2-vss-baseline-b`.
  - **No tie-breaker:** the gap is more than 0.01.
  - **Original-run view:** the same result.
- **Status:** the rule's result, **approved by the owner on 2026-10-29** for Stage 3.
  - **Stage 3 has not run.** It needs the owner's approval, its own configs and budget.
  - This heading is the selection record that a final test config must name.
- **Why:** the rule was fixed on 2026-10-27, before any Stage 2 output.
  - V8 passed the +0.02 bar and every guardrail, so it qualified.
  - V8 was not selected, because V1's ΔI is higher.
  - The cross-stage check (V8 − V1 −0.016 [−0.054, +0.021], descriptive) gives no reason to prefer the more complex prompt.
- **Rejected:**
  - Choosing V8 because it combines every block (the rule ranks by ΔI, not by coverage).
  - Re-pairing V1 and V8 against one baseline for selection (they were not interleaved; reported as sensitivity only).
- **Links:** [Stage 2b results and final selection](../eval/docs/experiments/stage2b-results.md#7-final-stage-2-selection-d9-v2-pre-registered-2026-10-27); [Stage 2a results](../eval/docs/experiments/stage2a-results.md).

### 2026-10-29: Stage 2a recovery classifies DNS failures and expired R2 URLs as recoverable infrastructure failures
- **Decision (approved by the owner 2026-10-29, after all 400 Stage 2a video-runs were recorded):**
  - recovery-v1 also recovers an `http_error` whose stored error is a DNS or connection failure (`transport_error`), or R2's `403 Forbidden` on the signed video URL (`expired_url`);
  - the runner records a new agent DNS failure as `transport_error`.
- **Unchanged:** timeout limits, the retry-v2 rules, prompts, model settings, ground truth, τ and the methodology. Original results stay untouched, and reliability is reported both as original-run and recovery-adjusted, kept separate.
- **Result:** 7 of 7 recovered with 11 attempts (462 of the 1,200 authorised).
- **Why:** three Stage 2a runs had no model output for host-side reasons that recovery-v1 rejected:
  - a 9-hour suspend expired a signed URL that the retry then reused;
  - a brief laptop DNS outage hit two runs.

  Leaving them out would have counted infrastructure as model misses.
- **Alternatives rejected:**
  - Re-run every `http_error`: a genuine agent or contract error must never be retried into a result.
  - Re-sign the URL inside retry-v2: that changes the approved retry rules mid-stage. A recovered run signs a fresh URL anyway.
  - Change the running process mid-stage: the owner forbade it.
- **Links:** [Stage 2a results](../eval/docs/experiments/stage2a-results.md), [infrastructure and recovery §4](../eval/docs/experiments/infrastructure-and-recovery.md), `eval/experiment_recovery.py`.

### 2026-10-28: The shadcn skill is canonical under dev-profile-incident/skills/ with multi-harness symlinks
- **Decision:** `shadcn` skill is housed at project level under `deploy/docker/developer-profiles/dev-profile-incident/skills/shadcn`. The repo root exposes symlinks to it at `.claude/skills/shadcn` (Claude Code) and `.agents/skills/shadcn` (Gemini CLI and other agentskills.io hosts).
- **Why:** The skill was originally placed as a real directory under `.claude/skills/shadcn`, hiding it from non-Claude harnesses (such as Antigravity/Gemini). Housing it alongside the other incident skills under `dev-profile-incident/skills/` keeps project skills canonical in one place while symlinks expose it to all harnesses.
- **Alternatives rejected:** keeping a real directory in `.claude/skills/shadcn` (Claude-specific, duplicates or hides skill from other agents); duplicating the folder into `.agents/skills/` (drift risk).
- **Links:** [`../skills/README.md`](../skills/README.md), [`../incident-console-v2/README.md`](../incident-console-v2/README.md).

### 2026-10-28: Incident search and evidence search share one search function; evidence search can be scoped to one video; the critic is off by default
- **Decision:** `semantic_search` in `services/agent/src/vss_agents/api/incident_search.py` embeds the query and hands the vector to a `retrieve` callback; `POST /api/v1/incidents/search` (evidence crops) and `POST /api/v1/incidents/revisions/search` (revision summaries) both call it and differ only in what they retrieve. `filters.video_id` (agent) and `p_video_id` (`search_evidence_items`) restrict the search to one video inside the database. An empty query is allowed only with a video id: nothing is embedded and the video's crops come back in video time order. The VLM critic runs only when `INCIDENT_SEARCH_CRITIC` is truthy; otherwise every hit is `unverified` (rationale `Critic not run`), with no VLM call and no delay. The console dropped the verdict badge and the "Show N rejected" switch.
- **Why:** "See evidence" on a library card showed nothing: the console filtered the global top 20 down to one video, so an incident outside that list gave zero hits. The critic called a rate-limited VLM (HTTP 429), which made searches take 10 to 30 seconds and added no usable signal.
- **Alternatives rejected:** keep filtering in the browser (still empties the page); a separate scoped route (a second search path to keep in step); delete the critic code (it is kept dormant for the retrieval eval, [`mvp2/eval.md`](mvp2/eval.md)).
- **Links:** PR #244, [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentssearch), [`data.md`](data.md#search_evidence_items), [`20261028090000_search_evidence_items_video_id.sql`](../supabase/migrations/20261028090000_search_evidence_items_video_id.sql).

### 2026-10-28: Entity ids and their order are canonical across report view, edit and compare
- **Decision:** an edit draft keeps each entity's canonical id (`E1`, `E2`, ...) as a field of its own, next to the draft-only key. Saving writes that id as `entityId`; an entity added in Edit gets the next free `E<n>` (`nextCanonicalEntityId`). The compare view pairs entities in canonical order instead of re-sorting them by timestamp.
- **Why:** View showed `E1 · person in white shirt`, Edit showed `entity-0 · ...` (the draft key leaked into the saved id and the timeline lane title), and Compare swapped E1 and E2 when E2 appeared on screen first.
- **Alternatives rejected:** renumber on every save (breaks the `source_id` link from an item to its evidence); sort by first-seen time everywhere (ids would then change with every edit).
- **Links:** PR #246, `incident-console-v2/src/modules/reports/domain/edit-draft.ts`, `incident-console-v2/src/lib/reports/compare.ts`.

### 2026-10-28: The report timeline is being removed
- **Amended (2026-11-06):** the contract removal is on hold, because the chat's chronology reads the timeline ([exception](#2026-11-06-the-chat-keeps-the-report-timeline-and-relevant-uncertainties-and-the-report-page-stays-without-them)).
- **Decision:** the model-generated `timeline` is being dropped from the report. The console no longer shows it ([2026-11-01](#2026-11-01-the-console-no-longer-shows-the-model-event-timeline-or-the-model-reported-uncertainties)), but `incident-contract-v4` still carries `timeline`. Removing it from the contract is a version bump per the contract rules and is an open action in [`status.md`](status.md#5-action-items).
- **Why:** the timeline is enrichment, not a core scored field: its violations are not fatal under `core-scored-v1`, and it could disagree with the incident window ([`analysis-schema.md`](analysis-schema.md)).
- **Links:** [`analysis-schema.md`](analysis-schema.md), [`status.md`](status.md#5-action-items).

### 2026-10-28: R2 object names are readable and deterministic: the original file name, `run-N` and `edit-N`, never a hash or UUID
- **Decision:** a new upload is stored as `uploads/<original name>.mp4` (the extension is replaced by the H.264 conversion, 2026-10-31) (unsafe characters become `_`, names over 150 characters are cut with the extension kept, a taken name gets `-2`, `-3`). The thumbnail is `thumbnails/<video key>.webp`. Evidence is `evidence/<video key>/run-<N>/<itemId>.jpg` (AI crops) and `evidence/<video key>/edit-<N>/<itemId>.jpg` (reviewer images). Every write is a conditional put (`If-None-Match: *`), so nothing is ever overwritten. The upload page warns before upload when the name is taken or has unsafe characters.
- **Existing objects:** `archived/supabase/r2/migrate_r2_names.py` copies each to its readable key, verifies the copy, and updates `videos.filepath`, `report_revisions.evidence` and `evidence_crops.image` through `apply_r2_rename`. The live rename was run on finals (2026-10-28): the old copies and the orphaned objects were then deleted by hand.
- **Durability:** the console verifies a direct upload with R2 `HeadObject` (exact nonzero byte length), checks again before inference, and reads back `videos`, `model_runs` and the AI revision, confirming `videos.filepath` is the submitted key, before `POST /api/analysis` returns 200. `anomaly/<category>/` is reserved for classified seed and eval media.
- **Why:** reviewers see and recognise file names, and operators can read the bucket. The previous keys carried a sensor id and a UUID that meant nothing outside the system. `videos.id` stays the compact hash (it is the primary key and URL id).
- **The append-only exception:** `report_revisions` rows keep the old R2 keys unless the table can be updated. `apply_r2_rename` sets a transaction-local flag and the trigger then allows an `UPDATE` that changes only the `evidence` column; any other change, and any `UPDATE` without the flag, is still refused. `model_runs.notes` is not rewritten, so it keeps the old key as history.
- **Alternatives rejected:** leave old objects as they are (the captain asked for no hashes in any name); resolve old keys through a lookup table (every reader would need it, and the names would still be unreadable); rewrite revisions with a plain `UPDATE` after disabling the trigger (loses the guarantee that revisions are never edited); a random suffix for collisions (not deterministic, brings the ids back).
- **Known limits:** the original name of a pre-migration upload is not in the database, so the script uses the VST sensor name, else the upload time. Two analyses of one video that start together can pick the same `run-N`; the conditional put makes one fail instead of overwriting.
- **Links:** [`data.md` §2](data.md#2-cloudflare-r2-storage-architecture), [`archived/supabase/r2/migrate_r2_names.py`](../archived/supabase/r2/migrate_r2_names.py), [`20261028090000_r2_rename.sql`](../supabase/migrations/20261028090000_r2_rename.sql).

### 2026-10-28: Methodology v1.3: severity MAE as a reporting-only extension
- **Decision (owner, 2026-10-28; proposed after Stage 2a was authorised and launched):**
  - **MAE** (mean \|predicted − expected\| over valid severity predictions, in levels) is the **primary severity-specific reporting metric**.
  - **Supporting metrics:** mean signed error, exact and within-±1 accuracy (over valid predictions), the confusion matrix, coverage and failure categories.
  - **Comparisons:** paired against the corresponding baseline, with a 95% video-cluster bootstrap.
- **Not changed:**
  - D9 v2 (its severity component stays exact accuracy), its weights, the selection criteria and the guardrails;
  - τ = 0.40, ground-truth-v1.0, the prompts, the Stage 2a configs and running code;
  - every existing score.
  - `METHODOLOGY_VERSION` stays v1.2. v1.3 metrics are computed offline into separately versioned reports, with no model or judge call.
- **Why:** severity is ordinal. Exact accuracy cannot tell a one-level miss from a four-level one, and the signed error shows the over-rating that Stage 1 found. The limit, that adjacent levels are not guaranteed equal distances, is documented.
- **Rejected:** replacing exact severity in D9 during Stage 2 (that would change a pre-registered objective after the data).
- **Links:** [`../eval/methodology/evaluation-methodology-v1.3.md`](../eval/methodology/evaluation-methodology-v1.3.md), [`../eval/docs/experiments/severity-v1.3.md`](../eval/docs/experiments/severity-v1.3.md).

### 2026-10-28: Stage 2a authorised; run controls pause instead of spending the budget
- **Decision (owner, 2026-10-28):**
  - **Authorised:** Stage 2a only: 8 configs × 25 dev clips × 2 repeats = 400 video-runs, at most 1,200 P1 attempts including retries, under the existing token and judge caps.
  - **Run controls:**
    - pause after 4 consecutive video-runs with no model output;
    - the 25% rate-limit rule pauses per session instead of ending the stage;
    - `--session-hours 4` sessions;
    - checkpoint and resume with no duplicated video-runs.
- **Why:** the owner's instruction is that if the gateway becomes unavailable, the run pauses and is preserved rather than repeatedly exhausting the request budget. A cap still stops the stage and is reported.
- **Not authorised:** Stage 2b, V8, Stage 3, the Stage 1 recovery, a Stage 1 judge re-score, any change to τ, the methodology or the prompts.
- **Links:** [`../eval/docs/experiments/stage2-plan.md`](../eval/docs/experiments/stage2-plan.md).

### 2026-10-28: Methodology v1.2 adopted with τ = 0.40 (AI-calibrated, not human-validated); retry-v2 and recovery-v1 approved; V1–V7 registered
- **Decision (owner instruction, 2026-10-28): evaluation-methodology-v1.2 is the scoring methodology from Stage 2 on.**
  - **Code:** `methodology.METHODOLOGY_VERSION` is v1.2, with τ = 0.40.
  - **Preserved:** v1.1 and every v1.1 result.
  - **Unchanged:** the ground truth, D9 v2 weights and criteria, the incident rules, the judge and its 1,500-token limit, one-to-one matching, and invalid- and missing-output handling.
- **How τ was chosen:** τ = 0.40 is the result of the selection rule fixed before labelling (commit `dac60a9b2`), on calibration v2: 26 blocks, 132 pairs, including 4 random large blocks.
  - **Labels:** AI-labelled and AI-audited. 30 of 36 audited pairs agree, and every pair with two decisive labels agrees.
  - **Result:** pooled F1 0.814 [0.65, 0.94], precision 0.889. Selected in 56% of bootstrap resamples, so the conservative fallback does not trigger.
  - **Not human-validated:** every result records `match_calibration.human_validated: false`. 8 pairs await human review. A changed label means τ is re-derived by the same rule.
- **Stage 1:** re-matched offline under v1.2 into new files. The v1.1 `results.json` files are unchanged and pass `verify`.
- **Approved (B1):** `retry-v2` (≤ 2 retries for infrastructure failures, 60 s then 180 s, every arm) and `recovery-v1` (≤ 15 video-runs per config), with host-suspend detection, keep-awake and checkpoint/resume.
- **C1:** V1–V7 are registered as immutable `candidate` prompts ([record](../eval/docs/experiments/stage2-prompts.md)). The V8 rule is fixed.
- **Not yet decided:**
  - the Stage 2 start and budget ([plan §3–§4](../eval/docs/experiments/stage2-plan.md));
  - the Stage 1 judge re-score (C3: 193 judged fields);
  - the Stage 1 recovery (deferred).
- **Rejected:**
  - choosing τ on Stage 1 model scores;
  - silently keeping the provisional 0.30;
  - presenting AI calibration as human-validated.
- **Links:** [`../eval/methodology/calibration/matching-v1.2-calibration-v2.md`](../eval/methodology/calibration/matching-v1.2-calibration-v2.md); [`../eval/methodology/evaluation-methodology-v1.2.md`](../eval/methodology/evaluation-methodology-v1.2.md).

### 2026-10-28: Preparation before Stage 2: methodology v1.2 item matching, retry-v2 and recovery-v1, draft prompts (proposals awaiting approval)
- **Approved by the owner (2026-10-28):** the *preparation* only, as listed below. No recovery, Stage 2 or Stage 3 inference until the final methodology and budgets are approved.
  - **Item matching:** option (b), a calibrated item-matching procedure.
  - **Failures:** a controlled recovery protocol and a fixed retry policy.
  - **Prompts:** V1–V7 as adjusted (V1 emphasises the rubric and evidence and is not a default to the lower level; V3 enforces the existing instrument definition), with no few-shot examples.
- **Prepared, proposals awaiting approval (not decisions):**
  - **[evaluation-methodology-v1.2](../eval/methodology/evaluation-methodology-v1.2.md):** only the item-matching τ changes. The calibration rule, fixed before labelling, picked τ = 0.30 on 70 blind AI-labelled dev pairs (pooled F1 0.857 [0.69, 0.98]; 0.75 gives 0.091).
    - **Caveats:** labels provisional pending a human audit; τ at the grid edge; large blocks not sampled.
    - **D9 v2:** weights and criteria unchanged. G3 now also requires the same methodology version and protocol.
    - **Not in force:** `METHODOLOGY_VERSION` stays v1.1, and the v1.1 Stage 1 scores are unchanged.
  - **`retry-v2` and `recovery-v1`:** [infrastructure-and-recovery.md](../eval/docs/experiments/infrastructure-and-recovery.md). Infrastructure failures only, the original preserved and linked, reliability reported apart, the same for every arm. Plus host-suspend detection and `keep-awake.sh`.
  - **Draft prompts V1–V7** (not registered) and the Stage 2 schedule with a concurrent baseline: [stage2-plan.md](../eval/docs/experiments/stage2-plan.md).
- **Investigation:** the Stage 1 suspend was a lid close into Modern Standby (12:51–16:46 SGT, on battery). The 429s come from the sponsor proxy's shared model budget (500k TPM). The production gateway is unchanged.
- **Open owner decisions:** A1–A4, B1–B2, C1–C3 in [stage2-plan.md §7](../eval/docs/experiments/stage2-plan.md#7-decision-status).
- **Links:** [`../eval/methodology/calibration/matching-v1.2-calibration.md`](../eval/methodology/calibration/matching-v1.2-calibration.md).

### 2026-10-28: ground-truth-v1.0 is frozen on the owner's dataset-level approval of the AI-assisted adjudication; Stage 1 ran
- **Decision (owner, 2026-10-28):** `ground-truth-v1.0` is frozen from `Ground Truth AI-Adjudicated Candidate v0.3` (records `391fcd27…`).
  - **Basis:** the owner approved it **at the dataset level**, on the documented adjudication process (#231), and accepted the remaining risk of annotation errors given the project timeline.
  - **The approval record** (`eval/ground_truth/freeze/ground-truth-v1.0-approval.json`) says this explicitly: `approval_scope: dataset-level`, `individually_human_verified: false`. It was written by the assistant on the owner's instruction. No individual human review is claimed, and the Reviewer fields stay empty.
- **Methodological limitation (disclosed in every result):** the reference labels are AI-assisted and not human-verified annotation by annotation. Every accuracy figure is accuracy against that reference. The ground truth is never changed because of model outputs or scores; a genuine error found later means `v1.1` and a re-score of every compared configuration.
- **Stage 1 ran** on the frozen ground truth (100 P1 attempts, dev only, [results](../eval/docs/experiments/stage1-baselines.md)).
  - **Reliability:** 34 of 100 video-runs were lost to gateway 429s and 524s.
  - **Parity:** the arms are in parity on five fields. The description difference is upstream non-determinism, not a pipeline effect.
  - **Items:** item F1 is at the floor at the 0.75 matching threshold. This is a measurement-validity finding raised for the owner as Stage 2 decision S2-A; the methodology is unchanged.
- **Runner fix:** the agent wraps an upstream 429 in a 500, which the runner recorded as `http_error`. It is now classified as `rate_limited` (`_upstream_status`). The stored Stage 1 records are unchanged, and the report reclassifies them from the stored error text.
- **Rejected:**
  - waiting for full human verification (no time in the project timeline);
  - presenting the labels as human-verified;
  - editing stored results.
- **Links:** [`../eval/ground_truth/freeze/README.md`](../eval/ground_truth/freeze/README.md#ground-truth-v10-as-frozen-limitation); [`../eval/docs/experiments/stage1-baselines.md`](../eval/docs/experiments/stage1-baselines.md); [`../eval/docs/experiments/stage2-plan.md`](../eval/docs/experiments/stage2-plan.md).

### 2026-10-28: The 98 Pending entries are resolved by AI-assisted adjudication into a separate, owner-approved candidate
- **Decision (owner-authorised, `.docs/mvp2/resolve-ground-truth-proposals.md`):** the 98 Pending entries were adjudicated by AI under `gt-adjudication-v1.0`.
  - **Method:** look first, then compare. Every entry was re-assessed on the video before the earlier AI proposal was read, and decided ACCEPT, REJECT, MODIFY or UNRESOLVED.
  - **Evidence:** all 98 are video-verified (38 clips inspected, 78 close-up images from `scripts/gt_frame_detail.py`). Every high-impact decision cites a close-up.
  - **Where the decisions live:** `ai-adjudication-v0.3.jsonl` (local), validated by `ground_truth_correction.validate_adjudication`, applied only to the separate **`Ground Truth AI-Adjudicated Candidate v0.3.xlsx`**.
  - **Labels:** statuses `AI-Accepted`, `AI-Rejected`, `AI-Modified` and `AI-Unresolved`. Never "Approved", the Reviewer field is empty, and the provenance reads "AI-assisted, not human-reviewed".
  - **Precedence:** a human decision always overrides an AI adjudication.
  - **Freeze:** it re-validates the adjudication file (it never trusts the workbook's statuses). AI-unresolved entries block until the owner keeps their originals (`unresolved_keep_original` in the approval record). Uncertain adjudications mark their records `Uncertain` (A13). The owner's approval record is still required.
- **Result:** ACCEPT 73, MODIFY 21, REJECT 4, UNRESOLVED 0; 58 values changed; 10 entries marked uncertain. Report: [`../eval/ground_truth/review/candidate-v0.3.md`](../eval/ground_truth/review/candidate-v0.3.md).
- **Why:** the owner could not review 98 entries by hand. The look-first procedure, mandatory video evidence and validation keep the result visually grounded and traceable, and the separate candidate and approval record keep a human in control of what becomes ground truth.
- **Rejected:**
  - applying the earlier AI proposals as they stood;
  - text-only adjudication;
  - writing AI decisions as human approvals.

### 2026-10-28: Filename is a protected ground-truth field and is never modified
- **Decision (user):** no correction may change `Filename`, whatever its source or review status. All suggested filename changes are discarded.
  - **R01** (a `_demo` presentation-copy name) is now `informational`, with no proposed value and status `Informational`. It records the alias only.
  - **Protection:** `ground_truth_correction.PROTECTED_FIELDS` blocks the field even for an Approved entry with an accepted value, and `apply_to_records` refuses to write it.
  - **Resolution:** a `_demo` name reaches its clip through `dataset_manifest.canonical_basename` wherever it is read (freeze schema check, video resolution), never by editing the label.
- **Effect:**
  - the 24 R01 entries are no longer applied;
  - Candidate v0.2.1 applies 62 mechanical fixes (was 86) and leaves every `Filename` cell as annotated;
  - the 98 AI proposals are unchanged and still Pending (none touched `Filename`);
  - review continues in package **v0.2.2**.

  The earlier candidate v0.2 and packages v0.2 and v0.2.1 are kept unchanged and superseded. The freeze readiness has 0 schema and 0 split problems, and the Stage 1 judge caps are unchanged (1,710).
- **Why:** the filename identifies the annotated clip and is part of the record's provenance; aliasing belongs in resolution, not in the label.
- **Links:** [`../eval/ground_truth/review/README.md`](../eval/ground_truth/review/README.md); [`../eval/ground_truth/review/candidate-v0.2.1.md`](../eval/ground_truth/review/candidate-v0.2.1.md).

### 2026-10-27: Stage 1 judge caps are derived from the ground truth and enforced before the run; gateway timeouts are timeouts
- **Decision:**
  - **Derived caps (user-approved):** each config's `max_judge_calls` is `repeats × Σ judged fields × 5 attempts`. Judged fields per clip are 1 + entities + 2 × instruments + 2 × assets from the ground truth.
  - **Stage 1 values:** `direct-vlm-baseline` and `vss-baseline` are each **1,710** (2 × 171 × 5), recorded per clip in `eval/experiments/judge-caps.json` (`eval_experiment.py caps`).
  - **Enforcement:** `run_stage` re-derives the requirement from the ground truth it runs on and **refuses to start** if a cap is below it, so a full run can never be stopped partway by the judge cap. The P1 request and token caps (50 and 1.05 M) and the judge output limit are unchanged.
  - **Timeouts:** HTTP 504, 522 and 524 (including the agent's `P1 call returned HTTP 524`) are classified as `timeout` in both arms.
- **Why:** with the old 400 cap, the worst-case reservation would have stopped a fully scored run after about 11 clips.
  - **The 524:** the pilot's 524 shows the sponsor gateway's effective request timeout is about 100 s (Cloudflare), below the configured 300 s.
  - **No exclusions:** timed-out clips stay in reliability and end-to-end accuracy (as misses), are excluded only from conditional accuracy and from pairs, and are counted. The gateway and production timeouts are unchanged.
- **Rejected:**
  - a fixed generous cap, which is not tied to the plan;
  - raising client timeouts, which has no effect above Cloudflare's limit;
  - dropping timed-out clips from metrics.
- **Links:** [`../eval/docs/experiments/stage1-readiness.md`](../eval/docs/experiments/stage1-readiness.md).

### 2026-10-27: Stage 0 pilot run; the gateway's $0 configured pricing is recorded apart from the unknown infrastructure cost
- **Decision:**
  - **Authorisation:** the user authorised the no-crop Stage 0 pilot on the sponsor-provided Switchyard key (given to the FYP team by the NVIDIA sponsor for this project).
  - **Pricing record:** `eval/experiments/pricing.json` records the gateway's configured price of $0 per token (`provisional: false`, with the `/model/info` and `/key/info` evidence) and, separately, that the GPU infrastructure cost of the sponsor's Brev instance is unknown. Logged costs are gateway charges to the project only. Budgets also show the old $10/M planning rate for comparison.
  - **The run:** 10 P1 HTTP attempts (no retries, no 429s) gave 9 scored outputs and 1 gateway timeout (HTTP 524).
- **Result:** [`../eval/docs/experiments/stage0-pilot.md`](../eval/docs/experiments/stage0-pilot.md). Pilot results are never used for selection, ground-truth changes or accuracy claims.
- **Open, needing approval before Stage 1:**
  - raise the Stage 1 judge-request caps to about 1,710 per config;
  - freeze the ground truth;
  - approve the Stage 1 budget.
- **Links:** [`mvp2/experiment-decision-record.md`](mvp2/experiment-decision-record.md).

### 2026-10-27: Evaluation methodology v1.1 limits the judge's output to 1,500 tokens; truncated or invalid replies are failures
- **Decision (user-requested):** `evaluation-methodology-v1.1` adds `max_tokens 1500` to the pinned judge request (`methodology.JUDGE_MAX_OUTPUT_TOKENS`). It applies to the Stage 0 pilot and every later experiment. Three kinds of reply are now **scoring failures**, which leave the field unscored and stop the run; they are never read as scores:
  - a reply cut off at the limit (`finish_reason: length`, not retried);
  - a score outside 0–1 (previously clamped);
  - a score present only in the reasoning (previously read from it).
- **Why:** it puts a hard ceiling on each judge attempt's output, so the pilot's judge spend is bounded (D11), and an incomplete or malformed reply can no longer pass as a score.
- **Rejected:** keeping v1.0's uncapped judge; clamping out-of-range scores; retrying truncated replies.
- **Effect:** v1.0 and v1.1 results are never pooled. If the judge often needs more than 1,500 tokens, the pilot shows it as scoring failures, and a new version decides the remedy.
- **Links:** [`../eval/methodology/evaluation-methodology-v1.1.md`](../eval/methodology/evaluation-methodology-v1.1.md); [`../eval/tests/test_judge_limits.py`](../eval/tests/test_judge_limits.py).

### 2026-10-27: Experimental crops go to a temporary, isolated in-memory evidence store
- **Decision (crop option (a), user-approved):** when an experimental `/analyze` request keeps cropping on, `incident_report_gen` crops into a fresh `InMemoryEvidenceStore` for that request only. It is discarded on return, with no disk, no R2 and no production data, and `experiment.evidence_store` records it. Production requests keep the service's store (R2 when configured), unchanged. An agent with R2 settings still refuses experimental crops (409).
- **Why:** crop cost and end-to-end latency can be measured without any shared-storage write.
- **Rejected:** (b) deferring the measurement to the end-to-end profile; (c) R2 writes to a scratch prefix (needs separate approval).
- **Open:** a crop pilot needs its own authorisation and a box-call bound; the runner cannot count the agent's box calls in advance.
- **Links:** [`vm-api-contracts.md`](vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b).

### 2026-10-27: Stage 2 prompt selection rule (D9 v2) pre-registered
- **Decision (approved by the user 2026-10-27, before any Stage 2 run):** the Stage 2 prompt is selected by D9 v2, implemented in `eval/experiment_selection.py` (`select_d9`). This heading is the pre-registration record that `select_d9` requires.
  - **Data:** dev clips only, complete, reportable, fully scored, non-pilot VSS-arm results, compared against `vss-baseline`.
  - **Primary metric `ΔI`:** the equal-weight mean of three paired component differences.
    1. **Incident:** per video, the mean of the eligible ones among type, severity, start, end and description.
    2. **Entity F1.**
    3. **Object F1:** the mean of the eligible ones among instrument F1 and asset F1.
  - **Secondary metric `ΔI8`:** the per-video mean of the eight scores. It is reported, and it is tie-breaker 2.
  - **Eligibility and denominators:**

    | Case | Rule |
    |---|---|
    | Out of taxonomy | Excludes **type only**. That clip's incident component averages the other four fields, and nothing else changes |
    | Unscored value | Never eligible |
    | Item F1 with ground truth and prediction both empty | Not applicable. It leaves that video out of the entity average (entity) or out of the object mean (object; the mean of 1 or 2 values, or not applicable when both are) |
    | Ground truth empty with predictions, or present with none | F1 = 0 |
    | Repeats | Averaged per score before pairing |
    | A component's mean | Taken over the videos eligible on **both** sides |
    | `ΔI` | Divides by the number of components with at least one eligible pair (normally 3) |
    | `ΔI8` | Per video, divides by its eligible scores |

  - **Eligible counts are reported** for every component and score: baseline, candidate, paired, and the number of out-of-taxonomy videos.
  - **Uncertainty:** a 95% video-cluster bootstrap (seed 20261027).
  - **Guardrails:**
    - **G1:** valid-output video-runs ≥ the baseline's − 1.
    - **G2:** no score with a point difference ≤ −0.05 **and** a CI upper bound < 0.
    - **G3:** same videos, repeats, model, ground-truth digest and split.
  - **Selected:** the highest `ΔI` with `ΔI ≥ +0.02`; otherwise `p1-v4-base`.
  - **Tie-breakers**, within 0.01 of the best `ΔI`, in order:
    1. Higher `ΔI` lower CI bound.
    2. Higher `ΔI8`.
    3. Higher severity difference.
    4. More valid runs.
    5. Shorter prompt.
    6. Earlier registry entry.
  - **Version cap:** at most 8 versions, all reported.
- **Why:** fixed before any Stage 2 result exists, so the choice cannot be tuned to the data. Equal weights stop the five incident fields from dominating the item scores.
- **Rejected:** the plain eight-score average as primary (kept as secondary); selection on test or pilot results.
- **Links:** [`mvp2/experiment-decision-record.md`](mvp2/experiment-decision-record.md#d9-v2-prompt-selection-rule-pre-registered); [`../eval/experiment_selection.py`](../eval/experiment_selection.py).

### 2026-10-27: Experiment controls approved: D10 order and repeats, D15 disclosure, D11 hard caps (dollar limits provisional), Stage 0 as a pilot only
- **Decision:**
  - **D10 (approved):** 2 repeats per configuration in Stages 1–3. A stage runs its configurations interleaved per video, the first rotating by position, in a video order shuffled per repeat with `random.Random(20261027 + repeat)` (`experiment_runner.run_stage`, `schedule`).
  - **D15 (approved):** the 55-clip test split is kept, and every prior exposure is disclosed (decision record). The 52-clip subset excludes only the clips named in recorded pilots and is never called unseen.
  - **D11:** every config carries hard caps on P1 requests, measured P1 tokens and judge requests.
    - The runner refuses a plan that cannot fit. Before each call it stops if the next could break a cap (leaving room for a 21,000-token call), and it stops when more than 25% of attempts are rate-limited.
    - A stopped stage keeps its partial results as incomplete. Every call is logged to `cost-log.jsonl`.
    - Costs use `eval/experiments/pricing.json`, which is **provisional** ($10 per M tokens assumed) until Switchyard pricing or quota is confirmed.
  - **Stage 0:** pilot configs (`purpose: pilot`) are dev-only and may use the candidate ground truth. They are never reportable and never feed selection (`experiment_selection.select_d9` refuses them), and their report shows no accuracy.
    - The VSS arm runs on a local experiment agent started by `eval/experiments/agent/start-experiment-agent.sh` with no Supabase or R2 settings.
    - The crop pilot is removed: without an R2 store the agent makes no box calls, so it cannot measure crop cost (a decision is open).
- **Why:** cost and order must be controlled by code, not by care. The pilot must not leak into selection or reported accuracy.
- **Not decided here:** the Switchyard price. D9 v2 was pre-registered in its own entry (above), and the crop-pilot option is (a), a temporary isolated evidence store (follow-up).
- **Links:** [`mvp2/experiment-decision-record.md`](mvp2/experiment-decision-record.md); [`../eval/experiments/README.md`](../eval/experiments/README.md).

### 2026-10-27: Pronoun policy P1 for ground-truth descriptions
- **Decision:** a gendered pronoun may follow a visually supported, qualified gender identification ("appears to be a man"). Where gender cannot be determined and the description is gender-neutral, later pronouns must be neutral too. It is added to the annotation guidelines §7 as a clarification of A7 (v1.0 unchanged).
- **Effect on the review:**
  - **Definite violations:** 4 of the 98 Pending proposals (CL-0043, CL-0046, CL-0054, CL-0056) carry a suggested neutral-pronoun correction.
  - **Permitted:** 18 hedged rewrites keep their pronouns, provided the reviewer confirms the hedge is visually supported.
  - **Still Pending:** all 98 entries.
- **Tooling:** `eval/scripts/gt_review_package.py` builds a new review package (never overwriting) with the P1 flags. Suggested fixes come from a local, gitignored overrides file because they quote annotation text.
- **Links:** [`../eval/ground_truth/annotation-guidelines-v1.0.md`](../eval/ground_truth/annotation-guidelines-v1.0.md); [`../eval/ground_truth/review/README.md`](../eval/ground_truth/review/README.md).

### 2026-10-27: Experiment reports are built from saved results only; selection is guarded to pre-registered rules on dev
- **Decision:** PR 7 adds the experiment tooling, with no paid runs.
  - **Reports and checks:** `eval/experiment_report.py` and `eval_experiment.py report|verify|budget`, plus `scripts/eval_experiment_plumbing.py`.
  - **Reports** read saved results only. A result on unfrozen ground truth puts a NOT REPORTABLE banner on the whole report. Inference latency and end-to-end latency are separate tables, and C3−C1 appears only as (C3−C4) + (C4−C1), with the §F.1 limits and the §F.5 exposure disclosure.
  - **Results are hashed** at write time (`results.sha256`). `verify` re-checks the hash, the prompt bytes against the registry, the config hash, the ground-truth digest, the split and the call count.
  - **`select`** refuses test-split records, records on unfrozen ground truth, and any rule that is not an existing decisions.md heading.
  - **Configs:** an optional `videos` subset of a split half, used by the Stage 0 pilot configs (1 dev clip per category; 2 clips with crops on).
  - **Stage 0 step 1 ran offline:** C1–C4 on the 25 dev clips with a scripted model and fake evaluators, all checks clean.
- **Why:** tuning on test, or reporting from unfrozen ground truth, must be impossible rather than discouraged. Budgets must come from measured pilot figures, not guesses.
- **Not decided:** D9 (the selection rule), D10, D11 and D15. The budget statement gives call counts only; tokens and cost wait for the paid pilot.
- **Links:** [`../eval/docs/experiments/readiness.md`](../eval/docs/experiments/readiness.md); [`../eval/experiments/README.md`](../eval/experiments/README.md).

### 2026-10-27: Experimental /analyze settings are opt-in per process, verified, never persisted, and invisible to production requests
- **Decision:** the agent's `/analyze` accepts `experiment_prompt_id` (a prompt from `contracts/experiments/registry.json`) and `skip_crops`, for the eval prompt experiments only (`services/agent/src/vss_agents/tools/incident_experiments.py`, `incident_report_gen.experiment_settings`).
  - **Opt-in:** refused with 403 unless the process runs with `INCIDENT_EXPERIMENTS_ENABLED=1`.
  - **Verified prompt:** served only when its SHA-256 and contract version match the registry. An unknown or edited prompt, or a reviewer prompt alongside it, is 400.
  - **No shared writes:** cropping with R2 configured is 409. An experimental request writes no revision.
  - **Telemetry:** the response echoes the prompt id and SHA-256 used and adds `p1_elapsed_ms` and `usage`, on a 422 as well.
  - **Production unchanged:** a request without these fields keeps its P1 body, persistence, cropping and response keys, with experiments enabled or not. The tests prove it, and the baseline registry prompt gives the production P1 body byte for byte.
- **Why:** the VSS arm needs the registry prompt and P1-only timing (plan §F.1, D14), but production must not change, and an experiment must not write to Supabase or R2 without approval.
- **Rejected:**
  - reusing `reviewer_prompt` (it appends a hint, so it cannot replace the prompt);
  - ignoring the fields silently when disabled (a caller could believe an experiment ran);
  - vendoring experiment prompts through `sync.py`;
  - persisting experimental revisions.
- **Links:** [`vm-api-contracts.md`](vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b); [`../eval/experiments/README.md`](../eval/experiments/README.md).

### 2026-10-27: Experiment prompts live in an append-only registry; one runner drives both arms under the same guards
- **Decision:**
  - **Registry:** `contracts/experiments/` (`registry.json` plus immutable `p1/<id>.txt`). `p1-v4-base` is byte-identical to the production prompt. `eval/prompt_registry.py` checks the hashes, ids and parents, and append-only against `origin/main`. `sync.py` vendors none of it, so the production contract is unchanged.
  - **Runner:** `eval/experiment_runner.py` with `scripts/eval_experiment.py` runs one configuration per config file. The configuration is an arm, a prompt, a model, a split half, the frozen ground truth, repeats and a budget. Both arms send the same P1 request under the same rate-limit policy, and are re-validated and scored by the same code (`eval_run.run_one_video` with a `p1_call` per arm).
  - **Guards** run before any call: test split only for a final config with a decisions.md selection record; frozen baselines are never rerun; budget; `--confirm-paid` for any paid call; frozen ground truth only (candidate = plumbing, `reportable: false`); `skip_rp1` and `skip_crops` for accuracy runs. A VSS experiment prompt counts only if the agent echoes its id and SHA-256.
  - **Comparisons:** `four_way` computes the four paired comparisons C2−C1, C3−C2, C4−C1 and C3−C4, plus C3−C1, from saved outputs. Repeats are averaged per video, then the methodology's seeded bootstrap applies.
- **Implements** plan D13 (a): the same model, the same `p1-v4-base` prompt and the v4 schema in both arms, with C4 mandatory. It also implements D14 (b): a local agent, the registry read from the checkout behind a flag, and crops off for accuracy.
- **Not decided here:** D9 (selection rule), D10 (repeats), D11 (budgets) and D15 (held-out exposure). The committed configs' `repeats: 2` and budgets are placeholders until approved.
- **Why:** prompt identity must be provable for every result, tuning must be impossible to do on test, and the two arms must differ only in the pipeline.
- **Rejected:** editing `incident_extraction_prompt.txt` per experiment (it would change production); storing prompts in eval only (the agent needs the same bytes); a separate scorer per arm.
- **Links:** [`../contracts/experiments/README.md`](../contracts/experiments/README.md); [`../eval/experiments/README.md`](../eval/experiments/README.md).

### 2026-10-27: Ground truth is frozen only against an explicit approval record; Pending always blocks
- **Decision:** `eval/scripts/gt_freeze.py` (with `eval/ground_truth_freeze.py`) prepares `ground-truth-v1.0` from the unchanged source plus the latest reviewed candidate workbook.
  - **Checks:** schema validation, `split-v2` consistency, and blocking issues. Any `Pending` entry blocks; it is never read as Approved.
  - **Recorded:** a `MANIFEST.json` with the SHA-256 of every output and input.
  - **Frozen only** when nothing blocks and an approval record names exactly that candidate: its workbook SHA-256, records digest and exclusions, plus who approved it and when. Otherwise the output is a `candidate`.
  - **Loading:** `eval_gt_schema.load_frozen_gt_index` verifies the checksums and refuses a candidate unless `allow_candidate` is set (plumbing only).
  - **Immutable:** a frozen directory is never overwritten; corrections are a new version.
  - **`split-v2`:** the existing seeded partition renamed (25 dev = former few-shot clips, 55 test = evaluation clips; plan D8 (a), user rule 2026-10-27). It is tracked in `eval_reproducibility/split-v2.json`.
- **Why:** the freeze must not make unapproved labels authoritative, and the approval must be bound to the exact content approved, so that a later edit to the workbook invalidates it.
- **Rejected:** treating Pending as accepted after a deadline; freezing on human statuses alone with no approval record; a free-form approval not tied to digests.
- **Open:** where frozen ground truth is stored (D7: committed JSON vs R2) and whether its annotation text may be committed. Until then the output is local under `eval_data/ground_truth/` (gitignored). The approval of the final annotations and exclusions is the user's.
- **Links:** [`../eval/ground_truth/freeze/README.md`](../eval/ground_truth/freeze/README.md); [`../eval/ground_truth/freeze/ground-truth-v1.0-readiness.md`](../eval/ground_truth/freeze/ground-truth-v1.0-readiness.md).

### 2026-10-27: Ground-truth corrections are AI-proposed from video frames, applied only when independently verified or human-approved
- **Decision:** PR 4 builds a versioned candidate workbook (`Ground Truth Candidate v0.2.xlsx`) from the unchanged source, the PR 3 review workbook and AI video-review proposals (`eval/scripts/gt_candidate_build.py`, `eval/ground_truth_correction.py`).
  - **Automatically applied:** only the 86 `verified_correction` entries, each re-checked by `verify_mechanical` independently of the audit's rule code (status `Auto-verified`, which a reviewer can still reject).
  - **Proposed, not applied:** every video-dependent finding gets an AI proposal (`propose_change`, `keep_original` or `uncertain`) with evidence tiles, a confidence and provenance, under the correction prompt `gt-correction-v1.0`. Proposals and the 2 rule-based proposals stay `Pending` until a person approves them; nothing uncertain is applied.
  - **Human decisions carry forward** from the prior workbook unchanged, the prior workbook is never written, and a candidate holding human decisions is never overwritten.
  - **The AI reviewer (plan decision D5)** is option (d): Claude (`claude-opus-5-5`, in Claude Code) reviews timestamped contact sheets cut from the verified local clips. The sheets are made by `scripts/gt_frames.py`, which runs in its own throwaway `uv` environment with OpenCV, as the SQL harness does; eval's dependencies are unchanged.
  - **Independence:** the review reads only the annotation, the findings and the frames, and `guard_inputs` refuses results, experiment-prompt and run paths.
- **Why:** this was the only option with no new key and no paid inference. It is also a different model family from the Cosmos/Nemotron VLMs under test, so the correction is independent of VSS. Contact sheets with burned-in times make every cited piece of evidence checkable against the exact image.
- **Rejected:**
  - a Switchyard VLM (paid, and the same family as the models under test);
  - an external video model (new key and cost);
  - adding OpenCV or ffmpeg to eval's lock (ask-first dependency);
  - writing AI values into the data sheets as if approved;
  - editing the v0.1 review workbook.
- **Open:** human review depth (D6: share of high-impact entries reviewed, blind sample of unchanged incidents, second reviewer and kappa) is not settled. The tooling supports any depth.
- **Links:** [`../eval/ground_truth/review/README.md`](../eval/ground_truth/review/README.md#correction-and-candidate-pr-4); [`../eval/ground_truth/review/candidate-v0.2.md`](../eval/ground_truth/review/candidate-v0.2.md); [`../eval/ground_truth/correction_prompts/gt-correction-v1.0.md`](../eval/ground_truth/correction_prompts/gt-correction-v1.0.md).

### 2026-10-27: Proposed ground-truth corrections live in a separate review workbook with a change log; the source is never edited
- **Decision:** `eval/scripts/gt_review_build.py` builds `eval/ground_truth/review/Ground Truth Review <version>.xlsx` from the unchanged `Complete Ground Truth Labelling.xlsx`, whose SHA-256 is checked before and after. The working copy:
  - keeps every sheet, column, id, relationship and formula of the source;
  - writes proposed values in place, appends new records with the next free id, and strikes through and flags rows proposed for removal instead of deleting them;
  - adds a `Change Log` (original and proposed values, reason, supporting video evidence, confidence, Pending/Approved/Rejected status) and a formula-driven `Review Summary`.

  Each finding is classed as `verified_correction` (provable from the workbook or the dataset manifest), `rule_based_proposal` (an approved guideline rule), `needs_video_review` (no value proposed) or `informational`. Possible out-of-taxonomy clips get a review flag, never a sixth type. The audit report (ids and counts only) and a manifest with hashes and the change-log digest are committed. The workbook is deliberately gitignored.
- **Why:** reviewers need an editable, traceable copy, and the human labels must stay intact until PR 4 reviews and PR 5 freezes. Separating what the data proves from what only the video can show stops the build from inventing visual facts. The workbook carries real annotations and annotator names, and the frozen ground truth's storage (D7) is still open.
- **Rejected:** editing the source workbook; deleting or renumbering records; proposing values from filenames or description wording; relabelling `Animal` to `Animal Attack` (the workbook's own dropdown uses `Animal`, and eval maps it); committing the workbook before D7 and a privacy decision.
- **Safeguards (added 2026-10-27):**
  - a rebuild refuses to replace an existing workbook unless `--overwrite` is passed, and refuses a workbook holding review decisions unless `--discard-review-decisions` is also passed;
  - it refuses while Excel has the file open;
  - it backs the old file up first.

  Reviewed states are kept as immutable local backups with a hash log (`scripts/gt_review_backup.py`).
- **Open:** a durable shared location for the reviewed workbook. The proposal is the private R2 prefix `ground-truth/review/<version>/`, which is a shared-storage write and needs approval. Until then, backups are local only.
- **Links:** [`../eval/ground_truth/review/README.md`](../eval/ground_truth/review/README.md); [`../eval/ground_truth/review/audit-v0.1.md`](../eval/ground_truth/review/audit-v0.1.md); [`../eval/ground_truth_review.py`](../eval/ground_truth_review.py).

### 2026-10-27: Evaluation methodology v1.0 pins the scorer and never turns a scoring failure into a score
- **Decision:** `eval/methodology.py` and `eval/methodology/evaluation-methodology-v1.0.md` fix every instrument that moves a score, and every result records them:
  - the judge: `nvidia/nemotron-3-nano-30b-a3b`, `judge-prompt-v1.txt` byte-identical to the earlier inline prompt, temperature 0, pass at ≥ 0.5;
  - MiniLM-L6-v2 at :8811 for matching, at cosine 0.75;
  - ±5 s for timestamps;
  - the bootstrap seed.

  How failures are treated:
  - a configured judge other than the pin stops the run;
  - transient judge failures are retried twice with the identical request;
  - a judge or embedder failure that remains leaves the field `null` and stops the run, and the aggregate excludes and counts `null`s;
  - request failures (no model output) are excluded from accuracy, while invalid model output stays a miss.

  The aggregate adds per-video 95% intervals, severity within ±1, bias and confusion, threat within ±1 and holder accuracy. It refuses to pool methodology versions; earlier results are labelled legacy.
- **Why:** before this, an embedder outage scored every item as a miss and an item-judge outage as a fail, the judge model came from an unchecked environment variable with no temperature, and results with different instruments could be pooled. These would silently move scores between prompt versions, which the experiments must compare.
- **Rejected:** a new judge prompt (it would break comparability with every earlier score); continuing a run past scoring errors (a partial result is easy to misread); counting request failures as misses (they measure the endpoint, not the model).
- **Clips outside the five types (Option C, approved 2026-10-27):**
  - status comes only from the ground truth's `Out_Of_Taxonomy` and `Nearest_Type` columns, never the prediction or the review workbook's candidate flag;
  - such a clip leaves type accuracy only, is counted and listed, and nearest-type agreement is reported as a secondary figure;
  - every other field is scored;
  - the clips form their own breakdown row, `Outside the five types`.

  Denominators are per eligible field, and pooling weights each field by its own count. Request failures and invalid outputs are reported apart, as conditional accuracy and end-to-end accuracy plus reliability rates.
- **Links:** [`../eval/methodology/evaluation-methodology-v1.0.md`](../eval/methodology/evaluation-methodology-v1.0.md); [`../eval/extraction_stats.py`](../eval/extraction_stats.py); [`../eval/tests/test_methodology.py`](../eval/tests/test_methodology.py).

### 2026-10-27: Annotation guidelines v1.0 are the approved definition of a correct annotation
- **Decision:** `eval/ground_truth/annotation-guidelines-v1.0.md` is the single definition of a correct annotation. Ground-truth review and correction and VSS prompt variants all use it, and it is separate from every prompt (plan decisions D1 and D2). The severity and instrument-threat scales are the workbook's, unchanged. It adds:
  - decision rules (observed harm and demonstrated danger, no inferred outcomes, counting people) and category calibration examples;
  - entity significance, the hand-held test for instruments, and asset relevance;
  - description templates and uncertainty handling.

  The fourteen interpretations A1-A14 are decided in its §11, all approved on 2026-10-27. The ones most likely to matter later:
  - **vehicles** are assets, and **unseen drivers** are not entities;
  - **explosives** are rated by plausible capability and context;
  - **age and gender words** need visual support, and ethnicity is never inferred;
  - **`burglary`** means property crime at premises, an intentional convention separated from the ordinary meanings of burglary, robbery and theft; incidental force keeps that type;
  - **`explosion`** includes sudden ignition;
  - **clips outside the five types** are marked `out_of_taxonomy`, never forced into a type;
  - **responders' equipment** follows the hand-held test;
  - **primary type** is decided by centrality (the event actively under way for more than half the window, passive aftermath excluded), then severity, then the initiating event.
- **Why:** the ground truth, the correction pass and the prompt experiments must measure against one definition, fixed before any label changes. Interpretations that could move labels were decided explicitly rather than silently. Centrality comes before severity because time spans are more reproducible than adjacent-level severity judgments: in the 2026-10-02 benchmark, start and end were within ±5 s for 30-81% of videos, but severity was exact for only 22-27%.
- **Rejected:** putting the definitions in a prompt (prompts change per experiment; definitions must not); new severity or threat levels; severity-first primary-type selection (the type would flip with one-level severity changes and fall back on chronology); forcing out-of-taxonomy clips into the nearest type; treating robbery with incidental force as assault.
- **Open:** how `out_of_taxonomy` clips are scored or excluded is decided by PR 1B and applied in PR 5. No label changes until the PR 4 review applies these rules.
- **Links:** [`../eval/ground_truth/annotation-guidelines-v1.0.md`](../eval/ground_truth/annotation-guidelines-v1.0.md); the local plan `mvp2/ground-truth-and-prompt-experiments-plan.md` (not tracked in Git) (PR 1A, D1, D2).

### 2026-10-27: The evaluation videos are local verified copies with a tracked manifest; `_demo` is the one filename alias
- **Decision:** `eval/scripts/eval_fetch_videos.py` downloads every `anomaly/<folder>/<file>.mp4` except `anomaly/shooting/` (80 clips) to the gitignored `eval/eval_data/videos/<folder>/<original filename>`. Each clip is verified (size equal to R2, the R2 ETag reproduced from the local bytes for single-part and multipart uploads, SHA-256, MP4 `mvhd` duration) through a `.part` file and kept only when it passes. The tracked `eval/eval_reproducibility/dataset-manifest-v1.json` records every clip and the integrity findings. Filename resolution ignores a `_demo` suffix just before the extension, so `anomaly/demo/<Id>_x264_demo.mp4` resolves from the ground-truth name `<Id>_x264.mp4`. The split manifests keep their 25/55 membership; `eval_refresh_split_keys.py` rewrites only their R2 keys.
- **Why:** 24 clips moved into `anomaly/demo/` on 2026-10-27 with that suffix and identical sizes, so the split manifests named keys that no longer exist and `eval_run.py` skipped those videos. The ground-truth correction and prompt work need a fixed, checkable video set: SHA-256 per clip plus a set hash make any later change visible. Model calls still use signed R2 URLs; local copies are for hashing, review and frame extraction.
- **Rejected:** renaming or copying R2 objects back (a write to shared R2, and the demo folder is wanted as it is); a general fuzzy filename match (would hide real mismatches); regenerating the splits (changes membership and the seeded draw); committing videos or their hashes only in gitignored files.
- **Links:** [`../eval/dataset_manifest.py`](../eval/dataset_manifest.py); [`../eval/scripts/eval_fetch_videos.py`](../eval/scripts/eval_fetch_videos.py); [`../eval/scripts/eval_refresh_split_keys.py`](../eval/scripts/eval_refresh_split_keys.py); the local plan `mvp2/ground-truth-and-prompt-experiments-plan.md` (not tracked in Git) (PR 2).

### 2026-10-27: eval scores offline by default; the database path and schema creation are explicit
- **Decision:** `eval_run.py` writes predictions to, and scores them from, an in-memory `OfflineEvalStore` (`eval/offline_store.py`), with ground truth loaded straight from the workbook by the same `write_gt` the ingest script uses. The scorer itself (`eval_gt`, `matching`) is unchanged. The database path needs `--db`. `db.get_db()` no longer creates tables: only `get_db(init_schema=True)` (`--db --init-schema`) does, and without it the database is only probed. `eval_ingest_gt.py` needs `--dry-run` (no database) or `--db`. The uncommitted 2026-10-02 benchmark work (rate-limit pacing, timing, outcome classes, `--incident-only`, export and dataset-statistics scripts) is recovered onto main with it.
- **Why:** finals dropped the `gt_*`, relational report and `*_matches` tables, and `get_db()` ran `init_schema()`, so any eval run with the shared `.env.local` would have recreated them on the live database. Offline scoring removes the database from experiments entirely. The store copies the database's observable behaviour (all table columns, SQL type coercion, id ordering, the replace-and-cascade on re-insert), and `tests/test_offline_store.py` requires identical scores to the SQLite `IncidentDB` path and fails if the default path touches any database entry point, even with finals credentials set.
- **Rejected:** new eval tables on finals (a schema change to support offline evaluation, which the workstream plan rules out); rewriting the scorer to take plain dicts (it would change the measuring instrument; the store keeps the scorer byte-identical); SQLite on disk as the default (a database file per run with no benefit over memory).
- **Links:** [`../eval/offline_store.py`](../eval/offline_store.py); [`../eval/tests/test_offline_store.py`](../eval/tests/test_offline_store.py); the local plan `mvp2/ground-truth-and-prompt-experiments-plan.md` (not tracked in Git) (PR 0).

### 2026-10-25: The library card shows the upload-time thumbnail
- **Decision:** The `/library` incident card shows the report-card image (`ReportThumbnail`): the video's upload-time screenshot only, a skeleton when it is missing or its one request fails, and the severity chip and AI/Human badge on top. The card never falls back to an evidence crop, and `/api/reports` signs only the screenshot. The five finals videos with no screenshot are a separate data gap, not backfilled.
- **Why:** The captain wants the original thumbnails back (known issue 4). The wrapper is a `<figure>` rather than a `<div>` so its `aria-label` is valid (Tailwind's base styles zero figure margins, so it renders the same), and the plain `<img>` is kept with a Biome suppression because `next/image` would proxy and re-encode the presigned R2 URL through the console server. #185 had added an evidence-crop fallback, a smaller chip and no badge, which also contradicted the 2026-09-27 decision ("a missing thumbnail shows a skeleton"). A failed screenshot is not retried or replaced, so a missing one costs one browser error, not two requests.
- **Rejected:** keeping the evidence-crop fallback with the same badges; backfilling the five missing screenshots into shared R2 without explicit approval; checking each screenshot with `HeadObject` before signing (an R2 call per card to hide a data gap the backfill would close).
- **Links:** [`status.md`](status.md#7-archive); [`../incident-console-v2/src/sections/library/components/ReportThumbnail/ReportThumbnail.tsx`](../incident-console-v2/src/sections/library/components/ReportThumbnail/ReportThumbnail.tsx); [2026-09-27 decision](#2026-09-27-report-library-and-thumbnails).

### 2026-10-25: Retrieval metrics semantics for the cases the eval spec leaves open
- **Decision:** `eval/retrieval_metrics.py` implements [`mvp2/eval.md`](mvp2/eval.md) §3.4-3.5 as pure functions over `QueryInstance` records, with these choices where the spec is silent: a duplicate item key in a pool keeps its slot (it counts in `|L|`, coverage, MRR positions and false positives) but is never a second hit; coverage and the empty share use every instance, and zero-relevant metrics are aggregated like the others (repeats, then variants, then seeds); intervals are 95% percentile intervals with linear interpolation over 10,000 resamples by default, and the bootstrap seed is a required argument. Resample indices come from `random.Random(seed).random()`, and inputs are sorted before aggregation, so a result depends only on its data and seed.
- **Why:** The route returns each `(revision_id, item_type, item_id)` once, so a duplicate is a defect that must show in the numbers rather than be removed silently. Python guarantees the `random()` sequence for a seed, which numpy's generators do not promise across versions. A required seed makes every reported interval reproducible.
- **Rejected:** removing duplicates before cutting `C[:K]` (it changes what `C[:K]` stands for); a numpy random generator for the draws (numpy still averages them, which keeps 10,000 resamples fast); implementing any §8 proposal (P-1 to P-7) or eval storage in step 1.
- **Links:** [`mvp2/eval.md` §10.1](mvp2/eval.md#101-step-1-retrieval-metrics-module-landed); `eval/tests/test_retrieval_metrics.py`.

### 2026-10-25: The agent applies the video-bounds rules, and an unknown length is a recorded outcome
- **Decision:** `/analyze` validates P1 with the video length, so `WINDOW_BEYOND_VIDEO` (core, a 422) and `TIMELINE_BEYOND_VIDEO` (enrichment, recorded) apply in the agent as in the console. The length is the request's optional `video_duration_seconds` (the console sends the one it read from the MP4 header) or, without one, the agent reads the MP4 `mvhd` through the signed `video_url` with ranged GETs on a client that carries no model key. A `video_duration_seconds` that is not a finite number above 0 is a 422. When no length can be read (non-MP4, a server that ignores `Range`, HTTP errors), the rules do not apply, the agent logs a warning and the 200 response says so (`video_bounds_checked: false` with `video_bounds_unchecked_reason`). The console keeps its own enforcement on the agent's raw output.
- **Why:** The agent only received a signed URL, so the rules never ran there and a standalone caller (such as eval Track X) got no bounds check at all (known issue 1). The contract fixes the unknown-length case: the shared fixture `contracts/fixtures/policy/bound-unknown-length-not-checked.json`, which the agent, the console and eval validators all run, expects an unknown length to leave the rule unapplied ("not a pass") with `core_ok` true, and the console and eval record `videoBoundsChecked: false`. Failing such an analysis would break that fixture and make agent mode stricter than gateway mode and eval. The console's check is not redundant: it records every attempt's validation in `model_runs.notes`, and an older agent build or a failed header read leaves the agent unchecked.
- **Rejected:** failing closed on an unknown length (diverges from the shared policy and blocks videos whose header cannot be read); giving the agent R2 credentials to read the header (the signed URL already allows ranged reads); dropping the console's agent-mode check (it covers older agents and records the outcome).
- **Links:** [`analysis-schema.md`](analysis-schema.md#6-agent-mode); [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentsincident_idanalyze); `services/agent/src/vss_agents/utils/video_duration.py`.

### 2026-10-25: Deleting a video removes its evidence images before its rows
- **Decision:** `deleteVideoAndReports` removes the video object and its thumbnail, then lists `evidence/<videoId>/` through the `EvidenceObjectStore` port and removes every image of that video, and only then deletes the rows. Any listing or removal failure throws and keeps the rows; repeating the delete is safe, because removing an absent object succeeds.
- **Why:** The orphan sweep needs the video row, so images left behind by a delete could never be found again (known issue 2). Removing objects before rows keeps the row as the handle for a retry.
- **Rejected:** deleting the rows first and sweeping afterwards (the sweep refuses an unknown video); a background job (no scheduler in the console). Images of videos deleted before this change were removed in the live R2 rename on 2026-10-28 ([status](status.md#7-archive)). As with videos, a removed finals image may still be named by the frozen midterm record ([architecture](architecture.md)).
- **Links:** [`data.md`](data.md#2-cloudflare-r2-storage-architecture); [`../incident-console-v2/src/modules/reports/application/delete-video-and-reports/index.ts`](../incident-console-v2/src/modules/reports/application/delete-video-and-reports/index.ts).

### 2026-10-25: start.sh waits on the console and stops each local process tree
- **Decision:** `start.sh` runs `npm run dev` as a background job and `wait`s on it, traps `INT`, `TERM` and `HUP`, and its cleanup stops each local job together with every process it started (found through parent pids with `pgrep -P`, listed before any kill).
- **Why:** Reproduced on 2026-10-25 (known issue 8): a SIGTERM to `start.sh` alone left `next-server`, the mock and the gateway listening, because bash runs a trap only after the foreground command returns, and killing a wrapper (`uv run`, `npm run`) does not stop the server it started. Ctrl-C from a terminal worked only because the terminal signals the whole process group.
- **Rejected:** `setsid` or `set -m` per child (`setsid` is not on macOS laptops, and `set -m` changes terminal and signal handling for every background job, including the VM lock's `ssh -tt`); killing process groups (all children share `start.sh`'s group, so it would signal `start.sh` too).
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md); `eval/tests/test_start_script.py`.

### 2026-10-24: A human revision's search text comes from its evidence entries as they are
- **Decision:** On Save, an item that keeps its image copies the parent's evidence entry, so its search passage (`"{item_name}: {description}"`) is the parent's text, not the reviewer's edit; an item with a replaced or added image gets an entry with neither field, so its vector is close to empty (`humanRevisionContent`). This is deliberate.
- **Why:** A deliberate choice by the captain (2026-10-24); no reason was recorded.
- **Rejected:** none recorded.
- **Links:** [pull/207](https://github.com/Danwidj/video-search-and-summarization/pull/207); [`data.md`](data.md#save_human_revision_with_crops).

### 2026-10-24: Drop multi-subagent routing and full RT-CV / RT-Embed indexing from MVP2
- **Decision:** Both items leave the MVP2 plan; they are not "not started" work. No incident `top_agent` config, no routing prompt, no RT-CV / RT-Embed / Elasticsearch indexing, and no R2-to-VST ingest bridge. Track F of the retrieval eval stays deferred with no planned pipeline.
- **Why:**
  - Routing is a leftover from the v1 MVP2 plan, which assumed a `search_agent` over Elasticsearch. The v2 plan dropped that design. The five incident routes are plain FastAPI routes that bypass subagent selection, and the VM agent runs the stock base config with one subagent (`report_agent`). Nothing consumes a routing config except the deferred Track F.
  - RT-Embed indexing is a different product from MVP2 search. It indexes 5-second video chunks (Cosmos-Embed1, 768-d in Elasticsearch) and RT-CV object embeddings (1152-d), while MVP2 searches VLM-extracted evidence items as 1024-d text embeddings in Supabase pgvector. The embedding spaces are incompatible, so it would be a second parallel index, not an upgrade. Nothing feeds it: uploads go straight to R2 and never reach VST. It also needs the full search stack (RT-CV, RT-Embed, Kafka, Elasticsearch, Logstash, analytics) on a shared VM where only GPU 0 is available.
- **Rejected:** a minimal routing config exposing only `incident_search` and `incident_chat` as tools (no consumer and no routing-accuracy evidence); an offline RT-Embed spike against Track R (worth doing only if temporal video-chunk search becomes a product goal; [`mvp2/eval.md`](mvp2/eval.md) §6 still allows offline experiments).
- **Links:** routing and indexing investigation (firstmate scout report, 2026-10-24); [`mvp2/README.md`](mvp2/README.md#4-delivered-dropped-and-open); [GPU rule](incident-profile-operations.md#5-vm-deployment-configuration-principles-envremote).

### 2026-10-24: Finals test data is removed by direct delete, and unproven items are kept
- **Decision:** The rows and R2 objects of the three end-to-end test videos, their 10 test `queries` rows and the 2 scout uploads that have no `videos` row were removed with direct statements (one transaction for `videos`, `model_runs` and `queries`, then the R2 keys), after a JSON rollback snapshot. Items that could not be proved to be test data stay: one upload of unknown origin, video `veb492932dac2d1d52e0`, and five "car" queries.
- **Why:** The console's delete path leaves evidence JPEGs, `queries` rows and uploads with no `videos` row behind, and cannot delete the last at all. Deleting only what is proved by id, source and time keeps real data safe.
- **Rejected:** the app delete path alone (it leaves the 8 evidence JPEGs, the 10 `queries` rows and the scout uploads behind); deleting the unproven items.
- **Links:** [`status.md`](status.md#3-database-status); [`data.md`](data.md).

### 2026-10-24: Biome lints and formats incident-console-v2
- **Decision:** `@biomejs/biome` 2.6.2 (pinned) with `biome.jsonc`. `npm run lint` is `biome check . && tsc --noEmit`; `npm run format` is `biome format --write .`. The style follows the existing code (single quotes, semicolons, two spaces, trailing commas, line width 140), import sorting is off, and the rules the code already broke report as warnings until each is fixed in its own change.
- **Why:** The console had no linter or formatter (`lint` was only `tsc --noEmit`). The console plan deferred Biome until the tree was stable, because its formatter rewrites most files and collides with open branches; it landed once the module moves were merged.
- **Rejected:** a line width of 80 (reformats far more); fixing the existing findings in the same PR.
- **Links:** [pull/210](https://github.com/Danwidj/video-search-and-summarization/pull/210); [`../incident-console-v2/biome.jsonc`](../incident-console-v2/biome.jsonc).

### 2026-10-24: Orphan evidence images are removed by an explicit, per-video sweep
- **Decision:** `POST /api/reports/<videoId>/evidence-sweep` lists `evidence/<videoId>/` in R2, then reads every image the video's revisions and `evidence_crops` rows name, and removes only unreferenced objects older than `minAgeHours` (default 24, floor 1). Dry run is the default; any read failure removes nothing. Images of a deleted video are not covered (since 2026-10-25 the delete itself removes them).
- **Why:** Save uploads an image before it writes the revision, so a failed or abandoned save leaves an image nothing names. An image an older revision names is history, not an orphan.
- **Rejected:** treating an image only an older revision names as an orphan (it is part of that revision); removing young objects (one may belong to a save still in flight).
- **Links:** [pull/209](https://github.com/Danwidj/video-search-and-summarization/pull/209); [`data.md`](data.md#2-cloudflare-r2-storage-architecture).

### 2026-10-24: The mocks answer search and chat from one finals snapshot
- **Decision:** `base_profile_mock` (:7777) answers incident search, revision search and chat from `finals_snapshot.json` (the finals AI revisions and their evidence items, captured 2026-10-24), scoring a hit by the share of query words it contains. `search_profile_mock` (:7778) answers incident search and revision search from the same file, loaded by path, so there is one copy. Critic verdicts (always `confirmed`) and crop URLs are placeholders, so mock results are not real.
- **Why:** The fixture video ids (`Assault007_x264` and similar) are not in finals, so mock-mode search, chat and Find evidence linked to nothing.
- **Rejected:** a live database query from the mock (it must stay offline and hermetic); a second copy of the snapshot for :7778. Trade-off: the snapshot is a fixed copy, so uploads after the capture are missing from mock search until it is refreshed by hand ([steps](../mock-backend/base_profile_mock/README.md#refresh-the-finals-snapshot)); a refresh script is a possible follow-up.
- **Links:** [pull/208](https://github.com/Danwidj/video-search-and-summarization/pull/208); [pull/209](https://github.com/Danwidj/video-search-and-summarization/pull/209); [`../mock-backend/base_profile_mock/README.md`](../mock-backend/base_profile_mock/README.md).

### 2026-10-24: npm test enforces the console's hexagonal import boundaries
- **Decision:** `tests/import-boundaries.test.mjs` fails when domain or application code imports infrastructure, `app`, `sections`, `next`, `react` or `node:*`, or when a section imports infrastructure or `node:*`. Each existing exception is listed in `ALLOWED` with its reason, and an entry that matches no import also fails. Two console files are allowlisted exceptions: `src/modules/analysis/application/build-request.ts` and `run-contract-analysis.ts` import the contract loader, and `run-contract-analysis.ts` also imports `node:crypto`; removing them is the `ContractCatalog` follow-up in [`status.md`](status.md#5-action-items).
- **Why:** The rules were conventions upheld in review, and the move into feature modules made them easy to break unnoticed. This reverses the 2026-10-19 rejection of an import-matching test, as the captain approved for Step 8 of the console plan.
- **Rejected:** ESLint `no-restricted-imports` or dependency-cruiser (a new dependency for one check).
- **Links:** [pull/208](https://github.com/Danwidj/video-search-and-summarization/pull/208); [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md#3-dependency-rules).

### 2026-10-24: A human save writes its revision and its searchable crops in one call, or nothing
- **Decision:** On a video with no official revision, Save asks the agent to embed the new revision's evidence entries (`POST /api/v1/incidents/evidence-embeddings` with `evidence` in the body), then calls `save_human_revision_with_crops`, which inserts the revision and replaces the video's `evidence_crops` in one transaction. An embedding failure answers 502 and writes no revision. On a video with an official revision, Save embeds nothing and the official rows stay. Analysis and re-run keep `storeSearchableCrops`, which logs a crop failure after the revision is written.
- **Why:** A saved revision without its crops left the video unsearchable with no signal to the reviewer. The database cannot embed, so the embedding must come first.
- **Rejected:** keeping the logged, after-the-fact crop write for Save; the agent embedding a stored revision after the insert (a revision would exist before its crops).
- **Links:** [pull/207](https://github.com/Danwidj/video-search-and-summarization/pull/207); [`../supabase/migrations/20261024090000_save_human_revision_with_crops.sql`](../supabase/migrations/20261024090000_save_human_revision_with_crops.sql); [`data.md`](data.md#save_human_revision_with_crops).

### 2026-10-24: An evidence crop is held in the browser and uploaded on Save
- **Decision:** "Use this crop" writes nothing to R2. `POST /api/reports/<videoId>/evidence-crop` returns the cropped JPEG, the browser holds it with a preview, and Save uploads each held crop through `POST /api/reports/<videoId>/evidence-image` before it writes the revision. The crop is still cut on the console server with `ffmpeg`.
- **Why:** Writing at crop time left an R2 object for every cancelled crop. The captain chose the browser-held crop on 2026-10-24. R2 has no CORS rule for the console origin, so a canvas crop of the signed video would be tainted, and the server crop stays.
- **Rejected:** cropping on a browser canvas (needs an R2 CORS change); writing at crop time and sweeping afterwards.
- **Links:** [pull/207](https://github.com/Danwidj/video-search-and-summarization/pull/207); [`architecture.md`](console-reference.md#report-versions-view-edit-and-history).

### 2026-10-23: incident-console-v2 uses a feature-module layout under src/
- **Decision:** The console moved under `src/` and into feature modules in small PRs (Steps 1 to 8 of the console hexagonal plan): `src/app` (routes and pages), `src/modules/<feature>/{domain,application,infrastructure}` for analysis, chat, contract, dashboard, health, reports, search, shared and videos, `src/sections/<feature>/components` for UI, and `src/lib` for shared technical code. `src/lib/container.ts` is the composition root and the only place that picks adapters. Routes get ports from `getDbAdapters()` and `getAnalysisPorts()`; use cases are one folder each. Analysis saving and run history went behind ports (`AnalysisRunRepository`, `ModelGateway`, `IncidentAgent`, `VideoObjectStore`) in #205, so no route builds a PostgREST query. The contract loader stays a documented exception for the domain validators (Step 6 minimum).
- **Why:** Files were grouped by technical area, so one feature's code was spread over `app`, `components` and `lib`, and the database rules lived in HTTP handlers. Feature modules keep each port, use case and adapter together, and in-memory fakes with contract suites keep use cases testable without a database. Console search goes through the agent, which already embeds the query, runs the critic and records queries and hits, so the console needs no embedding model.
- **Rejected:** one large move PR (hard to review and revert); a `Result` type instead of exceptions and `StoreRejection` (a semantic rewrite); shared `src/components/ui` primitives before a second consumer exists; the strict Step 6 (`ContractCatalog` port), deferred.
- **Links:** [PR 120](https://github.com/Danwidj/video-search-and-summarization/pull/120) (the first ports and adapters); [pull/198](https://github.com/Danwidj/video-search-and-summarization/pull/198) to [pull/206](https://github.com/Danwidj/video-search-and-summarization/pull/206); [`mvp2/console-hexagonal-architecture.md`](mvp2/console-hexagonal-architecture.md).

### 2026-10-23: Save as new version keeps the entity seen span and the drawn image's second and box
- **Decision:** Edit mode saves only as a new `human` revision, with a required note (no Restore). Entities keep `first_seen_seconds` and `last_seen_seconds`. A reviewer-drawn image keeps its `image_timestamp_seconds` and `image_box` (`[ymin, xmin, ymax, xmax]`, 0-1000) on its evidence entry, not in the payload. `saveHumanEdit` checks the built entities, instruments and assets against contract v4 required fields and returns 422 when one is missing. A draft from a v2 or v3 revision, which has no span, starts from the item's most-visible second.
- **Why:** Without these fields a save dropped the span the report timeline draws and the time and box the frame view needs (gap G3). Edit mode opens the chosen version as the read-only A side, so copying an older version back needs no Restore.
- **Rejected:** keeping Restore beside Edit (a second way to write a version, removed in #181); optional span fields in a save (contract v4 requires them).
- **Links:** [pull/193](https://github.com/Danwidj/video-search-and-summarization/pull/193); [pull/189](https://github.com/Danwidj/video-search-and-summarization/pull/189); [`analysis-schema.md`](analysis-schema.md#report-revisions-ai-and-human).

### 2026-10-23: The console cuts evidence frames with ffmpeg on its own host
- **Decision:** `GET /api/reports/[videoId]/frame?t=` decodes one frame, and `POST /api/reports/[videoId]/evidence-crop` cuts a reviewer-dragged rectangle from it and returns the JPEG (since 2026-10-24 it stores nothing; Save uploads it). Both run `ffmpeg` over a signed R2 URL (range reads); where the binary comes from is in the 2026-11-01 entry.
- **Why:** Choosing a frame needs the exact second decoded from the video. The console already holds the R2 credentials and does the byte-range reads; the agent does not (since 2026-10-25 it reads only the MP4 header, through the signed URL). This reverses the 2026-09-27 rejection of server-side frame extraction.
- **Rejected:** a new npm video library (ffmpeg is already the standard tool); cutting crops in the agent (it has no R2 credentials).
- **Links:** [pull/183](https://github.com/Danwidj/video-search-and-summarization/pull/183); [`architecture.md`](console-reference.md#report-versions-view-edit-and-history); [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-10-23: The console writes searchable crops for a new AI revision
- **Decision:** After an analysis or a re-run, a video with no official revision gets its newest revision made searchable by the console: `storeSearchableCrops` asks the agent for the revision's embeddings and calls `set_revision_crops`. A crop failure is logged and returned as `searchable.error`; the analysis still succeeds. An Edit save no longer works this way: it writes its crops in the same call or fails (2026-10-24 entry).
- **Why:** The revision is already saved, so a failed crop write should not lose it or fail the request. The database cannot compute embeddings, so a writer must, and the agent already serves them for marking official.
- **Rejected:** failing the analysis when crops fail; the agent writing crops for every revision (see the searchable-revision entry below).
- **Links:** [pull/192](https://github.com/Danwidj/video-search-and-summarization/pull/192); [`data.md`](data.md) (`set_revision_crops`).

### 2026-10-23: /library replaces the reports listing and carries both searches
- **Decision:** `/library` has two tabs, Find incidents (one card per video, its official version else its newest) and Find evidence (`POST /api/search`, which the console sends to the agent's `POST /api/v1/incidents/search`, top 20, critic rejections kept; since 2026-10-28 the critic is off and a scoped search lists one incident, see the first entry above). `/reports` redirects to `/library` with its query string, and dashboard links point there. `EvidenceSearchRepository` now has its agent adapter, `src/lib/adapters/agent/search.ts`.
- **Why:** One page holds incident and evidence search with shared filters. Old `/reports` links and the dashboard keep working through the redirect.
- **Rejected:** a separate `/search` page (the PR 118 plan); the mockup's "Find similar" and "Download crop", and the "No report yet" card, were left out for now.
- **Links:** [pull/185](https://github.com/Danwidj/video-search-and-summarization/pull/185); [`mvp2/README.md`](mvp2/README.md).

### 2026-10-23: Find incidents text search reads the agent's revision search and filters in the console
- **Decision:** The Find incidents text search calls `POST /api/v1/incidents/revisions/search` through `RevisionSearchRepository`, keeps the incidents the agent matched that pass the other filters, and keeps the user's sort (not similarity order). Zero hits also fall back to the library's ILIKE search, because revisions without a stored vector are invisible to the agent. No similarity threshold is sent (the agent's default is 0).
- **Why:** The library RPC has no text filter, and the agent already embeds each AI revision. A console-side filter keeps the library's other filters working on the same list.
- **Rejected:** a new RPC with a text filter (a migration for one search); ordering by similarity (it would hide the sort the library already offers).
- **Trade-off:** the console reads up to 1000 incidents and filters them, so a library over 1000 incidents drops matches. Revisit with a text filter in the RPC.
- **Links:** [pull/196](https://github.com/Danwidj/video-search-and-summarization/pull/196); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-23: Model choice applies in agent mode, and the run records the agent's reported model
- **Decision:** The re-run and upload model picker works in agent mode as well as gateway mode. The console sends the chosen allowlisted `model` to the agent's `/analyze`; the run records the model the agent reports.
- **Why:** The agent accepts an allowlisted `model` since #188, so the gateway-only guard had no reason left. Recording the agent's model keeps `model_runs` true to the model that ran.
- **Rejected:** keeping the 409 guard for agent mode (the console would offer a choice it then refused).
- **Links:** [pull/194](https://github.com/Danwidj/video-search-and-summarization/pull/194); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-23: The agent's field is reviewer_prompt, not additional_instruction
- **Decision:** `/analyze` keeps `reviewer_prompt` (max 1000 characters). The console's request field `additionalInstruction` on `POST /api/videos/[videoId]/runs` is unchanged; it is passed to the agent as `reviewer_prompt`.
- **Why:** The name already existed in the agent, the vendored docs and the console request. A second name would add a mapping for one value.
- **Rejected:** a second field `additional_instruction` on the agent.
- **Links:** [pull/188](https://github.com/Danwidj/video-search-and-summarization/pull/188); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-23: Incident-level search embeds each AI revision in a column on report_revisions
- **Decision:** Store one summary embedding per AI revision as `report_revisions.embedding vector(1024)` with an HNSW cosine index (migration `20261023120000_report_revision_embeddings.sql`). The agent embeds `incident.title` and `incident.description` before the insert and writes the vector in the same row; an embedding failure inserts NULL. Search is `search_report_revisions` over all revisions with a vector, exposed as `POST /api/v1/incidents/revisions/search`.
- **Why:** `report_revisions` rejects UPDATE, so the vector has to be known at insert time, and one row per saved version keeps the vector, its payload and its facets together with no join. The embedding is non-fatal, so a down endpoint cannot stop a report from saving.
- **Rejected:** a separate embeddings table (a second write per revision that cannot share the append-only insert, and a join on every search); searching only official revisions (the captain asked for one embedding per saved version, and the crop search already covers official evidence); embedding inside the `save_human_revision` SQL function (it would need the embedder inside Postgres, and the console is out of scope), so human revisions have NULL vectors until a later change.
- **Links:** [`../supabase/migrations/20261023120000_report_revision_embeddings.sql`](../supabase/migrations/20261023120000_report_revision_embeddings.sql); [`data.md`](data.md) (Revision search); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-23: Chat answers about any report version from that version's own evidence
- **Decision:** `POST /api/v1/incidents/chat` takes optional `version_id` (a `report_revisions.id`) and `draft_report` (requires `version_id`). The official revision still goes through the search client (`evidence_crops`); every other revision is answered by keyword-matching its saved `report_revisions.evidence`, and a draft by matching the draft's items, with each crop taken from the same item in the base revision's evidence. Revisions are read through a `RevisionStore` port (adapter over `incident_db`). The response shape is unchanged.
- **Why:** `evidence_crops` holds official revisions only, so a reviewer looking at an older or human-edited version, or an unsaved edit, would get citations for a different report. Each revision already stores its own crop keys.
- **Rejected:** writing crops for every revision into `evidence_crops` (needs a migration and breaks "searchable = official"); a `version_id` on each citation (changes the response contract for no current consumer); allowing `draft_report` without `version_id` (no crops to borrow and no incident to cite).
- **Links:** [`../contracts/chat-contract-v1/README.md`](../contracts/chat-contract-v1/README.md); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-23: A video with no official revision is searchable through its newest revision
- **Decision:** Each video has one searchable revision (`searchable_revision_id`): the official revision, else the newest. `evidence_crops` rows belong to it and `search_evidence_items` returns only those. A new function `set_revision_crops(video, revision, crops)` stores them without touching the official pointer and refuses any other revision. Saving a newer revision with no official one moves the searchable revision to it and the old rows stop being returned at once (no trigger); the writer then replaces them with `set_revision_crops`. `set_official_revision` with no crop list keeps the target revision's existing rows, and clearing the pointer leaves the newest revision searchable. `videos.official_since` records when the pointer last moved (existing rows backfilled from the revision's `created_at`). Library cards gain `officialSince`, `versionCount`, `evidenceCount` and `thumbnail`; the last two come from the revision's `evidence` list, not `evidence_crops`.
- **Why:** The five Assault videos have no official revision, so they had no rows and search could not find them. The database cannot compute embeddings, so only a writer can create rows; the rule keeps the invariant of one revision's rows per video and stops a stale revision's rows being returned.
- **Rejected:** a trigger that deletes rows when a newer revision is inserted (hidden side effect on the agent's plain insert, and the same gap); searching every revision's rows (stale hits, duplicates per video); crops for all revisions (storage and ambiguity over which report a hit belongs to); counting `evidence_crops` rows for the card (shows 0 until embeddings exist).
- **Links:** [`../supabase/migrations/20261023000200_searchable_latest_revision.sql`](../supabase/migrations/20261023000200_searchable_latest_revision.sql); [`data.md`](data.md); [`../supabase/README.md`](../supabase/README.md).

### 2026-10-23: Versioned report revisions as JSONB snapshots
- **Decision:**
  - A report is a list of immutable **revisions** per incident (video), `report_revisions`: the full contract report as `payload` JSONB, the evidence list as `evidence` JSONB, and facet columns (`incident_type`, `severity_level`, `start_seconds`, `end_seconds`) written by the caller. `kind='ai'` revisions are made by an analysis; `kind='human'` ones by Save as new version, with `parent_id` the revision that was opened. A trigger rejects any UPDATE or DELETE (a video's cascade may remove them).
  - Re-generating with another model (and an optional reviewer prompt typed in the console) makes a new AI revision. It does not carry earlier edits across.
  - One revision per incident is **official**: `videos.official_revision_id` (NULL = none). Marking it rebuilds that incident's `evidence_crops` (the only rows search reads) from the revision, with embeddings from the agent's `POST /api/v1/incidents/evidence-embeddings`; un-marking clears them. There is no verification status and no audit of who marked it: `kind='human'` with `created_by` and `created_at` says a person saved it.
  - Evidence edits (description, detail, a replacement image) are part of a new human revision. A replacement image gets a fresh R2 key `evidence/<videoId>/<uuid>/<itemId>.jpg`; R2 objects a revision references are never overwritten or deleted.
  - The console writes `model_runs` and the AI revision in gateway mode, and only `model_runs` in agent mode, where the agent inserts the revision and returns `revision_id`. The functions that need a transaction (`save_human_revision`, `set_official_revision`, and the rewritten `search_evidence_items`, `list_incident_report_summaries` and `get_incident_dashboard`) ship with the versioned-report schema in `supabase/migrations/`, produced by the schema task; this console change does not add a migration.
- **Why:** The team wants each upload to give an AI report with evidence, a human to edit it and keep every version, re-generation with a different model, and exactly one official version. Snapshots keep each version whole and make restore a copy, where the previous design (relational AI rows plus one reviewer copy per run) could keep only one reviewer version and needed `effective_*` views, `source_*_id` links and a review status machine.
- **Rejected:** a draft status (unsaved edits live in the form only; a refresh reloads the database version); a migration script in this change (the schema task owns the schema); deleting individual revisions or R2 images (an old revision may reference them); inferring the official report as "latest" (one explicit mark per incident); incident-level vector search (search stays on item crops of the official revision).
- **Links:** [`data.md`](data.md); [`architecture.md`](console-reference.md#report-versions-view-edit-and-history); [`analysis-schema.md`](analysis-schema.md#report-revisions-ai-and-human); [`../supabase/README.md`](../supabase/README.md).

### 2026-10-23: Hand-applied report schema is recorded as finals migrations
- **Decision:** Add `20261023000000_report_revisions_schema.sql` and `20261023000100_report_revisions_functions.sql` to reproduce the revision schema the captain applied out of band, and make them safe to apply to the live database that already has it (`IF NOT EXISTS`, `CREATE OR REPLACE`, guarded `DO` blocks, conditional drops). The schema migration also drops the retired relational report tables, functions and `videos.selected_*` columns, and the test harness reapplies both files over the built schema to prove idempotence.
- **Why:** The live database was changed by hand, so a fresh database could not be built and the repo no longer matched production. Migrations keep one rebuildable source of truth and let later changes reach the live project through the normal `db push` path.
- **Rejected:** a data migration for the old relational rows (the captain wants none and the tables are already gone); recording the change only with `migration repair` (the repo still would not build).
- **Links:** [`../supabase/migrations/20261023000000_report_revisions_schema.sql`](../supabase/migrations/20261023000000_report_revisions_schema.sql); [`../supabase/migrations/20261023000100_report_revisions_functions.sql`](../supabase/migrations/20261023000100_report_revisions_functions.sql); [`../supabase/README.md`](../supabase/README.md); [`data.md`](data.md).

### 2026-10-23: Contract v4 adds an entity seen span
- **Decision:** `incident-contract-v4` adds required integer `first_seen_seconds` and `last_seen_seconds` to every entity in `incident_report.schema.json` (vendored to the agent). The prompt asks for `first <= timestamp_seconds <= last`; no cross-field rule enforces it. `evidence_items` adds both to entity entries, falling back to `timestamp_seconds` for reports stored without them. Console validation is version-aware, so v2 and v3 reports still validate against their own schema.
- **Why:** The report page timeline draws a bar per entity from first to last seen and Edit mode changes the two times; one `timestamp_seconds` gave the bar no data. Required, not optional, because strict `response_format` needs every property in `required`; stored reports are never re-validated against the new schema, so requiring them is safe.
- **Rejected:** optional fields (strict mode forbids them); a cross-field rule for the span (a model slip would fail an otherwise good core under `core-scored-v1`; revisit if the eval shows violations); columns on `evidence_crops` or the search RPCs (needs a new migration, which the revisions work owns; `evidence_crops` and `search_evidence_items` still expose only `timestamp_seconds`).
- **Links:** [`analysis-schema.md`](analysis-schema.md); [`../contracts/README.md`](../contracts/README.md).

### 2026-10-23: Console chat route calls POST /api/v1/incidents/chat
- **Decision:** `incident-console-v2` `/api/chat` sends a `chat-contract-v1` request (`src/modules/chat/infrastructure/agent/agent-chat.ts`, types in `src/modules/chat/domain/chat.ts`) with `context.scope: "incident"` and `incident_id` set to the report's video ID, and returns `{sessionId, message: {content, citations}}`. The report follow-up chat shows each citation as a link to its crop with the timestamp. The old report-context system prompt to the generic `/chat` is gone, because the contract has no free-text context field.
- **Why:** The route called the generic NAT `/chat`, so the cited-evidence chat was unreachable from the UI (chat model audit, finding 5). The agent answers from stored evidence, which is still canned seed data (see [`vm-api-contracts.md`](vm-api-contracts.md)).
- **Rejected:** keeping the report context in a system message (the contract's strict models accept it but the agent ignores it); a new port and repository (one adapter function is enough until a second caller exists).
- **Links:** [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/).

### 2026-10-23: The agent writes JSONB report revisions
- **Decision:** After a valid analysis the agent appends one `report_revisions` row (`kind='ai'`, full report as JSONB `payload`, crop list as `evidence`, facet columns, `parent_id` NULL) in agent mode, and persists `query_results` against `revision_id`. Re-generation is a new AI branch and copies nothing from earlier revisions. `reviewer_prompt` (max 1000 chars) is added to the report prompt for that run only. Evidence images go to R2 under `evidence/<videoId>/<uuid>/<itemId>.jpg` with a new `<uuid>` per run; an item with no image records an `image_gap` reason in the evidence JSONB. The agent does not write `evidence_crops`: the console calls `POST /api/v1/incidents/evidence-embeddings {"revision_id"}` when a revision becomes official and stores the rows. `scripts/backfill_official_timestamps.py` is removed.
- **Why:** The captain moved the database to versioned JSONB snapshots (`videos`, `model_runs`, `queries`, `report_revisions`, `evidence_crops`, `query_results`) and dropped the relational report tables and their RPCs, so every old agent write was broken. An append-only snapshot needs one insert and no RPC. Gateway-mode runs write no images; cropping in the analyze route covers agent-mode runs, and unique keys mean a re-generation can never overwrite an official revision's images. Only official revisions are searched, so embedding on promotion avoids paying for revisions nobody searches.
- **Rejected:** a migration script for existing data (the captain applied the schema by hand and wants none); the agent writing `evidence_crops` itself (the console owns promotion); keeping the backfill loader (nothing left to backfill, the old tables are gone).
- **Links:** [`data.md`](data.md); [`vm-api-contracts.md`](vm-api-contracts.md); `services/agent/src/vss_agents/utils/incident_db.py`; `services/agent/src/vss_agents/tools/incident_report_gen.py`.

### 2026-10-22: Remove ground-truth features from incident-console-v2 and mark GT tables removed
- **Decision:** Remove all ground-truth features from `incident-console-v2` (the `/videos/[videoId]/ground-truth` page, `GroundTruthScreen` component, `/api/reports/[videoId]/ground-truth` route, links from video history and report tools, and corresponding tests). The ground-truth tables (`gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets`) and `severity_eval_log` have been deleted from Supabase and are marked removed across documentation.
- **Why:** The ground-truth evaluation screen and tables are no longer used by the incident console; evaluation is handled independently and the tables have been dropped from the live Supabase database.
- **Rejected:** Retaining dead UI links or mock routes in the console.
- **Links:** [`data.md`](data.md); [`status.md`](status.md); [`architecture.md`](architecture.md).

### 2026-10-22: Concurrency-safe native service startup across shared VM users
- **Decision:**
  - Serialise native service check-then-start via `flock` on `.run/native-services.lock` (group-writable); close descriptor 200 before daemonising background processes so `flock` is released when the launcher exits.
  - Add `umask 002` near the top of `.scripts/native-services.sh` and ensure `.run/`, lock files, PID files and log files are group-writable so concurrent/subsequent starts by different VM users do not fail with "Permission denied". Clear pre-existing unwritable log or lock files before launching.
  - Treat a healthy `/health` response (`isAlive`) on the service port as already running even when the PID file is missing or unreadable; print that it is already running and skip start.
  - Write PID files atomically (`mktemp` then `mv`) and remove PID files on failed start only when matching this run's own PID.
  - Make `status` (and `status --porcelain`) list only expected services: `vss-agent` by default, including `video-analytics-api` and `behavior-analytics` only when `ENABLE_ANALYTICS=true` or named explicitly. Keep the porcelain format start.sh relies on unchanged.
- **Why:** Multiple teammates running `./start.sh` concurrently or sequentially under different user accounts on the VM crashed with "Permission denied" on `.run/vss-agent.log` and `.pid` while another user's agent was already healthy on port 8000; `native-services.sh status` reported STOPPED because it trusted only its own user's PID file; and `status` listed optional analytics services as STOPPED by default, adding noise.
- **Rejected:** Running all native services under a single system daemon or dedicated VM service account (heavier, out of scope, complicates local git/venv development); trusting only PID files without HTTP endpoint health checks; changing `start.sh`'s porcelain parsing contract.
- **Links:** [`../.scripts/native-services.sh`](../.scripts/native-services.sh); [`../.scripts/test-native-services.sh`](../.scripts/test-native-services.sh); [`incident-profile-operations.md`](incident-profile-operations.md#managing-native-services-scriptsnative-servicessh).

### 2026-10-22: Strict chat models matching chat-contract-v1
- **Decision:** The agent and mock chat models use `Literal` types for `role`, `scope` and `item_type`, `extra="forbid"`, `min_length=1` on ids, `ge=0` on `timestamp_seconds`, and `AssistantMessage.citations` has no default. Fixture tests feed the contract fixtures to both sets of models. The hand-written scope check is gone; pydantic returns the `422`.
- **Why:** The models accepted values the schemas reject (`request-invalid-scope.json`, `response-invalid-role.json`). The contract requires `citations`, and the route always sends it. No console or eval code called the chat route then, so no current sender was rejected.
- **Rejected:** relaxing the contract; sharing one model module between agent and mock (the mock stays standalone).
- **Links:** [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-22: Drop retired v1 tables (matches and notifications) from finals schema
- **Decision:** Drop `asset_matches`, `entity_matches`, `instrument_matches`, and `notifications` via migration `20261022123252_drop_unused_tables.sql`. The unused notification methods in `services/agent/src/vss_agents/utils/incident_db.py` are removed. Evaluation match persistence in `eval/` is left alone and handled separately. (`gt_*` and `severity_eval_log` were dropped later, by `20261023000000`.)
- **Why:** These tables were only used by the retired v1 Streamlit console. The live finals Supabase database already dropped them. Removing them brings repository migrations, tests, and documentation in sync with the live database.
- **Rejected:** Retaining empty tables or recreating them on finals.
- **Links:** [`../supabase/migrations/20261022123252_drop_unused_tables.sql`](../supabase/migrations/20261022123252_drop_unused_tables.sql); [`data.md`](data.md); [`status.md`](status.md).

### 2026-10-22: Archive the Streamlit v1 console under `archived/incident-console/`
- **Decision:** Move the retired v1 console with `git mv` from `incident-console/` to `archived/incident-console/` (history kept) and treat everything under `archived/` as read-only: never launched, set up by `.githooks`, tested or changed. `incident-console-v2/` is the only console. The two active dependencies on the v1 path move to the services that use them. `start.sh --mode local` passes `mock-backend/.env.local` (was `incident-console/.env.local`) to the mock backend, and stops early with a fix command if that link or `vlm-gateway/.env.local` is missing. `.githooks/setup-worktree.sh` self-heals the `incident-console-v2`, `vlm-gateway` and `mock-backend` links, no longer syncs a v1 venv, and never copies env files or symlinks into `archived/`.
- **Why:** v1 has been retired since 2026-09-24, but its directory still sat beside the active services. `start.sh` and the hooks still depended on it, so v1 could not be removed without breaking local mode. All four `.env.local` links point at the same shared `../.env.local`, so the env-file switch is the same variables with the same values; `mock-backend/.env.local` was already a documented required link, and using it keeps `mock-backend/base_profile_mock/` untouched.
- **Rejected:**
  - Deleting v1: it is still the provenance of `eval/`'s scoring code and of fixture data, and git history alone is harder to browse.
  - Pointing the mock at `incident-console-v2/.env.local`: that couples the mock to the console's file.
  - Pointing it at the root `.env.local` directly: that breaks the one-link-per-service convention the hooks maintain.
  - A `base_profile_mock/.env.local`: teammates are actively changing that directory.
  - Leaving a compatibility symlink at `incident-console/`: it keeps the old path alive.
- **Links:** [`../archived/README.md`](../archived/README.md); [`../start.sh`](../start.sh); [`../../../../../.githooks/README.md`](../../../../../.githooks/README.md); [`../skills/incident-start/SKILL.md`](../skills/incident-start/SKILL.md).

### 2026-10-22: Standard incident types enforced at the writers, not by a DB CHECK
- **Decision:** `incidents.type`, `gt_incidents.type` and `severity_level` stay unconstrained in Postgres. The writers emit only the five standard types (`road accident`, `burglary`, `explosion`, `assault`, `animal attack`): the zero-GPU mock (`mock-backend/base_profile_mock`) emits only standard types and `E#` entity IDs, and `eval/` stores ground truth through `incident_report.canonical_incident_type` (trim, lowercase, `fighting` → `assault`, `animal` → `animal attack`). An unknown GT type is warned about and stored normalised, not dropped. GT-side scoring folds the retired names, so older ground-truth rows still score. The archived Streamlit v1 console (`archived/incident-console/`) keeps its own old `INCIDENT_TYPES` copy and is deliberately not synced.
- **Why:** With a CHECK rule, the database would reject AI output that uses a wrong name, and that output would be lost. The captain prefers keeping the row and fixing the writers.
- **Rejected:** DB CHECK constraints on type/severity, plus auto-mapping in `insert_incident`.
- **Links:** [`../eval/incident_report.py`](../eval/incident_report.py); [`../eval/scripts/eval_ingest_gt.py`](../eval/scripts/eval_ingest_gt.py); [`data.md`](data.md).

### 2026-10-22: Consolidate incident lifecycle helpers and publish search operations
- **Decision:** Delete the incident profile's datalog cleanup wrapper; merge GPU reporting into `.scripts/status.sh`; merge non-interactive SSH target resolution into `.scripts/vm-preflight.sh`; and keep native-image pruning with the `incident-operate-vm` skill, with an explicit `--non-interactive` option. Add `incident-search` as the operational entry point for search, grounded chat and evidence-crop loading.
- **Why:** The cleanup wrapper selected stock profiles and could erase the shared VM's cache, while the helper pairs were always sourced or used together. Keeping the pruning helper beside its VM-operation procedure makes its shared-host safety context explicit, and the search procedure had no dedicated skill despite the routes and crop pipeline being delivered.
- **Rejected:** retaining the profile-rejecting cleanup command; preserving duplicate helper files; making pruning implicitly non-interactive; and leaving search/chat/crop procedures scattered across status and architecture documents.
- **Links:** [`../.scripts/status.sh`](../.scripts/status.sh); [`../.scripts/vm-preflight.sh`](../.scripts/vm-preflight.sh); [`../skills/incident-operate-vm/`](../skills/incident-operate-vm/); [`../skills/incident-search/`](../skills/incident-search/).

### 2026-10-21: Single-source incident contract with sync script and .txt prompts
- **Decision:**
  - `dev-profile-incident/contracts/` is the single source of truth for the shared incident contract. Prompt files are renamed from `.md` to `.txt` (`incident_extraction_prompt.txt`, `report_generation_prompt.txt`) with byte-identical contents to preserve content hashes and clarify their plain-text contract role.
  - `services/agent/src/vss_agents/incident_contract/` maintains a vendored copy of the 5 contract files (`incident_report.schema.json`, `incident_extraction_prompt.txt`, `report_generation_prompt.txt`, `VERSION`, `inference.json`) required for agent deployment.
  - A standalone sync script (`contracts/sync.py`) regenerates the vendored copy and provides `--check` mode to detect drift and list differing files. The agent unit tests (`test_incident_contract.py`) import and call the exact same drift detection logic, ensuring the script and tests cannot disagree.
- **Why:** Having contract files duplicated across directories risked silent divergence. Prompt files contain prompt instructions rather than Markdown documentation, so `.txt` accurately reflects their format without changing prompt text or hashes. Single-source sync with shared check logic prevents drift while preserving the standalone deployment packaging of `services/agent`.
- **Rejected:** Maintaining manual copies; git submodules or symlinks (which break Python packaging and Docker context isolation); bumping contract `VERSION` (the prompt contents and schema are byte-identical).
- **Links:** [`../contracts/README.md`](../contracts/README.md); [`../contracts/sync.py`](../contracts/sync.py); [`analysis-schema.md`](analysis-schema.md); `services/agent/src/vss_agents/incident_contract/`.

### 2026-10-20: One Supabase project per phase; finals built from one baseline; midterm frozen
- **Decision:**
  - The midterm project (`rfevukimyftzbxlehwel`) becomes a frozen, read-only record, and a new finals project is built from scratch with `supabase/migrations/20261020000000_finals_baseline.sql`, then filled once by `archived/supabase/copy/copy_midterm_to_finals.py`.
  - The 14 midterm migrations move unchanged to `archived/supabase/midterm/migrations/` (an archive, not a CLI workdir); `supabase/migrations/` holds only finals files, so the CLI workdir and commands stay the same.
  - Security is on from the first statement: default privileges are revoked before any object exists, RLS is on for every table, nothing is granted to `PUBLIC`/`anon`/`authenticated`, every function pins `search_path`, pgvector lives in `extensions`, and a self-check block fails the migration if anything is exposed. No `FORCE ROW LEVEL SECURITY` (no effect with a `BYPASSRLS` owner).
  - The copy brings over every real row plus the ground truth, evaluation data and seed/fake test reports, and leaves behind 20 orphan runs, 15 unlinked test runs, 8 broken uploads and the 4 pre-v1 tables (guards fail on anything else, and on any edit the copy cannot turn into a reviewer version). A stamp is cleared only when provably a status change (a contract run whose rows equal its notes record); a contract run whose items changed is copied as it stands only when a person passes `--accept-item-edits` (items linked to their AI origin only by unique identical content); a stamped legacy run stops the copy until a person passes `--not-edited` or `--edited`, because the midterm console rewrote the stamp with the verifier on every status change, so a stamp equal to the verification proves nothing. It relabels `fighting`/`animal`/`person` once; query-time folding stays as a guard, and the one `other` value stays in an immutable run's notes.
  - At the cutover `archived/supabase/midterm/freeze_midterm.sql` locks midterm (anon out, `service_role` read-only, direct-DSN sessions read-only); `unfreeze_midterm.sql` is the rollback. R2 is shared, so no object moves.
  - A SQL harness (`supabase/tests/`, `pgserver`) tests the schema hermetically; every later finals migration extends it.
  - Finals uses the new `sb_secret_` / `sb_publishable_` keys (no legacy JWT keys). They are sent in `apikey` only; the VM's unpinned `supabase-py` is proven with a one-row connection test before the switch ([`incident-manage-database`](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_)).
- **Why:** The supervisor asked for one database per project phase. Midterm's migration history does not match what is applied (three applied migrations unrecorded, one recorded under another version, two never applied), its base tables came from no repo file, and the public key could read and change everything (RLS on 2 of 22 tables, default grants to `anon`). Starting clean removes the junk and the open access in one step, and the frozen midterm stays readable as the phase record. Freezing rather than leaving it writable makes a forgotten env file fail loudly instead of writing to the wrong database (the agent only warns when it cannot record a search).
- **Rejected:** more migrations on the shared database (the history is inconsistent and the lockdown and clean-up were never applied); a separate `supabase/finals/` workdir (changes every doc path, and the old folder stays pushable at midterm); pausing midterm at once (no longer a readable record); a bucket per phase (doubles 59.5 GB for no gain); copying the orphan and test runs or the pre-v1 tables (no reader can reach them).
- **Links:** [`../supabase/README.md`](../supabase/README.md); [`../archived/supabase/midterm/README.md`](../archived/supabase/midterm/README.md); [`data.md`](data.md); [`architecture.md`](architecture.md#two-supabase-projects-one-per-phase).

### 2026-10-19: Pin all VSS Docker appliances and native services to GPU 0 only
- **Decision:** Restrict the entire VSS system on the VM to GPU 0. Set `RT_EMBED_DEVICE_ID='0'`, `RTVI_EMBED_NVIDIA_VISIBLE_DEVICES='0'`, `FIXED_SHARED_DEVICE_IDS='0'`, `CUDA_VISIBLE_DEVICES='0'`, and `NVIDIA_VISIBLE_DEVICES='0'` in `dev-profile-incident/.env`. Override `streamprocessing-ms`, `sensor-ms`, and `rtvi-embed` in `compose.override.yml` with explicit GPU 0 device reservations (`device_ids: ["0"]`) and `NVIDIA_VISIBLE_DEVICES=0` / `CUDA_VISIBLE_DEVICES=0` environment variables (alongside `nvstreamer-2d-fusion` and `perception-2d-fusion`). Export `CUDA_VISIBLE_DEVICES=0` and `NVIDIA_VISIBLE_DEVICES=0` in `native-services.sh`, `vm-ensure-docker.sh`, and `start.sh`. Pin `vss-rtvi-embed` to GPU 0 even though it is unused by MVP2 (MVP2 uses remote `nvidia/llama-nemotron-embed-vl-1b-v2` text embeddings and remote Brev VLM).
- **Why:** The VM is shared with another user whose training job occupies GPU 1 (46.9 / 49 GB at 87°C). VSS must leave GPU 1 completely untouched. Previously `RT_EMBED_DEVICE_ID` and `FIXED_SHARED_DEVICE_IDS` defaulted to `1`, while `streamprocessing-ms` and `sensor-ms` ran with `runtime: nvidia` without a device reservation or visible device pin, exposing all GPUs.
- **Rejected:** Removing `vss-rtvi-embed` completely (pinning to GPU 0 preserves compatibility if stock VSS embedding flows are ever re-evaluated); dynamically sharing GPU 1 (the co-tenant workload leaves negligible memory and runs at high thermal load).
- **Links:** [`compose.override.yml`](../compose.override.yml); [`.env`](../.env); [`architecture.md`](architecture.md); [`status.md`](status.md).

### 2026-10-18: Console and agent bind loopback
- **Decision:** `incident-console-v2` runs with `-H 127.0.0.1` (npm `dev`/`start` scripts and `start.sh`). `VSS_AGENT_HOST` defaults to `127.0.0.1`; haproxy's agent backend uses `VSS_AGENT_BACKEND_HOST=127.0.0.1` (profile override of a new shared-template variable defaulting to `HOST_IP`) and the tunnel forwards to the VM loopback.
- **Why:** Next defaults to all interfaces and the console holds database and storage admin keys with no authentication. haproxy is host-network, so it can reach a loopback agent once its backend host is configurable; the console reaches the agent through the tunnel, not haproxy, and no `vss-ui` runs on the VM.
- **Rejected:** leaving the agent on 0.0.0.0 or HOST_IP (exposes unauthenticated search and DB key to the network); hardcoding 127.0.0.1 in the shared haproxy template (breaks other profiles).
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-10-18: No search similarity cutoff; hide critic-rejected hits
> Rejection hiding only applies while the critic is on; it is off by default since 2026-10-28.
- **Decision:** `POST /api/v1/incidents/search` defaults `min_similarity` to 0.0 and takes top_k; hits the critic marks `rejected` are dropped unless `hide_rejected` is false. The grounding step raises `max_tokens` to 2048 and recovers `timestamp_seconds` and `label` from a truncated reply. An item the detector cannot box is kept as `located: false` (2026-10-31 entry on whole-frame evidence).
- **Why:** Scores of all 57 loaded rows sit between 0.14 and 0.35, so the 0.2 cutoff flipped "edged weapon" between 0 and 5 hits on a 0.01 difference (best score 0.192). The critic already judges relevance. Unboxed items stay searchable, since scoring uses the description embedding.
- **Rejected:** a relative cutoff (the critic call is paid per hit anyway).
- **Links:** [`vm-api-contracts.md`](vm-api-contracts.md); [`data.md`](data.md).

### 2026-10-18: Remote embeddings and remote-VLM cropping for evidence search
- **Decision:**
  - Evidence descriptions (loader, input type `passage`) and search queries (`DefaultQueryEmbedder`, input type `query`) use one remote model, `nvidia/llama-nemotron-embed-vl-1b-v2` on `https://integrate.api.nvidia.com/v1/embeddings`, requesting `dimensions=1024` to match `evidence_crops.embedding`. Client: `utils/embeddings.py` (`EVIDENCE_EMBEDDING_BASE_URL`, `EVIDENCE_EMBEDDING_MODEL`, `EVIDENCE_EMBEDDING_API_KEY`, falling back to `NVIDIA_API_KEY` then `NGC_CLI_API_KEY`). Without a key, only the in-memory store falls back to a deterministic placeholder vector (zero-VM mocks and unit tests only); with the Supabase store or on an embedder error, the route fails with HTTP 503.
  - `DefaultDetector` in `crop_evidence.py` is backed by the remote VLM (one tight `bbox_2d` per frame, normalised 0-1000), not a local detector. `R2EvidenceStore` replaces the stub.
  - The evidence loader (`scripts/backfill_official_timestamps.py`) was later retired; see the 2026-10-23 revisions entry.
- **Why:** The earlier loader wrote nothing, so search returned 200 with zero hits on the VM. The Brev key cannot call `/v1/embeddings` (403), and `nv-embedqa-e5-v5` and `llama-3.2-nv-embedqa-1b-v2` are end-of-life (410). `llama-nemotron-embed-vl-1b-v2` is live and accepts `dimensions=1024` (`nemotron-3-embed-1b` only 2048). The remote VLM already serves grounding, and no local GPU model may be started.
- **Rejected:** a local MiniLM server (384 dimensions, not on the VM); padding or truncating 2048-d vectors (breaks cosine geometry); a local Grounding DINO / OWLv2 detector (needs a GPU model on the VM; detector comparison stays in the retrieval eval).
- **Links:** [`services/agent/src/vss_agents/utils/embeddings.py`](../../../../../services/agent/src/vss_agents/utils/embeddings.py); [`services/agent/src/vss_agents/utils/crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py); [`status.md`](status.md).

### 2026-10-18: start.sh vm mode explains unreachable VMs, bounds every VM step and detects the VM address
- **Decision:** `start.sh --mode vm` classifies an SSH failure first (`.scripts/vm-preflight.sh`: Tailscale state, VM offline, DNS, timeout, refused, no route, auth, host key) and prints cause and next step. The Docker deploy runs from `.scripts/vm-ensure-docker.sh`, piped over SSH: it clones a missing checkout, requires `.env.remote`, rewrites a stale `HOST_IP` (timestamped backup first), pulls missing images and runs `docker compose up -d` under `VSS_COMPOSE_UP_TIMEOUT`. Native start, ssh calls and the tunnel wait are bounded too. `VSS_VM_IP` defaults to the VM's default-route source address (`ip -4 route get 1.1.1.1`, fallback `10.131.1.5`); an explicit value wins. `--no-console` stops after the tunnel.
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
  - Migration `archived/supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql` adds pgvector, one unified `evidence_crops` table keyed `(incident_id, model_run_id, item_type, item_id)` (HNSW cosine index, `vector(1024)`), `query_results` (rank, similarity, critic verdict and rationale) and the `search_evidence_items` RPC. RLS on, `service_role` only. The RPC joins `videos.selected_model_run_id`, so only official reports are searchable.
  - `vss-agent` uses `SupabaseSearchStore` when `INCIDENT_SEARCH_STORE=supabase` or Supabase credentials are configured, otherwise `InMemorySearchStore`. Crop keys resolve to public URLs (`INCIDENT_VIDEO_BASE_URL`) or boto3 presigned R2 URLs (`utils/r2.py`). Queries and results are persisted.
  - Query embedding is covered by the remote-embeddings decision above.
- **Why:** The sample-data store pointed at a non-existent host, so the critic failed to fetch images and every hit was `unverified`. One table avoids three vector columns and three UNIONs. Official scoping stops re-analysis runs producing duplicate hits.
- **Rejected:** altering the legacy `entities` / `instruments` / `assets` tables; unscoped search; public-only URLs (private buckets need presigning); an external embedding service for now.
- **Links:** [`../archived/supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`](../archived/supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql); [`data.md`](data.md); [`mvp2/README.md`](mvp2/README.md).

### 2026-10-16: MVP2 search route, chat route, crop service and launcher
- **Decision:**
  - `POST /api/v1/incidents/search` (`search-contract-v1`) and `POST /api/v1/incidents/chat` (`chat-contract-v1`) in `vss-agent`, mounted unconditionally, behind hexagonal ports (`SearchStore`, `QueryEmbedder`, `SearchClient`) with in-memory adapters; mock routes on :7777 and :7778 serve the frontend without a GPU.
  - The VLM critic was always on (superseded 2026-10-28: it is off by default, see the first entry above). A failed or timed-out critic call degrades to `verdict="unverified"` with `confidence=None`; hits are never dropped. Critic calls start `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` apart (default 1.0, 0 disables) to avoid upstream 429/500 bursts.
  - `CropEvidenceService` crops keyframes at `timestamp_seconds` using a detector port (remote VLM boxes, see above) (JPEG quality 85) and stores them via an `EvidenceStore` port (key layout: [data.md](data.md#2-cloudflare-r2-storage-architecture)).
  - `start.sh` always brings up and checks search (no `--search` flag); local readiness polls `/health`; `.scripts/tunnel-check.sh` probes search through the tunnel.
- **Why:** A pilot showed VLM bounding boxes were 0% well-framed but timestamps over 95% accurate, so the VLM supplies timestamps and labels and a detector supplies boxes. Ports let the workstreams proceed in parallel. Spacing call starts smooths bursts without retries or sequential latency.
- **Rejected:** VLM bounding boxes; dropping hits on critic failure; a feature flag for search; retries or thread pools for the critic.
- **Links:** [`../contracts/search-contract-v1/`](../contracts/search-contract-v1/); [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/); [`mvp2/README.md`](mvp2/README.md).

### 2026-10-16: Contract v3 temporal grounding and RP1 on core_ok
- **Decision:** `incident-contract-v3` adds required `timestamp_seconds` and `label` to entities, instruments and assets; bounding boxes are detector-produced only. Console validation is version-aware, so v2 runs stay viewable. RP1 runs when `core_ok` (not only `full_contract_ok`), receives the unchanged prediction, and `report_generation_prompt.txt` says timeline events outside the incident time are context.
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

### 2026-10-02: VLM benchmark: incident fields only, timed P1 round trip, interleaved models, no blended score
- **Decision:**
  - The midterm VLM benchmark runs the existing `eval/` pipeline with `eval_run.py --incident-only` on the 55 held-out videos. It scores only the incident fields with their existing metrics (`eval_gt.compare_incident_fields` plus the description judge). It does no entity/instrument/asset matching and no RP1.
  - **Primary fields:** type, severity_level, start_timestamp, end_timestamp and description. `duration` (end − start) is a derived diagnostic only.
  - There is no overall, pass-rate or weighted score. Each field is reported separately, and the per-video, per-model rows are kept.
  - **Processing time:** one P1 HTTP round trip, `perf_counter` immediately before `requests.post` to immediately after it returns with the full body (`eval_vlm_client.chat_completion`). It excludes R2 signing, the MP4 header read, validation, DB writes, scoring and RP1. The summary reports mean, median and p90 over completed calls. Failed calls are counted separately.
  - **Order:** video by video, all three models per video, with the model order rotated per video; calls are sequential.
  - **Timeout:** P1 uses the console's 300 s `timeout_seconds` from `contracts/inference.json` for every model, replacing the generic 240 s.
  - **Rate-limit policy (fixed before any full-run result):**
    - At least 20 s between the end of one P1 attempt and the start of the next.
    - HTTP 429 only is retried with the same request after a 60 s cooldown, or `Retry-After` when longer, at most 2 retries.
    - Nothing else is retried.
    - Waiting is never processing time.
    - The basis is the smoke test's 429s: cosmos-3-super at its 240 requests/min limit, and nemotron-3-nano-omni at its 30,000 tokens/min limit. One P1 call is about 6k prompt tokens plus up to 16k completion tokens.
    - With the three models interleaved, the 20 s gap keeps each model to about one call a minute. The 60 s cooldown is one rate-limit window.
  - **Outcomes:** `scored`, `contract_invalid` and `parse_failure` are model outputs and enter the field metrics. `rate_limited`, `timeout` and `http_error` produce no output, are reported separately and are never a wrong prediction. A timeout is no output, not a miss.
  - **Empty predicted description:** scored 0.0 without a judge call (`eval_gt.run_evaluation`). The judge has no fixed temperature and scored the same empty input 0.0 in one smoke test and 0.95 in the next. The judge model and its settings are unchanged.
  - **Video set statistics:** size from R2 `HeadObject` and length from the MP4 `mvhd` header (no download, no ffprobe), from `eval_dataset_stats.py` before any model call.
  - Every attempted `(video, model)` pair stays in the output, including timeouts, HTTP failures and contract-invalid responses. No schema change: everything is in the run's result JSON.
- **Why:**
  - Entities, instruments and assets are out of scope for the slides, and their matching needs the embedding server and many extra judge calls.
  - A blended score would contradict `eval_aggregate`'s rule of keeping metrics separate.
  - Timing only the request keeps the measurement identical across models and free of scoring time.
  - Interleaving keeps load changes on the shared hosted endpoint from landing on one model.
  - 240 s cut slow calls off earlier than the console would.
  - The smoke test lost 2 of 3 calls to shared-quota 429s, which would otherwise have counted as wrong predictions.
- **Caveat recorded with the results:** the request is identical, but `cosmos-3-super-reasoner` samples about 24 frames instead of the requested 64.
- **Rejected:**
  - A separate benchmark harness (would duplicate the contract request and scoring).
  - Timing in the gateway (it runs only in gateway mode, and eval may call Switchyard directly).
  - A per-model sequential order (biased by drift).
  - Downloading videos to measure them (the header and `HeadObject` suffice).
- **Recorded:** 2026-10-27, from the uncommitted benchmark work recovered by the offline-scoring change (the run and its code predate this entry).
- **Links:** [`../eval/README.md`](../eval/README.md#vlm-benchmark-incident-fields-processing-time); [`../eval/scripts/eval_benchmark_export.py`](../eval/scripts/eval_benchmark_export.py); [`../eval/scripts/eval_dataset_stats.py`](../eval/scripts/eval_dataset_stats.py).

### 2026-09-28: Dashboard and time filters use the viewer's timezone
- **Decision:** `get_incident_dashboard` and `list_incident_report_summaries` take `p_timezone` (default `'UTC'`) and convert `reports.generated_datetime` (naive UTC) for weekday and hour grouping and filtering. The console sends the viewer's IANA zone (offsets rejected) detected after mount; labels show local hours with the zone name. Migration `20260928000000` must be applied before or with the console deploy.
- **Why:** Operators analyse by local shift. Dashboard drill-down links stay count-exact because both pages detect the same zone.
- **Rejected:** client-side re-bucketing; converting the column to `timestamptz`.
- **Links:** [`../archived/supabase/midterm/migrations/20260928000000_local_time_heatmap_and_time_filters.sql`](../archived/supabase/midterm/migrations/20260928000000_local_time_heatmap_and_time_filters.sql); [`../incident-console-v2/src/lib/time.ts`](../incident-console-v2/src/lib/time.ts).

### 2026-09-27: Validation policy core-scored-v1
- **Decision:** Only database-backed fields (type, window, description, severity, confidence, entities, instruments, assets) decide persistence and scoring. `title`, `severity_reason`, `location`, `timeline` and `uncertainties` are best-effort enrichment: a `TIMELINE_*` failure is recorded and shown but neither rejects the report nor empties the eval prediction, and is never repaired. A contextual core rule requires the window to lie within the video when its length is readable (`0 <= T < duration + 1`). Schema violations stay fatal. `full_contract_ok` keeps contract validity; `core_ok` decides.
  This covers the Cosmos models, which often put lead-up or aftermath events outside their own incident window: the timeline is recorded as returned, never repaired, and the report page labels it ([`analysis-schema.md`](analysis-schema.md#3-validation-id-only-repair-and-outcomes)).
- **Why:** In a 12-call pilot the strict timeline rule rejected 7 answers, 4 with windows matching ground truth, yet accepted a 29-36 s window on a 12.5 s clip. Recovered answers rose from 6 of 15 to 13 of 15.
- **Rejected:** a whole-video timeline (deferred); isolating enrichment schema errors (needs partial parsing).
- **Links:** [`../contracts/README.md`](../contracts/README.md); [`../eval/contract.py`](../eval/contract.py); [`../incident-console-v2/src/modules/contract/domain/validate.ts`](../incident-console-v2/src/modules/contract/domain/validate.ts).

### 2026-09-27: Console on the shared contract with ID-only repair
- **Decision:** Gateway analysis sends eval's exact P1 request (allowlisted model from `contracts/inference.json`, canonical prompt, strict `response_format`, 16384 tokens, 64 frames) plus an optional fenced reviewer instruction. It validates strictly and records every attempt immutably in `model_runs.notes` with outcome `valid_first_pass`, `valid_after_structural_repair`, `contract_failed` or `request_failed`. The only repair is `id-normalization-v1`: it applies only when every violation is ID-only, changes only IDs, holder references and order, then re-validates. Eval never credits repaired output.
- **Why:** The endpoint enforces the schema, but cross-field rules (sequential IDs, timeline window) can only be checked afterwards. Malformed IDs are safely repairable; timeline content is a model judgement.
- **Rejected:** LLM repair passes; retrying the same request (deterministic at temperature 0); ID patterns in the schema (only if malformed-ID evidence justifies a v4).
- **Links:** [`analysis-schema.md`](analysis-schema.md); [`../incident-console-v2/src/modules/contract/domain/repair.ts`](../incident-console-v2/src/modules/contract/domain/repair.ts).

### 2026-09-27: Unified contract decisions (eval, console, agent)
- **Decision:** The eval P1 prompt is the base. Nested snake_case output enforced by `response_format: json_schema`, with the prompt describing field meaning only. One request pattern everywhere: P1 (video to JSON) then RP1 (JSON to prose). Strict parsing, no few-shot, no alias normalisation. Taxonomy is eval's five labels: road accident, burglary, explosion, assault, animal attack. Video is a 1 h signed R2 URL in every path. `confidence_score` is null unless the API gives a native score. `incident.duration` is computed as `end_timestamp - start_timestamp` and is not in the schema. Files live in `contracts/`, validated in Python with `jsonschema` plus cross-field checks in `eval/contract.py`.
- **Why:** The three paths previously differed in prompt, schema, taxonomy, video encoding and parsing, so the benchmark did not measure production behaviour; category few-shot leaked the label; asking a model for a value code can compute only adds a failure mode.
- **Rejected:** a seven-label taxonomy (overlapping labels the ground truth cannot score); base64 video; tolerant parsing; Pydantic as the shared source (the schema file is the neutral source).
- **Links:** [`../contracts/README.md`](../contracts/README.md); [`analysis-schema.md`](analysis-schema.md).

### 2026-09-27: Report library and thumbnails
- **Decision:** The report library (now `/library`) is served by the `list_incident_report_summaries` RPC (`SECURITY INVOKER`, `service_role` only), six summaries per page, returning no notes, evidence arrays or signed URLs. Cards never load video. The browser captures a frame 25% into each new upload (at most 640x360 WebP) and uploads it to `thumbnails/<video-key>.webp`; a missing thumbnail shows a skeleton, and deleting a video deletes its thumbnail. `GET /api/reports/<videoId>?revision=<revisionId>` is the only path that signs and loads a video.
- **Why:** The old library read eight tables, parsed every report and signed every video before becoming usable.
- **Rejected:** a summary table; client-side slicing; per-card video loading; server-side frame extraction per request.
- **Links:** [`../archived/supabase/midterm/migrations/20260926120000_list_incident_report_summaries.sql`](../archived/supabase/midterm/migrations/20260926120000_list_incident_report_summaries.sql); [`../incident-console-v2/src/app/api/reports/route.ts`](../incident-console-v2/src/app/api/reports/route.ts).

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

### 2026-09-24: Separate eval pipeline
- **Decision:** Evaluation is a standalone P1/RP1 pipeline in `eval/`, not `nat eval`, because it scores per-field extraction against tabular ground truth rather than chat trajectories.
- **Links:** [`../eval/`](../eval/).

### 2026-09-21: Native services on the VM
- **Decision:** Run `vss-agent`, `video-analytics-api` and `behavior-analytics` as native host processes via `.scripts/native-services.sh`; VIOS/VST media and infrastructure stay in Docker.
- **Why:** A code change is a ~2 s restart instead of a container rebuild. Media, DeepStream, Triton and JVM appliances depend on container toolchains and gain nothing natively. All services use host networking, so native processes reach Docker ones on localhost.
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-17: Agent database access through PostgREST
- **Decision:** The agent uses Supabase PostgREST over HTTPS (`utils/incident_db.py`, `supabase-py`). Report writes are single-row `report_revisions` inserts (see the 2026-10-23 revisions entry).
- **Why:** The campus firewall on the VM drops outbound port 5432, so raw Postgres drivers fail; PostgREST lacks client-held transactions, so each write is one row.
- **Rejected:** direct Postgres / `asyncpg` on the VM.
- **2026-11-07 observation:** a `select 1` through the Supabase pooler connected from both the VM and the laptop on ports 5432 and 6543. The block has come and gone and the cause is not established, so the decision stands: the agent and console stay on HTTPS, and direct access is only for one-off database work.
- **Links:** [`data.md`](data.md); `services/agent/src/vss_agents/utils/incident_db.py`.

### 2026-11-02: `compose up --yes` in every start path
- **Decision:** Every `docker compose up` that start.sh reaches (`vm-ensure-docker.sh`, `tracking-stack.sh`, `rebuild-svc.sh`) passes `--yes`.
- **Why:** Compose 2.35.1 asks "Volume exists but doesn't match configuration. Recreate?" and waits on stdin, which hung start.sh for 13 minutes over no-tty ssh. With stdin closed and no `--yes` it does not abort, it silently keeps the old container. `--yes` recreates both. Verified on the VM with a throwaway project.
- **Rejected:** piping `yes` (undocumented, masks other prompts); `down -v` first (destroys unrelated state).

### 2026-11-02: Closing `start.sh` leaves the VM backend running
- **Decision:** No exit path of `start.sh` (last session or not, Ctrl-C, SIGTERM, SIGHUP, error) stops anything on the VM. `cleanup()` stops only laptop-side things: the console, the local mock and gateway, the SSH tunnel and temp files. The VM active-run flock (`.run/active-runs.lock`, held by `ssh -tt ... sleep infinity`), `VSS_LOCK_FILE`, `.scripts/vm-stop-backend.sh` and `test-vm-stop-backend.sh` are removed, since the lock only existed to find the last session. The start path is unchanged and still starts whatever is missing. To stop the backend on purpose, run `native-services.sh stop` and `tracking-stack.sh stop` on the VM.
- **Why:** The backend (shared vss-agent, Phoenix, the tracking stack) is shared by several people and workers. The last-exit stop killed it under others' runs on 2026-11-02, while workers were using it. Leaving a shared service up costs idle memory; stopping it costs other people's work.
- **Rejected:** keeping the stop behind an opt-in flag (nothing needs it; the manual scripts already exist); keeping the lock for registration only (no reader).
- **Links:** [`../start.sh`](../start.sh); [`incident-profile-operations.md`](incident-profile-operations.md); [`../skills/incident-start/SKILL.md`](../skills/incident-start/SKILL.md).

### 2026-11-02: Tracker model files are fetched at agent start, pinned by hash, not committed
- **Decision:** `.scripts/tracker-models.sh` (run by `native-services.sh` before it starts `vss-agent`, non-fatal) downloads the two NanoTrack v2 `.onnx` files (about 1.8 MB) into `<repo>/.tools/tracker-models` and checks each SHA-256 before renaming it into place. `native-services.sh` exports that dir as `INCIDENT_OBJECT_TRACKING_MODEL_DIR` unless the env file sets it.
- **Source:** `HonglinChu/SiamTrackers` at commit `8fe6791fecf13b95e6f19770af8963a9fc98759b` (2022-12-13), `NanoTrack/models/nanotrackv2/`: `https://raw.githubusercontent.com/HonglinChu/SiamTrackers/8fe6791fecf13b95e6f19770af8963a9fc98759b/NanoTrack/models/nanotrackv2/<file>`. `nanotrack_backbone_sim.onnx`: 1,056,849 bytes, SHA-256 `530bdd0cd00f19afab79a863e71ba71e3312395a5dc9151af675082bdaaa2fc4`. `nanotrack_head_sim.onnx`: 726,198 bytes, SHA-256 `0d8c0637be849f092cc7236cae02e55c8b9455ebe37ba50601d6115db4247cd9`.
- **Licence (unclear):** the repository has no licence file (`gh api repos/HonglinChu/SiamTrackers/license` returns 404), and it is the only published source of these weights (OpenCV's `opencv_extra` download script points to it). The captain chose Nano on 2026-11-02 knowing this. Because the licence is unclear, the files are fetched at deploy time and never redistributed through this repository. The Apache-2.0 alternative is `opencv_zoo`'s `object_tracking_vittrack_2023sep.onnx` (about 4 points less accurate in the tracker scout); switching needs only a new pinned file here.
- **Why:** the shared VM has no manual step, matches how `media-tools.sh` handles ffmpeg, and a mismatching download is refused rather than loaded.
- **Rejected:** committing the binaries (licence); an unpinned download (a moved upstream file would change tracking silently).
- **Links:** [`../.scripts/tracker-models.sh`](../.scripts/tracker-models.sh), [`../.scripts/native-services.sh`](../.scripts/native-services.sh), [`../.scripts/test-native-services.sh`](../.scripts/test-native-services.sh).

### 2026-11-02: Library cards trade info lines for a bigger thumbnail
- **Decision:** `IncidentCard` shows only the incident type, official status, title and one-line summary under the thumbnail. The file name and "Added" date are in the title tooltip; evidence and version counts are only in the "..." menu.
- **Why:** the earlier cards led with a larger thumbnail. Card height is fixed by the viewport grid (PR 264), so every info line removed gives the thumbnail height (93 to 137 px at 1440x900). The pre-shadcn card (before PR 255) had a 16:9 thumbnail; PR 255 cut it to 96 px, PR 260 to 80 px and PR 264 made it fill what the info left.
- **Rejected:** shrinking the summary or title (the title and type are what people scan for).

### 2026-11-03: Track labels show the item's name, never its id
- **Decision:** the player overlay box, the presence bars' accessible names and the pop-up label a track with the item's name (`TrackedReportItem.label`: entity label or type, instrument or asset name; the id only when a name is empty). Ids (`E1`, `T-1`, `N-1`) stay internal keys (`data-track-item`, selection, routes) and the id badge on cards and the pop-up title is unchanged.
- **Why:** captain, 2 Nov: tracking reads by the names of evidence, not codes; part of the add/track evidence build.
- **Links:** [`TrackOverlay.tsx`](../incident-console-v2/src/sections/reports/components/TrackOverlay/TrackOverlay.tsx), [`track.ts`](../incident-console-v2/src/modules/reports/domain/track.ts).
# 2026-11-05 — Reviewer frame extraction retries an HTTPS-reader segfault from a temporary local file

**Decision.** The console normally lets ffmpeg range-read the signed R2 video URL. If that process terminates with `SIGSEGV`, it streams the same URL to a temporary local MP4, retries the requested frame from disk, and removes the temporary directory. Reviewer crop and full-frame extraction remain sequential.

**Why.** The bundled static ffmpeg can segfault in its HTTPS/range reader for a valid uploaded clip. That prevented saving a human revision containing newly added evidence even though the browser could play the video. A local-file retry bypasses the crashing network protocol path without weakening validation or storing temporary media permanently.

**Alternatives rejected.** Retrying the same URL repeats the crash; making Add to draft generate the final image couples reversible draft work to ffmpeg; keeping the temporary file leaks incident video data; replacing the bundled ffmpeg globally is a broader deployment change and does not provide per-request recovery.

**Links.** [`incident-console-v2/src/lib/video/ffmpeg-frame.ts`](../incident-console-v2/src/lib/video/ffmpeg-frame.ts), [`console-reference.md`](console-reference.md)

### 2026-11-07: The inference endpoint address lives only in untracked env files

The Switchyard address was committed in the profile `.env`, the gateway and the agent code defaults. It now comes only from settings: `VLM_BASE_URL` (critic), `VLM_GATEWAY_BASE_URL` then `VLM_BASE_URL` (evidence detector), `VLM_GATEWAY_BASE_URL` (gateway and archived eval client), and the profile `.env` keeps `LLM_BASE_URL`, `VLM_BASE_URL`, `LLM_ENDPOINT_URL` and `VLM_ENDPOINT_URL` blank. The laptop reads them from `.env.local`, the VM agent from `.env.remote`. A missing address raises an error naming the setting when the first call is made (not at construction, so tests and tooling that build clients still work). Git history keeps the old address and is not rewritten. `eval/scripts/eval_vlm_client.py` still holds a default and belongs to another owner.

### 2026-11-07: The severity rationale is editable

The rationale was model output copied into every human version, so a human report showed text nobody on the team wrote. It is now a Class A field (`incident.severity_reason`, a string the contract already defines, so no contract version change) edited in Edit mode and stored on the human version; the "For model severity N/5" line is removed. Alternative rejected: leaving it read-only and hiding it on human versions (loses the explanation).

### 2026-11-07: Confidence is a tag beside the title, never a row

Confidence stays model-sourced and read-only, but a Confidence row (View and Edit) implied the reviewer could set it. It is now a small right-aligned tag beside the title in both modes and is absent when the version has none; the "Title generated by the model" line is removed with it.

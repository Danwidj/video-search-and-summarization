# Incident Profile Decision Log

Decisions that still shape `dev-profile-incident`, newest first. Each entry: decision, why, alternatives rejected, links. Superseded and purely historical decisions are removed; git history has them.

### 2026-10-31: Evidence shows the whole frame with a box, not a crop
- **Decision:** the agent stores each evidence item's whole video frame (`evidence/<video key>/run-<n>/<itemId>-frame.jpg`, native size) beside the crop, plus `box_seconds` and `located` in the evidence entry. The console draws the box on the frame (report cards, Edit cards, evidence search tiles and viewer; object-contain, never object-cover); the crop is kept only for evidence search. When the detector finds nothing the agent retries at +1, -1, +2 and -2 s and keeps the first hit with the second it used (each second is one call against the unchanged `max_crop_calls` budget); with no hit it stores the frame with no box, `located: false` and an `image_gap`, never `[0,0,1000,1000]`. Items analysed before this have no stored frame: the console cuts it from the stored video through the existing frame route and reads a stored whole-frame box as not located. No contract bump, no migration (evidence is JSONB).
- **Why:** crops were cut at the video's native size (25 to 117 px on a 480p clip) and shown object-cover in a 2:1 tile, so a tall crop became a magnified slice, and the whole-frame fallback was stored as a real box, so a card showed a hallway with no object. Context tells a reviewer more than a cut-out does.
- **Rejected:** returning the frame key from evidence search (the hit rows come from `evidence_crops`, which has no frame column and no migration is allowed: search tiles cut the frame from the video instead); upscaling the crop (still no context); regenerating old reports (their data stays as analysed); a new column or migration; Edit's picker writing a frame instead of a crop (search needs the crop; the picked frame and box are shown from the stored video instead); cherry-picking mvp3's #375 (it removed the crop-call cap and targets another schema).
- **Links:** [`../../../../services/agent/src/vss_agents/utils/crop_evidence.py`](../../../../services/agent/src/vss_agents/utils/crop_evidence.py), [`../incident-console-v2/src/lib/evidence/evidence-view.ts`](../incident-console-v2/src/lib/evidence/evidence-view.ts).

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

### 2026-10-29: Videos tab and screen removed in favour of focused incident workflow
- **Decision:** Remove the Videos tab (`/videos`) from the primary navigation header and mobile dropdown, delete the `/videos` page route (`src/app/videos/page.tsx`) and the `VideosScreen` section component (`src/sections/videos/components/VideosScreen/`). Dashboard overview metrics ("Uploaded videos", "Awaiting official report", "Without a report") render as static summary cards without links to the removed route. The individual video history route (`/videos/[videoId]`) is retained for history inspection and re-runs.
- **Why:** The dedicated `/videos` inventory table duplicated video discovery already served by the Incident Library (`/library`) and added navigational clutter. Removing the tab streamlines the console into three core areas: Analyze (upload orchestration), Library (incident exploration and evidence search), and Dashboard (analytics).
- **Alternatives rejected:**
  - *Retaining the Videos tab with reduced scope:* Rejected because user navigation is simpler when incident reports in `/library` serve as the single destination for video results.
  - *Repointing dashboard video metrics to `/library`:* Rejected because `/library` displays analyzed incident reports, not unanalyzed video assets or clips awaiting an official report selection.
- **Links:** `src/sections/shell/components/AppHeader/AppHeader.tsx`, `src/sections/dashboard/components/Dashboard/Dashboard.tsx`, `src/app/videos/page.tsx`, `src/sections/videos/components/VideosScreen/VideosScreen.tsx`.

### 2026-10-29: Remove orphaned "Analysis history for this video" section from report page
- **Decision:** Remove the orphaned `AdvancedReportTools` component (`src/sections/reports/components/AdvancedReportTools/`) and its "Analysis history for this video" section from `incident-console-v2`. Re-analysis continues to be provided by `ReanalysisDialog` in the sticky top bar, while video run history remains on `/videos/[videoId]` (`VideoHistoryScreen`). Test assertions and documentation references are updated accordingly.
- **Why:** The re-analysis card was migrated to `ReanalysisDialog` in the sticky top bar (#266), leaving `AdvancedReportTools` unmounted from the report page and orphaned. Deleting the component eliminates dead code and removes the obsolete bottom run history list per product direction.
- **Alternatives rejected:**
  - *Restyling or re-mounting the bottom run history on the report page:* Rejected as redundant with the version history panel in the top band and the dedicated video history screen.
  - *Deleting `RunHistoryList` or `/api/videos/[videoId]/runs`:* Rejected because they are still actively used by the Videos screen (`VideoHistoryScreen`) and re-analysis orchestration.
- **Links:** `src/sections/reports/components/ReportPage/ReportPage.tsx`, `tests/report-editing-ui.test.mjs`, PR #266.

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
  - *Adding resize handles to `EvidenceFramePicker`:* Inspected and rejected because `EvidenceFramePicker` is a video frame crop canvas for drawing 2D bounding boxes, not a split panel.
- **Links:** `src/sections/reports/components/ReportPage/ReportPage.tsx`, `src/components/ui/resizable.tsx`.

### 2026-10-29: Rebuild 5-stage analysis progress bar on shadcn Progress component with accessible announcements
- **Decision:** The video analysis workspace (`AnalysisWorkspace`) replaces the unsegmented stage card list and standalone upload bar with the unified shadcn `Progress` component (`@/components/ui/progress.tsx`). The continuous progress bar represents overall progress across the 5 analysis stages (`uploading` 0-20%, `preparing` 40%, `analyzing` 60%, `saving` 80%, `complete` 100%, and retains failed stage progress on error). Stage labels are maintained directly beneath the bar in a structured list (`<ol aria-label="Analysis stages">`) showing step numbers, checkmarks (`✓`), active indicator (`aria-current="step"`), failure indicators (`✕`), and upload percentage chips. Accessible screen reader support includes `role="progressbar"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, `aria-valuetext`, and a polite live region (`role="status" aria-live="polite"`).
- **Why:** The previous UI rendered the 5 stages solely as a list of static card borders with an upload-only progress bar displayed conditionally during file transfer, lacking a unified progress bar for the full analysis pipeline, proper ARIA progress values, and screen reader announcements.
- **Alternatives rejected:**
  - *Five separate disconnected Progress bars:* Rejected because Radix UI Progress represents a single value range; fragmented mini-bars clutter the UI and impair screen reader parsing.
  - *Hiding stage labels entirely:* Rejected because operators need visual and semantic confirmation of each pipeline stage.
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

### 2026-10-28: Videos screen uses a unified lifecycle status badge, direct report action, and responsive card-table layout
- **Decision:** The Videos list (`/videos`) replaces the separate "Reports" (version count) and "Status" (official boolean or dash) columns with a single consolidated "Report & Lifecycle Status" badge column (`Official`, `Report ready`, `Ready to analyse`, with subtext version counts). The table provides direct primary action buttons (`Open report →` when revisions exist, `Analyse video →` when 0 revisions exist) and a secondary `...` dropdown menu (`Analysis history`, `View report`, `Copy video ID`). Filtering supports `All`, `With report`, `Needs analysis`, and `Failed`. The header includes a filename search input and an `Upload video` button. On viewports below `md` (< 768px), the layout switches from a table to vertical stacked cards without horizontal clipping.
- **Why:** The previous Status column showed `—` on every video where an official version had not been explicitly chosen, misleading operators into thinking processing was missing or broken. Users had to navigate through the intermediate `/videos/<id>` history screen just to open a report. On mobile screens (390px), the table clipped horizontally with an unhelpful swipe banner.
- **Alternatives rejected:**
  - *Pure card grid (like `/library`):* Rejected because video asset inventory requires high scan density, fast chronological triage, and batch monitoring.
  - *Renaming the Status column only:* Rejected because it leaves mobile clipping, disjointed version counts, and missing direct report navigation unsolved.
- **Links:** `src/sections/videos/components/VideosScreen/VideosScreen.tsx`, `src/app/api/videos/route.ts`, `src/modules/videos/domain/VideoRepository.ts`.

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
- **Decision:** the model-generated `timeline` is being dropped from the report. It is not removed yet: `incident-contract-v4` still carries `timeline`, and the report page still draws the timeline lanes. The removal will change the contract (a version bump per the contract rules) and the console together.
- **Why:** the timeline is enrichment, not a core scored field: its violations are not fatal under `core-scored-v1`, and the report page already has to warn when it disagrees with the incident window ([`analysis-schema.md`](analysis-schema.md)).
- **Links:** [`analysis-schema.md`](analysis-schema.md), [`status.md`](status.md#5-action-items).

### 2026-10-28: R2 object names are readable and deterministic: the original file name, `run-N` and `edit-N`, never a hash or UUID
- **Decision:** a new upload is stored as `uploads/<original file name>` (unsafe characters become `_`, names over 150 characters are cut with the extension kept, a taken name gets `-2`, `-3`). The thumbnail is `thumbnails/<video key>.webp`. Evidence is `evidence/<video key>/run-<N>/<itemId>.jpg` (AI crops) and `evidence/<video key>/edit-<N>/<itemId>.jpg` (reviewer images). Every write is a conditional put (`If-None-Match: *`), so nothing is ever overwritten. The upload page warns before upload when the name is taken or has unsafe characters.
- **Existing objects:** `supabase/r2/migrate_r2_names.py` copies each to its readable key, verifies the copy, and updates `videos.filepath`, `report_revisions.evidence` and `evidence_crops.image` through `apply_r2_rename`. The live rename was run on finals (2026-10-28): the old copies and the orphaned objects were then deleted by hand.
- **Why:** reviewers see and recognise file names, and operators can read the bucket. The previous keys carried a sensor id and a UUID that meant nothing outside the system. `videos.id` stays the compact hash (it is the primary key and URL id).
- **The append-only exception:** `report_revisions` rows keep the old R2 keys unless the table can be updated. `apply_r2_rename` sets a transaction-local flag and the trigger then allows an `UPDATE` that changes only the `evidence` column; any other change, and any `UPDATE` without the flag, is still refused. `model_runs.notes` is not rewritten, so it keeps the old key as history.
- **Alternatives rejected:** leave old objects as they are (the captain asked for no hashes in any name); resolve old keys through a lookup table (every reader would need it, and the names would still be unreadable); rewrite revisions with a plain `UPDATE` after disabling the trigger (loses the guarantee that revisions are never edited); a random suffix for collisions (not deterministic, brings the ids back).
- **Known limits:** the original name of a pre-migration upload is not in the database, so the script uses the VST sensor name, else the upload time. Two analyses of one video that start together can pick the same `run-N`; the conditional put makes one fail instead of overwriting.
- **Links:** [`data.md` §2](data.md#2-cloudflare-r2-storage-architecture), [`supabase/r2/migrate_r2_names.py`](../supabase/r2/migrate_r2_names.py), [`20261028090000_r2_rename.sql`](../supabase/migrations/20261028090000_r2_rename.sql).

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
- **Open owner decisions:** A1–A4, B1–B2, C1–C3 in [stage2-plan.md §6](../eval/docs/experiments/stage2-plan.md#6-decisions-that-still-need-the-owner).
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
- **Links:** [`../eval/ground_truth/annotation-guidelines-v1.0.md`](../eval/ground_truth/annotation-guidelines-v1.0.md); [`mvp2/ground-truth-and-prompt-experiments-plan.md`](mvp2/ground-truth-and-prompt-experiments-plan.md) (PR 1A, D1, D2).

### 2026-10-27: The evaluation videos are local verified copies with a tracked manifest; `_demo` is the one filename alias
- **Decision:** `eval/scripts/eval_fetch_videos.py` downloads every `anomaly/<folder>/<file>.mp4` except `anomaly/shooting/` (80 clips) to the gitignored `eval/eval_data/videos/<folder>/<original filename>`. Each clip is verified (size equal to R2, the R2 ETag reproduced from the local bytes for single-part and multipart uploads, SHA-256, MP4 `mvhd` duration) through a `.part` file and kept only when it passes. The tracked `eval/eval_reproducibility/dataset-manifest-v1.json` records every clip and the integrity findings. Filename resolution ignores a `_demo` suffix just before the extension, so `anomaly/demo/<Id>_x264_demo.mp4` resolves from the ground-truth name `<Id>_x264.mp4`. The split manifests keep their 25/55 membership; `eval_refresh_split_keys.py` rewrites only their R2 keys.
- **Why:** 24 clips moved into `anomaly/demo/` on 2026-10-27 with that suffix and identical sizes, so the split manifests named keys that no longer exist and `eval_run.py` skipped those videos. The ground-truth correction and prompt work need a fixed, checkable video set: SHA-256 per clip plus a set hash make any later change visible. Model calls still use signed R2 URLs; local copies are for hashing, review and frame extraction.
- **Rejected:** renaming or copying R2 objects back (a write to shared R2, and the demo folder is wanted as it is); a general fuzzy filename match (would hide real mismatches); regenerating the splits (changes membership and the seeded draw); committing videos or their hashes only in gitignored files.
- **Links:** [`../eval/dataset_manifest.py`](../eval/dataset_manifest.py); [`../eval/scripts/eval_fetch_videos.py`](../eval/scripts/eval_fetch_videos.py); [`../eval/scripts/eval_refresh_split_keys.py`](../eval/scripts/eval_refresh_split_keys.py); [`mvp2/ground-truth-and-prompt-experiments-plan.md`](mvp2/ground-truth-and-prompt-experiments-plan.md) (PR 2).

### 2026-10-27: eval scores offline by default; the database path and schema creation are explicit
- **Decision:** `eval_run.py` writes predictions to, and scores them from, an in-memory `OfflineEvalStore` (`eval/offline_store.py`), with ground truth loaded straight from the workbook by the same `write_gt` the ingest script uses. The scorer itself (`eval_gt`, `matching`) is unchanged. The database path needs `--db`. `db.get_db()` no longer creates tables: only `get_db(init_schema=True)` (`--db --init-schema`) does, and without it the database is only probed. `eval_ingest_gt.py` needs `--dry-run` (no database) or `--db`. The uncommitted 2026-10-02 benchmark work (rate-limit pacing, timing, outcome classes, `--incident-only`, export and dataset-statistics scripts) is recovered onto main with it.
- **Why:** finals dropped the `gt_*`, relational report and `*_matches` tables, and `get_db()` ran `init_schema()`, so any eval run with the shared `.env.local` would have recreated them on the live database. Offline scoring removes the database from experiments entirely. The store copies the database's observable behaviour (all table columns, SQL type coercion, id ordering, the replace-and-cascade on re-insert), and `tests/test_offline_store.py` requires identical scores to the SQLite `IncidentDB` path and fails if the default path touches any database entry point, even with finals credentials set.
- **Rejected:** new eval tables on finals (a schema change to support offline evaluation, which the workstream plan rules out); rewriting the scorer to take plain dicts (it would change the measuring instrument; the store keeps the scorer byte-identical); SQLite on disk as the default (a database file per run with no benefit over memory).
- **Links:** [`../eval/offline_store.py`](../eval/offline_store.py); [`../eval/tests/test_offline_store.py`](../eval/tests/test_offline_store.py); [`mvp2/ground-truth-and-prompt-experiments-plan.md`](mvp2/ground-truth-and-prompt-experiments-plan.md) (PR 0).

### 2026-10-25: The library card shows MVP1's thumbnail again
- **Decision:** The `/library` incident card shows MVP1's report-card image (`ReportThumbnail`): the video's upload-time screenshot only, MVP1's skeleton when it is missing or its one request fails, and MVP1's severity chip and AI/Human badge on top. The card never falls back to an evidence crop, and `/api/reports` signs only the screenshot. The five finals videos with no screenshot are a separate data gap, not backfilled.
- **Why:** The captain wants the thumbnails identical to MVP1's (known issue 4). The wrapper is a `<figure>` rather than MVP1's `<div>` so its `aria-label` is valid (Tailwind's base styles zero figure margins, so it renders the same), and the plain `<img>` is kept with a Biome suppression because `next/image` would proxy and re-encode the presigned R2 URL through the console server. #185 had added an evidence-crop fallback, a smaller chip and no badge, which also contradicted the 2026-09-27 decision ("a missing thumbnail shows a skeleton"). A failed screenshot is not retried or replaced, so a missing one costs one browser error, not two requests.
- **Rejected:** keeping the evidence-crop fallback with MVP1's badges; backfilling the five missing screenshots into shared R2 without explicit approval; checking each screenshot with `HeadObject` before signing (an R2 call per card to hide a data gap the backfill would close).
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
- **Rejected:** deleting the rows first and sweeping afterwards (the sweep refuses an unknown video); a background job (no scheduler in the console). Images of videos deleted before this change stay in R2 until someone decides to remove them ([status](status.md#4-known-issues)). As with videos, a removed finals image may still be named by the frozen midterm record ([architecture](architecture.md)).
- **Links:** [`data.md`](data.md#2-cloudflare-r2-storage-architecture); [`../incident-console-v2/src/modules/reports/application/delete-video-and-reports/index.ts`](../incident-console-v2/src/modules/reports/application/delete-video-and-reports/index.ts).

### 2026-10-25: start.sh waits on the console and stops each local process tree
- **Decision:** `start.sh` runs `npm run dev` as a background job and `wait`s on it, traps `INT`, `TERM` and `HUP`, and its cleanup stops each local job together with every process it started (found through parent pids with `pgrep -P`, listed before any kill).
- **Why:** Reproduced on 2026-10-25 (known issue 8): a SIGTERM to `start.sh` alone left `next-server`, the mock and the gateway listening, because bash runs a trap only after the foreground command returns, and killing a wrapper (`uv run`, `npm run`) does not stop the server it started. Ctrl-C from a terminal worked only because the terminal signals the whole process group.
- **Rejected:** `setsid` or `set -m` per child (`setsid` is not on macOS laptops, and `set -m` changes terminal and signal handling for every background job, including the VM lock's `ssh -tt`); killing process groups (all children share `start.sh`'s group, so it would signal `start.sh` too).
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md); `eval/tests/test_start_script.py`.

### 2026-10-24: Chat about the official version uses the in-memory chat search client for MVP2
- **Decision:** A chat question about the official revision with no draft goes to the agent chat route's search client, which stays the in-memory canned client for MVP2, so it finds no evidence for a finals video. Other versions and drafts are answered from their saved evidence.
- **Why:** A deliberate choice by the captain (2026-10-24); no reason was recorded.
- **Rejected:** none recorded.
- **Links:** [`vm-api-contracts.md`](vm-api-contracts.md#post-apiv1incidentschat).

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
- **Links:** routing and indexing investigation (firstmate scout report, 2026-10-24); [`mvp2/README.md`](mvp2/README.md#7-still-not-final-planned-not-final--master-todo-index); [GPU rule](incident-profile-operations.md#5-vm-deployment-configuration-principles-generatedenvremote).

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
- **Decision:** `tests/import-boundaries.test.mjs` fails when domain or application code imports infrastructure, `app`, `sections`, `next`, `react` or `node:*`, or when a section imports infrastructure or `node:*`. Each existing exception is listed in `ALLOWED` with its reason, and an entry that matches no import also fails. Two console files are allowlisted exceptions: `src/modules/analysis/application/build-request.ts` and `run-contract-analysis.ts` import the contract loader, and `run-contract-analysis.ts` also imports `node:crypto`; removing them is the `ContractCatalog` follow-up in [`status.md`](status.md#5-follow-ups).
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
- **Links:** [pull/207](https://github.com/Danwidj/video-search-and-summarization/pull/207); [`architecture.md`](architecture.md#report-versions-view-edit-and-history).

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
- **Decision:** `GET /api/reports/[videoId]/frame?t=` decodes one frame, and `POST /api/reports/[videoId]/evidence-crop` cuts a reviewer-dragged rectangle from it and returns the JPEG (since 2026-10-24 it stores nothing; Save uploads it). Both run `ffmpeg` on the console host's PATH over a signed R2 URL (range reads). No npm dependency is added.
- **Why:** Choosing a frame needs the exact second decoded from the video. The console already holds the R2 credentials and does the byte-range reads; the agent does not (since 2026-10-25 it reads only the MP4 header, through the signed URL). This reverses the 2026-09-27 rejection of server-side frame extraction.
- **Rejected:** a new npm video library (ffmpeg is already the standard tool and needs no dependency); cutting crops in the agent (it has no R2 credentials).
- **Links:** [pull/183](https://github.com/Danwidj/video-search-and-summarization/pull/183); [`architecture.md`](architecture.md#report-versions-view-edit-and-history); [`incident-profile-operations.md`](incident-profile-operations.md).

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
- **Links:** [`data.md`](data.md); [`architecture.md`](architecture.md#report-versions-view-edit-and-history); [`analysis-schema.md`](analysis-schema.md#report-revisions-ai-and-human); [`../supabase/README.md`](../supabase/README.md).

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
- **Why:** Multiple teammates running `./start.sh` concurrently or sequentially under different user accounts on `kwanz-ws` crashed with "Permission denied" on `.run/vss-agent.log` and `.pid` while another user's agent was already healthy on port 8000; `native-services.sh status` reported STOPPED because it trusted only its own user's PID file; and `status` listed optional analytics services as STOPPED by default, adding noise.
- **Rejected:** Running all native services under a single system daemon or dedicated VM service account (heavier, out of scope, complicates local git/venv development); trusting only PID files without HTTP endpoint health checks; changing `start.sh`'s porcelain parsing contract.
- **Links:** [`../.scripts/native-services.sh`](../.scripts/native-services.sh); [`../.scripts/test-native-services.sh`](../.scripts/test-native-services.sh); [`incident-profile-operations.md`](incident-profile-operations.md#managing-native-services-scriptsnative-servicessh).

### 2026-10-23: The agent writes JSONB report revisions
- **Decision:** After a valid analysis the agent appends one `report_revisions` row (`kind='ai'`, full report as JSONB `payload`, crop list as `evidence`, facet columns, `parent_id` NULL) in agent mode, and persists `query_results` against `revision_id`. Re-generation is a new AI branch and copies nothing from earlier revisions. `reviewer_prompt` (max 1000 chars) is added to the report prompt for that run only. Evidence images go to R2 under `evidence/<videoId>/<uuid>/<itemId>.jpg` with a new `<uuid>` per run; an item with no image records an `image_gap` reason in the evidence JSONB. The agent does not write `evidence_crops`: the console calls `POST /api/v1/incidents/evidence-embeddings {"revision_id"}` when a revision becomes official and stores the rows. `scripts/backfill_official_timestamps.py` is removed.
- **Why:** The captain moved the database to versioned JSONB snapshots (`videos`, `model_runs`, `queries`, `report_revisions`, `evidence_crops`, `query_results`) and dropped the relational report tables and their RPCs, so every old agent write was broken. An append-only snapshot needs one insert and no RPC. Gateway-mode runs write no images; cropping in the analyze route covers agent-mode runs, and unique keys mean a re-generation can never overwrite an official revision's images. Only official revisions are searched, so embedding on promotion avoids paying for revisions nobody searches.
- **Rejected:** a migration script for existing data (the captain applied the schema by hand and wants none); the agent writing `evidence_crops` itself (the console owns promotion); keeping the backfill loader (nothing left to backfill, the old tables are gone).
- **Links:** [`data.md`](data.md); [`vm-api-contracts.md`](vm-api-contracts.md); `services/agent/src/vss_agents/utils/incident_db.py`; `services/agent/src/vss_agents/tools/incident_report_gen.py`.

### 2026-10-22: Strict chat models matching chat-contract-v1
- **Decision:** The agent and mock chat models use `Literal` types for `role`, `scope` and `item_type`, `extra="forbid"`, `min_length=1` on ids, `ge=0` on `timestamp_seconds`, and `AssistantMessage.citations` has no default. Fixture tests feed the contract fixtures to both sets of models. The hand-written scope check is gone; pydantic returns the `422`.
- **Why:** The models accepted values the schemas reject (`request-invalid-scope.json`, `response-invalid-role.json`). The contract requires `citations`, and the route always sends it. No console or eval code called the chat route then, so no current sender was rejected.
- **Rejected:** relaxing the contract; sharing one model module between agent and mock (the mock stays standalone).
- **Links:** [`../contracts/chat-contract-v1/`](../contracts/chat-contract-v1/); [`vm-api-contracts.md`](vm-api-contracts.md).

### 2026-10-22: Stop VM backend services on last exit via shared flock over SSH
- **Decision:** `start.sh --mode vm` registers active sessions by holding a shared flock on a world-writable lock file on the VM (`$VSS_REPO_ROOT/.run/active-runs.lock`) through a long-lived SSH connection with pseudo-terminal allocation (`-tt` so remote lock processes terminate when the client disconnects). If registration cannot be confirmed within 10s (e.g. while an exclusive stop lock is held during backend shutdown), `start.sh` aborts with a retry prompt rather than continuing unregistered. On exit (Ctrl+C, SIGTERM, normal exit), `start.sh` releases its shared lock and executes `.scripts/vm-stop-backend.sh` over SSH. `vm-stop-backend.sh` attempts a non-blocking exclusive flock; only when it succeeds (proving the exiting session is the last active user on the shared VM) does it stop the native services (`native-services.sh stop`) and expected Docker containers via `docker stop`. Docker containers are only stopped, never removed or deleted (`docker rm`, `compose down`, `-v` are never used). A failure to stop is non-fatal with a clear warning. Hermetic tests live in `.scripts/test-vm-stop-backend.sh`.
- **Why:** Teammates share `kwanz-ws`. Exiting `start.sh` previously left VM containers and native processes running indefinitely, consuming GPU and memory. Stopping unconditionally on Ctrl+C would disrupt teammates running concurrent sessions. Tracking active runs with a kernel-managed shared flock through a long-lived SSH session ensures that locks disappear automatically if a laptop crashes or disconnects without leaving stale state, and exclusive locking cleanly coordinates last-user shutdown.
- **Rejected:**
  - Unconditional shutdown on exit: takes the backend away from concurrent teammates.
  - Disk PID or registry files on the VM: leave stale entries after laptop crashes, killing future auto-stops.
  - `docker compose down` or `dev-profile.sh down`: removes containers and wipes model caches.
  - Server-side cron or idle timeouts: complex and disconnected from active client sessions.
- **Links:** [`../start.sh`](../start.sh); [`../.scripts/vm-stop-backend.sh`](../.scripts/vm-stop-backend.sh); [`../.scripts/test-vm-stop-backend.sh`](../.scripts/test-vm-stop-backend.sh); [`incident-profile-operations.md`](incident-profile-operations.md); [`../skills/incident-start/SKILL.md`](../skills/incident-start/SKILL.md).

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

### 2026-10-21: Health-check tunnelled HAProxy proxy on port 7777 during start.sh vm mode
- **Decision:** `start.sh --mode vm` adds a bounded health check for `http://localhost:7777/storage` (HEAD, matching `accept-ranges: bytes`) after opening the SSH tunnel, parallel to the existing `localhost:8000/health` check. When the check fails, `start.sh` diagnoses whether `vss-haproxy-ingress` is healthy on the VM (tunnel forward or VM IP issue) or dead on the VM (`docker logs --tail 40 vss-haproxy-ingress`), then cleans up and exits 1. `.scripts/tunnel-check.sh` also verifies port 7777 alongside the agent and search route.
- **Why:** In VM mode, video uploads go through the SSH tunnel to HAProxy on port 7777 (`vss-haproxy-ingress`), which routes `/vst/api/v1/storage/file` to VIOS ingress. Previously, `start.sh` verified only port 8000, allowing `start.sh` to report ready even when port 7777 was not listening or forwarded, which caused video uploads to fail later during user actions. HAProxy has no `/health` endpoint and returns 503 on `/` because `vss-ui` is not deployed on the VM, but its configuration responds directly with 200 OK and `Accept-Ranges: bytes` to `HEAD /storage` and `HEAD /vst/storage`.
- **Rejected:** Checking `GET http://localhost:7777/` (returns 503 because `vss-ui` is absent); checking `http://localhost:7777/health` (unmapped in HAProxy, falls through to absent UI); only checking port 7777 in `tunnel-check.sh` without startup gating in `start.sh`.
- **Links:** [`start.sh`](../start.sh); [`../.scripts/tunnel-check.sh`](../.scripts/tunnel-check.sh); [`architecture.md`](architecture.md#ssh-tunnel-port-forwards); [`vm-api-contracts.md`](vm-api-contracts.md#tunnel).

### 2026-10-21: Drop unused legacy NIM ports (30081, 30082) from SSH tunnel
- **Decision:** Remove ports 30081 (LLM NIM) and 30082 (VLM NIM) from the laptop-to-VM SSH port tunnel in `start.sh` and `.scripts/tunnel.sh`, from the preflight port check in `start.sh`, and from the probe loop in `.scripts/tunnel-check.sh`, leaving only ports 8000 (`vss-agent`) and 7777 (`vss-haproxy-ingress`).
- **Why:** Since switching to remote Brev Switchyard for LLM and VLM inference, no NIM containers run or listen on `kwanz-ws` on 30081/30082. Forwarding these ports was dead configuration that caused false startup failures when developer laptop ports collided and misleading connection errors in diagnostic scripts.
- **Rejected:** Keeping 30081/30082 forwarded for backwards compatibility (no consumers remain on laptop or VM; console v2 and eval scripts do not use them).
- **Links:** [`start.sh`](../start.sh); [`../.scripts/tunnel.sh`](../.scripts/tunnel.sh); [`../.scripts/tunnel-check.sh`](../.scripts/tunnel-check.sh); [`architecture.md`](architecture.md#ssh-tunnel-port-forwards); [`vm-api-contracts.md`](vm-api-contracts.md#tunnel).

### 2026-10-20: One Supabase project per phase; finals built from one baseline; midterm frozen
- **Decision:**
  - The midterm project (`rfevukimyftzbxlehwel`) becomes a frozen, read-only record, and a new finals project is built from scratch with `supabase/migrations/20261020000000_finals_baseline.sql`, then filled once by `supabase/copy/copy_midterm_to_finals.py`.
  - The 14 midterm migrations move unchanged to `supabase/midterm/migrations/` (an archive, not a CLI workdir); `supabase/migrations/` holds only finals files, so the CLI workdir and commands stay the same.
  - Security is on from the first statement: default privileges are revoked before any object exists, RLS is on for every table, nothing is granted to `PUBLIC`/`anon`/`authenticated`, every function pins `search_path`, pgvector lives in `extensions`, and a self-check block fails the migration if anything is exposed. No `FORCE ROW LEVEL SECURITY` (no effect with a `BYPASSRLS` owner).
  - The copy brings over every real row plus the ground truth, evaluation data and seed/fake test reports, and leaves behind 20 orphan runs, 15 unlinked test runs, 8 broken uploads and the 4 pre-v1 tables (guards fail on anything else, and on any edit the copy cannot turn into a reviewer version). A stamp is cleared only when provably a status change (a contract run whose rows equal its notes record); a contract run whose items changed is copied as it stands only when a person passes `--accept-item-edits` (items linked to their AI origin only by unique identical content); a stamped legacy run stops the copy until a person passes `--not-edited` or `--edited`, because the midterm console rewrote the stamp with the verifier on every status change, so a stamp equal to the verification proves nothing. It relabels `fighting`/`animal`/`person` once; query-time folding stays as a guard, and the one `other` value stays in an immutable run's notes.
  - At the cutover `supabase/midterm/freeze_midterm.sql` locks midterm (anon out, `service_role` read-only, direct-DSN sessions read-only); `unfreeze_midterm.sql` is the rollback. R2 is shared, so no object moves.
  - A SQL harness (`supabase/tests/`, `pgserver`) tests the schema hermetically; every later finals migration extends it.
  - Finals uses the new `sb_secret_` / `sb_publishable_` keys (no legacy JWT keys). They are sent in `apikey` only; the VM's unpinned `supabase-py` is proven with a one-row connection test before the switch ([`incident-manage-database`](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_)).
- **Why:** The supervisor asked for one database per project phase. Midterm's migration history does not match what is applied (three applied migrations unrecorded, one recorded under another version, two never applied), its base tables came from no repo file, and the public key could read and change everything (RLS on 2 of 22 tables, default grants to `anon`). Starting clean removes the junk and the open access in one step, and the frozen midterm stays readable as the phase record. Freezing rather than leaving it writable makes a forgotten env file fail loudly instead of writing to the wrong database (the agent only warns when it cannot record a search).
- **Rejected:** more migrations on the shared database (the history is inconsistent and the lockdown and clean-up were never applied); a separate `supabase/finals/` workdir (changes every doc path, and the old folder stays pushable at midterm); pausing midterm at once (no longer a readable record); a bucket per phase (doubles 59.5 GB for no gain); copying the orphan and test runs or the pre-v1 tables (no reader can reach them).
- **Links:** [`../supabase/README.md`](../supabase/README.md); [`../supabase/midterm/README.md`](../supabase/midterm/README.md); [`data.md`](data.md); [`architecture.md`](architecture.md#two-supabase-projects-one-per-phase).

### 2026-10-19: Pin all VSS Docker appliances and native services to GPU 0 only
- **Decision:** Restrict the entire VSS system on `kwanz-ws` to GPU 0. Set `RT_EMBED_DEVICE_ID='0'`, `RTVI_EMBED_NVIDIA_VISIBLE_DEVICES='0'`, `FIXED_SHARED_DEVICE_IDS='0'`, `CUDA_VISIBLE_DEVICES='0'`, and `NVIDIA_VISIBLE_DEVICES='0'` in `dev-profile-incident/.env`. Override `streamprocessing-ms`, `sensor-ms`, and `rtvi-embed` in `compose.override.yml` with explicit GPU 0 device reservations (`device_ids: ["0"]`) and `NVIDIA_VISIBLE_DEVICES=0` / `CUDA_VISIBLE_DEVICES=0` environment variables (alongside `nvstreamer-2d-fusion` and `perception-2d-fusion`). Export `CUDA_VISIBLE_DEVICES=0` and `NVIDIA_VISIBLE_DEVICES=0` in `native-services.sh`, `vm-ensure-docker.sh`, and `start.sh`. Pin `vss-rtvi-embed` to GPU 0 even though it is unused by MVP2 (MVP2 uses remote `nvidia/llama-nemotron-embed-vl-1b-v2` text embeddings and remote Brev VLM).
- **Why:** `kwanz-ws` is shared with another user whose training job occupies GPU 1 (46.9 / 49 GB at 87°C). VSS must leave GPU 1 completely untouched. Previously `RT_EMBED_DEVICE_ID` and `FIXED_SHARED_DEVICE_IDS` defaulted to `1`, while `streamprocessing-ms` and `sensor-ms` ran with `runtime: nvidia` without a device reservation or visible device pin, exposing all GPUs.
- **Rejected:** Removing `vss-rtvi-embed` completely (pinning to GPU 0 preserves compatibility if stock VSS embedding flows are ever re-evaluated); dynamically sharing GPU 1 (the co-tenant workload leaves negligible memory and runs at high thermal load).
- **Links:** [`compose.override.yml`](../compose.override.yml); [`.env`](../.env); [`architecture.md`](architecture.md); [`status.md`](status.md).

### 2026-10-18: Console and agent bind loopback
- **Decision:** `incident-console-v2` runs with `-H 127.0.0.1` (npm `dev`/`start` scripts and `start.sh`). `VSS_AGENT_HOST` defaults to `127.0.0.1`; haproxy's agent backend uses `VSS_AGENT_BACKEND_HOST=127.0.0.1` (profile override of a new shared-template variable defaulting to `HOST_IP`) and the tunnel forwards to the VM loopback.
- **Why:** Next defaults to all interfaces and the console holds database and storage admin keys with no authentication. haproxy is host-network, so it can reach a loopback agent once its backend host is configurable; the console reaches the agent through the tunnel, not haproxy, and no `vss-ui` runs on the VM.
- **Rejected:** leaving the agent on 0.0.0.0 or HOST_IP (exposes unauthenticated search and DB key to the network); hardcoding 127.0.0.1 in the shared haproxy template (breaks other profiles).
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-10-18: No search similarity cutoff; hide critic-rejected hits; loader keeps unboxed items
> Rejection hiding only applies while the critic is on; it is off by default since 2026-10-28.
- **Decision:** `POST /api/v1/incidents/search` defaults `min_similarity` to 0.0 and takes top_k; hits the critic marks `rejected` are dropped unless `hide_rejected` is false. The loader stores the whole frame (box `[0,0,1000,1000]`, confidence 0.0) when the detector finds no box, raises grounding `max_tokens` to 2048 and recovers `timestamp_seconds` and `label` from a truncated reply.
- **Why:** Scores of all 57 loaded rows sit between 0.14 and 0.35, so the 0.2 cutoff flipped "edged weapon" between 0 and 5 hits on a 0.01 difference (best score 0.192). The critic already judges relevance. Whole-frame crops keep items (including the only weapon) searchable, since scoring uses the description embedding.
- **Rejected:** a relative cutoff (the critic call is paid per hit anyway).
- **Links:** [`vm-api-contracts.md`](vm-api-contracts.md); [`data.md`](data.md).

### 2026-10-18: Remote embeddings and remote-VLM cropping for evidence search
- **Decision:**
  - Evidence descriptions (loader, input type `passage`) and search queries (`DefaultQueryEmbedder`, input type `query`) use one remote model, `nvidia/llama-nemotron-embed-vl-1b-v2` on `https://integrate.api.nvidia.com/v1/embeddings`, requesting `dimensions=1024` to match `evidence_crops.embedding`. Client: `utils/embeddings.py` (`EVIDENCE_EMBEDDING_BASE_URL`, `EVIDENCE_EMBEDDING_MODEL`, `EVIDENCE_EMBEDDING_API_KEY`, falling back to `NVIDIA_API_KEY` then `NGC_CLI_API_KEY`). Without a key, only the in-memory store falls back to a deterministic placeholder vector (zero-VM mocks and unit tests only); with the Supabase store or on an embedder error, the route fails with HTTP 503.
  - `DefaultDetector` in `crop_evidence.py` is backed by the remote VLM (one tight `bbox_2d` per frame, normalised 0-1000), not a local detector. `R2EvidenceStore` replaces the stub.
  - The evidence loader (`scripts/backfill_official_timestamps.py`) was later retired; see the 2026-10-23 revisions entry.
- **Why:** The earlier loader wrote nothing, so search returned 200 with zero hits on `kwanz-ws`. The Brev key cannot call `/v1/embeddings` (403), and `nv-embedqa-e5-v5` and `llama-3.2-nv-embedqa-1b-v2` are end-of-life (410). `llama-nemotron-embed-vl-1b-v2` is live and accepts `dimensions=1024` (`nemotron-3-embed-1b` only 2048). The remote VLM already serves grounding, and no local GPU model may be started.
- **Rejected:** a local MiniLM server (384 dimensions, not on the VM); padding or truncating 2048-d vectors (breaks cosine geometry); a local Grounding DINO / OWLv2 detector (needs a GPU model on the VM; detector comparison stays in the retrieval eval).
- **Links:** [`services/agent/src/vss_agents/utils/embeddings.py`](../../../../../services/agent/src/vss_agents/utils/embeddings.py); [`services/agent/src/vss_agents/utils/crop_evidence.py`](../../../../../services/agent/src/vss_agents/utils/crop_evidence.py); [`status.md`](status.md).

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
  - Migration `supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql` adds pgvector, one unified `evidence_crops` table keyed `(incident_id, model_run_id, item_type, item_id)` (HNSW cosine index, `vector(1024)`), `query_results` (rank, similarity, critic verdict and rationale) and the `search_evidence_items` RPC. RLS on, `service_role` only. The RPC joins `videos.selected_model_run_id`, so only official reports are searchable.
  - `vss-agent` uses `SupabaseSearchStore` when `INCIDENT_SEARCH_STORE=supabase` or Supabase credentials are configured, otherwise `InMemorySearchStore`. Crop keys resolve to public URLs (`INCIDENT_VIDEO_BASE_URL`) or boto3 presigned R2 URLs (`utils/r2.py`). Queries and results are persisted.
  - Query embedding is covered by the remote-embeddings decision above.
- **Why:** The sample-data store pointed at a non-existent host, so the critic failed to fetch images and every hit was `unverified`. One table avoids three vector columns and three UNIONs. Official scoping stops re-analysis runs producing duplicate hits.
- **Rejected:** altering the legacy `entities` / `instruments` / `assets` tables; unscoped search; public-only URLs (private buckets need presigning); an external embedding service for now.
- **Links:** [`../supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`](../supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql); [`data.md`](data.md); [`mvp2/README.md`](mvp2/README.md).

### 2026-10-16: MVP2 search route, chat route, crop service, backfill and launcher
- **Decision:**
  - `POST /api/v1/incidents/search` (`search-contract-v1`) and `POST /api/v1/incidents/chat` (`chat-contract-v1`) in `vss-agent`, mounted unconditionally, behind hexagonal ports (`SearchStore`, `QueryEmbedder`, `SearchClient`) with in-memory adapters; mock routes on :7777 and :7778 serve the frontend without a GPU.
  - The VLM critic was always on (superseded 2026-10-28: it is off by default, see the first entry above). A failed or timed-out critic call degrades to `verdict="unverified"` with `confidence=None`; hits are never dropped. Critic calls start `INCIDENT_SEARCH_CRITIC_DELAY_SECONDS` apart (default 1.0, 0 disables) to avoid upstream 429/500 bursts.
  - `CropEvidenceService` crops keyframes at `timestamp_seconds` using a detector port (remote VLM boxes, see above) (5% margin, JPEG quality 85) and stores them via an `EvidenceStore` port under `evidence/<videoId>/<uuid>/<itemId>.jpg`.
  - `start.sh` always brings up and checks search (no `--search` flag); local readiness polls `/health`; `.scripts/tunnel-check.sh` probes search through the tunnel.
- **Why:** A pilot showed VLM bounding boxes were 0% well-framed but timestamps over 95% accurate, so the VLM supplies timestamps and labels and a detector supplies boxes. Ports let the workstreams proceed in parallel. Spacing call starts smooths bursts without retries or sequential latency.
- **Rejected:** VLM bounding boxes; dropping hits on critic failure; a feature flag for search; retries or thread pools for the critic; full re-analysis for backfill (destroys reviewer edits).
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
- **Links:** [`../supabase/midterm/migrations/20260928000000_local_time_heatmap_and_time_filters.sql`](../supabase/midterm/migrations/20260928000000_local_time_heatmap_and_time_filters.sql); [`../incident-console-v2/src/lib/time.ts`](../incident-console-v2/src/lib/time.ts).

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
- **Links:** [`../supabase/midterm/migrations/20260926120000_list_incident_report_summaries.sql`](../supabase/midterm/migrations/20260926120000_list_incident_report_summaries.sql); [`../incident-console-v2/src/app/api/reports/route.ts`](../incident-console-v2/src/app/api/reports/route.ts).

### 2026-09-26: Durability checks and upload key layout
- **Decision:** `incident-console-v2` verifies direct uploads with R2 `HeadObject`, verifies again before inference, then reads back `videos`, `model_runs` and the AI revision and confirms `videos.filepath` is the submitted R2 key before `POST /api/analysis` returns 200. All new uploads go under `uploads/<sensorId>/<uuid>.<ext>`; `anomaly/<category>/` is reserved for classified seed and eval media.
- **Why:** A valid-looking key does not prove the object exists, independent PostgREST writes can partly succeed, and an upload path cannot encode a classification that happens after storage.
- **Rejected:** trusting individual write responses; moving objects after analysis.
- **Links:** [`../incident-console-v2/src/lib/r2/config.ts`](../incident-console-v2/src/lib/r2/config.ts); [`data.md`](data.md).

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

### 2026-09-24: Separate eval pipeline; R2 upload fallback
- **Decision:** Evaluation is a standalone P1/RP1 pipeline in `eval/`, not `nat eval`, because it scores per-field extraction against tabular ground truth rather than chat trajectories. When a real VST chunk upload returns no durable R2 key, the console uploads directly to R2 via `/api/uploads/r2`.
- **Why:** Real VST never returns an R2 key; only the mock faked it.
- **Links:** [`../eval/`](../eval/); [`../incident-console-v2/src/app/api/uploads/r2/route.ts`](../incident-console-v2/src/app/api/uploads/r2/route.ts).

### 2026-09-21: Native services on kwanz-ws
- **Decision:** Run `vss-agent`, `video-analytics-api` and `behavior-analytics` as native host processes via `.scripts/native-services.sh`; VIOS/VST media and infrastructure stay in Docker.
- **Why:** A code change is a ~2 s restart instead of a container rebuild. Media, DeepStream, Triton and JVM appliances depend on container toolchains and gain nothing natively. All services use host networking, so native processes reach Docker ones on localhost.
- **Links:** [`incident-profile-operations.md`](incident-profile-operations.md).

### 2026-09-17: Agent database access through PostgREST
- **Decision:** The agent uses Supabase PostgREST over HTTPS (`utils/incident_db.py`, `supabase-py`). Report writes are single-row `report_revisions` inserts (see the 2026-10-23 revisions entry).
- **Why:** The campus firewall on `kwanz-ws` drops outbound port 5432, so raw Postgres drivers fail; PostgREST lacks client-held transactions, so each write is one row.
- **Rejected:** direct Postgres / `asyncpg` on the VM.
- **Links:** [`data.md`](data.md); `services/agent/src/vss_agents/utils/incident_db.py`.

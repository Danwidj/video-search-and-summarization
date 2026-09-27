---
name: incident-analyze-video
description: Use to upload a video clip and generate, re-run, inspect, review or verify a structured incident report (type, severity, confidence, entities, instruments, assets, timeline) through incident-console-v2, in gateway (local) or agent (VM) mode. Not for batch scoring against ground truth - use incident-run-eval.
license: Apache-2.0
metadata:
  version: "0.1.0"
  profile: "dev-profile-incident"
  tags: "incident analysis vlm report review"
---
# Incident Analyze Video

**Identity rule: 1 video = 1 incident.** `videos.id` == `incidents.incident_id`. Every analysis creates a new `model_run_id`, and earlier runs are kept.

Canonical facts:
- Flows: [`.docs/architecture.md` §4](../../.docs/architecture.md#4-runtime-interaction-sequences), sequences A (gateway) and B (agent)
- Report contract, parsing and persistence: [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md); source files in [`contracts/`](../../contracts/README.md)
- Tables: [`.docs/data.md`](../../.docs/data.md)

## Prerequisites

The stack is running via [`incident-start`](../incident-start/SKILL.md), and `curl -s localhost:3200/api/health` is ready. Prefer short clips, because inference is synchronous.

## Mode routing

| `ANALYSIS_MODE` | Set by | Inference | Who writes Supabase |
|---|---|---|---|
| `gateway` | `start.sh --mode local` | console → `vlm-gateway` :8600 → Brev. P1 on `VLM_MODEL` (default `nvidia/cosmos-3-nano-reasoner`), RP1 on the model in `contracts/rp1_request.json` | Console writes everything: `videos`, `model_runs`, `insert_incident` RPC, evidence, `reports` |
| `agent` | `start.sh --mode vm` | console → `vss-agent` `POST /api/v1/incidents/{id}/analyze` → Brev. P1 on the agent's `VLM_NAME`, same RP1 | Agent writes `model_runs`, `incidents` and evidence. Console writes `videos` (before the call), `model_runs.notes` and `reports`. |

Both modes run the same contract: P1 (signed R2 URL + prompt, JSON Schema `response_format`) then RP1 (prose). Output that breaks the contract is **422** and nothing is persisted.

## Instructions

### Preferred: through the UI

Open `http://localhost:3200`, choose Analyze, and select the clip. Upload, analysis and persistence run in one go. The UI then redirects to `/reports/<video-id>?run=<model-run-id>`.

### Scripted: console API (same path the UI uses)

1. `POST /api/uploads` with `{"filename": "<name>.mp4"}` returns the VST upload URL.
2. Chunked upload to that URL. The browser does this in `lib/upload/chunked-upload.ts` using `nvstreamer-*` headers. **Real VST returns no R2 key**, so the console `PUT`s the file to R2 via `POST /api/uploads/r2`. Direct upload success includes an R2 `HeadObject` check against the original byte length.
3. `POST /api/uploads/complete` with `{"sensorId", "filename"}`.
4. `POST /api/analysis` with `{"sensorId", "filepath": "<R2 key>", "filename"}` (`reasoning` and `promptOverride` are no longer accepted: one prompt everywhere). Before inference the route verifies that the R2 object exists and is nonempty. A 200 response means it also read back `videos`, `model_runs`, `incidents`, and `reports` and confirmed that `videos.filepath` equals the submitted R2 key. A missing object, row, or mismatched key returns an operation-specific 500 instead of a false success. A contract violation returns 422 with the violations listed. The route allows up to 300 s.

Steps 1-2 are awkward from a shell. For scripted re-analysis of an already-uploaded video, go straight to step 4 with the existing R2 key.

### Direct agent call (vm mode, for debugging the agent)

```bash
curl -s -X POST localhost:8000/api/v1/incidents/<incident_id>/analyze \
  -H 'Content-Type: application/json' \
  -d '{"video_url": "<signed R2 URL>", "model_run_id": "<=20 chars, optional>"}'
```

The `videos` row must already exist (`incidents` references it); the agent does not write `videos`. It returns `{report, report_text, report_text_error, model, contract_version, raw_output}`, where `report` is the contract shape with the derived `incident.duration`.

| Status | Meaning |
|---|---|
| 422 | P1 output broke the contract (schema or cross-field rule), or P1 hit `max_tokens` with no content. Nothing is persisted. |
| 504 | Analysis timed out |
| 501 | `incident_report_gen` is not configured. The agent is on the wrong config: it must be the dev-profile-base config. |
| 500 | Any other failure. Check `./.scripts/logs.sh vss-agent` on the VM. |

## Review lifecycle

`PATCH /api/reports/<videoId>/review` with `{"modelRunId", "status", "reviewedBy"}`. Status moves `unreviewed` → `under review` → `verified`. Verifying a report with severity ≥ 4 creates a `notifications` row. Re-analysing resets `review_status` to `unreviewed` for that run (via the `insert_incident` RPC).

## Verify

Run the [end-to-end checklist](../../.docs/incident-profile-operations.md#6-end-to-end-verification-checklist). Minimum checks after one analysis:

- The report page shows type, severity, confidence ("—" when null), summary, timeline, evidence and the written (RP1) report, and the video plays from a fresh 1-hour signed R2 URL.
- `videos.filepath` is a classification-neutral **R2 key** (`uploads/<sensorId>/<uuid><ext>` in both modes), **not** a `http://10.131.1.5:...` VST URL. The agent no longer writes `videos` (known issue 3, fixed on the contract branch; see [`.docs/status.md`](../../.docs/status.md#2-known-issues--technical-debt)).
- There is a new `model_runs` row, and the previous runs still appear in the run picker.
- The analysis response was 200; `verifying the persisted report in PostgREST failed` means inference completed but the durable row graph is incomplete and must not be treated as a finished report.

## Known quirks

- The full report lives in `model_runs.notes` as `incidentConsoleV2.report` (plus `editedReport` after a reviewer edit). Notes written before `incident-contract-v2` are converted read-only and marked legacy in the UI. `title`, `severity_reason`, `timeline`, `uncertainties` and `location` are not relational columns yet (Option B: [`.docs/restructure-plan.md`](../../.docs/restructure-plan.md)).
- `confidence_score` is null unless the model API gives a native score; the model is never asked to self-report it.
- Cosmos Super (the VM default) ignores `num_frames` and may put lead-up events outside the incident window, which is a 422 under the strict timeline rule.
- `anomaly/<category>` is reserved for classified seed/evaluation media. VLM output such as `incident_type: none` does not determine or change the uploaded object's key.

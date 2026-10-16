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
- Report fields and translation: [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md)
- Tables: [`.docs/data.md`](../../.docs/data.md)

## Prerequisites

The stack is running via [`incident-start`](../incident-start/SKILL.md), and `curl -s localhost:3200/api/health` is ready. Prefer short clips, because inference is synchronous.

## Mode routing

| `ANALYSIS_MODE` | Set by | Inference | Who writes Supabase |
|---|---|---|---|
| `gateway` | `start.sh --mode local` | console -> `vlm-gateway` :8600 -> Brev, with the model chosen in the UI from `contracts/inference.json` (default `VLM_MODEL`), on `incident-contract-v3` | Console writes everything: `videos`, `model_runs`, `insert_incident` RPC, evidence, `reports` |
| `agent` | `start.sh --mode vm` | console -> `vss-agent` `POST /api/v1/incidents/{id}/analyze` -> Brev. P1 only, on the agent's `VLM_NAME` (the console sends `skip_rp1: true`, matching gateway mode). The console validates the agent's raw P1 output under `core-scored-v1` exactly as in gateway mode. | Console writes everything, as in gateway mode: `videos`, `model_runs`, `insert_incident` RPC, evidence, `reports`. The agent persists nothing when the console passes `model_run_id`. Additional instructions are gateway-only (400 in agent mode). |

## Instructions

### Preferred: through the UI

Open `http://localhost:3200`, choose the model, then select the clip. Upload, analysis and persistence run in one go. The UI then redirects to `/reports/<video-id>?run=<model-run-id>`. To analyse an already-uploaded video again (any model, optional additional instruction), open `/videos/<video-id>` or the report page's analysis card. Every attempt is a new run, failed attempts appear in the history only, and choosing the official report is a separate explicit action.

### Scripted: console API (same path the UI uses)

1. `POST /api/uploads` with `{"filename": "<name>.mp4"}` returns the VST upload URL.
2. Chunked upload to that URL. The browser does this in `lib/upload/chunked-upload.ts` using `nvstreamer-*` headers. **Real VST returns no R2 key**, so the console `PUT`s the file to R2 via `POST /api/uploads/r2`. Direct upload success includes an R2 `HeadObject` check against the original byte length.
3. `POST /api/uploads/complete` with `{"sensorId", "filename"}`.
4. `POST /api/analysis` with `{"sensorId", "filepath": "<R2 key>", "filename", "model"?}` (gateway; `reasoning`/`promptOverride` apply to agent mode only). Before inference the route verifies that the R2 object exists and is nonempty. A 200 response means it also read back `videos`, `model_runs`, `incidents`, and `reports` and confirmed that `videos.filepath` equals the submitted R2 key. A missing object, row, or mismatched key returns an operation-specific 500 instead of a false success.

Steps 1-2 are awkward from a shell. For scripted re-analysis of an already-uploaded video use `POST /api/videos/<video-id>/runs` with `{"model", "additionalInstruction"?}`: it never touches the video row. Responses: 200 `{run: {..., outcome}}` (`valid_first_pass` or `valid_after_structural_repair`), 422 `contract_failed` with `codes`, 502/504 `request_failed` with `code`; failures are recorded in `GET /api/videos/<video-id>/runs`.

### Direct agent call (vm mode, for debugging the agent)

```bash
curl -s -X POST localhost:8000/api/v1/incidents/<incident_id>/analyze \
  -H 'Content-Type: application/json' \
  -d '{"video_url": "<signed R2 URL>", "model_run_id": "<=20 chars, optional>", "skip_rp1": false}'
```

The `videos` row must already exist (`incidents` references it); the agent does not write `videos`. Without `model_run_id` the agent persists the run itself (under its configured `model_run_id`); with one, it persists nothing and the caller records the run. `skip_rp1` (default `false`) runs P1 only, leaving `report_text` null; otherwise RP1 runs on the model hardcoded in `incident_contract.rp1_request()`. It returns `{report, report_text, report_text_error, model, contract_version, raw_output, finish_reason}`, where `report` is the contract shape with the derived `incident.duration`, after `core-scored-v1` validation and any `id-normalization-v1` repair.

| Status | Meaning |
|---|---|
| 422 | P1 output failed `core-scored-v1` (a schema or core cross-field violation that `id-normalization-v1` cannot repair), or P1 hit `max_tokens` with no content. The agent persists nothing; `detail` carries `message`, `raw_output`, `finish_reason`, `model` and `contract_version`, and the console records a `contract_failed` (or `request_failed`) attempt in `model_runs.notes`. Timeline-only violations are not a 422. |
| 504 | Analysis timed out |
| 501 | `incident_report_gen` is not configured. The agent is on the wrong config: it must be the dev-profile-base config. |
| 500 | Any other failure. Check `./.scripts/logs.sh vss-agent` on the VM. |

## Review lifecycle

`PATCH /api/reports/<videoId>/review` with `{"modelRunId", "status", "reviewedBy"}`. Status moves `unreviewed` → `under review` → `verified`. Re-analysing resets `review_status` to `unreviewed` for that run (via the `insert_incident` RPC).

## Verify

Run the [end-to-end checklist](../../.docs/incident-profile-operations.md#6-end-to-end-verification-checklist). Minimum checks after one analysis:

- The report page shows type, severity, confidence, summary, timeline and evidence, and the video plays from a fresh 1-hour signed R2 URL.
- `videos.filepath` is a classification-neutral **R2 key** (`uploads/<sensorId>/<uuid><ext>` in both modes), **not** a `http://10.131.1.5:...` VST URL. The agent no longer writes `videos` (see [`.docs/decisions.md`](../../.docs/decisions.md) 2026-10-16).
- There is a new `model_runs` row, and the previous runs still appear in the run picker.
- The analysis response was 200; `verifying the persisted report in PostgREST failed` means inference completed but the durable row graph is incomplete and must not be treated as a finished report.

## Known quirks

- Both gateway and agent modes use `incident-contract-v3` and record every attempt immutably in `model_runs.notes` with its outcome under validation policy `core-scored-v1`. See [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md).
- `anomaly/<category>` is reserved for classified seed/evaluation media. VLM output such as `incident_type: none` does not determine or change the uploaded object's key.

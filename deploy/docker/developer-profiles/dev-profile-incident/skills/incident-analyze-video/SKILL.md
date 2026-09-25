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
| `gateway` | `start.sh --mode local` | console → `vlm-gateway` :8600 → Brev (VLM `VLM_MODEL`, default `nvidia/cosmos-3-nano-reasoner`) | Console writes everything: `videos`, `model_runs`, `insert_incident` RPC, evidence, `reports` |
| `agent` | `start.sh --mode vm` | console → `vss-agent` `POST /api/v1/incidents/{id}/analyze` → Brev | Agent writes `incidents` and evidence. Console writes `videos` before and after, `model_runs.notes` and `reports`. |

## Instructions

### Preferred: through the UI

Open `http://localhost:3200`, choose Analyze, and select the clip. Upload, analysis and persistence run in one go. The UI then redirects to `/reports/<video-id>?run=<model-run-id>`.

### Scripted: console API (same path the UI uses)

1. `POST /api/uploads` with `{"filename": "<name>.mp4"}` returns the VST upload URL.
2. Chunked upload to that URL. The browser does this in `lib/upload/chunked-upload.ts` using `nvstreamer-*` headers. **Real VST returns no R2 key**, so the console `PUT`s the file to R2 via `POST /api/uploads/r2`.
3. `POST /api/uploads/complete` with `{"sensorId", "filename"}`.
4. `POST /api/analysis` with `{"sensorId", "filepath": "<R2 key>", "filename", "reasoning"?, "promptOverride"?}`.

Steps 1-2 are awkward from a shell. For scripted re-analysis of an already-uploaded video, go straight to step 4 with the existing R2 key.

### Direct agent call (vm mode, for debugging the agent)

```bash
curl -s -X POST localhost:8000/api/v1/incidents/<incident_id>/analyze \
  -H 'Content-Type: application/json' \
  -d '{"model_run_id": "<=20 chars, optional>", "reasoning": false}'
```

The agent looks up the sensor id from `videos.source`, so the `videos` row must already exist. It returns an `IncidentReport` in snake_case.

| Status | Meaning |
|---|---|
| 422 | The VLM/LLM output failed `IncidentReport` validation. Nothing default is persisted. |
| 504 | Analysis timed out |
| 501 | `incident_report_gen` is not configured. The agent is on the wrong config: it must be the dev-profile-base config. |
| 500 | Any other failure. Check `./.scripts/logs.sh vss-agent` on the VM. |

## Review lifecycle

`PATCH /api/reports/<videoId>/review` with `{"modelRunId", "status", "reviewedBy"}`. Status moves `unreviewed` → `under review` → `verified`. Verifying a report with severity ≥ 4 creates a `notifications` row. Re-analysing resets `review_status` to `unreviewed` for that run (via the `insert_incident` RPC).

## Verify

Run the [end-to-end checklist](../../.docs/incident-profile-operations.md#6-end-to-end-verification-checklist). Minimum checks after one analysis:

- The report page shows type, severity, confidence, summary, timeline and evidence, and the video plays from a fresh 1-hour signed R2 URL.
- `videos.filepath` is an **R2 key** (`uploads/<sensorId>/<uuid><ext>` in vm mode, `anomaly/<category>/<file>` with the mock), **not** a `http://10.131.1.5:...` VST URL. In agent mode, the agent overwrites it and the console restores it. See known issue 3 in [`.docs/status.md`](../../.docs/status.md#2-known-issues--technical-debt).
- There is a new `model_runs` row, and the previous runs still appear in the run picker.

## Known quirks

- In agent mode the relational rows hold native agent values. The translated camelCase report exists only in `model_runs.notes`. Fields like `title`, `timeline` and `uncertainties` are not relational columns yet (Option B: [`.docs/restructure-plan.md`](../../.docs/restructure-plan.md)).
- The mock backend picks the `anomaly/<category>` folder by hashing the incident id, not from the content.

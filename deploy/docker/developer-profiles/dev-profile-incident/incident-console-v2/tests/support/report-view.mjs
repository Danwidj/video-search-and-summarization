// SPDX-License-Identifier: Apache-2.0

// Row fixtures of a run (the smoke-run fixture shape: video, modelRun,
// incident, entities, instruments, assets) -> the AI revision a run saves ->
// RevisionRecord or ReportView in one step: the Supabase report mapper, then
// the view builder. Import after registering ./alias-loader.mjs.

import { revisionRecordFromRows } from '../../src/modules/reports/infrastructure/supabase/mappers/report.ts';
import { toReportView } from '../../src/modules/reports/application/report-view.ts';
import '../../src/modules/contract/infrastructure/loader.ts';

const withoutKeys = (row, ...keys) => Object.fromEntries(Object.entries(row).filter(([key]) => !keys.includes(key)));
const dropIdentity = (row) => withoutKeys(row, 'incident_id', 'model_run_id', 'image');
// The contract gives every item the second it is most clearly visible; the row fixtures predate that field.
const withTimestamp = (row) => ({ timestamp_seconds: 2, ...dropIdentity(row) });

/** The report_revisions row, with its payload, of a fixture's AI revision. */
export function aiRevisionRow(rows, overrides = {}) {
  return {
    id: 1,
    video_id: rows.video.id,
    revision_no: 1,
    kind: 'ai',
    model_run_id: rows.modelRun.id,
    parent_id: null,
    payload: {
      incident: dropIdentity(rows.incident),
      entities: rows.entities.map(withTimestamp),
      instruments: rows.instruments.map(withTimestamp),
      assets: rows.assets.map(withTimestamp),
    },
    evidence: [],
    created_by: null,
    created_at: rows.reportRow?.generated_datetime ?? rows.modelRun.run_datetime,
    note: null,
    ...overrides,
  };
}

export const aiRunReport = (rows, overrides) =>
  revisionRecordFromRows({ video: rows.video, revision: aiRevisionRow(rows, overrides), modelRun: rows.modelRun });
export const buildReportView = (rows, overrides) => toReportView(aiRunReport(rows, overrides), rows.playbackUrl);

/** The edit a reviewer sends for the rows' AI revision without changing anything: every item names its source item. */
export function unchangedEdit(rows) {
  const { structured } = buildReportView(rows);
  const { incident } = structured;
  const details = (sourceId) => ({ source_id: sourceId, timestamp_seconds: incident.startSeconds, label: '', image: null });
  return {
    incident: {
      type: incident.type,
      start_timestamp: incident.startSeconds,
      end_timestamp: incident.endSeconds,
      description: incident.description,
      severity_level: incident.severityLevel,
    },
    entities: structured.entities.map((e) => ({
      entity_id: e.entityId,
      type: e.type,
      description: e.description,
      first_seen_seconds: incident.startSeconds,
      last_seen_seconds: incident.startSeconds,
      ...details(e.entityId),
    })),
    instruments: structured.instruments.map((i) => ({
      instrument_id: i.instrumentId,
      entity_id: i.entityId,
      name: i.name,
      description: i.description,
      threat_level: i.threatLevel,
      ...details(i.instrumentId),
    })),
    assets: structured.assets.map((a) => ({ asset_id: a.assetId, name: a.name, description: a.description, ...details(a.assetId) })),
  };
}

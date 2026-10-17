// SPDX-License-Identifier: Apache-2.0

// Row -> domain translation for one run's report rows (videos, model_runs,
// incidents, entities, instruments, assets, review_status, reports). The only
// place that knows those column names; lifted unchanged from lib/reports/view.ts.

import type { ReviewState, RunKey, RunReportRecord } from '@/lib/ports';
import { canonicalEntityType, canonicalIncidentType, parseTimestamp } from '@/lib/reports/normalize';
import { parseRunNotes } from '@/lib/reports/run-notes';
import type { ReviewStatus } from '@/lib/reports/storage';
import { toReportView, type ReportView } from '@/lib/reports/view';

type Row = Record<string, unknown>;

export interface ReportRows {
  videoId: string;
  modelRunId: string;
  video: Row;
  modelRun: Row;
  incident: Row;
  entities: Row[];
  instruments: Row[];
  assets: Row[];
  review: Row | null;
  reportRow: Row | null;
}

const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null);
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const byId = (key: string) => (a: Row, b: Row) => String(a[key] ?? '').localeCompare(String(b[key] ?? ''), undefined, { numeric: true });
const REVIEW_STATUSES = new Set(['unreviewed', 'under review', 'verified']);

/** review_status row -> ReviewState; an unknown stored status reads as 'unreviewed', as the report view always showed it. */
export function reviewFromRow(row: Row | null): ReviewState | null {
  if (!row) return null;
  const status = text(row.status);
  return {
    status: (status && REVIEW_STATUSES.has(status) ? status : 'unreviewed') as ReviewStatus,
    verifiedBy: text(row.verified_by),
    verifiedAt: text(row.verified_at),
    editedBy: text(row.edited_by),
    editedAt: text(row.edited_at),
  };
}

/** ReviewState -> review_status upsert row. */
export function reviewToRow(key: RunKey, review: ReviewState): Row {
  return {
    incident_id: key.videoId,
    model_run_id: key.modelRunId,
    status: review.status,
    edited_by: review.editedBy,
    edited_at: review.editedAt,
    verified_by: review.verifiedBy,
    verified_at: review.verifiedAt,
  };
}

export function runReportFromRows(rows: ReportRows): RunReportRecord {
  const { incident, video } = rows;
  const officialRunId = text(video.selected_model_run_id);
  return {
    key: { videoId: rows.videoId, modelRunId: rows.modelRunId },
    video: {
      storageKey: typeof video.filepath === 'string' && video.filepath ? video.filepath : null,
      filename: (text(video.filepath) ?? '').split('/').pop() || rows.videoId,
      official: {
        officialRunId,
        selectedBy: officialRunId ? text(video.selected_by) : null,
        selectedAt: officialRunId ? text(video.selected_at) : null,
      },
    },
    modelRun: {
      modelName: text(rows.modelRun.model_name),
      promptVersion: text(rows.modelRun.prompt_version),
      runAt: text(rows.modelRun.run_datetime),
      notes: parseRunNotes(rows.modelRun.notes),
    },
    incident: {
      type: canonicalIncidentType(incident.type),
      startSeconds: parseTimestamp(incident.start_timestamp),
      endSeconds: parseTimestamp(incident.end_timestamp),
      duration: num(incident.duration),
      description: text(incident.description),
      severityLevel: num(incident.severity_level),
      confidenceScore: num(incident.confidence_score),
    },
    entities: [...rows.entities].sort(byId('entity_id')).map((row) => ({ entityId: String(row.entity_id ?? ''), type: canonicalEntityType(row.type), description: String(row.description ?? '') })),
    instruments: [...rows.instruments].sort(byId('instrument_id')).map((row) => ({ instrumentId: String(row.instrument_id ?? ''), entityId: text(row.entity_id), name: String(row.name ?? ''), description: String(row.description ?? ''), threatLevel: num(row.threat_level) })),
    assets: [...rows.assets].sort(byId('asset_id')).map((row) => ({ assetId: String(row.asset_id ?? ''), name: String(row.name ?? ''), description: String(row.description ?? '') })),
    review: reviewFromRow(rows.review),
    report: rows.reportRow ? { reportId: text(rows.reportRow.id), generatedAt: text(rows.reportRow.generated_datetime) } : null,
  };
}

/** Rows -> view in one step: the seam the row-fixture tests use. */
export function buildReportView(rows: ReportRows & { playbackUrl: string }): ReportView {
  return toReportView(runReportFromRows(rows), rows.playbackUrl);
}

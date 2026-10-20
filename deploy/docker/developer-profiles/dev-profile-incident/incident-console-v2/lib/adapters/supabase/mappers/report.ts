// SPDX-License-Identifier: Apache-2.0

// Row -> domain translation for one run's report rows (videos, model_runs,
// the effective_* views, review_status, reports) and the results of the
// reviewer RPCs. The only place that knows those column and result names;
// the row mapping is lifted unchanged from lib/reports/view.ts.

import type { ReviewState, ReviewTransition, RunKey, RunReportRecord, StructuredEditResult } from '@/lib/ports';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import { canonicalEntityType, canonicalIncidentType, parseTimestamp } from '@/lib/reports/normalize';
import { parseRunNotes } from '@/lib/reports/run-notes';
import type { ReviewStatus } from '@/lib/reports/storage';

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
const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const REVIEW_STATUSES = new Set(['unreviewed', 'under review', 'verified']);
const reviewStatus = (value: unknown, fallback: ReviewStatus): ReviewStatus =>
  (typeof value === 'string' && REVIEW_STATUSES.has(value) ? value : fallback) as ReviewStatus;

/** review_status row -> ReviewState; an unknown stored status reads as 'unreviewed', as the report view always showed it. */
export function reviewFromRow(row: Row | null): ReviewState | null {
  if (!row) return null;
  return {
    status: reviewStatus(row.status, 'unreviewed'),
    verifiedBy: text(row.verified_by),
    verifiedAt: text(row.verified_at),
    editedBy: text(row.edited_by),
    editedAt: text(row.edited_at),
  };
}

/** set_review_status's result -> ReviewTransition. */
export function reviewTransitionFromRpc(result: unknown, status: ReviewStatus): ReviewTransition {
  const row = asRow(result);
  return {
    changed: row.changed === true,
    status: reviewStatus(row.status, status),
    verifiedBy: text(row.verifiedBy),
    verifiedAt: text(row.verifiedAt),
    humanVersionCreated: row.humanVersionCreated === true,
  };
}

/** save_human_report_edit's result (duration = end - start) -> StructuredEditResult. */
export function structuredEditResultFromRpc(result: unknown, key: RunKey, edit: StructuredEdit, editedBy: string): StructuredEditResult {
  const row = asRow(result);
  return {
    incidentId: text(row.incidentId) ?? key.videoId,
    modelRunId: text(row.modelRunId) ?? key.modelRunId,
    editedBy: text(row.editedBy) ?? editedBy.trim(),
    editedAt: text(row.editedAt) ?? '',
    duration: num(row.duration) ?? edit.incident.end_timestamp - edit.incident.start_timestamp,
    revision: num(row.revision) ?? 1,
    status: reviewStatus(row.status, 'unreviewed'),
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
    // source_*_id: an AI row's own ID, a reviewer row's AI origin (NULL when the reviewer added it).
    entities: [...rows.entities].sort(byId('entity_id')).map((row) => ({ entityId: String(row.entity_id ?? ''), sourceId: text(row.source_entity_id), type: canonicalEntityType(row.type), description: String(row.description ?? '') })),
    instruments: [...rows.instruments].sort(byId('instrument_id')).map((row) => ({ instrumentId: String(row.instrument_id ?? ''), sourceId: text(row.source_instrument_id), entityId: text(row.entity_id), name: String(row.name ?? ''), description: String(row.description ?? ''), threatLevel: num(row.threat_level) })),
    assets: [...rows.assets].sort(byId('asset_id')).map((row) => ({ assetId: String(row.asset_id ?? ''), sourceId: text(row.source_asset_id), name: String(row.name ?? ''), description: String(row.description ?? '') })),
    review: reviewFromRow(rows.review),
    report: rows.reportRow ? { reportId: text(rows.reportRow.id), generatedAt: text(rows.reportRow.generated_datetime) } : null,
  };
}

// SPDX-License-Identifier: Apache-2.0

// Server-only builder for the report view (types in lib/reports/report-view.ts).

import { canonicalEntityType, canonicalIncidentType, parseTimestamp } from '@/lib/reports/normalize';
import type { ModelOutput, ReportView, RunDetails } from '@/lib/reports/report-view';
import { parseRunNotes } from '@/lib/reports/run-notes';
import type { ReviewStatus } from '@/lib/reports/storage';

export { reportHeading } from '@/lib/reports/report-view';
export type { ReportView } from '@/lib/reports/report-view';

type Row = Record<string, unknown>;

export interface ReportRows {
  videoId: string;
  modelRunId: string;
  playbackUrl: string;
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

export function buildReportView(rows: ReportRows): ReportView {
  const { incident } = rows;
  const structured: ReportView['structured'] = {
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
  };

  const notes = parseRunNotes(rows.modelRun.notes);
  let modelOutput: ModelOutput | null = null;
  if (notes.kind === 'contract') {
    const { report } = notes;
    modelOutput = {
      source: 'contract',
      title: report.incident.title,
      location: report.incident.location,
      severityReason: report.incident.severity_reason,
      timeline: report.timeline.map((event) => ({ startSeconds: event.start_seconds, endSeconds: event.end_seconds, description: event.description })),
      uncertainties: [...report.uncertainties],
      original: {
        type: report.incident.type,
        severityLevel: report.incident.severity_level,
        startSeconds: report.incident.start_timestamp,
        endSeconds: report.incident.end_timestamp,
        description: report.incident.description,
      },
    };
  } else if (notes.kind === 'legacy') {
    const { report } = notes;
    modelOutput = {
      source: 'legacy',
      title: text(report.title),
      location: text(report.location),
      severityReason: text(report.severity_reason),
      timeline: report.timeline.map((event) => ({ startSeconds: Math.floor(event.start_seconds), endSeconds: event.end_seconds === null ? null : Math.floor(event.end_seconds), description: event.description })),
      uncertainties: [...report.uncertainties],
      original: {
        type: canonicalIncidentType(report.incident_type),
        severityLevel: report.severity,
        startSeconds: parseTimestamp(report.incident_start),
        endSeconds: parseTimestamp(report.incident_end),
        description: text(report.description),
      },
    };
  }

  const differences: ReportView['differences'] = { fields: [] };
  if (modelOutput) {
    const { original } = modelOutput;
    const current = structured.incident;
    if (original.type && current.type && original.type !== current.type) {
      differences.type = { model: original.type, current: current.type };
      differences.fields.push('type');
    }
    if (original.severityLevel !== null && current.severityLevel !== null && original.severityLevel !== current.severityLevel) {
      differences.severity = { model: original.severityLevel, current: current.severityLevel };
      differences.fields.push('severity');
    }
    if (original.description !== null && current.description !== null && original.description !== current.description) differences.fields.push('description');
    if (notes.kind === 'contract') {
      // Legacy start/end were strings the old editor rewrote freely, so only
      // contract runs compare timestamps and evidence exactly.
      if (original.startSeconds !== current.startSeconds || original.endSeconds !== current.endSeconds) differences.fields.push('incident window');
      const model = notes.report;
      const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
      if (!same(model.entities.map((e) => [e.entity_id, e.type, e.description]), structured.entities.map((e) => [e.entityId, e.type, e.description]))) differences.fields.push('entities');
      if (!same(model.instruments.map((i) => [i.instrument_id, i.entity_id, i.name, i.description, i.threat_level]), structured.instruments.map((i) => [i.instrumentId, i.entityId, i.name, i.description, i.threatLevel]))) differences.fields.push('instruments');
      if (!same(model.assets.map((a) => [a.asset_id, a.name, a.description]), structured.assets.map((a) => [a.assetId, a.name, a.description]))) differences.fields.push('assets');
    }
  }

  const filepath = text(rows.video.filepath) ?? '';
  const run: RunDetails = {
    videoId: rows.videoId,
    modelRunId: rows.modelRunId,
    reportId: text(rows.reportRow?.id) ?? `${rows.videoId}-${rows.modelRunId}`,
    filename: filepath.split('/').pop() || rows.videoId,
    playbackUrl: rows.playbackUrl,
    model: text(rows.modelRun.model_name) ?? 'Unknown model',
    promptVersion: text(rows.modelRun.prompt_version),
    generatedAt: text(rows.reportRow?.generated_datetime) ?? text(rows.modelRun.run_datetime) ?? '',
    notesKind: notes.kind,
  };
  if (notes.kind === 'contract' || notes.kind === 'invalid-contract') {
    run.request = notes.request;
    run.response = notes.response;
    run.rawModelOutput = notes.response.content ?? undefined;
    if (notes.kind === 'contract') {
      run.originalReport = notes.report;
      run.status = notes.status;
      run.statusInferred = notes.statusInferred;
      run.firstPassViolations = notes.validation.firstPass;
      run.repair = notes.repair;
    } else run.notesError = notes.error;
  } else if (notes.kind === 'failed-attempt') {
    // Unreachable through the report route (a failed attempt has no incident),
    // but never presented as a report either.
    run.request = notes.request;
    run.status = notes.status;
    run.notesError = notes.failure ? `${notes.failure.code}: ${notes.failure.message}` : notes.status;
  } else if (notes.kind === 'legacy') {
    run.rawModelOutput = notes.rawModelOutput;
    run.legacyReviewerEdits = notes.legacyReviewerEdits;
  }

  const status = text(rows.review?.status);
  return {
    videoId: rows.videoId,
    modelRunId: rows.modelRunId,
    structured,
    modelOutput,
    run,
    official: {
      officialRunId: text(rows.video.selected_model_run_id),
      selectedBy: text(rows.video.selected_model_run_id) ? text(rows.video.selected_by) : null,
      selectedAt: text(rows.video.selected_model_run_id) ? text(rows.video.selected_at) : null,
      isOfficial: text(rows.video.selected_model_run_id) === rows.modelRunId,
    },
    review: {
      status: (status && REVIEW_STATUSES.has(status) ? status : 'unreviewed') as ReviewStatus,
      verifiedBy: text(rows.review?.verified_by) ?? undefined,
      verifiedAt: text(rows.review?.verified_at) ?? undefined,
      editedBy: text(rows.review?.edited_by) ?? undefined,
      editedAt: text(rows.review?.edited_at) ?? undefined,
    },
    differences,
  };
}

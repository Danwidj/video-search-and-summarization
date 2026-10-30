// SPDX-License-Identifier: Apache-2.0

// Row and RPC-result translation for the mvp3 incident port: incidents, videos,
// report_revisions (envelope payload, video_names coverage) and the incident
// functions. The only place that knows these column and result names.

import { parseEnvelope } from '@/modules/reports/domain/envelope';
import type {
  CreatedAiRevision,
  IncidentOfficialChange,
  IncidentRecord,
  IncidentRevisionRecord,
  IncidentRevisionSummary,
  IncidentSummary,
  IncidentSummaryList,
  IncidentVideo,
  MergeResult,
} from '@/modules/reports/domain/IncidentReportRepository';
import { evidenceEntries, revisionFacets, type RevisionKind } from '@/modules/reports/domain/revision';
import { parseRunNotes } from '@/modules/reports/domain/run-notes';
import { StoreRejection } from '@/modules/shared/domain/common';

type Row = Record<string, unknown>;

const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null);
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const names = (value: unknown): string[] => (Array.isArray(value) ? value.filter((name): name is string => typeof name === 'string') : []);

/** The columns a version-list row needs: everything but the payload and evidence. */
export const INCIDENT_REVISION_SUMMARY_COLUMNS =
  'id,incident_id,revision_no,kind,model_run_id,parent_id,created_by,created_at,note,video_names';

export function incidentRevisionSummaryFromRow(row: Row, officialRevisionId: number | null, model: string | null): IncidentRevisionSummary {
  const id = Number(row.id);
  return {
    revisionId: id,
    incidentId: Number(row.incident_id),
    revisionNo: Number(row.revision_no),
    kind: (row.kind === 'human' ? 'human' : 'ai') as RevisionKind,
    createdBy: text(row.created_by),
    createdAt: text(row.created_at),
    note: text(row.note),
    parentId: num(row.parent_id),
    modelRunId: text(row.model_run_id),
    model,
    isOfficial: officialRevisionId !== null && officialRevisionId === id,
    videoNames: names(row.video_names),
  };
}

export function incidentVideoFromRow(row: Row): IncidentVideo {
  return {
    videoId: String(row.id),
    storageKey: text(row.filepath),
    uploadedAt: text(row.uploaded_datetime),
    recordedAt: text(row.recorded_at),
    durationSeconds: num(row.duration),
    source: text(row.source),
  };
}

/** Earliest upload first, ties by name (the order the library uses for the first video). */
const byUpload = (a: IncidentVideo, b: IncidentVideo) =>
  (a.uploadedAt ?? '').localeCompare(b.uploadedAt ?? '') || a.videoId.localeCompare(b.videoId);

export function incidentRecordFromRows(incident: Row, videos: Row[], revisions: Row[], models: Map<string, string | null>): IncidentRecord {
  const officialRevisionId = num(incident.official_revision_id);
  return {
    incidentId: Number(incident.id),
    officialRevisionId,
    officialSince: text(incident.official_since),
    createdAt: text(incident.created_at),
    videos: videos.map(incidentVideoFromRow).sort(byUpload),
    revisions: revisions.map((row) =>
      incidentRevisionSummaryFromRow(row, officialRevisionId, models.get(String(row.model_run_id)) ?? null),
    ),
  };
}

export function incidentRevisionRecordFromRows(input: { incident: Row; revision: Row; modelRun: Row | null }): IncidentRevisionRecord {
  const { incident, revision, modelRun } = input;
  const payload = asRow(revision.payload);
  const modelName = modelRun ? text(modelRun.model_name) : null;
  return {
    revision: incidentRevisionSummaryFromRow(revision, num(incident.official_revision_id), modelName),
    payload,
    envelope: parseEnvelope(payload),
    evidence: evidenceEntries(revision.evidence),
    modelRun: modelRun
      ? {
          modelName,
          promptVersion: text(modelRun.prompt_version),
          runAt: text(modelRun.run_datetime),
          notes: parseRunNotes(modelRun.notes),
        }
      : null,
  };
}

/** save_human_revision's result -> a version-list row (the model is not part of it, so it is unknown here). */
export function savedIncidentRevisionFromRpc(result: unknown): IncidentRevisionSummary {
  const row = asRow(result);
  return incidentRevisionSummaryFromRow(
    {
      id: row.revisionId,
      incident_id: row.incidentId,
      revision_no: row.revisionNo,
      kind: row.kind,
      created_by: row.createdBy,
      created_at: row.createdAt,
      note: row.note,
      parent_id: row.parentId,
      model_run_id: row.modelRunId,
      video_names: row.videoNames,
    },
    null,
    null,
  );
}

export function officialChangeFromRpc(result: unknown): IncidentOfficialChange {
  const row = asRow(result);
  return { incidentId: Number(row.incidentId), officialRevisionId: num(row.officialRevisionId), officialSince: text(row.officialSince) };
}

export function createdAiRevisionFromRpc(result: unknown): CreatedAiRevision {
  const row = asRow(result);
  return { revisionId: Number(row.revisionId), revisionNo: Number(row.revisionNo), crops: num(row.crops) ?? 0 };
}

export function mergeResultFromRpc(result: unknown): MergeResult {
  const row = asRow(result);
  return {
    incidentId: Number(row.incident_id),
    sourceIncidentId: Number(row.source_incident_id),
    movedVideoIds: names(row.moved_video_ids),
    orphanedCropImages: names(row.orphaned_crop_images),
  };
}

type Outcome = NonNullable<IncidentSummary['outcome']>;

function incidentSummary(item: Row): IncidentSummary {
  return {
    incidentId: Number(item.incidentId),
    revisionId: num(item.revisionId),
    revisionNo: num(item.revisionNo),
    modelRunId: text(item.modelRunId),
    kind: item.kind === 'human' || item.kind === 'ai' ? item.kind : null,
    createdBy: text(item.createdBy),
    note: text(item.note),
    title: typeof item.title === 'string' ? item.title : '',
    incidentType: typeof item.incident_type === 'string' ? item.incident_type : '',
    description: typeof item.description === 'string' ? item.description : '',
    // COALESCE(severity_level, 1) in the SQL.
    severity: num(item.severity) ?? 1,
    confidence: num(item.confidence),
    generatedAt: text(item.generatedAt),
    uploadedAt: text(item.uploadedAt),
    model: typeof item.model === 'string' ? item.model : '',
    outcome: typeof item.outcome === 'string' ? (item.outcome as Outcome) : null,
    isOfficial: item.isOfficial === true,
    officialSince: text(item.officialSince),
    versionCount: num(item.versionCount) ?? 0,
    videoCount: num(item.videoCount) ?? 0,
    firstVideoName: text(item.firstVideoName),
    firstVideoKey: text(item.firstVideoKey),
    thumbnail: text(item.thumbnail),
    sensorId: text(item.sensorId),
    coverage: names(item.coverage),
    missingVideos: names(item.missingVideos),
    removedVideos: names(item.removedVideos),
  };
}

export function incidentSummaryListFromRpc(value: unknown): IncidentSummaryList {
  const result = asRow(value);
  return {
    items: Array.isArray(result.reports) ? result.reports.map((item) => incidentSummary(asRow(item))) : [],
    totalItems: typeof result.totalItems === 'number' ? result.totalItems : 0,
    incidentTypes: names(result.incidentTypes),
  };
}

/**
 * The facet columns of an envelope payload: type and severity from the overview, and the single camera's
 * seconds when there is exactly one camera (a multi-camera revision has no single timeline).
 */
export function envelopeFacets(payload: unknown): ReturnType<typeof revisionFacets> {
  const envelope = parseEnvelope(payload);
  const single = envelope.cameras.length === 1 ? revisionFacets(envelope.cameras[0].report) : null;
  const { type, severity_level } = envelope.overview;
  return {
    incident_type: type ? type.toLowerCase() : null,
    severity_level,
    start_seconds: single?.start_seconds ?? null,
    end_seconds: single?.end_seconds ?? null,
  };
}

/**
 * The incident functions RAISE a SQLSTATE for a refusal: P0001 (a domain refusal, "not found" in the text for a
 * missing row), P0002 (missing row), 22023 (bad argument) and 23514 (the last video cannot move). Those become
 * StoreRejection; anything else is rethrown unchanged.
 */
export function incidentRefusal(error: unknown): never {
  const message = error instanceof Error ? error.message : '';
  const code = /"code":"(P0001|P0002|22023|23514)"/.exec(message)?.[1];
  if (!code) throw error;
  const match = /"message":"((?:[^"\\]|\\.)*)"/.exec(message);
  const reason = match ? (JSON.parse(`"${match[1]}"`) as string) : 'The database refused the request';
  throw new StoreRejection(code === 'P0002' || /not found|does not exist/i.test(reason) ? 'not-found' : 'invalid', reason);
}

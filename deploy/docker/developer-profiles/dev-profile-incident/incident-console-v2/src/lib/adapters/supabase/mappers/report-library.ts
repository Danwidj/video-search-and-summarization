// SPDX-License-Identifier: Apache-2.0

// list_incident_report_summaries: ReportListQuery -> RPC arguments, and its
// JSON -> ReportList field by field. Its SQL
// (supabase/functions-final.sql) builds every summary
// with exactly these keys and null for an empty column, so for every result it
// can build the output equals the input; the defaults only apply to a
// malformed result.

import type { ReportList, ReportListQuery } from '@/lib/ports';
import type { RevisionKind } from '@/lib/reports/revision';
import type { ReportLibraryItem } from '@/lib/reports/storage';

type Row = Record<string, unknown>;
type Outcome = NonNullable<ReportLibraryItem['outcome']>;

const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const textOrNull = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** A label the SQL derives from stored text (run outcome); kept as given, since no CHECK constrains it. */
const label = <T extends string>(value: unknown, fallback: T): T => (typeof value === 'string' ? (value as T) : fallback);

export function reportListRpcArgs(query: ReportListQuery): Row {
  return {
    p_page: query.page,
    p_page_size: query.pageSize,
    p_search: query.search,
    p_type: query.type,
    p_severity: query.severity,
    p_kind: query.kind,
    p_generated_after: query.generatedAfter,
    p_generated_before: query.generatedBefore,
    p_time_from: query.timeFrom,
    p_time_to: query.timeTo,
    p_entities: query.entities,
    p_instruments: query.instruments,
    p_assets: query.assets,
    p_day_of_week: query.dayOfWeek,
    p_sort: query.sort,
    p_scope: query.scope,
    p_entity_types: query.entityTypes,
    p_evidence_match: query.evidenceMatch,
    p_timezone: query.timezone,
  };
}

/** One summary, in the order the SQL builds it. */
function reportSummary(item: Row): ReportLibraryItem {
  return {
    revisionId: numberOrNull(item.revisionId) ?? 0,
    revisionNo: numberOrNull(item.revisionNo) ?? 0,
    videoId: text(item.videoId),
    modelRunId: textOrNull(item.modelRunId),
    kind: label<RevisionKind>(item.kind, 'ai'),
    createdBy: textOrNull(item.createdBy),
    note: textOrNull(item.note),
    title: text(item.title),
    filename: text(item.filename),
    incident_type: text(item.incident_type),
    description: text(item.description),
    // COALESCE(severity_level, 1) in the SQL.
    severity: numberOrNull(item.severity) ?? 1,
    confidence: numberOrNull(item.confidence),
    generatedAt: textOrNull(item.generatedAt),
    uploadedAt: textOrNull(item.uploadedAt),
    model: text(item.model),
    // From the run's immutable notes: how the analysis ended; null when the revision has no recorded run.
    outcome: typeof item.outcome === 'string' ? (item.outcome as Outcome) : null,
    // Whether this revision is the video's official one.
    isOfficial: item.isOfficial === true,
    officialSince: textOrNull(item.officialSince),
    versionCount: numberOrNull(item.versionCount) ?? 0,
    evidenceCount: numberOrNull(item.evidenceCount) ?? 0,
    thumbnail: textOrNull(item.thumbnail),
    r2Key: textOrNull(item.r2Key),
    sensorId: textOrNull(item.sensorId),
  };
}

export function reportListFromRpc(value: unknown): ReportList {
  const result = asRow(value);
  return {
    items: Array.isArray(result.reports) ? result.reports.map((item) => reportSummary(asRow(item))) : [],
    totalItems: typeof result.totalItems === 'number' ? result.totalItems : 0,
    incidentTypes: Array.isArray(result.incidentTypes) ? result.incidentTypes.filter((type): type is string => typeof type === 'string') : [],
  };
}

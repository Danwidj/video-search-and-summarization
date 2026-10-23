// SPDX-License-Identifier: Apache-2.0

// get_incident_dashboard: DashboardQuery -> RPC arguments, and its JSON ->
// DashboardAnalytics field by field. For every result its SQL can build
// (supabase/functions-final.sql) the output equals
// the input; the defaults only apply to a malformed result.

import type { DashboardAnalytics, ModelCoverage, RankedValue, SeverityCounts, TypeDetail } from '@/lib/dashboard/types';
import type { DashboardQuery } from '@/lib/ports';

type Row = Record<string, unknown>;

const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const asRows = (value: unknown): Row[] => (Array.isArray(value) ? value.map(asRow) : []);
const count = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const ranked = (value: unknown): RankedValue[] => asRows(value).map((item) => ({ label: text(item.label), count: count(item.count) }));

function severityCounts(value: unknown): SeverityCounts {
  const item = asRow(value);
  return { low: count(item.low), medium: count(item.medium), high: count(item.high) };
}

/** An instant as a timestamp without time zone: stored timestamps are naive UTC. */
const naiveUtc = (value: Date | null): string | null => value?.toISOString().replace('Z', '') ?? null;

export function dashboardRpcArgs(query: DashboardQuery): Row {
  return {
    p_period_start: naiveUtc(query.periodStart),
    p_period_end: naiveUtc(query.periodEnd),
    p_type: query.type,
    p_severity: query.severity,
    p_day_of_week: query.dayOfWeek,
    p_hour: query.hour,
    p_timezone: query.timezone,
  };
}

export function dashboardFromRpc(value: unknown): DashboardAnalytics {
  const result = asRow(value);
  const videos = asRow(result.videos);
  const revisions = asRow(result.revisions);
  // NULL for an all-time period, else one row of counts.
  const previous = result.previous && typeof result.previous === 'object' ? asRow(result.previous) : null;
  return {
    total: count(result.total),
    videos: {
      uploaded: count(videos.uploaded),
      withOfficial: count(videos.withOfficial),
      awaitingSelection: count(videos.awaitingSelection),
      withoutReport: count(videos.withoutReport),
    },
    previous: previous ? { total: count(previous.total), human: count(previous.human), ai: count(previous.ai), high: count(previous.high) } : null,
    averageConfidence: numberOrNull(result.averageConfidence),
    confidenceNotProvided: count(result.confidenceNotProvided),
    severity: severityCounts(result.severity),
    revisions: { ai: count(revisions.ai), human: count(revisions.human) },
    types: asRows(result.types).map((item): TypeDetail => ({
      type: text(item.type),
      count: count(item.count),
      severity: severityCounts(item.severity),
      entities: ranked(item.entities),
      instruments: ranked(item.instruments),
      assets: ranked(item.assets),
    })),
    trend: asRows(result.trend).map((item) => ({ date: text(item.date), count: count(item.count) })),
    heatmap: asRows(result.heatmap).map((item) => ({ day: numberOrNull(item.day), hour: numberOrNull(item.hour), count: count(item.count) })),
    confidence: asRows(result.confidence).map((item) => ({ bucket: count(item.bucket), count: count(item.count) })),
    entityTypes: ranked(result.entityTypes),
    topInstruments: ranked(result.topInstruments),
    topAssets: ranked(result.topAssets),
    threatLevels: asRows(result.threatLevels).map((item) => ({ level: count(item.level), count: count(item.count) })),
    modelCoverage: asRows(result.modelCoverage).map((item): ModelCoverage => ({
      model: text(item.model),
      withReport: count(item.withReport),
      validFirstPass: count(item.validFirstPass),
      repaired: count(item.repaired),
      legacy: count(item.legacy),
      contractFailed: count(item.contractFailed),
      requestFailed: count(item.requestFailed),
    })),
  };
}

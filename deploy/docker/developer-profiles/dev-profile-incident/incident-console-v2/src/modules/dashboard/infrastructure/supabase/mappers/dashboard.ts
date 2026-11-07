// SPDX-License-Identifier: Apache-2.0

// get_incident_dashboard: DashboardQuery -> RPC arguments, and its JSON ->
// DashboardAnalytics field by field. For every result its SQL can build (the
// latest definition in supabase/migrations/) the output equals the input; the
// defaults only apply to a malformed result. A field an older definition does
// not return (multipleVersions, versions, evidence, the entity and instrument split) is
// null, never 0, so the page never shows a figure it has not loaded.

import type {
  DashboardAnalytics,
  EvidenceKind,
  EvidenceTotal,
  HolderType,
  MaybeSplitRankedValue,
  ModelCoverage,
  OfficialSplit,
  RankedValue,
  SeverityCounts,
  SplitRankedValue,
  SeverityEvidenceCell,
  ThreatByHolder,
  TypeDetail,
} from '@/modules/dashboard/domain/types';
import type { DashboardQuery } from '@/modules/dashboard/domain/DashboardRepository';

type Row = Record<string, unknown>;

const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const asRows = (value: unknown): Row[] => (Array.isArray(value) ? value.map(asRow) : []);
const count = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const ranked = (value: unknown): RankedValue[] => asRows(value).map((item) => ({ label: text(item.label), count: count(item.count) }));

const EVIDENCE_KINDS: readonly EvidenceKind[] = ['entities', 'instruments', 'assets'];
/** The kinds the RPC returns; anything else is a malformed result and is read as the first kind with no count. */
const evidenceKind = (value: unknown): EvidenceKind => EVIDENCE_KINDS.find((kind) => kind === value) ?? 'entities';

const HOLDER_TYPES: readonly HolderType[] = ['human', 'animal', 'unknown', 'none'];
/** The holder types the RPC returns; anything else is a malformed result and is read as no holder (as evidenceKind does). */
const holderType = (value: unknown): HolderType => HOLDER_TYPES.find((holder) => holder === value) ?? 'none';

const split = (item: Row): OfficialSplit => ({ official: count(item.official), notOfficial: count(item.notOfficial) });
const splitRanked = (value: unknown): SplitRankedValue[] =>
  asRows(value).map((item) => ({ label: text(item.label), count: count(item.count), ...split(item) }));
/** A row without its split keys is from an older definition: its split is unknown, not zero. */
const maybeSplitRanked = (value: unknown): MaybeSplitRankedValue[] =>
  asRows(value).map((item) => {
    const known = 'official' in item || 'notOfficial' in item;
    return {
      label: text(item.label),
      count: count(item.count),
      official: known ? count(item.official) : null,
      notOfficial: known ? count(item.notOfficial) : null,
    };
  });

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
    p_scope: query.scope,
  };
}

export function dashboardFromRpc(value: unknown): DashboardAnalytics {
  const result = asRow(value);
  const videos = asRow(result.videos);
  const revisions = asRow(result.revisions);
  const versions = asRow(result.versions);
  const severityByScope = asRow(result.severityByScope);
  // NULL for an all-time period, else one row of counts.
  const previous = result.previous && typeof result.previous === 'object' ? asRow(result.previous) : null;
  return {
    total: count(result.total),
    ...split(result),
    multipleVersions: numberOrNull(result.multipleVersions),
    versions: 'versions' in result ? { total: count(versions.total), ai: count(versions.ai), human: count(versions.human) } : null,
    videos: {
      uploaded: count(videos.uploaded),
      withOfficial: count(videos.withOfficial),
      awaitingSelection: count(videos.awaitingSelection),
      withoutReport: count(videos.withoutReport),
    },
    previous: previous
      ? { total: count(previous.total), human: count(previous.human), ai: count(previous.ai), high: count(previous.high) }
      : null,
    averageConfidence: numberOrNull(result.averageConfidence),
    confidenceNotProvided: count(result.confidenceNotProvided),
    severity: severityCounts(result.severity),
    severityByScope: {
      official: severityCounts(severityByScope.official),
      notOfficial: severityCounts(severityByScope.notOfficial),
    },
    revisions: { ai: count(revisions.ai), human: count(revisions.human) },
    types: asRows(result.types).map(
      (item): TypeDetail => ({
        type: text(item.type),
        count: count(item.count),
        ...split(item),
        evidence: typeof item.evidence === 'number' ? count(item.evidence) : null,
        severity: severityCounts(item.severity),
        entities: ranked(item.entities),
        instruments: ranked(item.instruments),
        assets: ranked(item.assets),
      }),
    ),
    trend: asRows(result.trend).map((item) => ({ date: text(item.date), count: count(item.count), ...split(item) })),
    heatmap: asRows(result.heatmap).map((item) => ({
      day: numberOrNull(item.day),
      hour: numberOrNull(item.hour),
      count: count(item.count),
      ...split(item),
    })),
    confidence: asRows(result.confidence).map((item) => ({ bucket: count(item.bucket), count: count(item.count) })),
    evidence: Array.isArray(result.evidence)
      ? asRows(result.evidence).map((item): EvidenceTotal => ({ kind: evidenceKind(item.kind), count: count(item.count), ...split(item) }))
      : null,
    severityEvidence: Array.isArray(result.severityEvidence)
      ? asRows(result.severityEvidence).map(
          (item): SeverityEvidenceCell => ({
            severity: count(item.severity),
            evidenceItems: count(item.evidenceItems),
            count: count(item.count),
            ...split(item),
          }),
        )
      : null,
    entityTypes: maybeSplitRanked(result.entityTypes),
    topInstruments: maybeSplitRanked(result.topInstruments),
    topAssets: splitRanked(result.topAssets),
    threatLevels: asRows(result.threatLevels).map((item) => ({ level: count(item.level), count: count(item.count) })),
    threatByHolder: Array.isArray(result.threatByHolder)
      ? asRows(result.threatByHolder).map(
          (item): ThreatByHolder => ({
            holder: holderType(item.holder),
            high: count(item.high),
            medium: count(item.medium),
            low: count(item.low),
            ...split(item),
          }),
        )
      : null,
    modelCoverage: asRows(result.modelCoverage).map(
      (item): ModelCoverage => ({
        model: text(item.model),
        withReport: count(item.withReport),
        validFirstPass: count(item.validFirstPass),
        repaired: count(item.repaired),
        legacy: count(item.legacy),
        contractFailed: count(item.contractFailed),
        requestFailed: count(item.requestFailed),
      }),
    ),
  };
}

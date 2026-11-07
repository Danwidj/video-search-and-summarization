// SPDX-License-Identifier: Apache-2.0

import type { DashboardAnalytics, EvidenceKind, MaybeSplitRankedValue, OfficialSplit } from '@/modules/dashboard/domain/types';
import type { Range } from '@/modules/dashboard/domain/links';

export type DashboardView = 'loading' | 'failed' | 'ready';

/** No analytics means no figures to show: a first load never renders zeros, and neither does a failed one. */
export function dashboardView(data: DashboardAnalytics | null, error: string): DashboardView {
  if (data) return 'ready';
  return error ? 'failed' : 'loading';
}

/** One row of a bar chart that has only its total. */
export interface CountRow {
  key: string;
  label: string;
  total: number;
}

/** One row of a split bar chart. */
export interface SplitRow extends CountRow, OfficialSplit {}

/** A row of a bar chart: split when its split is known, else its total only. */
export type BarRow = SplitRow | CountRow;

export const isSplitRow = (row: BarRow): row is SplitRow => 'official' in row && 'notOfficial' in row;

/** Rows draw as the official split only when every row has one; otherwise as one series of totals. */
export const allSplit = (rows: BarRow[]): rows is SplitRow[] => rows.every(isSplitRow);

export const SEVERITY_LABELS = { high: 'High (4-5)', medium: 'Medium (3)', low: 'Low (1-2)' } as const;

export function severityRows(data: DashboardAnalytics): SplitRow[] {
  return (['high', 'medium', 'low'] as const).map((band) => ({
    key: band,
    label: SEVERITY_LABELS[band],
    total: data.severity[band],
    official: data.severityByScope.official[band],
    notOfficial: data.severityByScope.notOfficial[band],
  }));
}

/** Reports with no severity fall in no band, so the bands can sum to less than the total. */
export function unratedReports(data: DashboardAnalytics): number {
  return Math.max(0, data.total - data.severity.high - data.severity.medium - data.severity.low);
}

/** The Total reports chip's count: null when the RPC did not return it (not loaded) or when no counted report has several versions. */
export function revisedReports(data: DashboardAnalytics): number | null {
  const count = data.multipleVersions;
  return count === null || count <= 0 ? null : count;
}

export function typeRows(data: DashboardAnalytics): SplitRow[] {
  return data.types.map(({ type, count, official, notOfficial }) => ({ key: type, label: type, total: count, official, notOfficial }));
}

export function assetRows(data: DashboardAnalytics): SplitRow[] {
  return data.topAssets.map(({ label, count, official, notOfficial }) => ({ key: label, label, total: count, official, notOfficial }));
}

/** How many instrument rows the Top instruments panel shows; the RPC returns eight. */
export const TOP_INSTRUMENT_ROWS = 5;

const EVIDENCE_LABELS: Record<EvidenceKind, string> = { entities: 'Entities', instruments: 'Instruments', assets: 'Assets' };

/** Evidence items of the counted reports by kind (one row each, always in the RPC's order); null when not loaded. */
export function evidenceRows(data: DashboardAnalytics): SplitRow[] | null {
  if (!data.evidence) return null;
  return data.evidence.map(({ kind, count, official, notOfficial }) => ({
    key: kind,
    label: EVIDENCE_LABELS[kind],
    total: count,
    official,
    notOfficial,
  }));
}

function rankedRow({ label, count, official, notOfficial }: MaybeSplitRankedValue): BarRow {
  if (official === null || notOfficial === null) return { key: label, label, total: count };
  return { key: label, label, total: count, official, notOfficial };
}

/** Canonical entity types (human, animal, unknown), counted per report; a row without its split has its total only. */
export function entityTypeRows(data: DashboardAnalytics): BarRow[] {
  return data.entityTypes.map(rankedRow);
}

/** The most-used instrument names, exact and normalised, counted per report; a row without its split has its total only. */
export function instrumentRows(data: DashboardAnalytics): BarRow[] {
  return data.topInstruments.slice(0, TOP_INSTRUMENT_ROWS).map(rankedRow);
}

/** A calendar selection in the viewer's zone: a day, or the first and last day of a range. */
export interface CalendarSelection {
  from?: Date;
  to?: Date;
}

/**
 * A calendar range as the dashboard's window: local midnight of the first day up to local midnight after the last, written as
 * zoneless UTC (the API reads it as UTC). A single day is a range of one day.
 */
export function customWindow(selection: CalendarSelection): Range {
  const first = selection.from ?? new Date();
  const last = selection.to ?? first;
  const start = new Date(first.getFullYear(), first.getMonth(), first.getDate());
  const end = new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1);
  return { after: start.toISOString().replace('Z', ''), before: end.toISOString().replace('Z', '') };
}

/** "Oct 28, 2026" for a calendar day, read from the picker's local date; no time zone conversion. */
export function formatCalendarDay(date: Date): string {
  return `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

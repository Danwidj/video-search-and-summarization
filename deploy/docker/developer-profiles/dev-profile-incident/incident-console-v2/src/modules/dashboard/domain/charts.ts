// SPDX-License-Identifier: Apache-2.0

import type { DashboardAnalytics, OfficialSplit } from '@/modules/dashboard/domain/types';

export type DashboardView = 'loading' | 'failed' | 'ready';

/** No analytics means no figures to show: a first load never renders zeros, and neither does a failed one. */
export function dashboardView(data: DashboardAnalytics | null, error: string): DashboardView {
  if (data) return 'ready';
  return error ? 'failed' : 'loading';
}

/** One row of a split bar chart. */
export interface SplitRow extends OfficialSplit {
  key: string;
  label: string;
  total: number;
}

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

export function typeRows(data: DashboardAnalytics): SplitRow[] {
  return data.types.map(({ type, count, official, notOfficial }) => ({ key: type, label: type, total: count, official, notOfficial }));
}

export function assetRows(data: DashboardAnalytics): SplitRow[] {
  return data.topAssets.map(({ label, count, official, notOfficial }) => ({ key: label, label, total: count, official, notOfficial }));
}

/** Percent change against the previous period; null when there is nothing to compare with. */
export function delta(now: number, before?: number): number | null {
  if (before === undefined) return null;
  return before ? Math.round(((now - before) / before) * 100) : now ? 100 : 0;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** A trend date (YYYY-MM-DD, already the viewer's day) as "Oct 28"; never re-read through a Date, which would shift it. */
export function formatDay(date: string): string {
  const [, month, day] = date.split('-').map(Number);
  return month && day ? `${MONTHS[month - 1]} ${day}` : date;
}

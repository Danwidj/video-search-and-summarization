// SPDX-License-Identifier: Apache-2.0

import type { DashboardScope } from '@/modules/dashboard/domain/DashboardRepository';
import type { Filters, Range } from '@/modules/dashboard/domain/links';

/** The period presets in the filter bar; 'custom' is the calendar range. */
export const PERIOD_PRESETS = [
  { value: '7', label: '7d', hint: 'Last 7 days' },
  { value: '30', label: '30d', hint: 'Last 30 days' },
  { value: '90', label: '90d', hint: 'Last 90 days' },
  { value: 'all', label: 'All', hint: 'All time' },
] as const;

export const DEFAULT_PERIOD = '30';
export const DEFAULT_SCOPE: DashboardScope = 'all';

export const SCOPE_LABELS: Record<DashboardScope, string> = { all: 'All', official: 'Official', not_official: 'Not yet official' };

export const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** The zoneless UTC window of a day-count preset ending now; null for all time. */
export function presetWindow(days: string, now: Date): Range {
  if (days === 'all') return null;
  return {
    after: new Date(now.getTime() - Number(days) * 86_400_000).toISOString().replace('Z', ''),
    before: now.toISOString().replace('Z', ''),
  };
}

export type FilterChip = { key: 'period' | 'scope' | 'type' | 'severity' | 'cell'; label: string; value: string };

type FilterState = { days: string; customLabel: string; scope: DashboardScope; filters: Filters; timeZone: string };

/** One removable chip per active filter; the default period (30 days) and status (All) are not filters. */
export function filterChips({ days, customLabel, scope, filters, timeZone }: FilterState): FilterChip[] {
  const chips: FilterChip[] = [];
  if (days === 'custom') chips.push({ key: 'period', label: 'Dates', value: customLabel });
  else if (days !== DEFAULT_PERIOD) {
    chips.push({ key: 'period', label: 'Period', value: PERIOD_PRESETS.find((p) => p.value === days)?.hint ?? days });
  }
  if (scope !== DEFAULT_SCOPE) chips.push({ key: 'scope', label: 'Status', value: SCOPE_LABELS[scope] });
  if (filters.type) chips.push({ key: 'type', label: 'Type', value: filters.type });
  if (filters.severity) chips.push({ key: 'severity', label: 'Severity', value: filters.severity });
  if (filters.day && filters.hour) {
    chips.push({
      key: 'cell',
      label: 'Day and hour',
      value: `${DAY_NAMES[Number(filters.day)]} ${filters.hour.padStart(2, '0')}:00 ${timeZone}`,
    });
  }
  return chips;
}

/** The heatmap series that follows the Status filter. */
export function heatmapSeries(scope: DashboardScope): 'count' | 'official' | 'notOfficial' {
  return scope === 'official' ? 'official' : scope === 'not_official' ? 'notOfficial' : 'count';
}

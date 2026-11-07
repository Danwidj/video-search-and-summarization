// SPDX-License-Identifier: Apache-2.0

// Which colour each chart series, donut slice and bubble gets. Official and not yet official always use the
// status colours, and status colours go only to status series. Severity bands always use the severity colours, and
// they go only to severity series (a donut, a severity stack or a bubble's band) and threat series (a threat stack, whose
// bands are the same). No chart mixes the two sets.

import { CHART_COLORS } from '@/lib/ui/chart-colors';
import { severityChartColor } from '@/lib/ui/severity';
import type { ChartSeries, DrawnKind, ChartRow } from '@/modules/dashboard/domain/generated-chart';
import type { ChartDimensionName } from '@/modules/dashboard/domain/chart-spec';

export const OFFICIAL_SERIES = { key: 'official', label: 'Official', color: CHART_COLORS.official } as const;
export const NOT_OFFICIAL_SERIES = { key: 'not_official', label: 'Not official', color: CHART_COLORS.notOfficial } as const;

/**
 * A stacked bar by severity: high on top of medium on top of low, in the severity badge colours. Listed high first, as the
 * legend and table read; the agent draws the stack from low at the bottom.
 */
export const SEVERITY_SERIES: ChartSeries[] = [
  { key: 'high', label: 'High', color: severityChartColor.high },
  { key: 'medium', label: 'Medium', color: severityChartColor.medium },
  { key: 'low', label: 'Low', color: severityChartColor.low },
];

/**
 * A stacked bar by threat: high, medium and low threat, in the same band colours as severity (one band mapping, styles.css).
 * Listed high first, as SEVERITY_SERIES is; the agent draws the stack from low at the bottom.
 */
export const THREAT_SERIES: ChartSeries[] = [
  { key: 'high', label: 'High threat', color: severityChartColor.high },
  { key: 'medium', label: 'Medium threat', color: severityChartColor.medium },
  { key: 'low', label: 'Low threat', color: severityChartColor.low },
];

/** The line of the dual-axis chart: a categorical colour, not a status colour. */
export const EVIDENCE_LINE_COLOR = CHART_COLORS.categorical[4];

const SEVERITY_BY_LABEL: Record<string, string> = {
  Low: severityChartColor.low,
  Medium: severityChartColor.medium,
  High: severityChartColor.high,
};

/** The severity band colour of a level 1 to 5 (low 1-2, medium 3, high 4-5). */
export function severityLevelColor(level: number): string {
  if (level <= 2) return severityChartColor.low;
  return level === 3 ? severityChartColor.medium : severityChartColor.high;
}

/**
 * The colour of each donut slice, or of each bubble, in row order; null for every other kind. A bubble's row carries its
 * severity level, so its colour is that level's band.
 */
export function sliceColors(kind: DrawnKind, dimension: ChartDimensionName, rows: ChartRow[]): string[] | null {
  if (kind === 'bubble') return rows.map((row) => severityLevelColor(row.values.severity ?? 0));
  if (kind !== 'donut') return null;
  if (dimension === 'severity') return rows.map((row) => SEVERITY_BY_LABEL[row.category] ?? CHART_COLORS.total);
  if (dimension === 'report_status') {
    return rows.map((row) => (row.category === 'Official' ? CHART_COLORS.official : CHART_COLORS.notOfficial));
  }
  return rows.map((_, index) => CHART_COLORS.categorical[index % CHART_COLORS.categorical.length] ?? CHART_COLORS.total);
}

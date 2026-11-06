// SPDX-License-Identifier: Apache-2.0

// Which colour each chart series and donut slice gets. Official and not yet official always use the
// status colours; severity bands always use the severity colours. No chart mixes the two sets.

import { CHART_COLORS } from '@/lib/ui/chart-colors';
import { severityChartColor } from '@/lib/ui/severity';
import type { ChartKind, ChartRow } from '@/modules/dashboard/domain/generated-chart';
import type { ChartDimensionName } from '@/modules/dashboard/domain/chart-spec';

export const OFFICIAL_SERIES = { key: 'official', label: 'Official', color: CHART_COLORS.official } as const;
export const NOT_OFFICIAL_SERIES = { key: 'not_official', label: 'Not official', color: CHART_COLORS.notOfficial } as const;

const SEVERITY_BY_LABEL: Record<string, string> = {
  Low: severityChartColor.low,
  Medium: severityChartColor.medium,
  High: severityChartColor.high,
};

/** The colour of each donut slice, in row order; null for every other kind. */
export function sliceColors(kind: ChartKind, dimension: ChartDimensionName, rows: ChartRow[]): string[] | null {
  if (kind !== 'donut') return null;
  if (dimension === 'severity') return rows.map((row) => SEVERITY_BY_LABEL[row.category] ?? CHART_COLORS.total);
  if (dimension === 'report_status') {
    return rows.map((row) => (row.category === 'Official' ? CHART_COLORS.official : CHART_COLORS.notOfficial));
  }
  return rows.map((_, index) => CHART_COLORS.categorical[index % CHART_COLORS.categorical.length] ?? CHART_COLORS.total);
}

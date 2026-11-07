// SPDX-License-Identifier: Apache-2.0

// Which chart kinds suit which dimension. The user picks a kind from the picker; a chart view (see
// chart-spec.ts, viewKind) is always drawn in its own kind, so the picker does not apply to it. For every other
// dimension a kind that does not suit it is refused as "needs_bar" (bar always suits), so no chart shows parts that
// are not a whole or a trend that is not a time series.

import { CHART_DIMENSIONS, type ChartDimensionName } from '@/modules/dashboard/domain/chart-spec';
import type { ChartKind, DrawnKind } from '@/modules/dashboard/domain/generated-chart';

/** Dimensions that run through time, so a line or an area can show them. */
const TIME_DIMENSIONS: ReadonlySet<ChartDimensionName> = new Set(['report_day', 'report_week', 'report_month']);

/** The kind a request is drawn in: the view's own kind, else the kind the user picked. */
export function drawnKind(picked: ChartKind, dimension: ChartDimensionName): DrawnKind {
  return CHART_DIMENSIONS[dimension].viewKind ?? picked;
}

export function kindFitsDimension(kind: ChartKind, dimension: ChartDimensionName): boolean {
  // A view draws in its own kind whatever the picker says, so no pick is refused for it.
  if (CHART_DIMENSIONS[dimension].viewKind !== null) return true;
  switch (kind) {
    case 'bar':
    case 'horizontal_bar':
      return true;
    case 'stacked_bar':
      return CHART_DIMENSIONS[dimension].splits;
    case 'donut':
      return CHART_DIMENSIONS[dimension].pie;
    case 'line':
    case 'area':
      return TIME_DIMENSIONS.has(dimension);
  }
}

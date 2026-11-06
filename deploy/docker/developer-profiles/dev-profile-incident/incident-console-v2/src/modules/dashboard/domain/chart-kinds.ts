// SPDX-License-Identifier: Apache-2.0

// Which chart kinds suit which dimension. The user picks the kind; a kind that does not suit the
// dimension is refused as "needs_bar" (bar always suits), so no chart shows parts that are not a whole
// or a trend that is not a time series.

import { CHART_DIMENSIONS, type ChartDimensionName } from '@/modules/dashboard/domain/chart-spec';
import type { ChartKind } from '@/modules/dashboard/domain/generated-chart';

/** Dimensions that run through time, so a line or an area can show them. */
const TIME_DIMENSIONS: ReadonlySet<ChartDimensionName> = new Set(['report_day', 'report_week', 'report_month']);

export function kindFitsDimension(kind: ChartKind, dimension: ChartDimensionName): boolean {
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

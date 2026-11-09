// SPDX-License-Identifier: Apache-2.0

import type { ChartKind } from '@/modules/dashboard/domain/generated-chart';

/**
 * The example chips under "Ask for a chart". Each chip sends its own request with the chart kind it reads best in.
 * A chip that is not a chart view also sets the chart-type picker to that kind, so the picker shows what is drawn. A
 * view (the October chip, a stacked bar by severity) ignores the picker and leaves it as it is.
 */
export interface ChartExample {
  request: string;
  kind: ChartKind;
  /** True when a click also sets the chart-type picker to this kind. */
  setsPicker: boolean;
}

export const CHART_EXAMPLES: readonly ChartExample[] = [
  // A chart view: stacked bars by severity, one per incident type, for October.
  { request: 'Break down each incident type by severity throughout October', kind: 'stacked_bar', setsPicker: false },
  // Incident types as a whole: a donut.
  { request: 'Incident distribution', kind: 'donut', setsPicker: true },
  // Severity bands as a whole: a donut.
  { request: 'Severity breakdown', kind: 'donut', setsPicker: true },
];

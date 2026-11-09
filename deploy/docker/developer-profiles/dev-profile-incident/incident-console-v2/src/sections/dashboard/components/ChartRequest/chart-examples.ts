// SPDX-License-Identifier: Apache-2.0

import type { ChartKind } from '@/modules/dashboard/domain/generated-chart';

/**
 * The example chips under "Ask for a chart". Each chip sends its own request with the chart kind it reads best in, so a
 * click gives that chart whatever the picker shows. A chip whose request is a chart view ignores its kind (the view is
 * drawn in its own kind), so its kind is only the one the picker would send.
 */
export interface ChartExample {
  request: string;
  kind: ChartKind;
}

export const CHART_EXAMPLES: readonly ChartExample[] = [
  // A chart view: stacked bars by severity, one per incident type, for October.
  { request: 'Break down each incident type by severity throughout October', kind: 'stacked_bar' },
  // Incident types as a whole: a donut.
  { request: 'Incident distribution', kind: 'donut' },
  // Severity bands as a whole: a donut.
  { request: 'Severity breakdown', kind: 'donut' },
];

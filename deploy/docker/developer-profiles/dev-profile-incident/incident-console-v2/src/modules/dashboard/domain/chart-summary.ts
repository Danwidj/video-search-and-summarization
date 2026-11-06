// SPDX-License-Identifier: Apache-2.0

// The text a screen reader gets for a generated chart: its title, its scope and each series' total.
// The Table tab gives every figure; this sentence names the chart without reading each row.

import type { GeneratedChart } from '@/modules/dashboard/domain/generated-chart';

export function chartSummary(chart: Pick<GeneratedChart, 'title' | 'scope' | 'series' | 'rows'>): string {
  const totals = chart.series.map(({ key, label }) => {
    const total = chart.rows.reduce((sum, row) => sum + (row.values[key] ?? 0), 0);
    return `${label} ${total}`;
  });
  // A calendar period is named in the title already, so its scope is not read out a second time.
  const [period, ...filters] = chart.scope;
  const scope = period !== undefined && chart.title.endsWith(`, ${period}`) ? filters : chart.scope;
  return `${chart.title}${scope.length ? `, ${scope.join(', ')}` : ''}. ${totals.join('; ')}.`;
}

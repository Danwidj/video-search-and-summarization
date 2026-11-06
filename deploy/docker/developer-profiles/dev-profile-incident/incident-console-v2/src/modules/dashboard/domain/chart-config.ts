// SPDX-License-Identifier: Apache-2.0

// Checks the Chart.js configuration the agent sends back. The figures in it must be exactly the rows
// our code computed: a configuration that moves, rounds or drops a number is refused, never shown.

import type { ChartJsConfig, ChartRow, GeneratedChart } from '@/modules/dashboard/domain/generated-chart';

const TYPES = new Set(['bar', 'line', 'doughnut']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** A configuration of the shape the console can render; the figures are checked separately. */
export function isChartJsConfig(value: unknown): value is ChartJsConfig {
  if (!isRecord(value) || typeof value.type !== 'string' || !TYPES.has(value.type) || !isRecord(value.options)) return false;
  if (!isRecord(value.data) || !Array.isArray(value.data.labels) || !Array.isArray(value.data.datasets)) return false;
  return (
    value.data.labels.every((label) => typeof label === 'string') &&
    value.data.datasets.every(
      (dataset) =>
        isRecord(dataset) &&
        typeof dataset.label === 'string' &&
        Array.isArray(dataset.data) &&
        dataset.data.every((figure) => typeof figure === 'number' && Number.isFinite(figure)),
    )
  );
}

/** True when the configuration carries exactly these labels, series names and figures, in this order. */
export function configMatchesChart(config: ChartJsConfig, chart: Pick<GeneratedChart, 'rows' | 'series'>): boolean {
  const { labels, datasets } = config.data;
  if (labels.length !== chart.rows.length || datasets.length !== chart.series.length) return false;
  if (!chart.rows.every((row, index) => labels[index] === row.category)) return false;
  return chart.series.every((series, index) => {
    const dataset = datasets[index];
    return dataset !== undefined && dataset.label === series.label && sameFigures(dataset.data, chart.rows, series.key);
  });
}

function sameFigures(data: number[], rows: ChartRow[], key: string): boolean {
  return data.length === rows.length && rows.every((row, index) => data[index] === (row.values[key] ?? 0));
}

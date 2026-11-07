// SPDX-License-Identifier: Apache-2.0

// Checks the Chart.js configuration the agent sends back. The figures in it must be exactly the rows
// our code computed: a configuration that moves, rounds or drops a number is refused, never shown.

import type { ChartJsConfig, ChartRow, GeneratedChart } from '@/modules/dashboard/domain/generated-chart';

const TYPES = new Set(['bar', 'line', 'doughnut', 'bubble']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** A configuration of the shape the console can render; the figures are checked separately. */
export function isChartJsConfig(value: unknown): value is ChartJsConfig {
  if (!isRecord(value) || typeof value.type !== 'string' || !TYPES.has(value.type) || !isRecord(value.options)) return false;
  if (!isRecord(value.data) || !Array.isArray(value.data.datasets)) return false;
  if (value.type === 'bubble') {
    // A bubble has no labels: each dataset is a list of {x, y, r} points.
    return value.data.datasets.every(
      (dataset) =>
        isRecord(dataset) &&
        typeof dataset.label === 'string' &&
        Array.isArray(dataset.data) &&
        dataset.data.every((point) => isRecord(point) && isFiniteNumber(point.x) && isFiniteNumber(point.y) && isFiniteNumber(point.r)),
    );
  }
  if (!Array.isArray(value.data.labels)) return false;
  return (
    value.data.labels.every((label) => typeof label === 'string') &&
    value.data.datasets.every(
      (dataset) =>
        isRecord(dataset) && typeof dataset.label === 'string' && Array.isArray(dataset.data) && dataset.data.every(isFiniteNumber),
    )
  );
}

/**
 * True when the configuration carries exactly this chart's figures. A bar, line, doughnut or dual-axis chart needs these
 * labels, series names and figures, in this order. A bubble needs one dataset, named as the series, with each row's x
 * (severity level), y (evidence items) and a radius; the radius is a size, not a figure, so only its presence is checked.
 */
export function configMatchesChart(config: ChartJsConfig, chart: Pick<GeneratedChart, 'chartKind' | 'rows' | 'series'>): boolean {
  const { datasets } = config.data;
  if (chart.chartKind === 'bubble') return bubbleMatches(config, chart);
  const labels = config.data.labels ?? [];
  if (labels.length !== chart.rows.length || datasets.length !== chart.series.length) return false;
  if (!chart.rows.every((row, index) => labels[index] === row.category)) return false;
  return chart.series.every((series, index) => {
    const dataset = datasets[index];
    return dataset !== undefined && dataset.label === series.label && sameFigures(dataset.data, chart.rows, series.key);
  });
}

function bubbleMatches(config: ChartJsConfig, chart: Pick<GeneratedChart, 'rows' | 'series'>): boolean {
  const [dataset] = config.data.datasets;
  const series = chart.series[0];
  if (config.data.datasets.length !== 1 || !dataset || !series || dataset.label !== series.label) return false;
  return (
    dataset.data.length === chart.rows.length &&
    chart.rows.every((row, index) => {
      const point = dataset.data[index];
      return (
        isRecord(point) &&
        point.x === (row.values.severity ?? 0) &&
        point.y === (row.values.evidence ?? 0) &&
        isFiniteNumber(point.r) &&
        point.r > 0
      );
    })
  );
}

function sameFigures(data: unknown[], rows: ChartRow[], key: string): boolean {
  return data.length === rows.length && rows.every((row, index) => data[index] === (row.values[key] ?? 0));
}

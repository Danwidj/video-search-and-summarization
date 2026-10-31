// SPDX-License-Identifier: Apache-2.0

// What a generated chart is once our code has run its query: every label comes
// from the allowlist in chart-spec.ts and every figure from the dashboard data.
// No model output is in here. The client imports this file, so it stays free of zod.

export const CHART_REQUEST_MAX_LENGTH = 300;

/** The user picks this; the model does not. */
export const CHART_TYPES = ['bar', 'pie'] as const;
export type ChartType = (typeof CHART_TYPES)[number];

export interface ChartSeries {
  key: string;
  label: string;
}

export interface ChartRow {
  category: string;
  /** One value per series key. */
  values: Record<string, number>;
}

/** The reports behind a chart. */
export interface ReportTotals {
  total: number;
  official: number;
  notOfficial: number;
}

export interface GeneratedChart {
  chartType: ChartType;
  title: string;
  /** What is counted and how it is dated. */
  description: string;
  categoryLabel: string;
  valueLabel: string;
  /** The period, then any filters. */
  scope: string[];
  /** One entry, or official and not official. */
  series: ChartSeries[];
  rows: ChartRow[];
  /** Null for a chart of analysis attempts, which are not reports. */
  reports: ReportTotals | null;
  /** The static image as a data URL; null when no records match, and nothing is drawn. */
  image: string | null;
}

/** One request, one answer. A request outside the allowlist is not an error: it gets a plain refusal, never an invented chart. */
export type ChartAnswer = { kind: 'chart'; chart: GeneratedChart } | { kind: 'unsupported' } | { kind: 'needs_bar' };

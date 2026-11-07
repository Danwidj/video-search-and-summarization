// SPDX-License-Identifier: Apache-2.0

// What a generated chart is once our code has run its query: every label comes
// from the allowlist in chart-spec.ts and every figure from the dashboard data.
// No model output is in here. The client imports this file, so it stays free of zod.

export const CHART_REQUEST_MAX_LENGTH = 300;

/** The kinds the user picks from. The model does not pick a kind. */
export const CHART_KINDS = ['bar', 'stacked_bar', 'horizontal_bar', 'donut', 'line', 'area'] as const;
export type ChartKind = (typeof CHART_KINDS)[number];

/**
 * The kind a chart view is always drawn in, whatever the user picked: a dual-axis combo (reports as bars, evidence per
 * report as a line on a second axis), a stacked bar by severity, or a bubble chart. See chart-kinds.ts.
 */
export const VIEW_KINDS = ['combo_dual_axis', 'stacked_by_severity', 'bubble'] as const;
export type ViewKind = (typeof VIEW_KINDS)[number];

/** The kind a generated chart is drawn in: one the user picked, or a view's own. */
export type DrawnKind = ChartKind | ViewKind;

/** The kind's former name (bar or pie). A request that still says pie gets a donut. */
export const LEGACY_PIE = 'pie';
export const CHART_KIND_INPUTS = [...CHART_KINDS, LEGACY_PIE] as const;

export function normalizeChartKind(kind: ChartKind | typeof LEGACY_PIE): ChartKind {
  return kind === LEGACY_PIE ? 'donut' : kind;
}

export interface ChartSeries {
  key: string;
  label: string;
  /** A six-digit hex colour from the console's palette (lib/ui/chart-colors.ts). */
  color: string;
  /** False when adding the series up means nothing, as for a per-report average. Omitted means it is summed. */
  summable?: boolean;
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

/**
 * The Chart.js configuration the agent built, with the figures placed in it. Plain JSON, no functions. A bar, line or
 * doughnut has one figure per label; a bubble has no labels and one {x, y, r} point per row.
 */
export interface ChartJsDataset {
  label: string;
  data: unknown[];
  [option: string]: unknown;
}

export interface ChartJsConfig {
  type: 'bar' | 'line' | 'doughnut' | 'bubble';
  data: { labels?: string[]; datasets: ChartJsDataset[] };
  options: Record<string, unknown>;
}

export interface GeneratedChart {
  chartKind: DrawnKind;
  title: string;
  /** What is counted and how it is dated. */
  description: string;
  /** The category axis (for a bubble chart, the x axis). */
  categoryLabel: string;
  /** The value axis (for a bubble chart, the y axis). */
  valueLabel: string;
  /** The right-hand axis title of a dual-axis chart; null for every other kind. */
  secondValueLabel: string | null;
  /** The period, then any filters. */
  scope: string[];
  /** One entry, or official and not official. */
  series: ChartSeries[];
  rows: ChartRow[];
  /** Null for a chart of analysis attempts, which are not reports. */
  reports: ReportTotals | null;
  /** The Chart.js configuration, its figures checked against rows; null when no records match or the service sent none. */
  config: ChartJsConfig | null;
  /** The static PNG as a data URL, drawn only when no configuration came back; null otherwise. */
  image: string | null;
}

/** One request, one answer. A request outside the allowlist is not an error: it gets a plain refusal, never an invented chart. */
export type ChartAnswer =
  | { kind: 'chart'; chart: GeneratedChart }
  | { kind: 'unsupported' }
  | { kind: 'needs_bar' }
  /**
   * The view is valid, but the dashboard data it needs is not returned yet (the database change has not been applied).
   * It is a plain answer, never an empty or invented chart.
   */
  | { kind: 'not_available' };

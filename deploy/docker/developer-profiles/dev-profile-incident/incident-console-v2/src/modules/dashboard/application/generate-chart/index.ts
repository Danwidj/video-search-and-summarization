// SPDX-License-Identifier: Apache-2.0

// Generate chart: one request in, one chart out. The model only picks a spec from
// the allowlist; the figures come from getDashboard, so a generated chart counts
// exactly what the dashboard counts; and VSS chart_generator draws those figures.

import type { ChartInterpreter } from '@/modules/dashboard/domain/ChartInterpreter';
import { ChartRenderError, type ChartDrawing, type ChartRenderer } from '@/modules/dashboard/domain/ChartRenderer';
import { configMatchesChart, isChartJsConfig } from '@/modules/dashboard/domain/chart-config';
import { drawnKind, kindFitsDimension } from '@/modules/dashboard/domain/chart-kinds';
import {
  EVIDENCE_LINE_COLOR,
  NOT_OFFICIAL_SERIES,
  OFFICIAL_SERIES,
  SEVERITY_SERIES,
  THREAT_SERIES,
  sliceColors,
} from '@/modules/dashboard/domain/chart-palette';
import {
  CHART_DIMENSIONS,
  CHART_PERIODS,
  type ChartDimensionName,
  type ChartMetric,
  type ChartPeriod,
  type ChartSpec,
  type PresetPeriod,
  parseChartSpec,
} from '@/modules/dashboard/domain/chart-spec';
import { addDays, calendarDays, calendarWords, startOfDay, todayIn } from '@/modules/dashboard/domain/chart-period';
import type { DashboardQuery, DashboardRepository } from '@/modules/dashboard/domain/DashboardRepository';
import { CHART_COLORS } from '@/lib/ui/chart-colors';
import {
  type ChartAnswer,
  type ChartKind,
  type ChartRow,
  type ChartSeries,
  type GeneratedChart,
  normalizeChartKind,
  type ReportTotals,
} from '@/modules/dashboard/domain/generated-chart';
import { normalizeSeverityWords } from '@/modules/dashboard/domain/severity-words';
import type { DashboardAnalytics, HolderType, RankedValue } from '@/modules/dashboard/domain/types';

const COUNT = 'count';
const STATUS_SERIES: ChartSeries[] = [OFFICIAL_SERIES, NOT_OFFICIAL_SERIES];
const TOTAL_SERIES = (label: string): ChartSeries[] => [{ key: COUNT, label, color: CHART_COLORS.total }];
const VALUE_LABELS: Record<ChartMetric, string> = {
  incidents: 'Reports',
  instruments: 'Instruments',
  analyses: 'Analyses',
  evidence_per_report: 'Evidence items per report',
  evidence_items: 'Evidence items',
};
/** A dual-axis view: the reports as bars on the left axis, and evidence items per report as a line on the right. */
const COMBO_SERIES: ChartSeries[] = [
  { key: 'reports', label: 'Reports', color: CHART_COLORS.total },
  { key: 'per_report', label: 'Evidence items per report', color: EVIDENCE_LINE_COLOR, summable: false },
];
/** A bubble view: one bubble per severity level and evidence item count, sized by its reports. */
const BUBBLE_SERIES: ChartSeries[] = [{ key: 'reports', label: 'Reports', color: CHART_COLORS.total }];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const PERIOD_LABELS: Record<PresetPeriod, string> = {
  last_7_days: 'Last 7 days',
  last_30_days: 'Last 30 days',
  last_90_days: 'Last 90 days',
  last_365_days: 'Last 365 days',
  all_time: 'All time',
};
/**
 * The views' axes and series. A view's figures are built from the dashboard data by viewRows; the kind it is drawn in
 * is the dimension's viewKind (chart-spec.ts).
 */
const VIEW_FIGURES: Partial<Record<ChartDimensionName, { series: ChartSeries[]; valueLabel: string; secondValueLabel: string | null }>> = {
  incident_type_evidence: { series: COMBO_SERIES, valueLabel: 'Reports', secondValueLabel: 'Evidence items per report' },
  incident_type_severity: { series: SEVERITY_SERIES, valueLabel: 'Reports', secondValueLabel: null },
  severity_evidence: { series: BUBBLE_SERIES, valueLabel: 'Evidence items', secondValueLabel: null },
  threat_by_holder: { series: THREAT_SERIES, valueLabel: 'Instruments', secondValueLabel: null },
};
/** The category of each holder type in the threat chart. */
const HOLDER_LABELS: Record<HolderType, string> = { human: 'Human', animal: 'Animal', unknown: 'Unknown', none: 'No holder' };
const DAY_MS = 86_400_000;
/** chart_generator labels every bar, so past this many a trend moves to the next coarser bucket. */
const MAX_BUCKETS = 31;

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const countRow = (category: string, count: number): ChartRow => ({ category, values: { [COUNT]: count } });
const rankedRows = (items: RankedValue[]) => items.map((item) => countRow(capitalize(item.label), item.count));

/** A preset counts back from now; a calendar period is its days in the viewer's time zone, from local midnight to the next. */
function periodBounds(period: ChartPeriod, timezone: string, now: Date, today: string): Pick<DashboardQuery, 'periodStart' | 'periodEnd'> {
  if (typeof period === 'string') {
    const days = CHART_PERIODS[period];
    return days === null
      ? { periodStart: null, periodEnd: null }
      : { periodStart: new Date(now.getTime() - days * DAY_MS), periodEnd: now };
  }
  const range = calendarDays(period, today);
  // parseChartSpec has already refused a calendar period that calendarDays rejects, so this cannot fail on a parsed spec.
  if (!range) throw new Error('a calendar period must be checked before its bounds are read');
  return { periodStart: startOfDay(range.first, timezone), periodEnd: startOfDay(addDays(range.last, 1), timezone) };
}

/** The period in words for the chart's scope and, for a calendar period, its title: "Last 30 days", "October 2026", "1 to 15 October 2026". */
const periodLabel = (period: ChartPeriod, today: string): string =>
  typeof period === 'string' ? PERIOD_LABELS[period] : calendarWords(period, today);

function dashboardQuery(spec: ChartSpec, timezone: string, now: Date, today: string): DashboardQuery {
  return {
    ...periodBounds(spec.period, timezone, now, today),
    type: spec.incidentType,
    severity: spec.severity,
    dayOfWeek: null,
    hour: null,
    timezone,
    scope: 'all',
  };
}

function bucketOf(date: string, dimension: ChartDimensionName): string {
  if (dimension === 'report_month') return date.slice(0, 7);
  if (dimension !== 'report_week') return date;
  const day = new Date(`${date}T00:00:00Z`);
  const daysSinceMonday = (day.getUTCDay() + 6) % 7;
  return new Date(day.getTime() - daysSinceMonday * DAY_MS).toISOString().slice(0, 10);
}

/** The RPC's daily rows summed into the bucket; each day in it is zero-filled, so a bucket with no reports stays visible. */
function trendRows(dimension: ChartDimensionName, trend: DashboardAnalytics['trend']): ChartRow[] {
  const buckets = new Map<string, number>();
  for (const { date, count } of trend) {
    const bucket = bucketOf(date, dimension);
    buckets.set(bucket, (buckets.get(bucket) ?? 0) + count);
  }
  return Array.from(buckets, ([category, count]) => countRow(category, count));
}

/** The dimension a trend is drawn at: the one asked for, or a coarser one when that would be too many bars. */
function trendDimension(dimension: ChartDimensionName, trend: DashboardAnalytics['trend']): ChartDimensionName {
  if (dimension === 'report_day' && trendRows(dimension, trend).length > MAX_BUCKETS) return trendDimension('report_week', trend);
  if (dimension === 'report_week' && trendRows(dimension, trend).length > MAX_BUCKETS) return 'report_month';
  return dimension;
}

function heatmapRows(analytics: DashboardAnalytics, field: 'day' | 'hour', labels: string[]): ChartRow[] {
  const counts = labels.map(() => 0);
  for (const cell of analytics.heatmap) {
    const index = cell[field];
    if (index !== null && index in counts) counts[index] = (counts[index] ?? 0) + cell.count;
  }
  return labels.map((label, index) => countRow(label, counts[index] ?? 0));
}

/**
 * Evidence items per report, to two decimals, computed here and never by the model or the chart service. A type with
 * no reports has no per-report figure, so it is null and the type is left out of the chart.
 */
export function evidencePerReport(items: number, reports: number): number | null {
  if (reports <= 0) return null;
  return Math.round((items / reports) * 100) / 100;
}

/**
 * The rows of a chart view, or null when the dashboard data the view needs is not returned yet. The evidence per report
 * needs the per-type evidence total; the severity bubbles need the severity and evidence count pairs. Until the database
 * change that returns them is applied, a view answers "not available yet" rather than inventing a figure.
 */
export function viewRows(dimension: ChartDimensionName, analytics: DashboardAnalytics): ChartRow[] | null {
  switch (dimension) {
    case 'incident_type_evidence': {
      if (analytics.types.some((item) => item.evidence === null)) return null;
      return analytics.types.flatMap((item) => {
        const perReport = evidencePerReport(item.evidence ?? 0, item.count);
        return perReport === null ? [] : [{ category: capitalize(item.type), values: { reports: item.count, per_report: perReport } }];
      });
    }
    case 'incident_type_severity':
      return analytics.types.map((item) => ({
        category: capitalize(item.type),
        values: { high: item.severity.high, medium: item.severity.medium, low: item.severity.low },
      }));
    case 'threat_by_holder': {
      if (analytics.threatByHolder === null) return null;
      // The four holder types, but "no holder" only when some instrument has none, so the chart shows the holders there are.
      return analytics.threatByHolder
        .filter((row) => row.holder !== 'none' || row.high + row.medium + row.low > 0)
        .map((row) => ({ category: HOLDER_LABELS[row.holder], values: { high: row.high, medium: row.medium, low: row.low } }));
    }
    case 'severity_evidence': {
      if (analytics.severityEvidence === null) return null;
      return analytics.severityEvidence.map((cell) => ({
        category: `Severity ${cell.severity}, ${cell.evidenceItems} evidence ${cell.evidenceItems === 1 ? 'item' : 'items'}`,
        // severity and evidence are the bubble's x and y; reports is its size.
        values: { reports: cell.count, severity: cell.severity, evidence: cell.evidenceItems },
      }));
    }
    default:
      return null;
  }
}

function rowsFor(dimension: ChartDimensionName, analytics: DashboardAnalytics, reports: ReportTotals | null): ChartRow[] {
  const coverage = analytics.modelCoverage;
  const sum = (pick: (row: DashboardAnalytics['modelCoverage'][number]) => number) => coverage.reduce((total, row) => total + pick(row), 0);
  switch (dimension) {
    case 'incident_type_evidence':
    case 'incident_type_severity':
    case 'severity_evidence':
    case 'threat_by_holder':
      // A view's rows come from viewRows, which generateChart calls instead.
      return [];
    case 'incident_type':
      return analytics.types.map((item) => countRow(capitalize(item.type), item.count));
    case 'severity':
      return [
        countRow('Low', analytics.severity.low),
        countRow('Medium', analytics.severity.medium),
        countRow('High', analytics.severity.high),
      ];
    case 'report_status':
      return [countRow('Official', reports?.official ?? 0), countRow('Not official', reports?.notOfficial ?? 0)];
    case 'report_kind':
      return [countRow('AI as generated', analytics.revisions.ai), countRow('Human-edited', analytics.revisions.human)];
    case 'report_day':
    case 'report_week':
    case 'report_month':
      return trendRows(dimension, analytics.trend);
    case 'report_weekday':
      return heatmapRows(analytics, 'day', WEEKDAYS);
    case 'report_hour':
      return heatmapRows(
        analytics,
        'hour',
        Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, '0')}:00`),
      );
    case 'entity_type':
      return rankedRows(analytics.entityTypes);
    case 'instrument':
      return rankedRows(analytics.topInstruments);
    case 'asset':
      return rankedRows(analytics.topAssets);
    case 'confidence': {
      const buckets = new Map(analytics.confidence.map((item) => [item.bucket, item.count]));
      return Array.from({ length: 10 }, (_, bucket) => countRow(`${bucket * 10}-${(bucket + 1) * 10}%`, buckets.get(bucket) ?? 0));
    }
    case 'threat_level': {
      const levels = new Map(analytics.threatLevels.map((item) => [item.level, item.count]));
      return [1, 2, 3, 4, 5].map((level) => countRow(`Threat ${level}`, levels.get(level) ?? 0));
    }
    case 'model':
      return coverage.map((row) => countRow(row.model, row.withReport + row.contractFailed + row.requestFailed));
    case 'analysis_outcome':
      return [
        countRow(
          'Valid',
          sum((row) => row.validFirstPass),
        ),
        countRow(
          'IDs repaired',
          sum((row) => row.repaired),
        ),
        countRow(
          'Earlier',
          sum((row) => row.legacy),
        ),
        countRow(
          'Contract failed',
          sum((row) => row.contractFailed),
        ),
        countRow(
          'Request failed',
          sum((row) => row.requestFailed),
        ),
      ];
  }
}

/** The chart's rows with one count each for official and not official, on the axis of the combined query. */
async function splitRows(
  dimension: ChartDimensionName,
  rows: ChartRow[],
  analytics: DashboardAnalytics,
  query: DashboardQuery,
  dashboard: DashboardRepository,
): Promise<ChartRow[]> {
  if (dimension === 'asset') {
    return analytics.topAssets.map((item) => ({
      category: capitalize(item.label),
      values: { official: item.official, not_official: item.notOfficial },
    }));
  }
  const [official, notOfficial] = await Promise.all(
    (['official', 'not_official'] as const).map(async (scope) => {
      const scoped = await dashboard.getDashboard({ ...query, scope });
      return new Map(rowsFor(dimension, scoped, null).map((row) => [row.category, row.values[COUNT] ?? 0]));
    }),
  );
  return rows.map(({ category }) => ({
    category,
    values: { official: official?.get(category) ?? 0, not_official: notOfficial?.get(category) ?? 0 },
  }));
}

export interface GenerateChartPorts {
  interpreter: ChartInterpreter;
  dashboard: DashboardRepository;
  renderer: ChartRenderer;
}

export interface GenerateChartInput {
  request: string;
  chartType: ChartKind | 'pie';
  timezone: string;
  now: Date;
}

export async function generateChart(
  { interpreter, dashboard, renderer }: GenerateChartPorts,
  { request, chartType, timezone, now }: GenerateChartInput,
): Promise<ChartAnswer> {
  const kind = normalizeChartKind(chartType);
  // The viewer's day, so that "October" and "6 November" are read against today (a calendar period is never after it).
  const today = todayIn(timezone, now);
  // Canonical severity words become their band in code (domain/severity-words.ts); the model reads the result.
  const spec = parseChartSpec(await interpreter.interpret(normalizeSeverityWords(request), { today, timezone }), today);
  if (!spec) return { kind: 'unsupported' };
  if (!kindFitsDimension(kind, spec.dimension)) return { kind: 'needs_bar' };

  const query = dashboardQuery(spec, timezone, now, today);
  const label = periodLabel(spec.period, today);
  const analytics = await dashboard.getDashboard(query);
  const reports =
    spec.metric === 'analyses' ? null : { total: analytics.total, official: analytics.official, notOfficial: analytics.notOfficial };
  const dimensionName = trendDimension(spec.dimension, analytics.trend);
  const dimension = CHART_DIMENSIONS[dimensionName];
  // A view is always drawn in its own kind; the picker's kind is not used for it.
  const chartKind = drawnKind(kind, dimensionName);
  const view = VIEW_FIGURES[dimensionName];
  const rows = dimension.viewKind === null ? rowsFor(dimensionName, analytics, reports) : viewRows(dimensionName, analytics);
  // The views need dashboard figures this build cannot read yet: say so, rather than draw nothing or invent a figure.
  if (rows === null) return { kind: 'not_available' };
  // A donut has no split (its parts are the whole); every other kind shows official and not yet official where the dimension has them.
  const split = view === undefined && kind !== 'donut' && dimension.splits;
  const valueLabel = view?.valueLabel ?? VALUE_LABELS[spec.metric];
  const series = view?.series ?? (split ? STATUS_SERIES : TOTAL_SERIES(valueLabel));
  const chartRows = split ? await splitRows(dimensionName, rows, analytics, query, dashboard) : rows;
  const chart: GeneratedChart = {
    chartKind,
    // A calendar period names its range in the title, so a saved or shared chart says which days it counts.
    title: typeof spec.period === 'string' ? dimension.title : `${dimension.title}, ${label}`,
    description: dimension.description,
    categoryLabel: dimension.categoryLabel,
    valueLabel,
    secondValueLabel: view?.secondValueLabel ?? null,
    scope: [
      label,
      ...(spec.incidentType ? [capitalize(spec.incidentType)] : []),
      ...(spec.severity ? [`${capitalize(spec.severity)} severity`] : []),
    ],
    series,
    rows: chartRows,
    reports,
    config: null,
    image: null,
  };
  const hasData = chart.rows.some((row) => Object.values(row.values).some(Boolean));
  if (!hasData) return { kind: 'chart', chart };

  const drawing: ChartDrawing = {
    chartKind,
    title: chart.title,
    categoryLabel: chart.categoryLabel,
    valueLabel: chart.valueLabel,
    secondValueLabel: chart.secondValueLabel,
    series: chart.series,
    rows: chart.rows,
    sliceColors: sliceColors(chartKind, dimensionName, chart.rows),
  };
  // The agent places our figures in a Chart.js configuration. It is shown only if its figures are exactly ours.
  const configured = await renderer.configure(drawing);
  if (configured !== null) {
    if (!isChartJsConfig(configured) || !configMatchesChart(configured, chart)) {
      throw new ChartRenderError('The chart service returned figures that do not match the database');
    }
    return { kind: 'chart', chart: { ...chart, config: configured } };
  }
  // No configuration came back: the static picture stands in for it (a donut is drawn as a pie, everything else as bars).
  const image = await renderer.draw({ ...drawing, chartKind: chartKind === 'donut' ? 'donut' : 'bar' });
  return { kind: 'chart', chart: { ...chart, image } };
}

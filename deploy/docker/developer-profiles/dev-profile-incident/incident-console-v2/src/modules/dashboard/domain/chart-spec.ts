// SPDX-License-Identifier: Apache-2.0

// The allowlist for generated charts. A model reply is untrusted input: it counts
// only if it parses as a ChartSpec, which holds nothing but values from the lists
// below, so no model text reaches the database or the screen. Anything else,
// including extra keys such as data or a title, is refused as a whole.

import { z } from 'zod';

import { INCIDENT_TYPES } from '@/modules/contract/domain/types';
import { CALENDAR_MAX_DAYS, type CalendarPeriod, calendarDays } from '@/modules/dashboard/domain/chart-period';
import type { DashboardSeverity } from '@/modules/dashboard/domain/DashboardRepository';
import type { ViewKind } from '@/modules/dashboard/domain/generated-chart';

export const CHART_METRICS = ['incidents', 'instruments', 'analyses', 'evidence_per_report', 'evidence_items'] as const;
export type ChartMetric = (typeof CHART_METRICS)[number];

export const CHART_SEVERITIES = ['low', 'medium', 'high'] as const satisfies readonly DashboardSeverity[];

/** Days back from now; null is all time. */
export const CHART_PERIODS = {
  last_7_days: 7,
  last_30_days: 30,
  last_90_days: 90,
  last_365_days: 365,
  all_time: null,
} as const;
export type PresetPeriod = keyof typeof CHART_PERIODS;
const PERIOD_NAMES = Object.keys(CHART_PERIODS) as [PresetPeriod, ...PresetPeriod[]];

/** A preset (a string, as before) or a calendar period: one month, one day, or from and to (both inclusive). */
export type ChartPeriod = PresetPeriod | CalendarPeriod;

interface ChartDimension {
  metric: ChartMetric;
  /** The parts make one whole, so a pie is honest. A trend, or a list where one incident counts under several names, is not. */
  pie: boolean;
  /**
   * A bar chart can show official and not official beside each other. False for top
   * instruments, which the query cuts to eight per scope, so a name could drop out of
   * one scope and read as 0, and for analysis attempts, which are not reports.
   */
  splits: boolean;
  /** Period only for false: get_incident_dashboard applies no other filter to analysis attempts. */
  filterable: boolean;
  title: string;
  description: string;
  categoryLabel: string;
  /** How the interpreter is told to recognise this dimension. */
  meaning: string;
  /**
   * A chart view draws in this kind whatever the user picked, and its figures are built for it (generate-chart). Null for
   * every ordinary dimension, which the user's picked kind draws.
   */
  viewKind: ViewKind | null;
}

const REPORTS = 'Each video counts once: its official report, else its newest.';
const ATTEMPTS = 'Every analysis attempt in the period, all runs and not only reports.';
const NOT_INCIDENT_TIME = 'This is not when an incident happened.';

export const CHART_DIMENSIONS = {
  incident_type: {
    metric: 'incidents',
    pie: true,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports by incident type',
    description: REPORTS,
    categoryLabel: 'Incident type',
    meaning: 'count per incident type: "incident distribution", "what types of incident"',
  },
  severity: {
    metric: 'incidents',
    pie: true,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports by severity',
    description: `${REPORTS} Low is level 1-2, medium is 3, high is 4-5.`,
    categoryLabel: 'Severity',
    meaning: 'count per severity band: "severity breakdown"',
  },
  report_status: {
    metric: 'incidents',
    pie: true,
    splits: false,
    filterable: true,
    viewKind: null,
    title: 'Official and not official reports',
    description: `${REPORTS} Not official means no report has been marked official yet.`,
    categoryLabel: 'Status',
    meaning: 'how many reports are official and how many are not',
  },
  report_kind: {
    metric: 'incidents',
    pie: true,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports by version',
    description: `${REPORTS} As the model generated them, or saved by a reviewer.`,
    categoryLabel: 'Report version',
    meaning: 'AI-generated versus human-edited reports',
  },
  report_day: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports per day',
    description: `${REPORTS} By report date.`,
    categoryLabel: 'Day',
    meaning: 'count per day of the report date: "trends over time", "daily incidents"',
  },
  report_week: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports per week',
    description: `${REPORTS} By report date, in weeks from Monday.`,
    categoryLabel: 'Week starting',
    meaning: 'count per week of the report date',
  },
  report_month: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports per month',
    description: `${REPORTS} By report date.`,
    categoryLabel: 'Month',
    meaning: 'count per month of the report date',
  },
  report_weekday: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Report activity by weekday',
    description: `Reports by the weekday they were generated, in your time zone. ${NOT_INCIDENT_TIME}`,
    categoryLabel: 'Weekday',
    meaning: 'reports per weekday they were generated, never the weekday an incident happened',
  },
  report_hour: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Report activity by hour',
    description: `Reports by the hour they were generated, in your time zone. ${NOT_INCIDENT_TIME}`,
    categoryLabel: 'Hour',
    meaning: 'reports per hour they were generated, never the hour an incident happened',
  },
  entity_type: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Reports by entity type',
    description: 'Reports involving each entity type. A report can count under more than one.',
    categoryLabel: 'Entity type',
    meaning: 'incidents involving humans, animals or unknown entities',
  },
  instrument: {
    metric: 'incidents',
    pie: false,
    splits: false,
    filterable: true,
    viewKind: null,
    title: 'Top instruments',
    description: 'The eight most common instruments, by reports naming each. A report can count under more than one.',
    categoryLabel: 'Instrument',
    meaning: 'most common instruments or weapons',
  },
  asset: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Top assets',
    description: 'The eight most common assets, by reports naming each. A report can count under more than one.',
    categoryLabel: 'Asset',
    meaning: 'most commonly affected assets',
  },
  confidence: {
    metric: 'incidents',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Model confidence distribution',
    description: 'Reports by the confidence the model gave. Reports with no confidence value are left out.',
    categoryLabel: 'Confidence',
    meaning: 'histogram of model confidence scores',
  },
  threat_level: {
    metric: 'instruments',
    pie: false,
    splits: true,
    filterable: true,
    viewKind: null,
    title: 'Instrument threat levels',
    description: 'Instruments in the counted reports, by rated threat.',
    categoryLabel: 'Threat level',
    meaning: 'count of instruments per threat level',
  },
  model: {
    metric: 'analyses',
    pie: false,
    splits: false,
    filterable: false,
    viewKind: null,
    title: 'Analyses by model',
    description: ATTEMPTS,
    categoryLabel: 'Model',
    meaning: 'analysis attempts per model',
  },
  analysis_outcome: {
    metric: 'analyses',
    pie: true,
    splits: false,
    filterable: false,
    viewKind: null,
    title: 'Analyses by outcome',
    description: ATTEMPTS,
    categoryLabel: 'Outcome',
    meaning: 'analysis attempts per outcome: valid, repaired, failed',
  },
  // The chart views. Each is drawn in its own kind (VIEW_KINDS) and needs figures the dashboard returns per type, per
  // severity and evidence count, or per holder type and threat band (generate-chart); until the database change that
  // returns them is applied, a view answers "not available yet".
  incident_type_evidence: {
    metric: 'evidence_per_report',
    pie: false,
    splits: false,
    filterable: true,
    viewKind: 'combo_dual_axis',
    title: 'Evidence per report by incident type',
    description: `${REPORTS} Bars are the reports of each type; the line is its evidence items per report (each entity, instrument and asset item).`,
    categoryLabel: 'Incident type',
    meaning:
      'reports per incident type as bars, with evidence items per report as a line on a second axis: "evidence per report by type", "which types produce the most evidence"',
  },
  incident_type_severity: {
    metric: 'incidents',
    pie: false,
    splits: false,
    filterable: true,
    viewKind: 'stacked_by_severity',
    title: 'Severity within each incident type',
    description: `${REPORTS} Each bar is one incident type, split into high, medium and low severity. Low is level 1-2, medium is 3, high is 4-5.`,
    categoryLabel: 'Incident type',
    meaning:
      'severity inside each incident type, one stacked bar per type: "severity by incident type", "severity within each type"; never the plain severity breakdown, which is the severity dimension',
  },
  severity_evidence: {
    metric: 'evidence_items',
    pie: false,
    splits: false,
    filterable: true,
    viewKind: 'bubble',
    title: 'Severity against evidence',
    description: `${REPORTS} Each bubble is one severity level (1 to 5) and one evidence item count; its size is the number of reports with that pair.`,
    categoryLabel: 'Severity level',
    meaning:
      'evidence items against severity level, one bubble per level and item count, sized by reports: "do more severe incidents have more evidence", "severity against evidence"',
  },
  threat_by_holder: {
    metric: 'instruments',
    pie: false,
    splits: false,
    filterable: true,
    viewKind: 'stacked_by_severity',
    title: 'Instrument threat by holder type',
    description: `Instruments in the counted reports, by the type of entity holding each one, split into high, medium and low threat. Low is threat level 1-2, medium is 3, high is 4-5. An instrument with no holder is shown as no holder.`,
    categoryLabel: 'Holder type',
    meaning:
      'instruments per holder type (human, animal, unknown, or no holder), one stacked bar each, split into high, medium and low threat: "distribution of high-threat instruments among entities", "which entity type carries the most dangerous instruments"; never the plain count of instruments per threat level, which is the threat_level dimension, and never the report severity filter',
  },
} as const satisfies Record<string, ChartDimension>;

export type ChartDimensionName = keyof typeof CHART_DIMENSIONS;
const DIMENSION_NAMES = Object.keys(CHART_DIMENSIONS) as [ChartDimensionName, ...ChartDimensionName[]];

// Each calendar form is strict, so a month object cannot carry a day, and a date is checked by calendarDays, which needs today.
const calendarPeriodSchema = z.union([
  z.object({ month: z.string() }).strict(),
  z.object({ day: z.string() }).strict(),
  z.object({ from: z.string(), to: z.string() }).strict(),
]);

/** The spec schema for a request made on `today` (YYYY-MM-DD, in the viewer's time zone). */
function chartSpecSchema(today: string) {
  return z
    .object({
      metric: z.enum(CHART_METRICS),
      dimension: z.enum(DIMENSION_NAMES),
      period: z.union([z.enum(PERIOD_NAMES), calendarPeriodSchema]),
      incidentType: z.enum(INCIDENT_TYPES).nullable(),
      severity: z.enum(CHART_SEVERITIES).nullable(),
    })
    .strict()
    .refine((spec) => {
      const dimension: ChartDimension = CHART_DIMENSIONS[spec.dimension];
      return dimension.metric === spec.metric && (dimension.filterable || (spec.incidentType === null && spec.severity === null));
    })
    .refine((spec) => typeof spec.period === 'string' || calendarDays(spec.period, today) !== null);
}

export type ChartSpec = Omit<z.infer<ReturnType<typeof chartSpecSchema>>, 'period'> & { period: ChartPeriod };

/**
 * The spec a model reply describes, or null for anything else: a refusal, a non-allowlisted value, an unknown key, or a
 * calendar period that is malformed, reversed, longer than CALENDAR_MAX_DAYS or starts after today (`today`, YYYY-MM-DD).
 * A period that ends after today is kept as written here; generateChart charts it up to today.
 */
export function parseChartSpec(reply: unknown, today: string): ChartSpec | null {
  const parsed = chartSpecSchema(today).safeParse(reply);
  return parsed.success ? (parsed.data as ChartSpec) : null;
}

/** Every allowlisted value, as exported to contracts/prompts/chart/allowlist.json for evaluation (drift-tested). */
export function chartAllowlist(): Record<string, unknown> {
  return {
    metrics: [...CHART_METRICS],
    severities: [...CHART_SEVERITIES],
    periods: { ...CHART_PERIODS },
    calendarPeriods: { forms: ['month', 'day', 'from-to'], maxRangeDays: CALENDAR_MAX_DAYS },
    incidentTypes: [...INCIDENT_TYPES],
    dimensions: CHART_DIMENSIONS,
  };
}

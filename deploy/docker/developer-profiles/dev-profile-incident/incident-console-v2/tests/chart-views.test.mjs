// SPDX-License-Identifier: Apache-2.0

// Chart views: the three views drawn in their own kind (a dual-axis combo, a stacked bar by severity and a bubble chart).
// Covers the spec that asks for them, the figures they count (evidence per report is rounded in code and a type with no
// reports is left out), the kind each is drawn in whatever the picker says, the configuration checks, the agent payloads,
// and "not available yet" until the database change that returns their figures is applied.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { CHART_DIMENSIONS, CHART_METRICS, parseChartSpec } = await import('../src/modules/dashboard/domain/chart-spec.ts');
const { drawnKind, kindFitsDimension } = await import('../src/modules/dashboard/domain/chart-kinds.ts');
const { bubbleTooltipText, chartJsOptions, configMatchesChart, isChartJsConfig } = await import(
  '../src/modules/dashboard/domain/chart-config.ts'
);
const { sliceColors, severityLevelColor } = await import('../src/modules/dashboard/domain/chart-palette.ts');
const { evidencePerReport, generateChart, viewRows } = await import('../src/modules/dashboard/application/generate-chart/index.ts');
const { AgentChartRenderer } = await import('../src/modules/dashboard/infrastructure/agent/chart-renderer.ts');
const { ChartRenderError } = await import('../src/modules/dashboard/domain/ChartRenderer.ts');
const { dashboardFromRpc } = await import('../src/modules/dashboard/infrastructure/supabase/mappers/dashboard.ts');
const { severityChartColor } = await import('../src/lib/ui/severity.ts');
const { chartSummary } = await import('../src/modules/dashboard/domain/chart-summary.ts');

const NOW = new Date('2026-10-31T12:00:00.000Z');
const TODAY = '2026-10-31';
const rpc = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));
const analytics = dashboardFromRpc(rpc);
const VIEWS = ['incident_type_evidence', 'incident_type_severity', 'severity_evidence'];

const spec = (overrides = {}) => ({
  metric: 'incidents',
  dimension: 'incident_type',
  period: 'all_time',
  incidentType: null,
  severity: null,
  ...overrides,
});
const viewSpec = (dimension) => spec({ dimension, metric: CHART_DIMENSIONS[dimension].metric });
const dashboardWith = (overrides = {}) => ({ getDashboard: async () => ({ ...analytics, ...overrides }) });

/** A chart service that returns `configured` (null: none) and records what it was asked to draw. */
function recorder(configured = null) {
  const configures = [];
  const draws = [];
  return {
    configures,
    draws,
    async configure(drawing) {
      configures.push(drawing);
      return typeof configured === 'function' ? configured(drawing) : configured;
    },
    async draw(drawing) {
      draws.push(drawing);
      return 'data:image/png;base64,aW1hZ2U=';
    },
  };
}

/** The configuration a correct agent returns for the combo view: our labels and figures in Chart.js's shape. */
function faithfulCombo(drawing) {
  return {
    type: 'bar',
    data: {
      labels: drawing.rows.map((row) => row.category),
      datasets: drawing.series.map((series, index) => ({
        label: series.label,
        data: drawing.rows.map((row) => row.values[series.key] ?? 0),
        type: index === 0 ? undefined : 'line',
        yAxisID: index === 0 ? 'y' : 'y1',
      })),
    },
    options: { scales: { y1: { title: { text: drawing.secondValueLabel } } } },
  };
}

/** The configuration a correct agent returns for the severity stack: our figures, low first so high is drawn on top. */
function faithfulSeverityStack(drawing) {
  return {
    type: 'bar',
    data: {
      labels: drawing.rows.map((row) => row.category),
      datasets: [...drawing.series]
        .reverse()
        .map((series) => ({ label: series.label, data: drawing.rows.map((row) => row.values[series.key] ?? 0) })),
    },
    options: { plugins: { legend: { reverse: true } } },
  };
}

/** The configuration a correct agent returns for the bubble view: label, x, y and count as ours, and a radius it scaled itself. */
function faithfulBubble(drawing) {
  return {
    type: 'bubble',
    data: {
      datasets: [
        {
          label: drawing.series[0].label,
          data: drawing.rows.map((row) => ({
            x: row.values.severity,
            y: row.values.evidence,
            r: 9,
            count: row.values.reports,
            label: row.category,
          })),
        },
      ],
    },
    options: {},
  };
}

describe('the spec asks for a view with its own metric', () => {
  test('the three views are allowlisted, each with its metric and the kind it is drawn in', () => {
    const views = Object.keys(CHART_DIMENSIONS).filter((name) => CHART_DIMENSIONS[name].viewKind !== null);
    assert.deepEqual(views.sort(), [...VIEWS].sort());
    assert.equal(CHART_DIMENSIONS.incident_type_evidence.metric, 'evidence_per_report');
    assert.equal(CHART_DIMENSIONS.incident_type_evidence.viewKind, 'combo_dual_axis');
    assert.equal(CHART_DIMENSIONS.incident_type_severity.viewKind, 'stacked_by_severity');
    assert.equal(CHART_DIMENSIONS.severity_evidence.metric, 'evidence_items');
    assert.equal(CHART_DIMENSIONS.severity_evidence.viewKind, 'bubble');
    assert.ok(CHART_METRICS.includes('evidence_per_report') && CHART_METRICS.includes('evidence_items'));
  });

  test('a view is parsed only with its own metric', () => {
    for (const dimension of VIEWS) {
      assert.notEqual(parseChartSpec(viewSpec(dimension), TODAY), null, dimension);
      const wrongMetric = CHART_DIMENSIONS[dimension].metric === 'incidents' ? 'instruments' : 'incidents';
      assert.equal(parseChartSpec(spec({ dimension, metric: wrongMetric }), TODAY), null, `${dimension} with ${wrongMetric}`);
    }
  });

  test('an invented view name, or a view metric on an ordinary dimension, is refused', () => {
    assert.equal(parseChartSpec(spec({ dimension: 'bubble' }), TODAY), null);
    assert.equal(parseChartSpec(spec({ dimension: 'incident_type', metric: 'evidence_items' }), TODAY), null);
    assert.equal(parseChartSpec(spec({ dimension: 'severity_evidence', metric: 'evidence_items', extra: 1 }), TODAY), null);
  });
});

describe('the kind each view is drawn in', () => {
  test('a view is drawn in its own kind, whatever the picker says', () => {
    for (const picked of ['bar', 'stacked_bar', 'donut', 'line', 'area']) {
      assert.equal(drawnKind(picked, 'incident_type_evidence'), 'combo_dual_axis', picked);
      assert.equal(drawnKind(picked, 'incident_type_severity'), 'stacked_by_severity', picked);
      assert.equal(drawnKind(picked, 'severity_evidence'), 'bubble', picked);
      assert.ok(kindFitsDimension(picked, 'severity_evidence'), `${picked} is not refused for a view`);
    }
  });

  test('an ordinary dimension keeps the picker, and a kind that does not suit it is still refused', () => {
    assert.equal(drawnKind('donut', 'incident_type'), 'donut');
    assert.equal(kindFitsDimension('donut', 'report_day'), false);
    assert.equal(kindFitsDimension('line', 'incident_type'), false);
  });
});

describe('the figures a view counts', () => {
  test('evidence per report is the items over the reports, to two decimals, and null with no reports', () => {
    assert.equal(evidencePerReport(3, 2), 1.5);
    assert.equal(evidencePerReport(1, 3), 0.33);
    assert.equal(evidencePerReport(2, 3), 0.67);
    assert.equal(evidencePerReport(7, 3), 2.33);
    assert.equal(evidencePerReport(0, 4), 0);
    assert.equal(evidencePerReport(5, 0), null, 'a type with no reports has no per-report figure');
  });

  test('the evidence per report bars and line come from the per-type evidence of the dashboard', () => {
    assert.deepEqual(viewRows('incident_type_evidence', analytics), [
      { category: 'Assault', values: { reports: 2, per_report: 1.5 } },
      { category: 'Road accident', values: { reports: 1, per_report: 3 } },
    ]);
  });

  test('a type with no reports is left out of the evidence per report chart, never drawn as 0', () => {
    const empty = { ...analytics, types: [{ ...analytics.types[0], count: 0, evidence: 4 }] };
    assert.deepEqual(viewRows('incident_type_evidence', empty), []);
  });

  test('a dashboard without the per-type evidence answers not available, never a zero', () => {
    const older = { ...analytics, types: analytics.types.map((type) => ({ ...type, evidence: null })) };
    assert.equal(viewRows('incident_type_evidence', older), null);
  });

  test('severity within each incident type is the three bands of each type', () => {
    assert.deepEqual(viewRows('incident_type_severity', analytics), [
      { category: 'Assault', values: { high: 2, medium: 0, low: 0 } },
      { category: 'Road accident', values: { high: 0, medium: 0, low: 1 } },
    ]);
  });

  test('severity against evidence is one row per level and item count, sized by reports', () => {
    const rows = viewRows('severity_evidence', analytics);
    assert.deepEqual(
      rows.map((row) => row.category),
      ['Severity 2, 3 evidence items', 'Severity 4, 1 evidence item', 'Severity 5, 2 evidence items'],
    );
    assert.deepEqual(rows[1].values, { reports: 1, severity: 4, evidence: 1 });
  });

  test('severity against evidence is not available until the severity pairs are returned', () => {
    assert.equal(viewRows('severity_evidence', { ...analytics, severityEvidence: null }), null);
  });
});

describe('generateChart draws each view in its own kind, or says it is not available', () => {
  test('the evidence per report view is a dual-axis combo with its right-hand axis titled', async () => {
    const renderer = recorder(faithfulCombo);
    const answer = await generateChart(
      { interpreter: { interpret: async () => viewSpec('incident_type_evidence') }, dashboard: dashboardWith(), renderer },
      { request: 'evidence per report by incident type', chartType: 'donut', timezone: 'UTC', now: NOW },
    );
    assert.equal(answer.kind, 'chart');
    const { chart } = answer;
    assert.equal(chart.chartKind, 'combo_dual_axis', 'the picker (donut) does not apply to a view');
    assert.deepEqual(
      chart.series.map((series) => series.key),
      ['reports', 'per_report'],
    );
    assert.equal(chart.valueLabel, 'Reports');
    assert.equal(chart.secondValueLabel, 'Evidence items per report');
    assert.ok(chart.config && isChartJsConfig(chart.config));
    assert.equal(renderer.configures.length, 1);
    assert.equal(renderer.configures[0].secondValueLabel, 'Evidence items per report');
  });

  test('severity within each type is a stacked bar in the severity colours, whatever the picker', async () => {
    const renderer = recorder(faithfulSeverityStack);
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => viewSpec('incident_type_severity') }, dashboard: dashboardWith(), renderer },
      { request: 'severity by incident type', chartType: 'line', timezone: 'UTC', now: NOW },
    );
    assert.equal(chart.chartKind, 'stacked_by_severity');
    assert.deepEqual(
      chart.series.map(({ key, label, color }) => ({ key, label, color })),
      [
        { key: 'high', label: 'High', color: severityChartColor.high },
        { key: 'medium', label: 'Medium', color: severityChartColor.medium },
        { key: 'low', label: 'Low', color: severityChartColor.low },
      ],
    );
    assert.equal(renderer.configures[0].sliceColors, null, 'only a donut or a bubble has per-row colours');
  });

  test('severity against evidence is a bubble, each bubble coloured by its severity band', async () => {
    const renderer = recorder(faithfulBubble);
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => viewSpec('severity_evidence') }, dashboard: dashboardWith(), renderer },
      { request: 'do more severe incidents have more evidence', chartType: 'bar', timezone: 'UTC', now: NOW },
    );
    assert.equal(chart.chartKind, 'bubble');
    assert.equal(chart.categoryLabel, 'Severity level');
    assert.equal(chart.valueLabel, 'Evidence items');
    assert.deepEqual(renderer.configures[0].sliceColors, [severityLevelColor(2), severityLevelColor(4), severityLevelColor(5)]);
    assert.equal(severityLevelColor(2), severityChartColor.low);
    assert.equal(severityLevelColor(3), severityChartColor.medium);
    assert.equal(severityLevelColor(5), severityChartColor.high);
    assert.deepEqual(sliceColors('bubble', 'severity_evidence', chart.rows), renderer.configures[0].sliceColors);
  });

  test('a view with its figures not returned yet answers not available, and draws nothing', async () => {
    for (const [dimension, missing] of [
      ['incident_type_evidence', { types: analytics.types.map((type) => ({ ...type, evidence: null })) }],
      ['incident_type_severity', {}],
      ['severity_evidence', { severityEvidence: null }],
    ]) {
      const renderer = recorder(dimension === 'incident_type_severity' ? faithfulSeverityStack : faithfulCombo);
      const answer = await generateChart(
        { interpreter: { interpret: async () => viewSpec(dimension) }, dashboard: dashboardWith(missing), renderer },
        { request: 'a view', chartType: 'bar', timezone: 'UTC', now: NOW },
      );
      if (dimension === 'incident_type_severity') {
        assert.equal(answer.kind, 'chart', 'the severity bands are in the dashboard today');
        continue;
      }
      assert.deepEqual(answer, { kind: 'not_available' }, dimension);
      assert.equal(renderer.configures.length + renderer.draws.length, 0, `${dimension} draws nothing`);
    }
  });

  test('an ordinary chart that does not suit its kind is still refused as needs_bar', async () => {
    const answer = await generateChart(
      { interpreter: { interpret: async () => spec({ dimension: 'report_day' }) }, dashboard: dashboardWith(), renderer: recorder() },
      { request: 'x', chartType: 'donut', timezone: 'UTC', now: NOW },
    );
    assert.deepEqual(answer, { kind: 'needs_bar' });
  });

  test('an unreadable reply is unsupported for a view too', async () => {
    const answer = await generateChart(
      { interpreter: { interpret: async () => ({ unsupported: true }) }, dashboard: dashboardWith(), renderer: recorder() },
      { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
    );
    assert.deepEqual(answer, { kind: 'unsupported' });
  });
});

describe('what a view says about its totals', () => {
  test('the dual-axis summary totals the reports and does not add up per-report averages', async () => {
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => viewSpec('incident_type_evidence') }, dashboard: dashboardWith(), renderer: recorder() },
      { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
    );
    assert.equal(chartSummary(chart), 'Evidence per report by incident type, All time. Reports 3.');
  });
});

describe('the configuration of each view is checked against our rows', () => {
  const comboChart = async () =>
    (
      await generateChart(
        { interpreter: { interpret: async () => viewSpec('incident_type_evidence') }, dashboard: dashboardWith(), renderer: recorder() },
        { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
      )
    ).chart;

  test('a combo configuration with the rows exact figures matches; a moved line figure does not', async () => {
    const chart = await comboChart();
    const good = faithfulCombo({ ...chart, sliceColors: null });
    assert.ok(isChartJsConfig(good));
    assert.ok(configMatchesChart(good, chart));
    const moved = structuredClone(good);
    moved.data.datasets[1].data[0] = 1.6;
    assert.equal(configMatchesChart(moved, chart), false, 'a rounded or changed evidence per report is refused');
  });

  test('a severity stack is drawn low first, so high is on top; a stack in legend order is refused', async () => {
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => viewSpec('incident_type_severity') }, dashboard: dashboardWith(), renderer: recorder() },
      { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
    );
    const good = faithfulSeverityStack(chart);
    assert.deepEqual(
      good.data.datasets.map((dataset) => dataset.label),
      ['Low', 'Medium', 'High'],
    );
    assert.ok(configMatchesChart(good, chart));
    const legendOrder = structuredClone(good);
    legendOrder.data.datasets.reverse();
    assert.equal(configMatchesChart(legendOrder, chart), false, 'high would be drawn at the bottom');
  });

  test('a bubble tooltip shows its label and report count, never the radius', async () => {
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => viewSpec('severity_evidence') }, dashboard: dashboardWith(), renderer: recorder() },
      { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
    );
    const config = faithfulBubble(chart);
    const label = chartJsOptions(config).plugins.tooltip.callbacks.label;
    config.data.datasets[0].data.forEach((point, index) => {
      const row = chart.rows[index];
      const count = row.values.reports;
      const text = label({ raw: point });
      assert.equal(text, `${row.category}: ${count} ${count === 1 ? 'report' : 'reports'}`);
      assert.ok(!text.includes(String(point.r)), 'the radius is not a figure');
    });
    const point = { x: 3, y: 2, r: 17.856406460551018, count: 5, label: 'Severity 3, 2 evidence items' };
    assert.equal(bubbleTooltipText(point), 'Severity 3, 2 evidence items: 5 reports');
    assert.equal(bubbleTooltipText({ ...point, count: 1 }), 'Severity 3, 2 evidence items: 1 report');
    const bar = faithfulCombo({ ...chart, sliceColors: null });
    assert.equal(chartJsOptions(bar), bar.options, 'only a bubble gets its own tooltip');
  });

  test('a bubble configuration needs label, x, y and count as ours and a radius; a changed figure or a missing radius is refused', async () => {
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => viewSpec('severity_evidence') }, dashboard: dashboardWith(), renderer: recorder() },
      { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
    );
    const good = faithfulBubble(chart);
    assert.ok(isChartJsConfig(good), 'a bubble has no labels and is still a configuration');
    assert.ok(configMatchesChart(good, chart));
    const moved = structuredClone(good);
    moved.data.datasets[0].data[1].x = 3;
    assert.equal(configMatchesChart(moved, chart), false, 'a moved severity level');
    const recounted = structuredClone(good);
    recounted.data.datasets[0].data[0].count += 1;
    assert.equal(configMatchesChart(recounted, chart), false, 'a changed report count');
    const radiusless = structuredClone(good);
    delete radiusless.data.datasets[0].data[0].r;
    assert.equal(configMatchesChart(radiusless, chart), false, 'no radius');
    assert.equal(
      isChartJsConfig({ type: 'bubble', options: {}, data: { datasets: [{ label: 'R', data: [{ x: '1', y: 1, r: 2 }] }] } }),
      false,
    );
  });

  test('a view whose configuration the agent moved is an error, never shown', async () => {
    const tampered = (drawing) => ({ ...faithfulBubble(drawing), data: { datasets: [{ label: 'Reports', data: [] }] } });
    await assert.rejects(
      generateChart(
        { interpreter: { interpret: async () => viewSpec('severity_evidence') }, dashboard: dashboardWith(), renderer: recorder(tampered) },
        { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
      ),
      ChartRenderError,
    );
  });
});

describe('the agent payloads for the views', () => {
  test('a combo is sent as one bar series and one line series, with the right axis title', async () => {
    const posted = [];
    globalThis.fetch = async (url, init) => {
      if (String(url).endsWith('/api/v1/incidents/charts')) {
        posted.push(JSON.parse(init.body).charts_data[0]);
        return Response.json([{ success: true, error_message: null, object_store_key: null, chart_config: { type: 'bar' } }]);
      }
      return new Response(null, { status: 204 });
    };
    try {
      await new AgentChartRenderer('http://agent.test').configure({
        chartKind: 'combo_dual_axis',
        title: 'Evidence per report by incident type',
        categoryLabel: 'Incident type',
        valueLabel: 'Reports',
        secondValueLabel: 'Evidence items per report',
        series: [
          { key: 'reports', label: 'Reports', color: '#174f3b' },
          { key: 'per_report', label: 'Evidence items per report', color: '#3e5c76' },
        ],
        rows: [{ category: 'Assault', values: { reports: 2, per_report: 1.5 } }],
        sliceColors: null,
      });
      assert.equal(posted[0].kind, 'combo_dual_axis');
      assert.equal(posted[0].y2_label, 'Evidence items per report');
      assert.deepEqual(
        posted[0].series.map((series) => series.values),
        [[2], [1.5]],
      );
      assert.equal(posted[0].slice_colors, null);
    } finally {
      delete globalThis.fetch;
    }
  });

  test('a bubble is sent as points: severity as x, evidence as y, reports as count, no labels', async () => {
    const posted = [];
    globalThis.fetch = async (url, init) => {
      if (String(url).endsWith('/api/v1/incidents/charts')) {
        posted.push(JSON.parse(init.body).charts_data[0]);
        return Response.json([{ success: true, error_message: null, object_store_key: null, chart_config: { type: 'bubble' } }]);
      }
      return new Response(null, { status: 204 });
    };
    try {
      await new AgentChartRenderer('http://agent.test').configure({
        chartKind: 'bubble',
        title: 'Severity against evidence',
        categoryLabel: 'Severity level',
        valueLabel: 'Evidence items',
        secondValueLabel: null,
        series: [{ key: 'reports', label: 'Reports', color: '#174f3b' }],
        rows: [{ category: 'Severity 4, 1 evidence item', values: { reports: 1, severity: 4, evidence: 1 } }],
        sliceColors: [severityChartColor.high],
      });
      assert.equal(posted[0].kind, 'bubble');
      assert.equal(posted[0].labels, undefined);
      assert.deepEqual(posted[0].points, [{ label: 'Severity 4, 1 evidence item', x: 4, y: 1, count: 1, color: severityChartColor.high }]);
      assert.equal(posted[0].series_label, 'Reports');
    } finally {
      delete globalThis.fetch;
    }
  });
});

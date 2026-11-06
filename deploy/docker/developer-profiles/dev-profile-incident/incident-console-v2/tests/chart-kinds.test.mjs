// SPDX-License-Identifier: Apache-2.0

// Chart kinds: which kind suits which dimension, the colours each series and slice gets, the Chart.js
// configuration the agent returns (checked against our rows), and the PNG fallback.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { CHART_DIMENSIONS } = await import('../src/modules/dashboard/domain/chart-spec.ts');
const { kindFitsDimension } = await import('../src/modules/dashboard/domain/chart-kinds.ts');
const { CHART_KINDS, normalizeChartKind } = await import('../src/modules/dashboard/domain/generated-chart.ts');
const { sliceColors, OFFICIAL_SERIES, NOT_OFFICIAL_SERIES } = await import('../src/modules/dashboard/domain/chart-palette.ts');
const { configMatchesChart, isChartJsConfig } = await import('../src/modules/dashboard/domain/chart-config.ts');
const { chartSummary } = await import('../src/modules/dashboard/domain/chart-summary.ts');
const { generateChart } = await import('../src/modules/dashboard/application/generate-chart/index.ts');
const { ChartRenderError } = await import('../src/modules/dashboard/domain/ChartRenderer.ts');
const { AgentChartRenderer } = await import('../src/modules/dashboard/infrastructure/agent/chart-renderer.ts');
const { dashboardFromRpc } = await import('../src/modules/dashboard/infrastructure/supabase/mappers/dashboard.ts');
const { CHART_COLORS } = await import('../src/lib/ui/chart-colors.ts');
const { severityChartColor } = await import('../src/lib/ui/severity.ts');

const NOW = new Date('2026-10-31T12:00:00.000Z');
const rpc = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));
const analytics = dashboardFromRpc(rpc);
const spec = (overrides = {}) => ({
  metric: 'incidents',
  dimension: 'incident_type',
  period: 'all_time',
  incidentType: null,
  severity: null,
  ...overrides,
});
const dashboard = {
  async getDashboard() {
    return analytics;
  },
};

/** A chart service that returns `configured` (null: none) and records what it was asked to draw. */
function service(configured = null) {
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

/** The configuration a correct agent would return: our labels and figures, placed in Chart.js's shape. */
function faithful(drawing) {
  return {
    type: drawing.chartKind === 'donut' ? 'doughnut' : drawing.chartKind === 'line' || drawing.chartKind === 'area' ? 'line' : 'bar',
    data: {
      labels: drawing.rows.map((row) => row.category),
      datasets: drawing.series.map((series) => ({
        label: series.label,
        data: drawing.rows.map((row) => row.values[series.key] ?? 0),
        backgroundColor: series.color,
      })),
    },
    options: { responsive: true },
  };
}

function luminance(hex) {
  const channels = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}
const contrastWithWhite = (hex) => 1.05 / (luminance(hex) + 0.05);

describe('which kinds suit which dimension', () => {
  test('bar and horizontal bar suit every dimension', () => {
    for (const dimension of Object.keys(CHART_DIMENSIONS)) {
      assert.ok(kindFitsDimension('bar', dimension), dimension);
      assert.ok(kindFitsDimension('horizontal_bar', dimension), dimension);
    }
  });

  test('a stacked bar needs a dimension split by official and not yet official', () => {
    assert.ok(kindFitsDimension('stacked_bar', 'incident_type'));
    assert.equal(kindFitsDimension('stacked_bar', 'instrument'), false, 'top instruments are one series');
    assert.equal(kindFitsDimension('stacked_bar', 'model'), false, 'analysis attempts are not reports');
  });

  test('a donut needs a true whole, the same rule as the pie', () => {
    for (const dimension of Object.keys(CHART_DIMENSIONS)) {
      assert.equal(kindFitsDimension('donut', dimension), CHART_DIMENSIONS[dimension].pie, dimension);
    }
  });

  test('a line or an area needs a time dimension', () => {
    for (const kind of ['line', 'area']) {
      assert.ok(kindFitsDimension(kind, 'report_day'));
      assert.ok(kindFitsDimension(kind, 'report_week'));
      assert.ok(kindFitsDimension(kind, 'report_month'));
      assert.equal(kindFitsDimension(kind, 'incident_type'), false);
      assert.equal(kindFitsDimension(kind, 'report_hour'), false, 'hour of day is not a trend');
    }
  });

  test('the former pie name still means a donut', () => {
    assert.equal(normalizeChartKind('pie'), 'donut');
    assert.equal(normalizeChartKind('bar'), 'bar');
    assert.deepEqual([...CHART_KINDS], ['bar', 'stacked_bar', 'horizontal_bar', 'donut', 'line', 'area']);
  });
});

describe('colours', () => {
  test('official and not yet official are the --chart-1 and --chart-3 tokens', () => {
    const css = readFileSync(join(process.cwd(), 'src', 'app', 'styles.css'), 'utf8');
    assert.ok(css.includes(`--chart-1: ${CHART_COLORS.official};`), 'official colour drifted from --chart-1');
    assert.ok(css.includes(`--chart-3: ${CHART_COLORS.notOfficial};`), 'not yet official colour drifted from --chart-3');
  });

  test('every chart colour passes the 3:1 non-text contrast rule against white', () => {
    const colours = [CHART_COLORS.official, CHART_COLORS.notOfficial, CHART_COLORS.total, ...CHART_COLORS.categorical];
    for (const colour of colours) assert.ok(contrastWithWhite(colour) >= 3, `${colour} is ${contrastWithWhite(colour).toFixed(2)}:1`);
  });

  test('the faint --chart-2 and --chart-4 colours are not used for data', () => {
    const used = [CHART_COLORS.official, CHART_COLORS.notOfficial, CHART_COLORS.total, ...CHART_COLORS.categorical];
    assert.equal(used.includes('#76b900'), false);
    assert.equal(used.includes('#f59e0b'), false);
  });

  test('a status donut shows the status colours, a severity donut the severity colours', () => {
    const status = [
      { category: 'Official', values: { count: 1 } },
      { category: 'Not official', values: { count: 2 } },
    ];
    assert.deepEqual(sliceColors('donut', 'report_status', status), [OFFICIAL_SERIES.color, NOT_OFFICIAL_SERIES.color]);
    const severity = [
      { category: 'Low', values: { count: 1 } },
      { category: 'Medium', values: { count: 1 } },
      { category: 'High', values: { count: 1 } },
    ];
    assert.deepEqual(sliceColors('donut', 'severity', severity), [
      severityChartColor.low,
      severityChartColor.medium,
      severityChartColor.high,
    ]);
  });
});

describe('the configuration the agent returns', () => {
  test('a configuration with the rows exact figures matches; one moved figure, label or series does not', async () => {
    const chart = (
      await generateChart(
        { interpreter: { interpret: async () => spec() }, dashboard, renderer: service() },
        { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
      )
    ).chart;
    const good = faithful({ ...chart, chartKind: 'bar', sliceColors: null });
    assert.ok(isChartJsConfig(good));
    assert.ok(configMatchesChart(good, chart));

    const moved = structuredClone(good);
    moved.data.datasets[0].data[0] += 1;
    assert.equal(configMatchesChart(moved, chart), false, 'a changed figure');
    const relabelled = structuredClone(good);
    relabelled.data.labels[0] = 'Something else';
    assert.equal(configMatchesChart(relabelled, chart), false, 'a changed label');
    const dropped = structuredClone(good);
    dropped.data.datasets = dropped.data.datasets.slice(0, 0);
    assert.equal(configMatchesChart(dropped, chart), false, 'a missing series');
  });

  test('a value that is not a number, or a missing type, is not a configuration', () => {
    assert.equal(isChartJsConfig({ type: 'bar', options: {}, data: { labels: ['a'], datasets: [{ label: 'R', data: ['1'] }] } }), false);
    assert.equal(isChartJsConfig({ type: 'pie', options: {}, data: { labels: [], datasets: [] } }), false);
    assert.equal(
      isChartJsConfig({ type: 'bar', options: {}, data: { labels: [], datasets: [{ label: 'R', data: [Number.NaN] }] } }),
      false,
    );
  });

  test('the configuration is shown with its figures, no image is drawn', async () => {
    const drawer = service(faithful);
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => spec({ dimension: 'report_month' }) }, dashboard, renderer: drawer },
      { request: 'x', chartType: 'area', timezone: 'UTC', now: NOW },
    );
    assert.ok(chart.config, 'the configuration is set');
    assert.equal(chart.image, null);
    assert.equal(drawer.draws.length, 0);
    assert.equal(drawer.configures[0].chartKind, 'area');
    assert.deepEqual(
      drawer.configures[0].series.map((s) => s.color),
      [CHART_COLORS.official, CHART_COLORS.notOfficial],
    );
  });

  test('a configuration whose figures differ from the database is refused, never shown', async () => {
    const tampered = (drawing) => {
      const config = faithful(drawing);
      config.data.datasets[0].data[0] = 9999;
      return config;
    };
    await assert.rejects(
      generateChart(
        { interpreter: { interpret: async () => spec() }, dashboard, renderer: service(tampered) },
        { request: 'x', chartType: 'bar', timezone: 'UTC', now: NOW },
      ),
      ChartRenderError,
    );
  });

  test('with no configuration back, the PNG stands in: a donut is drawn as a pie, others as bars', async () => {
    const drawer = service(null);
    const { chart } = await generateChart(
      { interpreter: { interpret: async () => spec({ dimension: 'severity' }) }, dashboard, renderer: drawer },
      { request: 'x', chartType: 'donut', timezone: 'UTC', now: NOW },
    );
    assert.equal(chart.config, null);
    assert.ok(chart.image);
    assert.equal(drawer.draws[0].chartKind, 'donut');

    const line = service(null);
    await generateChart(
      { interpreter: { interpret: async () => spec({ dimension: 'report_day' }) }, dashboard, renderer: line },
      { request: 'x', chartType: 'line', timezone: 'UTC', now: NOW },
    );
    assert.equal(line.draws[0].chartKind, 'bar', 'a line falls back to bars in the picture');
  });

  test('a kind that does not suit the dimension is refused as needs_bar before any figure is read', async () => {
    const answer = await generateChart(
      { interpreter: { interpret: async () => spec({ dimension: 'incident_type' }) }, dashboard, renderer: service() },
      { request: 'x', chartType: 'line', timezone: 'UTC', now: NOW },
    );
    assert.deepEqual(answer, { kind: 'needs_bar' });
  });
});

describe('the chart summary a screen reader gets', () => {
  test('names the title, the scope and each series total', () => {
    const summary = chartSummary({
      title: 'Reports by incident type',
      scope: ['All time'],
      series: [OFFICIAL_SERIES, NOT_OFFICIAL_SERIES],
      rows: [
        { category: 'Assault', values: { official: 2, not_official: 3 } },
        { category: 'Burglary', values: { official: 1, not_official: 0 } },
      ],
    });
    assert.equal(summary, 'Reports by incident type, All time. Official 3; Not official 3.');
  });
});

describe('the agent renderer', () => {
  const originalFetch = globalThis.fetch;
  test('sends the figures as a chartjs chart with colours, and returns the configuration it gets back', async () => {
    const calls = [];
    const config = { type: 'bar', data: { labels: ['A'], datasets: [] }, options: {} };
    globalThis.fetch = async (url, init) => {
      calls.push({ url, body: JSON.parse(init.body) });
      return Response.json([{ success: true, error_message: null, object_store_key: null, chart_config: config }]);
    };
    try {
      const drawing = {
        chartKind: 'stacked_bar',
        title: 'T',
        categoryLabel: 'Incident type',
        valueLabel: 'Reports',
        series: [OFFICIAL_SERIES, NOT_OFFICIAL_SERIES],
        rows: [{ category: 'Assault', values: { official: 2, not_official: 3 } }],
        sliceColors: null,
      };
      assert.deepEqual(await new AgentChartRenderer('http://agent.test').configure(drawing), config);
      const [chart] = calls[0].body.charts_data;
      assert.equal(chart.output, 'chartjs');
      assert.equal(chart.kind, 'stacked_bar');
      assert.deepEqual(chart.labels, ['Assault']);
      assert.deepEqual(chart.series, [
        { label: 'Official', values: [2], color: CHART_COLORS.official },
        { label: 'Not official', values: [3], color: CHART_COLORS.notOfficial },
      ]);
      assert.equal(chart.slice_colors, null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  for (const status of [404, 422, 501]) {
    test(`an agent that answers ${status} for the chartjs item gets the picture, not an error`, async () => {
      const posted = [];
      globalThis.fetch = async (url, init) => {
        const path = String(url).replace('http://agent.test', '');
        if (path === '/api/v1/incidents/charts') {
          const [item] = JSON.parse(init.body).charts_data;
          posted.push(item);
          if (item.output === 'chartjs') return Response.json({ detail: 'Extra inputs are not permitted' }, { status });
          return Response.json([{ success: true, error_message: null, object_store_key: 'dashboard-charts/old_0.png' }]);
        }
        if (init?.method === 'GET') return new Response(Buffer.from('image'));
        return new Response(null, { status: 204 });
      };
      try {
        const answer = await generateChart(
          {
            interpreter: { interpret: async () => spec({ dimension: 'severity' }) },
            dashboard,
            renderer: new AgentChartRenderer('http://agent.test'),
          },
          { request: 'severity breakdown', chartType: 'bar', timezone: 'UTC', now: NOW },
        );
        assert.equal(answer.kind, 'chart');
        assert.equal(answer.chart.config, null);
        assert.equal(answer.chart.image, 'data:image/png;base64,aW1hZ2U=');
        assert.deepEqual(
          posted.map((item) => item.output ?? item.chart_file_format),
          ['chartjs', 'png'],
        );
        assert.deepEqual(posted[1].x_categories, ['Low', 'Medium', 'High']);
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  }

  test('a failing or unreachable agent is still an error, not the picture', async () => {
    const drawing = {
      chartKind: 'bar',
      title: 'T',
      categoryLabel: 'c',
      valueLabel: 'v',
      series: [OFFICIAL_SERIES],
      rows: [{ category: 'A', values: { official: 1 } }],
      sliceColors: null,
    };
    try {
      for (const status of [500, 502, 503]) {
        globalThis.fetch = async () => new Response('boom', { status });
        await assert.rejects(() => new AgentChartRenderer('http://agent.test').configure(drawing), ChartRenderError);
      }
      globalThis.fetch = async () => {
        throw new DOMException('The operation was aborted due to timeout', 'TimeoutError');
      };
      await assert.rejects(() => new AgentChartRenderer('http://agent.test').configure(drawing), ChartRenderError);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('a reply with no configuration is null, so the caller falls back to the picture', async () => {
    globalThis.fetch = async () => Response.json([{ success: true, error_message: null, object_store_key: 'k' }]);
    try {
      const drawing = {
        chartKind: 'bar',
        title: 'T',
        categoryLabel: 'c',
        valueLabel: 'v',
        series: [OFFICIAL_SERIES],
        rows: [{ category: 'A', values: { official: 1 } }],
        sliceColors: null,
      };
      assert.equal(await new AgentChartRenderer('http://agent.test').configure(drawing), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

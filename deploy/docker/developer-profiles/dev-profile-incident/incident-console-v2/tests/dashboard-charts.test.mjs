// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import {
  assetRows,
  customWindow,
  dashboardView,
  delta,
  entityTypeRows,
  evidenceRows,
  formatCalendarDay,
  formatDay,
  instrumentRows,
  severityRows,
  TOP_INSTRUMENT_ROWS,
  typeRows,
  unratedReports,
} from '../src/modules/dashboard/domain/charts.ts';
import { severityChartColor } from '../src/lib/ui/severity.ts';

const analytics = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));

test('no figures are shown until analytics exist, and a failed first load is an error', () => {
  assert.equal(dashboardView(null, ''), 'loading');
  assert.equal(dashboardView(null, 'boom'), 'failed');
  assert.equal(dashboardView(analytics, ''), 'ready');
  assert.equal(dashboardView(analytics, 'boom'), 'ready', 'a failed refresh keeps the last figures under the error');
});

test('every chart row adds up: official plus not yet official is the total', () => {
  for (const rows of [severityRows(analytics), typeRows(analytics), assetRows(analytics)]) {
    for (const row of rows) assert.equal(row.official + row.notOfficial, row.total, row.label);
  }
  assert.equal(analytics.official + analytics.notOfficial, analytics.total);
  assert.deepEqual(
    severityRows(analytics).map((row) => row.key),
    ['high', 'medium', 'low'],
  );
});

test('reports with no severity are counted apart from the severity bands', () => {
  const withBands = (total, high, medium, low) => ({ ...analytics, total, severity: { high, medium, low } });
  assert.equal(unratedReports(withBands(6, 3, 2, 1)), 0);
  assert.equal(unratedReports(withBands(8, 3, 2, 1)), 2);
  assert.equal(unratedReports(withBands(3, 0, 0, 0)), 3);
  assert.equal(unratedReports(withBands(0, 0, 0, 0)), 0);
});

test('a period comparison and a trend day read as written', () => {
  assert.equal(delta(5, undefined), null);
  assert.equal(delta(5, 0), 100);
  assert.equal(delta(0, 0), 0);
  assert.equal(delta(3, 2), 50);
  assert.equal(formatDay('2026-10-28'), 'Oct 28');
  assert.equal(formatDay('2026-01-01'), 'Jan 1', 'never shifted by a time zone');
});

test('each day of the trend adds up, and the severity donut colours are readable against white', () => {
  for (const point of analytics.trend) assert.equal(point.official + point.notOfficial, point.count, point.date);
  for (const color of Object.values(severityChartColor)) {
    assert.ok(contrastWithWhite(color) >= 4.5, `${color} needs 4.5:1 against white`);
  }
});

/** WCAG 2.x contrast ratio of a #rrggbb colour against white. */
function contrastWithWhite(hex) {
  const channel = (i) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
  return 1.05 / (luminance + 0.05);
}

test('evidence, entity and instrument rows keep the RPC order and add up to their totals', () => {
  const evidence = evidenceRows(analytics);
  assert.deepEqual(
    evidence.map((row) => row.label),
    ['Entities', 'Instruments', 'Assets'],
  );
  for (const row of [...evidence, ...entityTypeRows(analytics), ...instrumentRows(analytics)]) {
    assert.equal(row.official + row.notOfficial, row.total, row.label);
  }
  assert.deepEqual(entityTypeRows(analytics)[0], { key: 'human', label: 'human', total: 3, official: 1, notOfficial: 2 });
  const many = {
    ...analytics,
    topInstruments: Array.from({ length: 8 }, (_, i) => ({ label: `i${i}`, count: 1, official: 0, notOfficial: 1 })),
  };
  assert.equal(instrumentRows(many).length, TOP_INSTRUMENT_ROWS, 'the panel shows the top rows only');
});

test('a calendar range is a zoneless UTC window from the first day to the day after the last', () => {
  const day = customWindow({ from: new Date(2026, 9, 1), to: new Date(2026, 9, 8) });
  assert.match(day.after, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$/, 'zoneless, like every stored timestamp');
  assert.equal(day.after, new Date(2026, 9, 1).toISOString().replace('Z', ''));
  assert.equal(day.before, new Date(2026, 9, 9).toISOString().replace('Z', ''), 'the last day is included');
  const single = customWindow({ from: new Date(2026, 9, 5) });
  assert.equal(single.before, new Date(2026, 9, 6).toISOString().replace('Z', ''), 'one picked day is a one-day range');
  assert.equal(formatCalendarDay(new Date(2026, 9, 28)), 'Oct 28, 2026');
});

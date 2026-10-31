// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { assetRows, dashboardView, delta, formatDay, severityRows, typeRows } from '../src/modules/dashboard/domain/charts.ts';
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

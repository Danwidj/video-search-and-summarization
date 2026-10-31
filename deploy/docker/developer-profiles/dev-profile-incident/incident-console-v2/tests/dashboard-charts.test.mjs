// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { assetRows, dashboardView, delta, formatDay, severityRows, typeRows } from '../src/modules/dashboard/domain/charts.ts';

const analytics = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));
const source = () => readFileSync(new URL('../src/sections/dashboard/components/Dashboard/Dashboard.tsx', import.meta.url), 'utf8');

test('no figures are shown until analytics exist, and a failed first load is an error', () => {
  assert.equal(dashboardView(null, ''), 'loading');
  assert.equal(dashboardView(null, 'boom'), 'failed');
  assert.equal(dashboardView(analytics, ''), 'ready');
  assert.equal(dashboardView(analytics, 'boom'), 'ready', 'a failed refresh keeps the last figures under the error');
  assert.match(source(), /useState<DashboardAnalytics \| null>\(null\)/);
  assert.doesNotMatch(source(), /const EMPTY: DashboardAnalytics/, 'no zero-filled placeholder to render');
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

test('the page shows the six fixed displays and says only what is true of its links', () => {
  const titles = [...source().matchAll(/(?<![a-z])title="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(titles, [
    'Total reports',
    'Incidents over time',
    'Incidents by type',
    'Severity breakdown',
    'Top targeted assets',
    'Activity by day and hour',
  ]);
  assert.doesNotMatch(source(), /Every number opens/);
  assert.doesNotMatch(source(), /#[0-9a-f]{6}/i, 'theme tokens, not raw colours');
});

test('a period comparison and a trend day read as written', () => {
  assert.equal(delta(5, undefined), null);
  assert.equal(delta(5, 0), 100);
  assert.equal(delta(0, 0), 0);
  assert.equal(delta(3, 2), 50);
  assert.equal(formatDay('2026-10-28'), 'Oct 28');
  assert.equal(formatDay('2026-01-01'), 'Jan 1', 'never shifted by a time zone');
});

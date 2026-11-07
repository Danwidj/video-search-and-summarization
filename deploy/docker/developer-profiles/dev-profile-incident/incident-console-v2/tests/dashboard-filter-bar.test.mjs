// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';
import { filterChips, heatmapSeries, presetWindow } from '../src/modules/dashboard/domain/filter-bar.ts';

const NONE = { type: '', severity: '', day: '', hour: '' };
const base = { days: '30', customLabel: '', scope: 'all', filters: NONE, timeZone: 'Asia/Singapore' };

test('the default period and status are not filters, so no chip shows', () => {
  assert.deepEqual(filterChips(base), []);
});

test('each active filter is one removable chip, keyed for its clear action', () => {
  const chips = filterChips({
    days: 'custom',
    customLabel: 'Oct 1, 2026 – Oct 7, 2026',
    scope: 'not_official',
    filters: { type: 'burglary', severity: 'high', day: '2', hour: '9' },
    timeZone: 'Asia/Singapore',
  });
  assert.deepEqual(
    chips.map((chip) => [chip.key, chip.value]),
    [
      ['period', 'Oct 1, 2026 – Oct 7, 2026'],
      ['scope', 'Not yet official'],
      ['type', 'burglary'],
      ['severity', 'high'],
      ['cell', 'Tue 09:00 Asia/Singapore'],
    ],
  );
  assert.equal(filterChips({ ...base, days: '90' })[0].value, 'Last 90 days');
});

test('a preset window ends now and starts that many days earlier; all time has no window', () => {
  const now = new Date('2026-11-07T00:00:00.000Z');
  assert.deepEqual(presetWindow('90', now), { after: '2026-08-09T00:00:00.000', before: '2026-11-07T00:00:00.000' });
  assert.equal(presetWindow('all', now), null);
});

test('the heatmap follows the Status filter', () => {
  assert.equal(heatmapSeries('all'), 'count');
  assert.equal(heatmapSeries('official'), 'official');
  assert.equal(heatmapSeries('not_official'), 'notOfficial');
});

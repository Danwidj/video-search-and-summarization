// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { EMPTY_FILTERS, activeFilters, filterParams, parseFilters, presetAfter } from '../lib/library/filters.ts';

test('a dashboard link round-trips through the filters', () => {
  const query = new URLSearchParams('scope=official&after=2026-09-01T00:00:00&before=2026-09-30T00:00:00&day=2&entityType=vehicle&instrument=Knife&match=exact&fromTime=09:00&toTime=09:59:59.999');
  const filters = parseFilters(query);
  assert.equal(filters.official, true);
  assert.equal(filters.exact, true);
  assert.deepEqual(Object.fromEntries(filterParams(filters)), Object.fromEntries(query));
});

test('defaults are left out of the query and "all" means no filter', () => {
  assert.equal(String(filterParams(EMPTY_FILTERS)), '');
  assert.deepEqual(parseFilters(new URLSearchParams('type=all&severity=all&kind=all&page=0&sort=sideways')), EMPTY_FILTERS);
  assert.equal(String(filterParams({ ...EMPTY_FILTERS, sort: 'oldest', page: 3 })), 'sort=oldest&page=3');
});

test('every active filter is one removable chip that clears only itself', () => {
  const filters = { ...EMPTY_FILTERS, search: ' blade ', type: 'assault', official: true, severity: 'high', after: '2026-09-01T00:00:00' };
  const chips = activeFilters(filters);
  assert.deepEqual(chips.map((chip) => chip.key), ['search', 'type', 'official', 'severity', 'date']);
  assert.deepEqual({ ...filters, ...chips[2].clear }.official, false);
  assert.equal(activeFilters({ ...filters, ...chips.reduce((all, chip) => ({ ...all, ...chip.clear }), {}) }).length, 0);
});

test('date presets count back from local midnight', () => {
  const now = new Date(2026, 9, 23, 15, 30);
  assert.equal(presetAfter('any', now), '');
  assert.equal(presetAfter('today', now), '2026-10-23T00:00:00');
  assert.equal(presetAfter('7d', now), '2026-10-17T00:00:00');
  assert.equal(presetAfter('30d', now), '2026-09-24T00:00:00');
});

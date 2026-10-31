// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';
import { EMPTY_FILTERS, FILTER_KEYS, parseFilters } from '../src/lib/library/filters.ts';
import { href } from '../src/modules/dashboard/domain/links.ts';

test('each half of the official split opens its own library list', () => {
  assert.equal(new URL(href({ scope: 'official' }, null), 'http://localhost').searchParams.get('scope'), 'official');
  assert.equal(new URL(href({ scope: 'not_official' }, null), 'http://localhost').searchParams.get('scope'), 'not_official');
  assert.equal(new URL(href({}, null), 'http://localhost').searchParams.get('scope'), 'all', 'always a URL filter, never remembered state');
});

test('dashboard numbers link to the library page with every report and exact filters (URL is the state)', () => {
  const link = new URL(
    href(
      { entityType: 'vehicle', instrument: 'Knife', day: '2', hour: '9' },
      { after: '2026-09-01T00:00:00', before: '2026-09-30T00:00:00' },
    ),
    'http://localhost',
  );
  assert.equal(link.pathname, '/library');
  assert.deepEqual(Object.fromEntries(link.searchParams), {
    scope: 'all',
    after: '2026-09-01T00:00:00',
    before: '2026-09-30T00:00:00',
    day: '2',
    entityType: 'vehicle',
    instrument: 'Knife',
    match: 'exact',
    fromTime: '09:00',
    toTime: '09:59:59.999',
  });
  assert.equal(
    new URL(href({}, null), 'http://localhost').searchParams.has('timezone'),
    false,
    'the library page uses the viewer zone, not a link parameter',
  );
  const arrival = href(
    { type: 'Theft', severity: 'high', kind: 'human', asset: 'Warehouse', scope: 'not_official' },
    { after: '2026-09-01T00:00:00', before: '2026-09-30T00:00:00' },
  );
  const query = new URL(arrival, 'http://localhost').searchParams;
  assert.deepEqual(parseFilters(query), {
    ...EMPTY_FILTERS,
    type: 'Theft',
    severity: 'high',
    kind: 'human',
    asset: 'Warehouse',
    scope: 'not_official',
    exact: true,
    after: '2026-09-01T00:00:00',
    before: '2026-09-30T00:00:00',
  });
  assert.deepEqual(parseFilters(link.searchParams), {
    ...EMPTY_FILTERS,
    entityType: 'vehicle',
    instrument: 'Knife',
    exact: true,
    day: '2',
    fromTime: '09:00',
    toTime: '09:59:59.999',
    after: '2026-09-01T00:00:00',
    before: '2026-09-30T00:00:00',
  });
  assert.deepEqual(parseFilters(new URL(href({}, null), 'http://localhost').searchParams), EMPTY_FILTERS, 'scope=all is every report');
  for (const url of [link, new URL(arrival, 'http://localhost')]) {
    for (const key of url.searchParams.keys()) assert.ok(FILTER_KEYS.includes(key), `${key} is applied on arrival`);
  }
  for (const key of ['scope', 'entityType', 'match', 'type', 'instrument', 'asset', 'after', 'before']) {
    assert.ok(FILTER_KEYS.includes(key), key);
  }
});

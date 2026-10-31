// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { href } from '../src/modules/dashboard/domain/links.ts';

const components = new URL('../src/sections/', import.meta.url);

test('each half of the official split opens its own library list', () => {
  assert.equal(new URL(href({ scope: 'official' }, null), 'http://localhost').searchParams.get('scope'), 'official');
  assert.equal(new URL(href({ scope: 'not_official' }, null), 'http://localhost').searchParams.get('scope'), 'not_official');
  assert.equal(new URL(href({}, null), 'http://localhost').searchParams.get('scope'), 'all', 'always a URL filter, never remembered state');
});

test('dashboard numbers link to the library page with every report and exact filters (URL is the state)', async () => {
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
  const dashboard = await readFile(new URL('dashboard/components/Dashboard/Dashboard.tsx', components), 'utf8');
  assert.doesNotMatch(dashboard, /clearFilters|dashboard: '1'/, 'no hidden dashboard-only filter markers');
  assert.doesNotMatch(dashboard, /href="\/videos/, 'dashboard does not link to the removed videos tab');
  const filters = await readFile(new URL('../src/lib/library/filters.ts', import.meta.url), 'utf8');
  for (const key of ['scope', 'entityType', 'match', 'type', 'instrument', 'asset', 'after', 'before']) {
    assert.match(filters, new RegExp(`FILTER_KEYS = \\[[^\\]]*'${key}'`), key);
  }
  const library = await readFile(new URL('library/components/LibraryScreen/LibraryScreen.tsx', components), 'utf8');
  assert.match(
    library,
    /if \(FILTER_KEYS\.some\(\(key\) => query\.has\(key\)\)\)/,
    'URL filters are applied alone, never mixed with remembered state',
  );
  assert.match(await readFile(new URL('library/components/IncidentCard/IncidentCard.tsx', components), 'utf8'), /library-official-marker/);
});

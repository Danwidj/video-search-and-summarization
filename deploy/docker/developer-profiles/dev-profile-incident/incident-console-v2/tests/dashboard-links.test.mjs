// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { href } from '../src/lib/dashboard/links.ts';

const components = new URL('../src/components/', import.meta.url);

test('dashboard numbers link to the library page with official scope and exact filters (URL is the state)', async () => {
  const link = new URL(href({ entityType: 'vehicle', instrument: 'Knife', day: '2', hour: '9' }, { after: '2026-09-01T00:00:00', before: '2026-09-30T00:00:00' }), 'http://localhost');
  assert.equal(link.pathname, '/library');
  assert.deepEqual(Object.fromEntries(link.searchParams), { scope: 'official', after: '2026-09-01T00:00:00', before: '2026-09-30T00:00:00', day: '2', entityType: 'vehicle', instrument: 'Knife', match: 'exact', fromTime: '09:00', toTime: '09:59:59.999' });
  assert.equal(new URL(href({}, null), 'http://localhost').searchParams.has('timezone'), false, 'the library page uses the viewer zone, not a link parameter');
  const dashboard = await readFile(new URL('dashboard.tsx', components), 'utf8');
  assert.doesNotMatch(dashboard, /clearFilters|dashboard: '1'/, 'no hidden dashboard-only filter markers');
  assert.match(dashboard, /href="\/videos\?filter=awaiting-selection"/);
  assert.match(dashboard, /href="\/videos\?filter=without-report"/);
  const filters = await readFile(new URL('../src/lib/library/filters.ts', import.meta.url), 'utf8');
  for (const key of ['scope', 'entityType', 'match', 'type', 'instrument', 'asset', 'after', 'before']) {
    assert.match(filters, new RegExp(`FILTER_KEYS = \\[[^\\]]*'${key}'`), key);
  }
  const library = await readFile(new URL('library/library-screen.tsx', components), 'utf8');
  assert.match(library, /if \(FILTER_KEYS\.some\(\(key\) => query\.has\(key\)\)\)/, 'URL filters are applied alone, never mixed with remembered state');
  assert.match(await readFile(new URL('library/incident-card.tsx', components), 'utf8'), /library-official-marker/);
});

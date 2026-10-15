// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const components = new URL('../components/', import.meta.url);

test('dashboard numbers link to the reports page with official scope and exact filters (URL is the state)', async () => {
  const dashboard = await readFile(new URL('dashboard.tsx', components), 'utf8');
  assert.match(dashboard, /new URLSearchParams\(\{ scope: 'official' \}\)/);
  assert.match(dashboard, /if \(f\.instrument \|\| f\.asset\) p\.set\('match', 'exact'\)/);
  assert.match(dashboard, /p\.set\('entityType', f\.entityType\)/);
  assert.doesNotMatch(dashboard, /clearFilters|dashboard: '1'/, 'no hidden dashboard-only filter markers');
  assert.match(dashboard, /href="\/videos\?filter=awaiting-selection"/);
  assert.match(dashboard, /href="\/videos\?filter=without-report"/);
  const library = await readFile(new URL('reports-library.tsx', components), 'utf8');
  for (const key of ['scope', 'entityType', 'match', 'type', 'instrument', 'asset', 'after', 'before']) {
    assert.match(library, new RegExp(`FILTER_KEYS = \\[[^\\]]*'${key}'`), key);
  }
  assert.match(library, /if \(FILTER_KEYS\.some\(\(key\) => query\.has\(key\)\)\)/, 'URL filters are applied alone, never mixed with remembered state');
  assert.match(library, /library-official-marker/);
});

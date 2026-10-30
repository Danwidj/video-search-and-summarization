// SPDX-License-Identifier: Apache-2.0

// The star column's official state: a second click right after a mark must still ask before it replaces.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { officialRevisionIdOf, shouldConfirmReplace } = await import('../src/lib/reports/official-state.ts');

const list = (official) => [1, 2, 3].map((revisionId) => ({ revisionId, isOfficial: revisionId === official }));

test('the list decides until a local answer exists', () => {
  assert.equal(officialRevisionIdOf(list(2)), 2);
  assert.equal(officialRevisionIdOf(list(null)), null);
  assert.equal(shouldConfirmReplace(list(null), 1), false);
  assert.equal(shouldConfirmReplace(list(2), 1), true);
  assert.equal(shouldConfirmReplace(list(2), 2), false);
});

test('a mark that just succeeded counts before the refetched list shows it', () => {
  // v1 was marked a moment ago, the list still has no official version: marking v2 must ask.
  assert.equal(shouldConfirmReplace(list(null), 2, 1), true);
  assert.equal(shouldConfirmReplace(list(null), 1, 1), false);
});

test('a clear that just succeeded counts before the refetched list shows it', () => {
  assert.equal(officialRevisionIdOf(list(2), null), null);
  assert.equal(shouldConfirmReplace(list(2), 1, null), false);
});

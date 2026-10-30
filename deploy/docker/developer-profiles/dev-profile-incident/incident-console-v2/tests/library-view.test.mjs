// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cardTitle } from '../src/lib/library/view.ts';

test('a card led by the official version says which version it shows', () => {
  assert.equal(cardTitle({ title: 'Forklift near miss', isOfficial: true, revisionNo: 3 }, 'x'), 'Official v3 · Forklift near miss');
  assert.equal(cardTitle({ title: 'Forklift near miss', isOfficial: false, revisionNo: 4 }, 'x'), 'Forklift near miss');
  assert.equal(cardTitle({ title: 'Forklift near miss', revisionNo: 4 }, 'x'), 'Forklift near miss');
  assert.equal(cardTitle({ title: '', isOfficial: true, revisionNo: 2 }, 'Fall · today'), 'Official v2 · Fall · today');
  assert.equal(cardTitle({ title: '', isOfficial: false, revisionNo: null }, 'Fall · today'), 'Fall · today');
});

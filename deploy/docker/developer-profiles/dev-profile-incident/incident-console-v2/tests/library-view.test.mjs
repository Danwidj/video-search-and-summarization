// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cardTitle } from '../src/lib/library/view.ts';

test('a card title is the report title with no official prefix, or the fallback when empty', () => {
  assert.equal(cardTitle({ title: 'Forklift near miss', isOfficial: true, revisionNo: 3 }, 'x'), 'Forklift near miss');
  assert.equal(cardTitle({ title: 'Forklift near miss', isOfficial: false, revisionNo: 4 }, 'x'), 'Forklift near miss');
  assert.equal(cardTitle({ title: '', isOfficial: true, revisionNo: 2 }, 'Fall · today'), 'Fall · today');
});

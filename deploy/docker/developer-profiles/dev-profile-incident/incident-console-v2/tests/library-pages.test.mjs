// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pageItems } from '../src/lib/library/pages.ts';

test('4 pages or fewer show every page', () => {
  assert.deepEqual(pageItems(1, 1), [1]);
  assert.deepEqual(pageItems(2, 3), [1, 2, 3]);
  assert.deepEqual(pageItems(3, 4), [1, 2, 3, 4]);
});

test('the first 2 and last 2 pages show with an ellipsis for the middle', () => {
  assert.deepEqual(pageItems(1, 14), [1, 2, 'gap', 13, 14]);
  assert.deepEqual(pageItems(2, 14), [1, 2, 'gap', 13, 14]);
  assert.deepEqual(pageItems(13, 14), [1, 2, 'gap', 13, 14]);
  assert.deepEqual(pageItems(14, 14), [1, 2, 'gap', 13, 14]);
  assert.deepEqual(pageItems(1, 5), [1, 2, 'gap', 4, 5]);
});

test('a page in the middle shows too, and pages next to each other join without an ellipsis', () => {
  assert.deepEqual(pageItems(7, 14), [1, 2, 'gap', 7, 'gap', 13, 14]);
  assert.deepEqual(pageItems(3, 14), [1, 2, 3, 'gap', 13, 14]);
  assert.deepEqual(pageItems(12, 14), [1, 2, 'gap', 12, 13, 14]);
  assert.deepEqual(pageItems(3, 5), [1, 2, 3, 4, 5]);
});

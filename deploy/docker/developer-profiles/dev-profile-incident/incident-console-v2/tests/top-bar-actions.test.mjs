// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { topBarActions } from '../src/lib/reports/top-bar-actions.ts';

test('with a showable camera every action is available', () => {
  const actions = topBarActions({ report: {}, incidentVideos: ['a.mp4', 'b.mp4'] });
  for (const action of Object.values(actions)) assert.deepEqual(action, { enabled: true, reason: null });
});

test('a page with no showable camera disables Re-analyse and Remove with a reason, and keeps Merge and Regenerate', () => {
  const actions = topBarActions({ report: null, incidentVideos: ['a.mp4', 'b.mp4'] });
  assert.equal(actions.reanalyse.enabled, false);
  assert.equal(actions.remove.enabled, false);
  assert.match(actions.reanalyse.reason, /No camera of this version can be shown/);
  assert.match(actions.remove.reason, /Regenerate|regenerate/);
  assert.equal(actions.merge.enabled, true);
  assert.equal(actions.regenerate.enabled, true);
});

test('an incident with no videos can neither merge nor regenerate', () => {
  const actions = topBarActions({ report: null, incidentVideos: [] });
  assert.equal(actions.merge.enabled, false);
  assert.equal(actions.regenerate.enabled, false);
});

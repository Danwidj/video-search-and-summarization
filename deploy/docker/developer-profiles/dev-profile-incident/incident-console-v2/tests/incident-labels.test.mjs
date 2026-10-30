// SPDX-License-Identifier: Apache-2.0

// P6.10: the dashboard and the report chat speak per incident. Labels live in the components;
// these tests pin the wording and the helper that names a citation's camera.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { citationTitle } = await import('../src/lib/chat/report-chat.ts');
const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

test('a citation names the camera it was seen in, when known', () => {
  assert.equal(citationTitle({ itemId: 'I1', itemType: 'instrument', videoName: 'rear.mp4' }), 'I1 · instrument · rear.mp4');
  assert.equal(citationTitle({ itemId: 'E2', itemType: 'entity', videoName: null }), 'E2 · entity');
});

test('the dashboard counts incidents and says which cards count videos', () => {
  const dashboard = source('sections/dashboard/components/Dashboard/Dashboard.tsx');
  assert.match(dashboard, /count each incident once/);
  assert.doesNotMatch(dashboard, /count each video once/);
  assert.match(dashboard, /label="Uploaded videos"/);
  assert.match(dashboard, /label="Incidents awaiting official report"/);
  assert.match(dashboard, /label="Incidents without a report"/);
});

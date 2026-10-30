// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import { REGENERATE_STAGES, regeneratedMessage, regenerateReport, regenerateStageAt } from '../src/lib/reports/regenerate.ts';

test('the stage follows elapsed time and the last stage holds below 100%', () => {
  assert.equal(regenerateStageAt(0).label, 'Reading stored analyses');
  assert.equal(regenerateStageAt(2000).label, 'Combining the overview');
  assert.equal(regenerateStageAt(10 * 60_000).label, 'Saving the new version');
  assert.ok(REGENERATE_STAGES.every((stage, i, all) => stage.percent < 100 && (i === 0 || stage.percent > all[i - 1].percent)));
});

test('the done message counts the covered videos', () => {
  assert.equal(
    regeneratedMessage({ revisionId: 9, revisionNo: 5, videoNames: ['a.mp4', 'b.mp4', 'c.mp4'] }),
    'v5 created from 3 videos and selected.',
  );
  assert.equal(regeneratedMessage({ revisionId: 2, revisionNo: 1, videoNames: ['a.mp4'] }), 'v1 created from 1 video and selected.');
});

function withFetch(handler, run) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return run().finally(() => {
    globalThis.fetch = original;
  });
}

test('regenerateReport posts to the incident build route and returns the new version', async () => {
  const calls = [];
  const version = await withFetch(
    async (url, init) => {
      calls.push([url, init.method]);
      return new Response(JSON.stringify({ built: { revisionId: 11, revisionNo: 4, videoNames: ['front door.mp4'] } }), { status: 200 });
    },
    () => regenerateReport('12'),
  );
  assert.deepEqual(calls, [['/api/reports/12/build', 'POST']]);
  assert.deepEqual(version, { revisionId: 11, revisionNo: 4, videoNames: ['front door.mp4'] });
});

test('regenerateReport throws the route message when the build is refused', async () => {
  await withFetch(
    async () => new Response(JSON.stringify({ error: 'No analysis is stored for: b.mp4. Analyse them first.' }), { status: 409 }),
    () => assert.rejects(regenerateReport('12'), /No analysis is stored for: b\.mp4/),
  );
  await withFetch(
    async () => new Response('<html>', { status: 502 }),
    () => assert.rejects(regenerateReport('12'), /HTTP 502/),
  );
});

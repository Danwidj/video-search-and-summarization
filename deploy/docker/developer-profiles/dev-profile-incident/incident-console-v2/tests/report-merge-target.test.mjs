// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import { mergeIncidentInto } from '../src/lib/reports/merge-client.ts';
import { mergeCandidates, mergedVideoCount, pluralVideos } from '../src/lib/reports/merge-target.ts';

const items = [
  { incidentId: 3, title: 'Package left unattended', incidentType: 'package', videoCount: 1, firstVideoName: 'loading-bay.mp4' },
  { incidentId: 12, title: 'Unauthorised entry', incidentType: 'entry', videoCount: 3, firstVideoName: 'front-door.mp4' },
  { incidentId: 9, title: '', incidentType: 'entry', videoCount: 2, firstVideoName: 'gate-cam.mp4' },
  { incidentId: 5, title: '', incidentType: '', videoCount: 0, firstVideoName: null },
];

test('the chooser lists every other incident, newest first, with its video names', () => {
  const list = mergeCandidates(items, 12);
  assert.deepEqual(
    list.map((entry) => entry.incidentId),
    [9, 5, 3],
  );
  assert.equal(list[0].label, 'Incident 9 · entry');
  assert.equal(list[0].detail, 'gate-cam.mp4 +1 more · 2 videos');
  assert.equal(list[1].label, 'Incident 5');
  assert.equal(list[2].detail, 'loading-bay.mp4 · 1 video');
});

test('the merged count adds the moving videos to the target', () => {
  assert.equal(mergedVideoCount({ videoCount: 1 }, 3), 4);
  assert.equal(pluralVideos(1), '1 video');
  assert.equal(pluralVideos(2), '2 videos');
});

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test('merging posts the source to the target incident and surfaces the route error', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init.method, JSON.parse(init.body)]);
    return Response.json({ merged: {} });
  };
  await mergeIncidentInto(12, 9);
  assert.deepEqual(calls, [['/api/reports/9/merge', 'POST', { sourceIncidentId: 12 }]]);

  globalThis.fetch = async () => Response.json({ error: 'Incident not found' }, { status: 404 });
  await assert.rejects(mergeIncidentInto(12, 99), /Incident not found/);
});

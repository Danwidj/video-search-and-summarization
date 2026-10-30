// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

import {
  buildFirstReport,
  defaultRemoveChoice,
  effectiveRemoveChoice,
  incidentHref,
  isLastVideo,
  removeChoices,
  removeVideo,
} from '../src/lib/reports/remove-video.ts';

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

test('an incident with several videos offers move (first) and delete; the last video offers only delete', () => {
  assert.deepEqual(removeChoices(3), ['move', 'delete']);
  assert.equal(defaultRemoveChoice(2), 'move');
  assert.deepEqual(removeChoices(1), ['delete']);
  assert.equal(defaultRemoveChoice(1), 'delete');
  assert.equal(isLastVideo(1), true);
  assert.equal(isLastVideo(2), false);
});

test('removeVideo posts the choice to the encoded video name and returns the outcome', async () => {
  const calls = [];
  const fetcher = async (url, init) => {
    calls.push([url, JSON.parse(init.body)]);
    return json(200, { removed: { choice: 'move', videoId: 'side gate.mp4', incidentId: 12, newIncidentId: 14 } });
  };
  const outcome = await removeVideo('side gate.mp4', 'move', fetcher);
  assert.deepEqual(calls, [['/api/videos/side%20gate.mp4/remove', { choice: 'move' }]]);
  assert.equal(outcome.newIncidentId, 14);
});

test('removeVideo and buildFirstReport surface the server message', async () => {
  await assert.rejects(
    removeVideo('a.mp4', 'move', async () => json(400, { error: 'last video' })),
    /last video/,
  );
  await assert.rejects(
    buildFirstReport(14, async () => json(502, { error: 'agent down' })),
    /agent down/,
  );
  await assert.rejects(
    buildFirstReport(14, async () => new Response('nope', { status: 500 })),
    /HTTP 500/,
  );
});

test('buildFirstReport posts to the new incident build route', async () => {
  const calls = [];
  await buildFirstReport(14, async (url, init) => {
    calls.push([url, init.method]);
    return json(200, { built: {} });
  });
  assert.deepEqual(calls, [['/api/reports/14/build', 'POST']]);
  assert.equal(incidentHref(14), '/reports/14');
});

test('the report page mounts the dialog for the selected camera and reloads without it', async () => {
  const page = await readFile(new URL('../src/sections/reports/components/ReportPage/ReportPage.tsx', import.meta.url), 'utf8');
  assert.match(page, /<RemoveVideoDialog[\s\S]*video=\{report\.run\.filename\}/);
  assert.match(page, /reportQuery\(revisionId, null\)/);
});

test('a move picked while the incident had several videos becomes delete once one video is left', () => {
  assert.equal(effectiveRemoveChoice('move', 3), 'move');
  assert.equal(effectiveRemoveChoice('move', 1), 'delete');
  assert.equal(effectiveRemoveChoice('delete', 3), 'delete');
});

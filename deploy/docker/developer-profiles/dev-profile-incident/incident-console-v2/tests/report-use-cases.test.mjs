// SPDX-License-Identifier: Apache-2.0

// Use cases tested against the in-memory fake: no fetch, no PostgREST, no R2.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../lib/adapters/memory/incidents.ts');
const { InMemoryVideoRepository } = await import('../lib/adapters/memory/videos.ts');
const { changeReviewStatus, deleteReport, getReport } = await import('../lib/application/reports.ts');
const { aiRunReport } = await import('./support/report-view.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const KEY = { videoId: smoke.videoId, modelRunId: smoke.modelRunId };
const clock = () => new Date('2026-10-17T02:00:00.000Z');

test('verifying a run records the verifier and the stored time once; repeating it changes nothing', async () => {
  const incidents = new InMemoryIncidentRepository([aiRunReport({ ...smoke, review: null })]);
  incidents.now = () => '2026-10-17T02:00:00.123';
  assert.deepEqual(await changeReviewStatus(incidents, KEY, 'verified', 'Lead', clock), { kind: 'changed', at: '2026-10-17T02:00:00.123' });
  assert.deepEqual(await incidents.getReview(KEY), { status: 'verified', editedBy: null, editedAt: null, verifiedBy: 'Lead', verifiedAt: '2026-10-17T02:00:00.123' });
  assert.deepEqual(await changeReviewStatus(incidents, KEY, 'verified', 'Someone else', clock), { kind: 'unchanged' });
  assert.deepEqual(await changeReviewStatus(incidents, { ...KEY, modelRunId: 'm-none' }, 'verified', 'Lead', clock), { kind: 'not-found' });
});

test('a review change never claims to be an edit: the last content edit stays', async () => {
  const edited = { status: 'under review', verifiedBy: null, verifiedAt: null, editedBy: 'Editor', editedAt: '2026-10-16T09:00:00' };
  const incidents = new InMemoryIncidentRepository([aiRunReport({ ...smoke, review: null })]);
  incidents.reviews.set(`${KEY.videoId}\u0000${KEY.modelRunId}`, edited);
  assert.deepEqual(await changeReviewStatus(incidents, KEY, 'unreviewed', 'Lead', clock), { kind: 'changed', at: '2026-10-17T02:00:00.000Z' });
  assert.deepEqual(await incidents.getReview(KEY), { ...edited, status: 'unreviewed' });
  await changeReviewStatus(incidents, KEY, 'verified', 'Lead', clock);
  assert.deepEqual([(await incidents.getReview(KEY)).editedBy, (await incidents.getReview(KEY)).editedAt], ['Editor', '2026-10-16T09:00:00']);
});

test('getReport signs the stored key and refuses a run without one', async () => {
  const incidents = new InMemoryIncidentRepository([aiRunReport(smoke)]);
  const signed = [];
  const view = await getReport(incidents, KEY, async (key) => { signed.push(key); return 'https://signed/x'; });
  assert.deepEqual(signed, [smoke.video.filepath]);
  assert.equal(view.run.playbackUrl, 'https://signed/x');
  assert.equal(await getReport(incidents, { ...KEY, modelRunId: 'm-none' }, async () => 'unused'), null);

  const noVideo = new InMemoryIncidentRepository([aiRunReport({ ...smoke, video: { ...smoke.video, filepath: '' } })]);
  await assert.rejects(getReport(noVideo, KEY, async () => 'unused'), /The report has no linked R2 video/);
});

function stores(storageKey = smoke.video.filepath) {
  return {
    incidents: new InMemoryIncidentRepository([aiRunReport(smoke)]),
    videos: new InMemoryVideoRepository([{ videoId: KEY.videoId, storageKey, uploadedAt: null, source: null, officialRunId: null, runsWithReport: [KEY.modelRunId] }]),
  };
}

test('deleting one report removes only that run', async () => {
  const ports = stores();
  await deleteReport(ports, KEY, false, async () => assert.fail('no stored object is removed for a single report'));
  assert.equal(await ports.incidents.runExists(KEY), false);
  assert.notEqual(await ports.videos.getVideo(KEY.videoId), null);
});

test('deleting a whole video removes its stored objects before the video row', async () => {
  const ports = stores();
  const removed = [];
  await deleteReport(ports, KEY, true, async (storageKey) => {
    removed.push({ storageKey, videoStillStored: Boolean(await ports.videos.getVideo(KEY.videoId)) });
  });
  assert.deepEqual(removed, [{ storageKey: smoke.video.filepath, videoStillStored: true }]);
  assert.equal(await ports.videos.getVideo(KEY.videoId), null);
});

test('a whole-video delete refuses a video without a stored object and deletes nothing', async () => {
  const ports = stores(null);
  await assert.rejects(deleteReport(ports, KEY, true, async () => assert.fail('nothing to remove')), /Video has no R2 object key/);
  assert.notEqual(await ports.videos.getVideo(KEY.videoId), null);
  await assert.rejects(deleteReport(ports, { ...KEY, videoId: 'v-none' }, true, async () => undefined), /Video has no R2 object key/);
});

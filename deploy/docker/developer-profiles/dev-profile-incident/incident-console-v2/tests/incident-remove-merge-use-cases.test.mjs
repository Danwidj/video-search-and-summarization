// SPDX-License-Identifier: Apache-2.0

// P5.3 use cases (merge, remove a video, delete an incident) against the in-memory fakes.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentVideoRepository } = await import('../src/modules/videos/infrastructure/memory/incident-videos.ts');
const { InMemoryIncidentReportRepository } = await import('../src/modules/reports/infrastructure/memory/incident-reports.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');
const { removeVideoFromIncident } = await import('../src/modules/reports/application/remove-video/index.ts');
const { deleteIncident } = await import('../src/modules/reports/application/delete-incident/index.ts');
const { mergeIncidents } = await import('../src/modules/reports/application/merge-incidents/index.ts');

const video = (videoId, incidentId, storageKey = `uploads/${videoId}`) => ({
  videoId,
  incidentId,
  storageKey,
  recordedAt: null,
  uploadedAt: '2026-10-01T00:00:00.000Z',
  durationSeconds: 10,
  source: null,
});

/** An evidence store holding `keys`; it records each removal and whether the video row still existed then. */
function evidenceStore(keys, videos, { failing = [], rowOf = null } = {}) {
  const removed = [];
  const listed = [];
  return {
    removed,
    listed,
    async list(prefix) {
      listed.push(prefix);
      return keys.filter((key) => key.startsWith(prefix)).map((key) => ({ key, lastModified: null }));
    },
    async remove(key) {
      if (failing.includes(key)) throw new Error('R2 refused');
      removed.push({ key, rowStillStored: rowOf ? Boolean(await videos.getVideo(rowOf(key))) : null });
    },
  };
}

const ports = (videos, evidence, removedVideos = []) => ({
  videos,
  evidence,
  removeStoredVideo: async (storageKey) => removedVideos.push(storageKey),
});

test('removing entirely deletes the video object and its evidence images before the row, and no other video', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1), video('b.mp4', 1)]);
  const evidence = evidenceStore(
    [
      'evidence/uploads/a.mp4/r1/E1.jpg',
      'evidence/uploads/a.mp4/r2/A1.jpg',
      'evidence/uploads/a.mp4-2/r1/E1.jpg',
      'evidence/uploads/b.mp4/r1/E1.jpg',
    ],
    videos,
    { rowOf: () => 'a.mp4' },
  );
  const removedVideos = [];
  const result = await removeVideoFromIncident(ports(videos, evidence, removedVideos), 'a.mp4', 'delete');
  assert.equal(result.choice, 'delete');
  assert.equal(result.incidentDeleted, false);
  assert.deepEqual(removedVideos, ['uploads/a.mp4']);
  assert.deepEqual(evidence.listed, ['evidence/uploads/a.mp4/'], 'the trailing slash keeps a.mp4-2 out');
  assert.deepEqual(evidence.removed, [
    { key: 'evidence/uploads/a.mp4/r1/E1.jpg', rowStillStored: true },
    { key: 'evidence/uploads/a.mp4/r2/A1.jpg', rowStillStored: true },
  ]);
  assert.equal(await videos.getVideo('a.mp4'), null);
  assert.notEqual(await videos.getVideo('b.mp4'), null);
});

test('removing the last video entirely deletes the incident', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1)]);
  const result = await removeVideoFromIncident(ports(videos, evidenceStore([], videos)), 'a.mp4', 'delete');
  assert.equal(result.incidentDeleted, true);
  assert.deepEqual(await videos.listVideos(1), []);
});

test('moving a video to its own incident touches no file and keeps the video', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1), video('b.mp4', 1)]);
  const evidence = {
    list: async () => assert.fail('a move lists no file'),
    remove: async () => assert.fail('a move removes no file'),
  };
  const result = await removeVideoFromIncident(
    { videos, evidence, removeStoredVideo: async () => assert.fail('a move removes no file') },
    'b.mp4',
    'move',
  );
  assert.deepEqual([result.choice, result.videoId, result.incidentId], ['move', 'b.mp4', 1]);
  assert.notEqual(result.newIncidentId, 1);
  assert.equal((await videos.getVideo('b.mp4')).incidentId, result.newIncidentId);
  assert.equal((await videos.getVideo('b.mp4')).storageKey, 'uploads/b.mp4');
});

test('moving the last video is refused and nothing changes', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1)]);
  await assert.rejects(
    removeVideoFromIncident(ports(videos, evidenceStore([], videos)), 'a.mp4', 'move'),
    (error) => error instanceof StoreRejection && error.reason === 'invalid',
  );
  assert.equal((await videos.getVideo('a.mp4')).incidentId, 1);
});

test('an unknown video is a not-found rejection for both choices', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1)]);
  for (const choice of ['delete', 'move']) {
    await assert.rejects(
      removeVideoFromIncident(ports(videos, evidenceStore([], videos)), 'none.mp4', choice),
      (error) => error instanceof StoreRejection && error.reason === 'not-found',
    );
  }
});

test('a failed evidence removal keeps the video row, and the delete can be repeated', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1), video('b.mp4', 1)]);
  const keys = ['evidence/uploads/a.mp4/r1/E1.jpg', 'evidence/uploads/a.mp4/r2/A1.jpg'];
  const evidence = evidenceStore(keys, videos, { failing: [keys[0]] });
  await assert.rejects(
    removeVideoFromIncident(ports(videos, evidence), 'a.mp4', 'delete'),
    /Could not remove 1 of 2 evidence images, so the video was kept: evidence\/uploads\/a\.mp4\/r1\/E1\.jpg: R2 refused/,
  );
  assert.deepEqual(
    evidence.removed.map(({ key }) => key),
    [keys[1]],
    'the other image is still removed',
  );
  assert.notEqual(await videos.getVideo('a.mp4'), null);
  await removeVideoFromIncident(ports(videos, evidenceStore(keys, videos)), 'a.mp4', 'delete');
  assert.equal(await videos.getVideo('a.mp4'), null);
});

test('an unlistable evidence folder keeps the video row', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1), video('b.mp4', 1)]);
  const unlistable = {
    list: async () => {
      throw new Error('R2 listing was cut short');
    },
    remove: async () => assert.fail('nothing listed'),
  };
  await assert.rejects(removeVideoFromIncident(ports(videos, unlistable), 'a.mp4', 'delete'), /R2 listing was cut short/);
  assert.notEqual(await videos.getVideo('a.mp4'), null);
});

test('a video without a stored object is refused and nothing is deleted', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1, null), video('b.mp4', 1)]);
  const evidence = evidenceStore(['evidence/uploads/a.mp4/r1/E1.jpg'], videos);
  await assert.rejects(removeVideoFromIncident(ports(videos, evidence), 'a.mp4', 'delete'), /Video has no R2 object key/);
  assert.deepEqual(evidence.removed, []);
  assert.notEqual(await videos.getVideo('a.mp4'), null);
});

test('deleting an incident removes every video with its objects, and the incident goes with the last one', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1), video('b.mp4', 1), video('c.mp4', 2)]);
  const evidence = evidenceStore(
    ['evidence/uploads/a.mp4/r1/E1.jpg', 'evidence/uploads/b.mp4/r1/E1.jpg', 'evidence/uploads/c.mp4/r1/E1.jpg'],
    videos,
  );
  const removedVideos = [];
  const result = await deleteIncident(ports(videos, evidence, removedVideos), 1);
  assert.deepEqual(result, { incidentId: 1, deletedVideoIds: ['a.mp4', 'b.mp4'] });
  assert.deepEqual(removedVideos.sort(), ['uploads/a.mp4', 'uploads/b.mp4']);
  assert.deepEqual(evidence.removed.map(({ key }) => key).sort(), ['evidence/uploads/a.mp4/r1/E1.jpg', 'evidence/uploads/b.mp4/r1/E1.jpg']);
  assert.deepEqual(await videos.listVideos(1), []);
  assert.equal((await videos.listVideos(2)).length, 1, 'another incident is untouched');
});

test('a delete that fails on a later video can be repeated, and an unknown incident is not-found', async () => {
  const videos = new InMemoryIncidentVideoRepository([video('a.mp4', 1), video('b.mp4', 1)]);
  const keys = ['evidence/uploads/b.mp4/r1/E1.jpg'];
  await assert.rejects(deleteIncident(ports(videos, evidenceStore(keys, videos, { failing: keys })), 1), /1 of 1 evidence images/);
  assert.deepEqual(
    (await videos.listVideos(1)).map((v) => v.videoId),
    ['b.mp4'],
  );
  assert.equal((await deleteIncident(ports(videos, evidenceStore(keys, videos)), 1)).deletedVideoIds.length, 1);
  await assert.rejects(
    deleteIncident(ports(videos, evidenceStore([], videos)), 1),
    (error) => error instanceof StoreRejection && error.reason === 'not-found',
  );
});

test('merging moves the source videos into the target, deletes the source and moves no file', async () => {
  const reports = new InMemoryIncidentReportRepository({
    incidents: [1, 2].map((incidentId) => ({ incidentId, officialRevisionId: null, officialSince: null, createdAt: null })),
    videos: [video('a.mp4', 1), video('b.mp4', 2), video('c.mp4', 2)],
  });
  const result = await mergeIncidents(reports, 1, 2);
  assert.deepEqual([result.incidentId, result.sourceIncidentId, result.movedVideoIds.sort()], [1, 2, ['b.mp4', 'c.mp4']]);
  assert.deepEqual((await reports.getIncident(1)).videos.map((v) => v.videoId).sort(), ['a.mp4', 'b.mp4', 'c.mp4']);
  assert.equal(await reports.getIncident(2), null);
  for (const [source, target] of [
    [1, 1],
    [1, 9],
  ]) {
    await assert.rejects(mergeIncidents(reports, source, target), (error) => error instanceof StoreRejection);
  }
});

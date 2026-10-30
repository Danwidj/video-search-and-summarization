// SPDX-License-Identifier: Apache-2.0

// getReport and listRevisions over the in-memory incident repository: no fetch, no PostgREST, no R2.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('../../../../tests/support/alias-loader.mjs', import.meta.url);

await import('../../../../src/modules/contract/infrastructure/loader.ts');
const { InMemoryIncidentReportRepository } = await import('../../../../src/modules/reports/infrastructure/memory/incident-reports.ts');
const { StoreRejection } = await import('../../../../src/modules/shared/domain/common.ts');
const { getReport } = await import('@/modules/reports/application/get-report');
const { listRevisions } = await import('@/modules/reports/application/list-revisions');

const valid = JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'full-report.json'), 'utf8'));
const A = 'reads-a.mp4';
const B = 'reads-b.mp4';
const GONE = 'reads-gone.mp4';
const IMAGE = `evidence/videos/${A}/E1.jpg`;

const video = (videoId) => ({
  incidentId: 1,
  videoId,
  storageKey: `videos/${videoId}`,
  uploadedAt: '2026-10-01T01:00:00',
  recordedAt: null,
  durationSeconds: 10,
  source: 'upload',
});
const revision = (revisionId, revisionNo, videoNames, cameras, evidence = []) => ({
  revision: {
    revisionId,
    incidentId: 1,
    revisionNo,
    kind: 'ai',
    createdBy: null,
    createdAt: `2026-10-01T0${revisionNo}:00:00`,
    note: null,
    parentId: null,
    modelRunId: 'run',
    model: 'model-x',
    videoNames,
    isOfficial: false,
  },
  payload: {
    overview: { title: 'Two vans', type: 'Theft', severity_level: 2, description: 'd', location: null },
    cameras: cameras.map((name) => ({ video: name, report: name === B ? { broken: true } : valid })),
  },
  evidence,
});

const repository = () =>
  new InMemoryIncidentReportRepository({
    incidents: [{ incidentId: 1, officialRevisionId: null, officialSince: null, createdAt: '2026-10-01T00:00:00' }],
    videos: [video(A), video(B)],
    revisions: [
      revision(1, 1, [A, B, GONE], [A, B, GONE], [{ item_type: 'entity', item_id: valid.entities[0].entity_id, video: A, image: IMAGE }]),
      revision(2, 2, [A], [A]),
    ],
    modelRuns: { run: 'model-x' },
  });

const sign =
  (signed = []) =>
  async (key) => {
    signed.push(key);
    return `https://signed/${key}`;
  };

test('getReport defaults to the newest revision and its first valid camera, signing that video and its item images', async () => {
  const signed = [];
  const view = await getReport(repository(), 1, null, null, sign(signed));
  assert.equal(view.revision.revisionId, 2);
  assert.equal(view.camera, A);
  assert.deepEqual(signed, [`videos/${A}`]);
  assert.equal(view.report.run.playbackUrl, `https://signed/videos/${A}`);
  assert.equal(view.coverage.verdict.status, 'lacks');
});

test('getReport tags evidence images to their camera and signs them; an image that cannot be signed is shown as missing', async () => {
  const signed = [];
  const view = await getReport(repository(), 1, 1, A, sign(signed));
  const items = [...view.report.structured.entities, ...view.report.structured.instruments, ...view.report.structured.assets];
  assert.ok(signed.includes(IMAGE), 'the tagged image is signed');
  assert.ok(items.some((item) => item.evidence?.imageUrl === `https://signed/${IMAGE}`));

  const broken = await getReport(repository(), 1, 1, A, async (key) => {
    if (key.startsWith('evidence/')) throw new Error('gone');
    return 'https://signed/video';
  });
  assert.ok(
    [...broken.report.structured.entities].every((item) => !item.evidence || item.evidence.imageUrl === null),
    'no image URL when signing fails',
  );
});

test('getReport lists every camera; a removed video has no player and an invalid report is never shown', async () => {
  const view = await getReport(repository(), 1, 1, null, sign());
  assert.deepEqual(
    view.cameras.map((camera) => [camera.video, camera.current, camera.valid]),
    [
      [A, true, true],
      [B, true, false],
      [GONE, false, true],
    ],
  );
  assert.deepEqual(view.incidentVideos, [A, B]);
  const removed = await getReport(repository(), 1, 1, GONE, sign());
  assert.equal(removed.report.run.playbackUrl, '');
  const invalid = await getReport(repository(), 1, 1, B, sign());
  assert.deepEqual([invalid.camera, invalid.report], [B, null]);
});

test('getReport lists an incident video the open version does not cover as a camera without a report', async () => {
  const view = await getReport(repository(), 1, 2, null, sign());
  assert.deepEqual(view.incidentVideos, [A, B]);
  assert.deepEqual(
    view.cameras.map((camera) => [camera.video, camera.current, camera.inVersion, camera.valid]),
    [
      [A, true, true, true],
      [B, true, false, false],
    ],
  );
  assert.equal(view.camera, A);
});

test('getReport is null for an unknown incident or revision and rejects a camera the revision does not hold', async () => {
  assert.equal(await getReport(repository(), 9, null, null, sign()), null);
  assert.equal(await getReport(repository(), 1, 99, null, sign()), null);
  await assert.rejects(
    getReport(repository(), 1, 2, B, sign()),
    (error) => error instanceof StoreRejection && error.reason === 'not-found',
  );
});

test('listRevisions is newest first with each coverage verdict, and empty for an unknown incident', async () => {
  const versions = await listRevisions(repository(), 1);
  assert.deepEqual(
    versions.map((version) => [version.revisionNo, version.coverage.verdict.status]),
    [
      [2, 'lacks'],
      [1, 'removed'],
    ],
  );
  assert.deepEqual(await listRevisions(repository(), 9), []);
});

// SPDX-License-Identifier: Apache-2.0

// Repeat uploads: the same file content never makes a second video or job.
// The race (one file selected twice, double-clicked, or sent twice in the same
// second) is the regression test; the unique indexes behind it are tested on a
// real Postgres in supabase/tests/test_baseline.py.

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryAnalysisJobRepository } = await import('../src/modules/jobs/infrastructure/memory/analysis-jobs.ts');
const { InMemoryVideoRepository } = await import('../src/modules/videos/infrastructure/memory/videos.ts');
const app = await import('../src/modules/jobs/application/index.ts');
const dup = await import('../src/modules/uploads/domain/duplicate.ts');
const { sha256OfBlob } = await import('../src/lib/uploads-hash.ts');
const { newBatchItem, runBatchItem, canRetryUpload } = await import('../src/sections/analysis/batch-upload.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');

const catalog = { findAllowedModel: (id) => (id === 'model-a' ? { id, label: id, timeout_seconds: 300 } : undefined) };
const HASH = 'a'.repeat(64);
const OTHER = 'b'.repeat(64);
const input = (name, contentSha256 = HASH) => ({ filePath: `uploads/${name}`, filename: name, model: 'model-a', contentSha256 });

test('sha256OfBlob matches the SHA-256 of the bytes', async () => {
  const expected = createHash('sha256').update('hello clip').digest('hex');
  assert.equal(await sha256OfBlob(new Blob(['hello clip'])), expected);
});

test('the same content uploaded at once ends with one job (the race)', async () => {
  const jobs = new InMemoryAnalysisJobRepository(new Date('2026-11-06T08:00:00Z'));
  const videos = new InMemoryVideoRepository([]);
  const results = await Promise.allSettled([
    app.enqueueAnalysisJob(jobs, catalog, input('clip.mp4'), 'model-a', videos),
    app.enqueueAnalysisJob(jobs, catalog, input('clip-2.mp4'), 'model-a', videos),
    app.enqueueAnalysisJob(jobs, catalog, input('clip-3.mp4'), 'model-a', videos),
  ]);
  assert.equal(results.filter((r) => r.status === 'fulfilled').length, 1);
  for (const lost of results.filter((r) => r.status === 'rejected')) {
    assert.ok(lost.reason instanceof dup.DuplicateUploadError);
    assert.equal(lost.reason.duplicate.kind, 'job');
  }
  assert.equal((await jobs.list(10)).length, 1);
});

test('content already in the library is refused with the existing video', async () => {
  const jobs = new InMemoryAnalysisJobRepository(new Date('2026-11-06T08:00:00Z'));
  const videos = new InMemoryVideoRepository([
    {
      videoId: 'v1',
      storageKey: 'uploads/Assault018.mp4',
      uploadedAt: '2026-11-06T08:00:00',
      source: null,
      officialRevisionId: null,
      revisionIds: [],
      contentSha256: HASH,
    },
  ]);
  const error = await app.enqueueAnalysisJob(jobs, catalog, input('Assault018.mp4'), 'model-a', videos).catch((e) => e);
  assert.ok(error instanceof dup.DuplicateUploadError);
  assert.deepEqual(error.duplicate, { kind: 'video', name: 'Assault018.mp4', videoId: 'v1', jobId: null });
  assert.equal(dup.duplicateReportPath(error.duplicate), '/reports/v1');
  assert.equal((await jobs.list(10)).length, 0, 'nothing is queued');
});

test('a new file, and a finished job with the same hash, are not duplicates', async () => {
  const jobs = new InMemoryAnalysisJobRepository(new Date('2026-11-06T08:00:00Z'));
  const videos = new InMemoryVideoRepository([]);
  const first = await app.enqueueAnalysisJob(jobs, catalog, input('a.mp4'), 'model-a', videos);
  await app.enqueueAnalysisJob(jobs, catalog, input('b.mp4', OTHER), 'model-a', videos);
  assert.equal((await jobs.list(10)).length, 2);
  await jobs.cancel(first.id);
  assert.equal((await app.enqueueAnalysisJob(jobs, catalog, input('a-2.mp4'), 'model-a', videos)).status, 'queued');
});

test('a malformed hash is rejected; no hash is still accepted', async () => {
  const jobs = new InMemoryAnalysisJobRepository(new Date('2026-11-06T08:00:00Z'));
  await assert.rejects(app.enqueueAnalysisJob(jobs, catalog, input('a.mp4', 'xyz'), 'model-a'), StoreRejection);
  const { contentSha256: _drop, ...bare } = input('a.mp4');
  assert.equal((await app.enqueueAnalysisJob(jobs, catalog, bare, 'model-a')).status, 'queued');
});

test('a batch with a repeated file queues it once and marks the repeat Already uploaded', async () => {
  const jobs = new InMemoryAnalysisJobRepository(new Date('2026-11-06T08:00:00Z'));
  const videos = new InMemoryVideoRepository([]);
  const deps = {
    upload: async (f, onProgress, onUploaded) => {
      onProgress(100);
      onUploaded();
      return { filePath: `uploads/${f.name}`, filename: f.name, converted: false, contentSha256: HASH };
    },
    enqueue: (request) => app.enqueueAnalysisJob(jobs, catalog, request, 'model-a', videos),
  };
  const finals = [];
  for (const name of ['clip.mp4', 'clip.mp4']) {
    let item = newBatchItem({ name, size: 2 * 1024 * 1024, type: 'video/mp4' }, name);
    await runBatchItem({ name, size: 2 * 1024 * 1024, type: 'video/mp4' }, 'model-a', deps, (change) => {
      item = { ...item, ...change };
    });
    finals.push(item);
  }
  assert.equal((await jobs.list(10)).length, 1);
  assert.equal(finals[0].status, 'waiting');
  assert.equal(finals[1].status, 'failed');
  assert.equal(finals[1].duplicate.kind, 'job');
  assert.equal(canRetryUpload(finals[1]), false, 'a repeat has no Retry');
});

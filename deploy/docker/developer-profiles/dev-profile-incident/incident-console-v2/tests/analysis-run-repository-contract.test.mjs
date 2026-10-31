// SPDX-License-Identifier: Apache-2.0

// One AnalysisRunRepository contract, run against the in-memory fake and the
// Supabase adapter over a fake PostgREST (tests/support/fake-postgrest.mjs).
// The analysis route tests cover the same writes end to end; this file pins the
// port's own guarantees.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryAnalysisRunRepository } = await import('../src/modules/analysis/infrastructure/memory/analysis-runs.ts');
const { SupabaseAnalysisRunAdapter } = await import('../src/modules/analysis/infrastructure/supabase/analysis-runs.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const KEY = 'uploads/sensor-1/v1.mp4';
const UPLOAD = { videoId: 'v1', r2Key: KEY, uploadedAt: '2026-10-01T08:00:00.000Z' };
const INCIDENT = {
  type: 'assault',
  start_timestamp: 10,
  end_timestamp: 20,
  duration: 10,
  description: 'A scuffle.',
  severity_level: 3,
  confidence_score: 0.9,
};

/** A valid run, as runContractAnalysis builds one. */
const validRun = (overrides = {}) => ({
  status: 'valid_first_pass',
  stage: null,
  failure: null,
  contractVersion: 'incident-contract-v4',
  videoId: 'v1',
  r2Key: KEY,
  modelRunId: 'm1',
  attemptedAt: '2026-10-22T10:00:00.000Z',
  generatedAt: '2026-10-22T10:00:00.000Z',
  request: {
    model: 'nvidia/cosmos-3-super-reasoner',
    inferenceConfig: {},
    additionalInstruction: null,
    promptSha256: 'p',
    schemaSha256: 's',
  },
  response: null,
  validation: { firstPass: [] },
  repair: null,
  report: { incident: INCIDENT, entities: [], instruments: [], assets: [], timeline: [] },
  ...overrides,
});

const failedAttempt = (overrides = {}) => ({
  ...validRun(),
  status: 'request_failed',
  stage: 'gateway',
  failure: { code: 'GATEWAY_TIMEOUT', message: 'timed out' },
  report: undefined,
  generatedAt: undefined,
  ...overrides,
});

const implementations = {
  memory: () => {
    const repo = new InMemoryAnalysisRunRepository();
    return {
      repo,
      storedVideo: (videoId) => {
        const video = repo.videos.get(videoId);
        return video ? { r2Key: video.r2Key, uploadedAt: video.uploadedAt } : null;
      },
      hasRun: (modelRunId) => repo.attempts.has(modelRunId),
    };
  },
  supabase: (tables = {}) => {
    const db = fakePostgrest({ videos: [], model_runs: [], report_revisions: [], ...tables }, { identity: { report_revisions: 'id' } });
    globalThis.fetch = db.fetch;
    const repo = new SupabaseAnalysisRunAdapter(new PostgrestClient('https://supabase.test', 'k'));
    return {
      repo,
      storedVideo: (videoId) => {
        const row = db.store.videos.find((video) => video.id === videoId);
        return row ? { r2Key: row.filepath, uploadedAt: row.uploaded_datetime } : null;
      },
      hasRun: (modelRunId) => db.store.model_runs.some((row) => row.id === modelRunId),
    };
  },
};

for (const [name, make] of Object.entries(implementations)) {
  describe(`AnalysisRunRepository contract: ${name}`, () => {
    test('an uploaded video is recorded once; a later record never resets it', async () => {
      const { repo, storedVideo } = make();
      await repo.recordUploadedVideo(UPLOAD);
      await repo.recordUploadedVideo({ ...UPLOAD, uploadedAt: '2026-10-22T09:00:00.000Z' });
      assert.deepEqual(storedVideo('v1'), { r2Key: KEY, uploadedAt: UPLOAD.uploadedAt });
    });

    test('a failed attempt is a run record only, and a valid attempt cannot be saved as a failure', async () => {
      const { repo, hasRun } = make();
      await repo.saveFailedAttempt(failedAttempt({ modelRunId: 'm-failed' }));
      assert.equal(hasRun('m-failed'), true);
      await assert.rejects(repo.saveFailedAttempt(validRun()), /saveFailedAttempt called with a valid_first_pass attempt/);
    });

    test('a valid run is saved with its revision and read back, returning the revision id', async () => {
      const { repo, hasRun } = make({ videos: [{ id: 'v1', filepath: KEY }] });
      await repo.recordUploadedVideo(UPLOAD);
      const steps = [];
      const revisionId = await repo.saveRun(validRun(), { revisionId: null, evidence: null }, (step) => steps.push(step));
      assert.equal(typeof revisionId, 'number');
      assert.equal(hasRun('m1'), true);
      assert.match(steps.at(-1), /verifying/, 'the read-back is the last step');
    });

    test('a revision the agent already stored is verified, not stored again', async () => {
      const { repo } = make({ videos: [{ id: 'v1', filepath: KEY }], report_revisions: [{ id: 5, video_id: 'v1', model_run_id: 'm1' }] });
      await repo.recordUploadedVideo(UPLOAD);
      assert.equal(await repo.saveRun(validRun(), { revisionId: 5, evidence: null }, () => {}), 5);
    });

    test('a run whose video is stored under another key is refused', async () => {
      const { repo } = make({ report_revisions: [{ id: 5, video_id: 'v1', model_run_id: 'm1' }] });
      await repo.recordUploadedVideo({ ...UPLOAD, r2Key: 'uploads/other.mp4' });
      await assert.rejects(
        repo.saveRun(validRun(), { revisionId: 5, evidence: null }, () => {}),
        /unexpected videos\.filepath value/,
      );
    });
  });
}

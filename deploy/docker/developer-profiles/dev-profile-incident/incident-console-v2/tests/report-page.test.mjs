// SPDX-License-Identifier: Apache-2.0

// The report page's server-side load (app/reports/[videoId]/(report)/load-report.ts):
// the getReport use case over the Supabase adapter and a fake PostgREST, with
// the playback URL signed on the server, and the outcome the page renders.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';
import { effectiveRowsOfAiRun, effectiveViews } from './support/finals-database.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const signed = [];
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class { send() { return Promise.resolve({}); } },
    GetObjectCommand: class { constructor(input) { this.input = input; } },
    PutObjectCommand: class { constructor(input) { this.input = input; } },
    HeadObjectCommand: class { constructor(input) { this.input = input; } },
    DeleteObjectCommand: class { constructor(input) { this.input = input; } },
  },
});
mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_client, command) => { signed.push(command.input.Key); return 'https://signed.r2.test/video.mp4'; } },
});

const { loadReportPage } = await import('../app/reports/[videoId]/(report)/load-report.ts');
const { buildReportView } = await import('./support/report-view.mjs');
const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  signed.length = 0;
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a', R2_ACCESS_KEY: 'b', R2_SECRET_KEY: 'c', R2_BUCKET: 'd',
  });
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

function database(video = smoke.video) {
  const db = fakePostgrest({
    videos: [video], model_runs: [smoke.modelRun], incidents: [smoke.incident], review_status: [smoke.review],
    entities: smoke.entities, instruments: smoke.instruments, assets: smoke.assets, reports: [smoke.reportRow],
  }, { views: effectiveViews });
  globalThis.fetch = db.fetch;
  return db;
}

test('a stored run loads as the report view with a playback URL signed on the server', async () => {
  const db = database();
  const load = await loadReportPage(smoke.videoId, [smoke.modelRunId, 'ignored']);
  assert.equal(load.kind, 'found');
  assert.deepEqual(JSON.parse(JSON.stringify(load.report)), JSON.parse(JSON.stringify(buildReportView({ ...effectiveRowsOfAiRun(smoke), playbackUrl: 'https://signed.r2.test/video.mp4' }))));
  assert.deepEqual(signed, [smoke.video.filepath]);
  assert.ok(db.requests.every((request) => request.method === 'GET'), 'loading the page never writes');
});

test('a link without a run asks for one and reads nothing', async () => {
  const db = database();
  assert.deepEqual(await loadReportPage(smoke.videoId, undefined), { kind: 'missing-run' });
  assert.deepEqual(await loadReportPage(smoke.videoId, []), { kind: 'missing-run' });
  assert.equal(db.requests.length, 0);
});

test('an unknown run or video is not found', async () => {
  database();
  assert.deepEqual(await loadReportPage(smoke.videoId, 'm-unknown'), { kind: 'not-found' });
  assert.deepEqual(await loadReportPage('v-unknown', smoke.modelRunId), { kind: 'not-found' });
  assert.deepEqual(signed, []);
});

test('a load failure is the reason the page shows in place', async () => {
  globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
  const unreachable = await loadReportPage(smoke.videoId, smoke.modelRunId);
  assert.equal(unreachable.kind, 'failed');
  assert.match(unreachable.message, /fetch failed/);

  database({ ...smoke.video, filepath: null });
  assert.deepEqual(await loadReportPage(smoke.videoId, smoke.modelRunId), { kind: 'failed', message: 'The report has no linked R2 video' });

  delete process.env.INCIDENT_SUPABASE_URL;
  const unconfigured = await loadReportPage(smoke.videoId, smoke.modelRunId);
  assert.equal(unconfigured.kind, 'failed');
  assert.ok(unconfigured.message.length > 0);
});

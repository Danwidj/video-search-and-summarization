// SPDX-License-Identifier: Apache-2.0

// GET /api/reports/[videoId]?revision=...: the view of one revision with a signed playback URL.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class { send() { return Promise.resolve({}); } },
    GetObjectCommand: class { constructor(input) { this.input = input; } },
    PutObjectCommand: class { constructor(input) { this.input = input; } },
    HeadObjectCommand: class { constructor(input) { this.input = input; } },
    DeleteObjectCommand: class { constructor(input) { this.input = input; } },
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.r2.test/video.mp4' } });

const { GET } = await import('../src/app/api/reports/[videoId]/route.ts');
const { aiRevisionRow, buildReportView } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a', R2_ACCESS_KEY: 'b', R2_SECRET_KEY: 'c', R2_BUCKET: 'd',
  });
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const call = (query) => GET(new Request(`http://localhost/api/reports/${smoke.videoId}${query}`), { params: Promise.resolve({ videoId: smoke.videoId }) });

/** The smoke video with an AI revision (1) and a later human one (2); revision `official` is marked official. */
function database({ official = null, video = smoke.video, modelRuns = [smoke.modelRun] } = {}) {
  const human = { ...aiRevisionRow(smoke, { id: 2, revision_no: 2, kind: 'human', parent_id: 1, created_by: 'Lead', note: 'Checked' }) };
  human.payload = { ...human.payload, incident: { ...human.payload.incident, severity_level: 4 } };
  const db = fakePostgrest({
    videos: [{ ...video, official_revision_id: official }], model_runs: modelRuns, report_revisions: [aiRevisionRow(smoke), human],
  });
  globalThis.fetch = db.fetch;
  return db;
}

test('a revision ID that is not a positive whole number is 400', async () => {
  database();
  for (const bad of ['0', '-1', '1.5', 'abc']) assert.equal((await call(`?revision=${bad}`)).status, 400, bad);
});

test('the report is the view of the asked-for revision with a signed playback URL', async () => {
  database({ official: 1 });
  const response = await call('?revision=2');
  assert.equal(response.status, 200);
  const { report } = await response.json();
  assert.deepEqual([report.revisionId, report.revision.kind, report.revision.createdBy, report.structured.incident.severityLevel], [2, 'human', 'Lead', 4]);
  assert.equal(report.official.isOfficial, false);
  assert.equal(report.official.officialRevisionId, 1);
  assert.equal(report.run.playbackUrl, 'https://signed.r2.test/video.mp4');
  const expected = JSON.parse(JSON.stringify(buildReportView({ ...smoke, playbackUrl: 'https://signed.r2.test/video.mp4' }, { id: 1 })));
  assert.deepEqual((await (await call('?revision=1')).json()).report, { ...expected, official: { officialRevisionId: 1, isOfficial: true }, revision: { ...expected.revision, isOfficial: true } });
});

test('with no revision asked for, the official revision is shown, else the newest', async () => {
  database({ official: 1 });
  assert.equal((await (await call('')).json()).report.revisionId, 1);
  database();
  assert.equal((await (await call('')).json()).report.revisionId, 2);
});

test('a missing video or revision is 404', async () => {
  database();
  assert.equal((await call('?revision=9')).status, 404);
  database({ video: { ...smoke.video, id: 'someone-else' } });
  assert.equal((await call('')).status, 404);
});

test('a video without an R2 key is a 500 with the original message', async () => {
  database({ video: { ...smoke.video, filepath: null } });
  const response = await call('?revision=1');
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: 'The report has no linked R2 video' });
});

test('a revision whose run is not recorded still renders from its payload', async () => {
  database({ modelRuns: [] });
  const { report } = await (await call('?revision=1')).json();
  assert.equal(report.modelOutput, null);
  assert.equal(report.run.model, 'Unknown model');
  assert.equal(report.structured.incident.type, 'assault');
});

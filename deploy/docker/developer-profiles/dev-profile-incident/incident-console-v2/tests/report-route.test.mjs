// SPDX-License-Identifier: Apache-2.0

// Characterisation test for GET /api/reports/[videoId]?run=..., written against
// the pre-refactor route so the hexagonal migration can prove no behaviour change.

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

const { GET } = await import('../app/api/reports/[videoId]/route.ts');
const { buildReportView } = await import('../lib/adapters/supabase/mappers/report.ts');
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

function database(overrides = {}) {
  const rows = { ...smoke, video: { ...smoke.video, selected_model_run_id: smoke.modelRunId, selected_by: 'Lead', selected_at: '2026-10-01T00:00:00' }, ...overrides };
  const requests = [];
  globalThis.fetch = async (url) => {
    const parsed = new URL(String(url));
    const table = parsed.pathname.replace('/rest/v1/', '');
    requests.push(`${table}?${parsed.searchParams}`);
    const one = (row) => new Response(JSON.stringify(row ? [row] : []));
    if (table === 'model_runs') return one(rows.modelRun);
    if (table === 'videos') return one(rows.video);
    if (table === 'review_status') return one(rows.review);
    if (table === 'incidents') return one(rows.incident);
    if (table === 'reports') return one(rows.reportRow);
    if (table in { entities: 1, instruments: 1, assets: 1 }) return new Response(JSON.stringify(rows[table]));
    return new Response('[]');
  };
  return { rows, requests };
}

test('a run ID is required', async () => {
  assert.equal((await call('')).status, 400);
});

test('the report is the view built from the run rows with a signed playback URL', async () => {
  const { rows, requests } = database();
  const response = await call(`?run=${smoke.modelRunId}`);
  assert.equal(response.status, 200);
  const expected = JSON.parse(JSON.stringify(buildReportView({ ...rows, playbackUrl: 'https://signed.r2.test/video.mp4' })));
  assert.deepEqual((await response.json()).report, expected);
  assert.equal(expected.official.isOfficial, true);
  assert.equal(requests.length, 8);
});

test('a missing incident, run or video is 404', async () => {
  for (const missing of ['incident', 'modelRun', 'video']) {
    database({ [missing]: null });
    assert.equal((await call(`?run=${smoke.modelRunId}`)).status, 404, missing);
  }
});

test('a video without an R2 key is a 500 with the original message', async () => {
  database({ video: { ...smoke.video, filepath: null } });
  const response = await call(`?run=${smoke.modelRunId}`);
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: 'The report has no linked R2 video' });
});

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const deletedObjects = [];
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class { send(command) { deletedObjects.push(command.input?.Key); return Promise.resolve({}); } },
    GetObjectCommand: class { constructor(input) { this.input = input; } },
    PutObjectCommand: class { constructor(input) { this.input = input; } },
    HeadObjectCommand: class { constructor(input) { this.input = input; } },
    DeleteObjectCommand: class { constructor(input) { this.input = input; } },
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.test/x' } });

const { DELETE } = await import('../src/app/api/reports/[videoId]/delete/route.ts');
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a', R2_ACCESS_KEY: 'b', R2_SECRET_KEY: 'c', R2_BUCKET: 'd',
  });
  deletedObjects.length = 0;
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const attempt = (id, videoId, status) => ({
  id,
  notes: JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status, contractVersion: 'incident-contract-v3', videoId, request: {}, response: null, validation: { firstPass: [] }, repair: null } }),
});

const call = () => DELETE(new Request('http://localhost/api/reports/v-target/delete', { method: 'DELETE' }), { params: Promise.resolve({ videoId: 'v-target' }) });

test('deleting a video removes its objects, the video row, and the run records that name only it and no revision uses', async () => {
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    const table = parsed.pathname.replace('/rest/v1/', '');
    if (init.method === 'DELETE') { deletes.push(`${table}?${parsed.searchParams}`); return new Response(null, { status: 204 }); }
    if (table === 'videos') return new Response(JSON.stringify([{ id: 'v-target', filepath: 'uploads/s/v.mp4' }]));
    if (table === 'model_runs') {
      assert.match(parsed.searchParams.get('notes'), /^like\.\*"videoId":"v-target"\*$/);
      return new Response(JSON.stringify([
        attempt('m-failed', 'v-target', 'contract_failed'),
        attempt('m-request', 'v-target', 'request_failed'),
        attempt('m-other-video', 'v-target-2', 'contract_failed'),
        attempt('m-valid', 'v-target', 'valid_first_pass'),
        { id: 'm-legacy', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v-target', incident_type: 'burglary' } } }) },
        { id: 'm-legacy-other', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v-target-2' } } }) },
        { id: 'm-mentions', notes: JSON.stringify({ incidentConsoleV2: { contractVersion: 'incident-contract-v3', note: '"videoId":"v-target"' } }) },
        attempt('m-used', 'v-target', 'valid_first_pass'),
      ]));
    }
    if (table === 'report_revisions') {
      return new Response(JSON.stringify(parsed.searchParams.get('model_run_id') === 'eq.m-used' ? [{ id: 9 }] : []));
    }
    return new Response('[]');
  };

  const response = await call();

  assert.equal(response.status, 200);
  assert.deepEqual(deletes.filter((d) => d.startsWith('model_runs')).sort(), ['model_runs?id=eq.m-failed', 'model_runs?id=eq.m-legacy', 'model_runs?id=eq.m-request', 'model_runs?id=eq.m-valid']);
  assert.ok(deletes.indexOf('videos?id=eq.v-target') < deletes.indexOf('model_runs?id=eq.m-failed'), 'the video (and its cascaded revisions) goes first');
  assert.deepEqual(deletedObjects.sort(), ['thumbnails/uploads/s/v.mp4.webp', 'uploads/s/v.mp4'], 'only the video object and its thumbnail; evidence images stay');
});

test('a video without a stored object is refused and nothing is deleted', async () => {
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    if (init.method === 'DELETE') deletes.push(String(url));
    return new Response(JSON.stringify([{ id: 'v-target', filepath: null }]));
  };
  assert.notEqual((await call()).status, 200);
  assert.deepEqual(deletes, []);
});

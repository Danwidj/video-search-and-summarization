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

const { DELETE } = await import('../app/api/reports/[videoId]/delete/route.ts');
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
  notes: JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status, contractVersion: 'incident-contract-v2', videoId, request: {}, response: null, validation: { firstPass: [] }, repair: null } }),
});

test('deleting a video removes only failed attempts that explicitly name that video and have no incident', async () => {
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
        { id: 'm-mentions', notes: JSON.stringify({ incidentConsoleV2: { contractVersion: 'incident-contract-v2', note: '"videoId":"v-target"' } }) },
        attempt('m-has-incident', 'v-target', 'contract_failed'),
      ]));
    }
    if (table === 'incidents') {
      const run = parsed.searchParams.get('model_run_id');
      return new Response(JSON.stringify(run === 'eq.m-has-incident' ? [{ incident_id: 'v-target' }] : []));
    }
    return new Response('[]');
  };

  const response = await DELETE(new Request('http://localhost/api/reports/v-target/delete?run=m-valid&deleteVideo=true', { method: 'DELETE' }), { params: Promise.resolve({ videoId: 'v-target' }) });

  assert.equal(response.status, 200);
  assert.deepEqual(deletes.filter((d) => d.startsWith('model_runs')).sort(), ['model_runs?id=eq.m-failed', 'model_runs?id=eq.m-request']);
  assert.ok(deletes.includes('videos?id=eq.v-target'));
});

test('deleting a single report does not touch attempt records', async () => {
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    if (init.method === 'DELETE') deletes.push(parsed.pathname.replace('/rest/v1/', ''));
    return new Response('[]');
  };
  const response = await DELETE(new Request('http://localhost/api/reports/v-target/delete?run=m-valid', { method: 'DELETE' }), { params: Promise.resolve({ videoId: 'v-target' }) });
  assert.equal(response.status, 200);
  assert.deepEqual(deletes, ['incidents']);
});

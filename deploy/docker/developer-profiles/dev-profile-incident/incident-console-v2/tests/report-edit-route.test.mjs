// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);
const { PATCH } = await import('../app/api/reports/[videoId]/edit/route.ts');
const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
});

afterEach(() => {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) delete process.env[key];
    else process.env[key] = originalEnv[key];
  }
  globalThis.fetch = originalFetch;
});

test('report edits send only changed fields to the atomic Supabase RPC', async () => {
  let rpcBody;
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), 'https://supabase.test/rest/v1/rpc/apply_incident_report_patch');
    rpcBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ title: 'Corrected title' }), { status: 200 });
  };

  const response = await PATCH(new Request('http://localhost/api/reports/video-1/edit', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      modelRunId: 'run-1',
      originalReport: { title: 'Original title', description: 'unchanged', assets: [{ name: 'door' }] },
      editedReport: { title: 'Corrected title', description: 'unchanged', assets: [{ name: 'door' }] },
    }),
  }), { params: Promise.resolve({ videoId: 'video-1' }) });

  assert.equal(response.status, 200);
  assert.equal(rpcBody.p_incident_id, 'video-1');
  assert.equal(rpcBody.p_model_run_id, 'run-1');
  assert.deepEqual(rpcBody.p_report_patch, { title: 'Corrected title' });
});

test('unchanged report does not make a partial or redundant database write', async () => {
  let called = false;
  globalThis.fetch = async () => { called = true; return new Response('{}'); };
  const report = { title: 'Same title', description: 'same' };
  const response = await PATCH(new Request('http://localhost/api/reports/video-1/edit', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ modelRunId: 'run-1', originalReport: report, editedReport: report }),
  }), { params: Promise.resolve({ videoId: 'video-1' }) });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).unchanged, true);
  assert.equal(called, false);
});

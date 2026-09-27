// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';
register('./support/alias-loader.mjs', import.meta.url);
const { GET } = await import('../app/api/dashboard/route.ts');
const originalEnv = { ...process.env }; const originalFetch = globalThis.fetch;
beforeEach(() => { process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test'; process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key'; });
afterEach(() => { for (const key of Object.keys(process.env)) { if (!(key in originalEnv)) delete process.env[key]; else process.env[key] = originalEnv[key]; } globalThis.fetch = originalFetch; });

test('dashboard sends period and cross-filters to one analytics RPC', async () => {
  let body;
  globalThis.fetch = async (url, init) => { assert.equal(String(url), 'https://supabase.test/rest/v1/rpc/get_incident_dashboard'); body = JSON.parse(String(init?.body)); return new Response(JSON.stringify({ total: 4, types: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } }); };
  const response = await GET(new Request('http://localhost/api/dashboard?days=7&type=animal&severity=high&day=2&hour=23'));
  assert.equal(response.status, 200); assert.equal(body.p_type, 'animal'); assert.equal(body.p_severity, 'high'); assert.equal(body.p_day_of_week, 2); assert.equal(body.p_hour, 23); assert.ok(body.p_period_start); assert.ok(body.p_period_end);
});

test('dashboard rejects invalid heatmap coordinates before Supabase', async () => {
  let called = false; globalThis.fetch = async () => { called = true; return new Response('{}'); };
  const response = await GET(new Request('http://localhost/api/dashboard?hour=24'));
  assert.equal(response.status, 400); assert.equal(called, false);
});

test('dashboard period bounds are read as UTC whatever the server time zone', async () => {
  const { GET: dashboard } = await import('../app/api/dashboard/route.ts');
  let body;
  globalThis.fetch = async (_url, init) => { body = JSON.parse(String(init?.body)); return new Response(JSON.stringify({ total: 0 })); };
  const response = await dashboard(new Request('http://localhost/api/dashboard?days=30&after=2026-08-28T11:00:00.000&before=2026-09-27T11:00:00.000'));
  assert.equal(response.status, 200);
  assert.equal(body.p_period_start, '2026-08-28T11:00:00.000');
  assert.equal(body.p_period_end, '2026-09-27T11:00:00.000');
});

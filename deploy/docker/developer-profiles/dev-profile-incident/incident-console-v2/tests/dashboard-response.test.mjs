// SPDX-License-Identifier: Apache-2.0

// Characterisation test for GET /api/dashboard's response, written against the
// pre-refactor route: get_incident_dashboard's result, in the shape its SQL
// builds (supabase/migrations/20261020000000_finals_baseline.sql), reaches the
// browser unchanged, and the checks run in the same order.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { GET } = await import('../src/app/api/dashboard/route.ts');

const analytics = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));
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

function serve(result) {
  const bodies = [];
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), 'https://supabase.test/rest/v1/rpc/get_incident_dashboard');
    bodies.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  return bodies;
}

test('the analytics reach the browser exactly as get_incident_dashboard returns them', async () => {
  const bodies = serve(analytics);
  const response = await GET(new Request('http://localhost/api/dashboard?days=30&after=2026-08-30T00:00:00.000&before=2026-09-29T00:00:00.000&timezone=Asia%2FSingapore'));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { analytics });
  assert.deepEqual(bodies, [{
    p_period_start: '2026-08-30T00:00:00.000',
    p_period_end: '2026-09-29T00:00:00.000',
    p_type: null,
    p_severity: null,
    p_day_of_week: null,
    p_hour: null,
    p_timezone: 'Asia/Singapore',
  }]);
});

test('an all-time dashboard sends no period and keeps the null comparison and a heatmap cell without a time', async () => {
  // The SQL emits a null day and hour for an official report without generated_datetime.
  const allTime = { ...analytics, previous: null, averageConfidence: null, confidenceNotProvided: 3, heatmap: [...analytics.heatmap, { day: null, hour: null, count: 1 }] };
  const bodies = serve(allTime);
  const response = await GET(new Request('http://localhost/api/dashboard?days=all&type=%20assault%20&severity=high&day=2&hour=23'));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { analytics: allTime });
  assert.deepEqual(bodies, [{ p_period_start: null, p_period_end: null, p_type: 'assault', p_severity: 'high', p_day_of_week: 2, p_hour: 23, p_timezone: 'UTC' }]);
});

test('a database failure is a 500 with its message, and the configuration is checked between the filter checks', async () => {
  globalThis.fetch = async () => new Response('{"message":"boom"}', { status: 500 });
  const failed = await GET(new Request('http://localhost/api/dashboard'));
  assert.equal(failed.status, 500);
  assert.match((await failed.json()).error, /^PostgREST returned HTTP 500/);

  delete process.env.INCIDENT_SUPABASE_URL;
  assert.equal((await GET(new Request('http://localhost/api/dashboard?days=9'))).status, 400, 'period, severity and timezone are checked first');
  for (const query of ['', '?day=7', '?after=not-a-date']) {
    const unconfigured = await GET(new Request(`http://localhost/api/dashboard${query}`));
    assert.equal(unconfigured.status, 500, query);
    assert.deepEqual(await unconfigured.json(), { error: 'Supabase PostgREST is not configured' });
  }
});

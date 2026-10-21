// SPDX-License-Identifier: Apache-2.0

// Characterisation test for PATCH /api/reports/[videoId]/review, written against
// the pre-refactor route so the hexagonal migration can prove no behaviour change.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../app/api/reports/[videoId]/review/route.ts');
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => { Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' }); });
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const call = (body) => PATCH(new Request('http://localhost/x', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { params: Promise.resolve({ videoId: 'v1' }) });

/** incidents and review_status reads, and set_review_status as the finals baseline returns it. */
function database({ incident = { incident_id: 'v1', model_run_id: 'm1' }, review = null, refusal = null } = {}) {
  const writes = [];
  const fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    const table = parsed.pathname.replace('/rest/v1/', '');
    if (init.method === 'POST') {
      const body = JSON.parse(String(init.body));
      writes.push({ table, body });
      if (table !== 'rpc/set_review_status') return new Response('[]');
      if (refusal) return new Response(JSON.stringify({ code: 'P0001', details: null, hint: null, message: refusal }), { status: 400 });
      const base = { incidentId: body.p_incident_id, modelRunId: body.p_model_run_id, status: body.p_status };
      if ((review?.status ?? 'unreviewed') === body.p_status) return new Response(JSON.stringify({ ...base, changed: false }));
      const verified = body.p_status === 'verified';
      return new Response(JSON.stringify({
        ...base, verifiedBy: verified ? body.p_reviewer : null, verifiedAt: verified ? '2026-10-21T01:02:03.456789' : null, changed: true, humanVersionCreated: verified,
      }));
    }
    if (table === 'incidents') return new Response(JSON.stringify(incident ? [incident] : []));
    if (table === 'review_status') return new Response(JSON.stringify(review ? [review] : []));
    return new Response('[]');
  };
  return { fetch, writes };
}

const rpcCall = (status) => ({ table: 'rpc/set_review_status', body: { p_incident_id: 'v1', p_model_run_id: 'm1', p_status: status, p_reviewer: 'R' } });

test('invalid input is rejected before Supabase', async () => {
  let called = false;
  globalThis.fetch = async () => { called = true; return new Response('[]'); };
  assert.equal((await call({ status: 'verified', reviewedBy: 'R' })).status, 400);
  assert.equal((await call({ modelRunId: 'm1', status: 'approved', reviewedBy: 'R' })).status, 400);
  assert.equal((await call({ modelRunId: 'm1', status: 'verified', reviewedBy: '  ' })).status, 400);
  assert.equal(called, false);
});

test('a run without an incident is 404 and writes nothing', async () => {
  const db = database({ incident: null });
  globalThis.fetch = db.fetch;
  const response = await call({ modelRunId: 'm1', status: 'verified', reviewedBy: 'R' });
  assert.equal(response.status, 404);
  assert.deepEqual(db.writes, []);
});

test('an unchanged status is acknowledged; set_review_status decides it and writes nothing', async () => {
  const db = database({ review: { incident_id: 'v1', model_run_id: 'm1', status: 'verified' } });
  globalThis.fetch = db.fetch;
  const response = await call({ modelRunId: 'm1', status: 'verified', reviewedBy: ' R ' });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'verified', reviewedBy: 'R' });
  assert.deepEqual(db.writes, [rpcCall('verified')]);
});

test('each status change is one set_review_status call; review_status is never written directly', async () => {
  for (const status of ['verified', 'under review', 'unreviewed']) {
    const db = database({ review: { incident_id: 'v1', model_run_id: 'm1', status: status === 'verified' ? 'unreviewed' : 'verified' } });
    globalThis.fetch = db.fetch;
    const response = await call({ modelRunId: 'm1', status, reviewedBy: 'R' });
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.status, status);
    assert.equal(payload.reviewedBy, 'R');
    // Verifying reports the stored verification time; other changes the time of the request.
    if (status === 'verified') assert.equal(payload.reviewedAt, '2026-10-21T01:02:03.456789');
    else assert.match(payload.reviewedAt, /^\d{4}-\d\d-\d\dT.*Z$/);
    assert.deepEqual(db.writes, [rpcCall(status)]);
  }
});

test('verifying an AI report the database refuses as it stands is a 422 with its reason, not a 500', async () => {
  const refusal = 'The AI report of run m1 cannot be verified as it stands (type fighting, window 0:15-1:05, severity 3); edit it first';
  const db = database({ refusal });
  globalThis.fetch = db.fetch;
  const response = await call({ modelRunId: 'm1', status: 'verified', reviewedBy: 'R' });
  assert.equal(response.status, 422);
  assert.deepEqual(await response.json(), { error: refusal });
});

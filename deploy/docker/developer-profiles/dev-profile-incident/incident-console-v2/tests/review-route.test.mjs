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

function database({ incident = { incident_id: 'v1', model_run_id: 'm1' }, review = null } = {}) {
  const writes = [];
  const fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    const table = parsed.pathname.replace('/rest/v1/', '');
    if (init.method === 'POST') { writes.push({ table, onConflict: parsed.searchParams.get('on_conflict'), body: JSON.parse(String(init.body)) }); return new Response('[]'); }
    if (table === 'incidents') return new Response(JSON.stringify(incident ? [incident] : []));
    if (table === 'review_status') return new Response(JSON.stringify(review ? [review] : []));
    return new Response('[]');
  };
  return { fetch, writes };
}

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

test('an unchanged status is acknowledged without a write', async () => {
  const db = database({ review: { incident_id: 'v1', model_run_id: 'm1', status: 'verified' } });
  globalThis.fetch = db.fetch;
  const response = await call({ modelRunId: 'm1', status: 'verified', reviewedBy: ' R ' });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'verified', reviewedBy: 'R' });
  assert.deepEqual(db.writes, []);
});

test('verifying stamps verifier and editor; other statuses clear the verifier', async () => {
  for (const status of ['verified', 'under review', 'unreviewed']) {
    const db = database({ review: { incident_id: 'v1', model_run_id: 'm1', status: status === 'verified' ? 'unreviewed' : 'verified' } });
    globalThis.fetch = db.fetch;
    const response = await call({ modelRunId: 'm1', status, reviewedBy: 'R' });
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.status, status);
    assert.equal(payload.reviewedBy, 'R');
    assert.match(payload.reviewedAt, /^\d{4}-\d\d-\d\dT/);
    assert.equal(db.writes.length, 1);
    const [write] = db.writes;
    assert.equal(write.table, 'review_status');
    assert.equal(write.onConflict, 'incident_id,model_run_id');
    assert.deepEqual(write.body, {
      incident_id: 'v1', model_run_id: 'm1', status, edited_by: 'R', edited_at: payload.reviewedAt,
      verified_by: status === 'verified' ? 'R' : null, verified_at: status === 'verified' ? payload.reviewedAt : null,
    });
  }
});

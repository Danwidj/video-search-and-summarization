// SPDX-License-Identifier: Apache-2.0

// The suggestions routes' request handling: validation, and the answers that need no database row.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const list = await import('../src/app/api/suggestions/route.ts');
const evaluate = await import('../src/app/api/suggestions/evaluate/route.ts');
const accept = await import('../src/app/api/suggestions/[suggestionId]/accept/route.ts');
const reject = await import('../src/app/api/suggestions/[suggestionId]/reject/route.ts');

const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' });
  delete process.env.INCIDENT_AGENT_BASE_URL;
});
afterEach(() => {
  process.env = { ...originalEnv };
});

const json = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const params = (suggestionId) => ({ params: Promise.resolve({ suggestionId }) });

test('GET rejects an incidentId that is not a positive integer', async () => {
  for (const bad of ['abc', '0', '-1', '1.5']) {
    const response = await list.GET(new Request(`http://localhost/api/suggestions?incidentId=${bad}`));
    assert.equal(response.status, 400, bad);
  }
});

test('evaluate rejects a missing or unknown body field', async () => {
  for (const body of [{}, { incidentId: 'x' }, { incidentId: 1, extra: true }, null]) {
    const response = await evaluate.POST(new Request('http://localhost/api/suggestions/evaluate', json(body)));
    assert.equal(response.status, 400);
  }
});

test('evaluate answers 503 when the agent is not configured', async () => {
  const response = await evaluate.POST(new Request('http://localhost/api/suggestions/evaluate', json({ incidentId: 1 })));
  assert.equal(response.status, 503);
});

test('accept and reject reject a bad suggestion id, and accept a bad body', async () => {
  for (const id of ['abc', '0']) {
    assert.equal((await accept.POST(new Request('http://localhost/x', json({})), params(id))).status, 400);
    assert.equal((await reject.POST(new Request('http://localhost/x', { method: 'POST' }), params(id))).status, 400);
  }
  assert.equal((await accept.POST(new Request('http://localhost/x', json({ incidentId: 'x' })), params('1'))).status, 400);
  assert.equal((await accept.POST(new Request('http://localhost/x', { method: 'POST', body: 'not json' }), params('1'))).status, 400);
});

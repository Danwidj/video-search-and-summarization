// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../app/api/reports/[videoId]/edit/route.ts');
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function patch(editedReport) {
  return PATCH(
    new Request('http://localhost/api/reports/v1/edit', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modelRunId: 'run-1', editedReport }),
    }),
    { params: Promise.resolve({ videoId: 'v1' }) },
  );
}

test('an edit that breaks the contract is a 400 and never reaches the database', async () => {
  let dbCalled = false;
  globalThis.fetch = async () => { dbCalled = true; return new Response('[]'); };
  const response = await patch({
    incident: {
      type: 'assault', title: 't', start_timestamp: 5, end_timestamp: 9, description: 'd', severity_level: 2,
      severity_reason: 'r', confidence_score: null, location: null,
    },
    entities: [], instruments: [], assets: [], uncertainties: [],
    timeline: [{ start_seconds: 1, end_seconds: null, description: 'before the incident window' }],
  });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /does not match the incident contract.*outside/);
  assert.equal(dbCalled, false);
});

test('an old-shape edit (persons, flat fields) is rejected', async () => {
  const response = await patch({ title: 't', incident_type: 'assault', persons: [] });
  assert.equal(response.status, 400);
});

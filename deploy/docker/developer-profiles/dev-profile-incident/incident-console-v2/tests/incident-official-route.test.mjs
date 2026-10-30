// SPDX-License-Identifier: Apache-2.0

// PUT/DELETE /api/videos/[videoId]/official (the segment is the incident id): marking a revision official embeds its
// evidence per camera through the agent (mocked here) and rebuilds the incident's crops; clearing rebuilds them from
// the newest revision.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PUT, DELETE } = await import('../src/app/api/videos/[videoId]/official/route.ts');
const { A, B, incidentDatabase, withAgent, writes } = await import('./support/incident-write-fixture.mjs');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    INCIDENT_AGENT_BASE_URL: 'http://agent.test:8000/',
  });
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const params = (id) => ({ params: Promise.resolve({ videoId: id }) });
const put = (body, id = '1') =>
  PUT(new Request('http://localhost/x', { method: 'PUT', body: typeof body === 'string' ? body : JSON.stringify(body) }), params(id));
const del = (id = '1') => DELETE(new Request('http://localhost/x', { method: 'DELETE' }), params(id));
const cropsOf = (db) => db.store.evidence_crops.map((crop) => [crop.revision_id, crop.video_id, crop.item_id]).sort();

test('marking a revision official embeds each camera and rebuilds the incident crops against it', async () => {
  const db = incidentDatabase();
  const agentCalls = withAgent(db);
  db.store.evidence_crops.push({ revision_id: 1, video_id: A, item_type: 'entity', item_id: 'STALE', image: 'x' });

  const response = await put({ revisionId: 1 });

  assert.equal(response.status, 200);
  const { official } = await response.json();
  assert.deepEqual([official.incidentId, official.officialRevisionId], [1, 1]);
  assert.ok(official.officialSince);
  assert.equal(agentCalls.length, 2, 'one embedding call per camera');
  assert.deepEqual(cropsOf(db), [
    [1, A, 'E1'],
    [1, B, 'E1'],
  ]);
  assert.deepEqual(
    writes(db).map((r) => r.path),
    ['rpc/set_official_revision', 'rpc/set_revision_crops'],
    'embedded first, then marked, then the crops',
  );
});

test('clearing the official revision sets it null and rebuilds the crops from the newest revision', async () => {
  const db = incidentDatabase({ official: 1 });
  const agentCalls = withAgent(db);
  const response = await del();
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).official, { incidentId: 1, officialRevisionId: null, officialSince: null });
  assert.equal(db.store.incidents[0].official_revision_id, null);
  assert.equal(agentCalls.length, 2);
  assert.deepEqual(cropsOf(db), [
    [1, A, 'E1'],
    [1, B, 'E1'],
  ]);
});

test('clearing still succeeds when the crops cannot be rebuilt', async () => {
  const db = incidentDatabase({ official: 1 });
  withAgent(db, { agent: () => new Response('down', { status: 502 }) });
  const response = await del();
  assert.equal(response.status, 200);
  assert.equal(db.store.incidents[0].official_revision_id, null);
});

test('a missing revision or incident is 404 and a malformed body or id is 400, and none reaches the agent or the database', async () => {
  const db = incidentDatabase();
  const agentCalls = withAgent(db);
  assert.equal((await put({ revisionId: 9 })).status, 404);
  assert.equal((await put({ revisionId: 1 }, '7')).status, 404);
  assert.equal((await put({ revisionId: 'x' })).status, 400);
  assert.equal((await put('not json')).status, 400);
  assert.equal((await put({ revisionId: 1 }, 'abc')).status, 400);
  assert.equal((await del('abc')).status, 400);
  assert.equal(agentCalls.length, 0);
  assert.equal(writes(db).length, 0);
});

test('an agent failure leaves the incident without an official revision', async () => {
  const db = incidentDatabase();
  withAgent(db, { agent: () => new Response('{"detail":"boom"}', { status: 500 }) });
  const response = await put({ revisionId: 1 });
  assert.equal(response.status, 500);
  assert.equal(db.store.incidents[0].official_revision_id, null);
  assert.equal(writes(db).length, 0);
});

test('an unreachable agent is a 503 with a plain-language message and nothing is written', async () => {
  const db = incidentDatabase();
  withAgent(db, {
    agent: () => {
      throw new TypeError('fetch failed');
    },
  });
  const response = await put({ revisionId: 1 });
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /agent service is not reachable/);
  assert.equal(db.store.incidents[0].official_revision_id, null);
  assert.equal(writes(db).length, 0);
});

test('when storing the crops fails, the previous official revision is put back', async () => {
  const db = incidentDatabase({ official: 1 });
  db.store.report_revisions.push({
    ...db.store.report_revisions[0],
    id: 2,
    revision_no: 2,
    kind: 'human',
    parent_id: 1,
    created_by: 'Rev',
  });
  withAgent(db);
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) =>
    String(url).includes('rpc/set_revision_crops') ? new Response('{"message":"boom"}', { status: 500 }) : realFetch(url, init);

  const response = await put({ revisionId: 2 });

  assert.equal(response.status, 500);
  assert.equal(db.store.incidents[0].official_revision_id, 1, 'restored to the previous official revision');
});

test('an image-less revision is marked official with no embedding call and no crops', async () => {
  const db = incidentDatabase({ evidence: [] });
  const agentCalls = withAgent(db);
  const response = await put({ revisionId: 1 });
  assert.equal(response.status, 200);
  assert.equal(agentCalls.length, 0);
  assert.deepEqual(cropsOf(db), []);
});

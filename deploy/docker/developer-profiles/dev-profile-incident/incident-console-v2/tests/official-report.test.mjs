// SPDX-License-Identifier: Apache-2.0

// PUT/DELETE /api/videos/[videoId]/official: marking a revision official embeds its
// evidence through the agent (mocked here) and rebuilds the incident's evidence_crops.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PUT, DELETE } = await import('../app/api/videos/[videoId]/official/route.ts');
const { aiRevisionRow, buildReportView } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { revisionRpcs } = await import('./support/revisions-database.mjs');
const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k', INCIDENT_AGENT_BASE_URL: 'http://agent.test:8000/' });
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const vector = (seed) => Array.from({ length: 1024 }, (_, index) => seed + index / 10_000);
const IMAGE = `evidence/${repaired.videoId}/u1/E1.jpg`;

/** PostgREST (fake) plus the agent's evidence-embeddings endpoint, one fetch for both. */
function services({ agent = async () => new Response(JSON.stringify([{ item_type: 'entity', item_id: 'E1', embedding: vector(1) }])) } = {}) {
  const revision = aiRevisionRow(repaired);
  revision.evidence = [{ item_type: 'entity', item_id: 'E1', image: IMAGE, bounding_box: [1, 2, 3, 4], timestamp_seconds: 2 }, { item_type: 'asset', item_id: 'A1', image: null }];
  const db = fakePostgrest(
    { videos: [{ ...repaired.video, official_revision_id: null }], report_revisions: [revision], evidence_crops: [] },
    { rpc: revisionRpcs },
  );
  const agentCalls = [];
  globalThis.fetch = async (url, init = {}) => {
    if (String(url).startsWith('http://agent.test')) {
      agentCalls.push({ url: String(url), body: JSON.parse(String(init.body)) });
      return agent();
    }
    return db.fetch(url, init);
  };
  return { db, agentCalls };
}

const call = (handler, body) => handler(new Request('http://localhost/x', { method: handler === PUT ? 'PUT' : 'DELETE', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }), { params: Promise.resolve({ videoId: repaired.videoId }) });

test('marking a revision official embeds its evidence through the agent and rebuilds that incident\'s crops', async () => {
  const { db, agentCalls } = services();
  const response = await call(PUT, { revisionId: 1 });
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).official, { videoId: repaired.videoId, officialRevisionId: 1, crops: 1 });
  assert.deepEqual(agentCalls, [{ url: 'http://agent.test:8000/api/v1/incidents/evidence-embeddings', body: { revision_id: 1 } }]);
  const rpcs = db.requests.filter((r) => r.path.startsWith('rpc/'));
  assert.deepEqual(rpcs.map((r) => r.path), ['rpc/set_official_revision']);
  const crops = rpcs[0].body.p_crops;
  assert.deepEqual(crops.map((e) => [e.item_type, e.item_id, e.embedding.length]), [['entity', 'E1', 1024]]);
  assert.deepEqual([crops[0].item_name, crops[0].bounding_box, crops[0].timestamp_seconds], ['human', [1, 2, 3, 4], 2]);
  assert.equal(crops[0].description, 'Person attacking victim with object');
  assert.deepEqual(db.store.evidence_crops.map((c) => [c.revision_id, c.item_id, c.image]), [[1, 'E1', IMAGE]]);
  assert.equal(db.store.videos[0].official_revision_id, 1);
});

test('clearing the official revision sets it null and clears the crops without calling the agent', async () => {
  const { db, agentCalls } = services();
  await call(PUT, { revisionId: 1 });
  const response = await call(DELETE);
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).official, { videoId: repaired.videoId, officialRevisionId: null, crops: 0 });
  assert.equal(agentCalls.length, 1, 'only the marking asked the agent');
  assert.deepEqual(db.store.evidence_crops, []);
  assert.equal(db.store.videos[0].official_revision_id, null);
});

test('a missing revision is 404 and a malformed body is 400, and neither reaches the agent', async () => {
  const { agentCalls } = services();
  assert.equal((await call(PUT, { revisionId: 9 })).status, 404);
  assert.equal((await call(PUT, {})).status, 400);
  assert.equal((await call(PUT, { revisionId: 1, markedBy: 'x' })).status, 400);
  assert.equal(agentCalls.length, 0, 'the agent is asked only for a revision that exists');
});

test('an agent failure or a malformed embedding leaves the incident without an official revision', async () => {
  for (const agent of [async () => new Response('boom', { status: 500 }), async () => new Response(JSON.stringify([{ item_type: 'entity', item_id: 'E1', embedding: [1, 2] }]))]) {
    const { db } = services({ agent });
    const response = await call(PUT, { revisionId: 1 });
    assert.equal(response.status, 500);
    assert.equal(db.store.videos[0].official_revision_id, null);
    assert.deepEqual(db.store.evidence_crops, []);
  }
});

test('an unreachable agent is a 503 with a plain-language message and leaves the incident without an official revision', async () => {
  const { db } = services({ agent: async () => { throw new TypeError('fetch failed'); } });
  const response = await call(PUT, { revisionId: 1 });
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /^The agent service is not reachable, so this report could not be made official\. /);
  assert.equal(db.store.videos[0].official_revision_id, null);
  assert.deepEqual(db.store.evidence_crops, []);
});

test('the report view marks the official revision explicitly and never infers it from recency', () => {
  const none = buildReportView(repaired);
  assert.deepEqual(none.official, { officialRevisionId: null, isOfficial: false });
  const withOfficial = (id) => ({ ...repaired, video: { ...repaired.video, official_revision_id: id } });
  const other = buildReportView(withOfficial(7));
  assert.deepEqual(other.official, { officialRevisionId: 7, isOfficial: false }, 'a newer revision is not official just because it is newer');
  assert.deepEqual(buildReportView(withOfficial(1)).official, { officialRevisionId: 1, isOfficial: true });
});

test('analysis code never writes the official pointer or rebuilds crops', async () => {
  for (const file of ['lib/analysis/persistence.ts', 'lib/analysis/run-contract-analysis.ts', 'app/api/analysis/route.ts', 'app/api/videos/[videoId]/runs/route.ts']) {
    const source = await readFile(join(process.cwd(), file), 'utf8');
    // Reads of videos.official_revision_id are fine; no object key assigning it, no RPC, no crops.
    assert.doesNotMatch(source, /[{,]\s*official_revision_id:|set_official_revision|evidence_crops/, file);
  }
});

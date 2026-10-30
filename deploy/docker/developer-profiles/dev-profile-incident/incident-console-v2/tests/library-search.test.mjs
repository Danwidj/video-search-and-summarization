// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {},
    GetObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    PutObjectCommand: class {},
    HeadObjectCommand: class {},
    DeleteObjectCommand: class {},
  },
});
mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_client, command) => `https://signed.r2.test/${command.input.Key}` },
});

const { fromAgentSearchResponse, toAgentSearchBody } = await import('../src/lib/adapters/agent/search.ts');
const { filterHits, groupByIncident, hitsInFrame, relationshipOf } = await import('../src/lib/library/search.ts');
const { POST } = await import('../src/app/api/search/route.ts');

const contractDir = join(process.cwd(), '..', 'contracts', 'search-contract-v1', 'fixtures', 'valid');
const full = JSON.parse(readFileSync(join(contractDir, 'full-response.json'), 'utf8'));
const summaries = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'report-summaries-rpc.json'), 'utf8'));

test('a request becomes the agent body with only what was set', () => {
  assert.deepEqual(toAgentSearchBody({ query: 'knife' }), { query: 'knife' });
  assert.deepEqual(
    toAgentSearchBody({
      query: 'knife',
      topK: 20,
      minSimilarity: 0,
      hideRejected: false,
      filters: { incidentTypes: ['assault'], itemTypes: ['instrument'], minSeverity: 3, incidentId: '12', videoName: 'v1' },
    }),
    {
      query: 'knife',
      top_k: 20,
      min_similarity: 0,
      hide_rejected: false,
      filters: { incident_types: ['assault'], min_severity: 3, item_types: ['instrument'], incident_id: 12, video_id: 'v1' },
    },
  );
});

test('the contract fixture maps to camelCase hits keyed by incident and run', () => {
  const result = fromAgentSearchResponse(full);
  assert.equal(result.queryId, 'q-search-9921');
  assert.equal(result.totalHits, 2);
  const [first] = result.hits;
  assert.equal(first.similarityScore, 0.89);
  assert.deepEqual(first.item.boundingBox, [320, 450, 510, 600]);
  assert.equal(first.item.holderEntityId, 'E1');
  assert.equal(first.incident.incidentId, 'Assault007_x264');
  assert.equal(first.incident.modelRunId, 'm86a5c319e26659804b0');
  assert.deepEqual(first.incident.incidentWindow, [10, 28]);
  assert.equal(first.critic.verdict, 'confirmed');
  assert.throws(() => fromAgentSearchResponse({ nothing: true }), /invalid search response/);
});

test('hits filter by threat and incident, group by incident and relate holder to item', () => {
  const { hits } = fromAgentSearchResponse(full);
  assert.equal(filterHits(hits, { minThreat: 1 }).length, hits.length);
  assert.ok(filterHits(hits, { minThreat: 5 }).every((hit) => (hit.item.threatLevel ?? 0) >= 5));
  const groups = groupByIncident(hits);
  assert.equal(
    groups.reduce((total, group) => total + group.hits.length, 0),
    hits.length,
  );
  assert.deepEqual(
    groups.map((group) => group.best),
    [...groups.map((group) => group.best)].sort((a, b) => b - a),
  );
  const instrument = hits.find((hit) => hit.item.holderEntityId);
  assert.equal(relationshipOf(instrument, hits).heldBy.itemId, instrument.item.holderEntityId);
  assert.ok(hitsInFrame(instrument, hits).includes(instrument));
});

const env = { ...process.env };
const fetchBefore = globalThis.fetch;
beforeEach(() => {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test';
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'key';
  process.env.R2_ACCOUNT_ID = 'a';
  process.env.R2_ACCESS_KEY = 'b';
  process.env.R2_SECRET_KEY = 'c';
  process.env.R2_BUCKET = 'd';
});
afterEach(() => {
  for (const key of Object.keys(process.env))
    if (!(key in env)) delete process.env[key];
    else process.env[key] = env[key];
  globalThis.fetch = fetchBefore;
});

const post = (body) => POST(new Request('http://localhost/api/search', { method: 'POST', body: JSON.stringify(body) }));

test("/api/search asks the agent for every ranked hit and adds each video's searched version", async () => {
  const agentBodies = [];
  globalThis.fetch = async (url, init) => {
    if (String(url) === 'http://agent.test/api/v1/incidents/search') {
      agentBodies.push(JSON.parse(String(init.body)));
      return new Response(
        JSON.stringify({
          ...full,
          hits: full.hits.map((hit) => ({ ...hit, incident: { ...hit.incident, incident_id: summaries.reports[0].videoId } })),
        }),
        { status: 200 },
      );
    }
    assert.match(String(url), /rpc\/list_incident_report_summaries$/);
    return new Response(JSON.stringify(summaries), { status: 200 });
  };
  const response = await post({ query: ' blade ' });
  assert.equal(response.status, 200);
  assert.deepEqual(agentBodies, [{ query: 'blade', top_k: 20, min_similarity: 0 }]);
  const body = await response.json();
  assert.equal(body.hits.length, 2);
  const version = body.versions[summaries.reports[0].videoId];
  assert.equal(version.revisionNo, summaries.reports[0].revisionNo);
  assert.equal(version.isOfficial, summaries.reports[0].isOfficial);
});

test('/api/search with an incidentId asks the agent for that incident only, and allows an empty query', async () => {
  const agentBodies = [];
  globalThis.fetch = async (url, init) => {
    if (String(url) === 'http://agent.test/api/v1/incidents/search') {
      agentBodies.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify(full), { status: 200 });
    }
    return new Response(JSON.stringify({ reports: [], total: 0 }), { status: 200 });
  };
  assert.equal((await post({ query: '', incidentId: '12' })).status, 200);
  assert.equal((await post({ query: ' knife ', incidentId: '12', videoName: 'front.mp4' })).status, 200);
  assert.equal((await post({ query: '', videoName: 'front.mp4' })).status, 200);
  assert.deepEqual(agentBodies, [
    { query: '', top_k: 50, min_similarity: 0, filters: { incident_id: 12 } },
    { query: 'knife', top_k: 50, min_similarity: 0, filters: { incident_id: 12, video_id: 'front.mp4' } },
    { query: '', top_k: 50, min_similarity: 0, filters: { video_id: 'front.mp4' } },
  ]);
  for (const incidentId of ['Assault007_x264', '0', '-3', '1.5']) {
    assert.equal((await post({ query: 'x', incidentId })).status, 400, incidentId);
  }
  assert.equal((await post({ query: 'x', videoName: 'v'.repeat(256) })).status, 400);
});

test('/api/search refuses empty text and a missing agent, and reports an agent failure', async () => {
  assert.equal((await post({ query: '  ' })).status, 400);
  delete process.env.INCIDENT_AGENT_BASE_URL;
  const missing = await post({ query: 'x' });
  assert.equal(missing.status, 500);
  assert.match((await missing.json()).error, /INCIDENT_AGENT_BASE_URL/);
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test';
  globalThis.fetch = async () => new Response('down', { status: 503 });
  const failed = await post({ query: 'x' });
  assert.equal(failed.status, 500);
  assert.match((await failed.json()).error, /HTTP 503/);
});

test('the viewer cuts its frame through the report frame route and falls back to the crop', () => {
  const viewer = readFileSync(join(process.cwd(), 'src', 'sections', 'library', 'components', 'HitViewer', 'HitViewer.tsx'), 'utf8');
  assert.match(viewer, /\/api\/reports\/\$\{encodeURIComponent\(hit\.incident\.incidentId\)\}\/frame\?t=/);
  assert.match(viewer, /<FrameViewer/);
  assert.match(viewer, /<EvidenceFrame/);
});

test('the evidence UI shows no critic verdict, and the incident card search loads that incident at once', () => {
  const dir = join(process.cwd(), 'src', 'sections', 'library', 'components');
  for (const file of ['HitCard/HitCard.tsx', 'HitViewer/HitViewer.tsx', 'EvidenceTab/EvidenceTab.tsx']) {
    assert.doesNotMatch(readFileSync(join(dir, file), 'utf8'), /critic|verdict|rejected/i, file);
  }
  const screen = readFileSync(join(dir, 'LibraryScreen', 'LibraryScreen.tsx'), 'utf8');
  assert.match(screen, /void searchEvidence\('', item\.videoId\)/);
  assert.match(screen, /searchEvidence\(evidenceQuery, scope\?\.incidentId \?\? null\)/);
});

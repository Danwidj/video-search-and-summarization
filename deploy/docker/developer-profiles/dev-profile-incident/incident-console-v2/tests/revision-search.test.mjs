// SPDX-License-Identifier: Apache-2.0

// "Find incidents" text search over saved revisions: the agent adapter, and the
// reports route's semantic path with its ILIKE fallback.

import assert from 'node:assert/strict';
import { register } from 'node:module';
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

const { fromAgentRevisionSearchResponse, toAgentRevisionSearchBody } = await import('../src/lib/adapters/agent/revision-search.ts');
const { GET } = await import('../src/app/api/reports/route.ts');
const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;

const AGENT_HIT = {
  incident_id: 2,
  revision_id: 41,
  video_id: 'v2',
  revision_no: 3,
  kind: 'ai',
  model_run_id: 'm2',
  title: 'Knife in a shop',
  description: 'A man holds a knife.',
  incident_type: 'assault',
  severity_level: 4,
  start_seconds: 6,
  end_seconds: 20,
  similarity_score: 0.83,
};
const RPC_ROWS = [
  {
    incidentId: 1,
    modelRunId: 'm1',
    title: 'Road accident',
    firstVideoKey: 'uploads/sensor-1/video.mp4',
    outcome: 'valid_after_structural_repair',
    isOfficial: true,
  },
  {
    incidentId: 2,
    modelRunId: 'm2',
    title: 'Knife in a shop',
    firstVideoKey: 'uploads/sensor-2/video.mp4',
    outcome: 'legacy',
    isOfficial: false,
  },
];

/** Routes the stubbed fetch: the RPC returns RPC_ROWS, the agent returns agentResponse (a status and body). */
function stubUpstream(agentResponse) {
  const calls = { rpc: [], agent: [] };
  globalThis.fetch = async (url, init) => {
    if (String(url).endsWith('/rpc/list_incident_report_summaries')) {
      const body = JSON.parse(String(init?.body));
      calls.rpc.push(body);
      return new Response(
        JSON.stringify({
          reports: body.p_search === null ? RPC_ROWS : RPC_ROWS.slice(1),
          totalItems: body.p_search === null ? RPC_ROWS.length : 1,
          incidentTypes: ['assault'],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }
    if (String(url) === 'https://agent.test/api/v1/incidents/revisions/search') {
      calls.agent.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify(agentResponse.body), {
        status: agentResponse.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  return calls;
}

beforeEach(() => {
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  process.env.INCIDENT_AGENT_BASE_URL = 'https://agent.test/';
  process.env.R2_ACCOUNT_ID = 'test-account';
  process.env.R2_ACCESS_KEY = 'test-access';
  process.env.R2_SECRET_KEY = 'test-secret';
  process.env.R2_BUCKET = 'test-bucket';
});

afterEach(() => {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) delete process.env[key];
    else process.env[key] = originalEnv[key];
  }
  globalThis.fetch = originalFetch;
});

test('a revision search becomes the agent body with only what was set, and its hits in camelCase', () => {
  assert.deepEqual(toAgentRevisionSearchBody({ query: 'knife' }), { query: 'knife' });
  assert.deepEqual(toAgentRevisionSearchBody({ query: 'knife', topK: 50, minSimilarity: 0 }), {
    query: 'knife',
    top_k: 50,
    min_similarity: 0,
  });
  const [hit] = fromAgentRevisionSearchResponse([AGENT_HIT]);
  assert.deepEqual(hit, {
    incidentId: 2,
    revisionId: 41,
    videoId: 'v2',
    revisionNo: 3,
    kind: 'ai',
    modelRunId: 'm2',
    title: 'Knife in a shop',
    description: 'A man holds a knife.',
    incidentType: 'assault',
    severityLevel: 4,
    startSeconds: 6,
    endSeconds: 20,
    similarityScore: 0.83,
  });
  assert.throws(() => fromAgentRevisionSearchResponse({ hits: [] }), /invalid revision search response/);
});

test('text search keeps the incidents the agent matched, under the other filters and sort', async () => {
  const calls = stubUpstream({ status: 200, body: [AGENT_HIT] });
  const response = await GET(new Request('http://localhost/api/reports?search=knife&type=assault&sort=oldest'));
  const payload = await response.json();

  assert.equal(response.status, 200);
  assert.deepEqual(calls.agent, [{ query: 'knife', top_k: 50 }]);
  assert.equal(calls.rpc.length, 1);
  assert.equal(calls.rpc[0].p_search, null, 'the store is not asked for the ILIKE match');
  assert.equal(calls.rpc[0].p_page_size, 1000);
  assert.equal(calls.rpc[0].p_type, 'assault');
  assert.equal(calls.rpc[0].p_sort, 'oldest');
  assert.deepEqual(
    payload.reports.map((report) => report.incidentId),
    [2],
  );
  assert.deepEqual(payload.pagination, { page: 1, pageSize: 6, totalItems: 1, totalPages: 1 });
  assert.equal(payload.searchMode, 'semantic');
});

test('text search falls back to the store ILIKE filter when the agent fails', async () => {
  const calls = stubUpstream({ status: 503, body: { detail: 'query embedding key not configured' } });
  const payload = await (await GET(new Request('http://localhost/api/reports?search=knife'))).json();

  assert.equal(calls.rpc[0].p_search, 'knife');
  assert.equal(calls.rpc[0].p_page_size, 6);
  assert.equal(payload.searchMode, 'text');
});

test('text search falls back to the store ILIKE filter when the agent finds nothing', async () => {
  const calls = stubUpstream({ status: 200, body: [] });
  const payload = await (await GET(new Request('http://localhost/api/reports?search=knife'))).json();

  assert.equal(calls.rpc[0].p_search, 'knife');
  assert.equal(payload.searchMode, 'text');
});

test('without text, no agent call is made and searchMode is null', async () => {
  const calls = stubUpstream({ status: 200, body: [AGENT_HIT] });
  const payload = await (await GET(new Request('http://localhost/api/reports'))).json();

  assert.equal(calls.agent.length, 0);
  assert.equal(calls.rpc[0].p_search, null);
  assert.equal('searchMode' in payload, false);
});

test('without an agent URL, text search uses the store ILIKE filter', async () => {
  delete process.env.INCIDENT_AGENT_BASE_URL;
  const calls = stubUpstream({ status: 200, body: [AGENT_HIT] });
  const payload = await (await GET(new Request('http://localhost/api/reports?search=knife'))).json();

  assert.equal(calls.agent.length, 0);
  assert.equal(calls.rpc[0].p_search, 'knife');
  assert.equal(payload.searchMode, 'text');
});

// SPDX-License-Identifier: Apache-2.0

// Characterisation test for GET /api/reports' response, written against the
// pre-refactor route: list_incident_report_summaries' result, in the shape its
// SQL builds (supabase/functions-final.sql), reaches
// the browser unchanged apart from the signed thumbnail of an R2 video.

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

const { GET } = await import('../src/app/api/reports/route.ts');

const summaries = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'report-summaries-rpc.json'), 'utf8'));
const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
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

function serve(result) {
  const bodies = [];
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), 'https://supabase.test/rest/v1/rpc/list_incident_report_summaries');
    bodies.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  return bodies;
}

const DEFAULT_ARGS = {
  p_page: 1,
  p_page_size: 6,
  p_search: null,
  p_type: null,
  p_severity: null,
  p_kind: null,
  p_generated_after: null,
  p_generated_before: null,
  p_time_from: null,
  p_time_to: null,
  p_entities: null,
  p_instruments: null,
  p_assets: null,
  p_day_of_week: null,
  p_sort: 'newest',
  p_scope: 'all',
  p_entity_types: null,
  p_evidence_match: 'contains',
  p_timezone: 'UTC',
};

test('every summary field reaches the browser as the RPC returns it, plus a signed thumbnail for an R2 video', async () => {
  const bodies = serve(summaries);
  const response = await GET(new Request('http://localhost/api/reports?page=3&timezone=Asia%2FSingapore'));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    reports: [
      {
        ...summaries.reports[0],
        thumbnailUrl: 'https://signed.r2.test/thumbnails/uploads/sensor-1/assault-1.mp4.webp',
        evidenceThumbnailUrl: 'https://signed.r2.test/evidence/v-assault-1/u1/I1.jpg',
      },
      summaries.reports[1],
      { ...summaries.reports[2], evidenceThumbnailUrl: 'https://signed.r2.test/evidence/v-repaired-3/m/E1.jpg' },
    ],
    incidentTypes: summaries.incidentTypes,
    pagination: { page: 3, pageSize: 6, totalItems: 13, totalPages: 3 },
  });
  assert.deepEqual(bodies, [{ ...DEFAULT_ARGS, p_page: 3, p_timezone: 'Asia/Singapore' }]);
});

test('the full export (all=true) asks for up to 1000 reports and signs no thumbnails', async () => {
  const bodies = serve(summaries);
  const response = await GET(
    new Request('http://localhost/api/reports?all=true&page=0&search=%20blade%20&kind=human&type=all&severity=all&sort=oldest'),
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    reports: summaries.reports,
    incidentTypes: summaries.incidentTypes,
    pagination: { page: 1, pageSize: 1000, totalItems: 13, totalPages: 1 },
    searchMode: 'text',
  });
  assert.deepEqual(bodies, [{ ...DEFAULT_ARGS, p_page_size: 1000, p_search: 'blade', p_kind: 'human', p_sort: 'oldest' }]);
});

test('a thumbnail that cannot be signed is left out and its report is still listed', async () => {
  delete process.env.R2_BUCKET;
  serve(summaries);
  const response = await GET(new Request('http://localhost/api/reports'));
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).reports, summaries.reports);
});

test('an unknown revision kind is a 400 and nothing is asked of the database', async () => {
  const bodies = serve(summaries);
  const response = await GET(new Request('http://localhost/api/reports?kind=verified'));
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: 'Invalid revision kind' });
  assert.deepEqual(bodies, []);
});

test('an empty RPC result lists nothing', async () => {
  serve(null);
  const response = await GET(new Request('http://localhost/api/reports'));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    reports: [],
    incidentTypes: [],
    pagination: { page: 1, pageSize: 6, totalItems: 0, totalPages: 0 },
  });
});

test('a database failure is a 500 with its message, and an unconfigured database is refused before any validation', async () => {
  globalThis.fetch = async () => new Response('{"message":"boom"}', { status: 500 });
  const failed = await GET(new Request('http://localhost/api/reports'));
  assert.equal(failed.status, 500);
  assert.match((await failed.json()).error, /^PostgREST returned HTTP 500/);

  delete process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY;
  const unconfigured = await GET(new Request('http://localhost/api/reports?sort=sideways'));
  assert.equal(unconfigured.status, 500);
  assert.deepEqual(await unconfigured.json(), { error: 'Supabase PostgREST is not configured' });
});

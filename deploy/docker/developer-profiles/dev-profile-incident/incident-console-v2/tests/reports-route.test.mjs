// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';
import { reportThumbnailView } from '../lib/reports/thumbnail.ts';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {},
    GetObjectCommand: class { constructor(input) { this.input = input; } },
    PutObjectCommand: class {},
    HeadObjectCommand: class {},
    DeleteObjectCommand: class {},
  },
});

mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_client, command) => `https://signed.r2.test/${command.input.Key}` },
});

const { GET } = await import('../app/api/reports/route.ts');
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

test('report library requests one six-item summary page without video URLs', async () => {
  let rpcBody;
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), 'https://supabase.test/rest/v1/rpc/list_incident_report_summaries');
    rpcBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({
      reports: [{ reportId: 'r1', videoId: 'v1', modelRunId: 'm1', title: 'Road Accident report', r2Key: 'uploads/sensor-1/video.mp4' }],
      totalItems: 13,
      incidentTypes: ['road accident'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  const response = await GET(new Request('http://localhost/api/reports?page=2&severity=high&sort=newest'));
  const payload = await response.json();

  assert.equal(response.status, 200);
  assert.equal(rpcBody.p_page, 2);
  assert.equal(rpcBody.p_page_size, 6);
  assert.equal(rpcBody.p_severity, 'high');
  assert.deepEqual(payload.pagination, { page: 2, pageSize: 6, totalItems: 13, totalPages: 3 });
  assert.equal('playbackUrl' in payload.reports[0], false);
  assert.equal(payload.reports[0].thumbnailUrl, 'https://signed.r2.test/thumbnails/uploads/sensor-1/video.mp4.webp');
});

test('report library rejects a severity that could make the RPC cast fail', async () => {
  let called = false;
  globalThis.fetch = async () => { called = true; return new Response('{}'); };
  const response = await GET(new Request('http://localhost/api/reports?severity=urgent'));
  assert.equal(response.status, 400);
  assert.equal(called, false);
});

test('report thumbnail contract lazy-loads only its screenshot image', () => {
  assert.deepEqual(reportThumbnailView('https://signed.r2.test/thumbnail.webp'), {
    kind: 'image',
    loading: 'lazy',
    src: 'https://signed.r2.test/thumbnail.webp',
  });
});

test('report thumbnail contract falls back to a skeleton when missing or failed', () => {
  assert.deepEqual(reportThumbnailView(), { kind: 'skeleton' });
  assert.deepEqual(reportThumbnailView('https://signed.r2.test/thumbnail.webp', true), { kind: 'skeleton' });
});

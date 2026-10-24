// SPDX-License-Identifier: Apache-2.0

// Supabase API keys: a legacy JWT key goes in apikey and Authorization: Bearer;
// a new sb_secret_... key is not a JWT, and the API gateway rejects it as a
// bearer token, so it goes in apikey only.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PostgrestClient, authHeaders } = await import('../src/lib/postgrest/client.ts');

const JWT_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJlLV8';
const SECRET_KEY = 'sb_secret_AbCdEf0123456789_-xyz';
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('a JWT key is sent as apikey and bearer token; any other key as apikey only', () => {
  assert.deepEqual(authHeaders(JWT_KEY), { apikey: JWT_KEY, Authorization: `Bearer ${JWT_KEY}` });
  assert.deepEqual(authHeaders(SECRET_KEY), { apikey: SECRET_KEY });
  assert.deepEqual(authHeaders('a.b'), { apikey: 'a.b' });
  assert.deepEqual(authHeaders('a.b.c.d'), { apikey: 'a.b.c.d' });
});

test('every request, including the health probe, carries the headers for its key', async () => {
  for (const [key, authorization] of [
    [JWT_KEY, `Bearer ${JWT_KEY}`],
    [SECRET_KEY, null],
  ]) {
    const seen = [];
    globalThis.fetch = async (url, init = {}) => {
      const headers = new Headers(init.headers);
      seen.push({ path: new URL(String(url)).pathname, apikey: headers.get('apikey'), authorization: headers.get('authorization') });
      return new Response('[]');
    };
    const client = new PostgrestClient('https://supabase.test/', key);
    assert.equal(await client.health(), true);
    await client.selectOne('videos', { id: 'v1' });
    await client.rpc('set_review_status', {});
    await client.selectPage('videos', {}, 1, 0);
    assert.deepEqual(
      seen.map((request) => request.path),
      ['/rest/v1/videos', '/rest/v1/videos', '/rest/v1/rpc/set_review_status', '/rest/v1/videos'],
    );
    for (const request of seen) assert.deepEqual([request.apikey, request.authorization], [key, authorization]);
  }
});

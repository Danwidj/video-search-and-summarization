// SPDX-License-Identifier: Apache-2.0

// GET /api/reports/[videoId]/evidence-track: a video's person track read through the console, with fake PostgREST
// and R2 (R2 has no CORS rule for the console origin, so the browser cannot read the signed URL itself).

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_c, command) => `https://signed.r2.test/${command.input.Key}` },
});

const { GET } = await import('../src/app/api/reports/[videoId]/evidence-track/route.ts');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');

const KEY = 'evidence/videos/v1.mp4/run-2/E1-track.json';
const TRACK = [{ t: 80.9, box: [100, 200, 500, 300], score: 0.9 }];
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
let r2 = {};
const r2Reads = [];
beforeEach(() => {
  r2 = { [KEY]: JSON.stringify(TRACK) };
  r2Reads.length = 0;
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
  });
  const postgrest = fakePostgrest({
    videos: [{ id: 'v1', filepath: 'videos/v1.mp4', uploaded_datetime: null, source: null, official_revision_id: null }],
  }).fetch;
  globalThis.fetch = async (url, init) => {
    const href = String(url);
    if (!href.startsWith('https://signed.r2.test/')) return postgrest(url, init);
    const key = decodeURIComponent(href.slice('https://signed.r2.test/'.length));
    r2Reads.push(key);
    return key in r2 ? new Response(r2[key]) : new Response('NoSuchKey', { status: 404 });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const get = (key, videoId = 'v1') =>
  GET(new Request(`http://localhost/api/reports/${videoId}/evidence-track?key=${encodeURIComponent(key)}`), {
    params: Promise.resolve({ videoId }),
  });

test("a video's track file is answered as stored, read from R2 on the server", async () => {
  const response = await get(KEY);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), TRACK);
  assert.deepEqual(r2Reads, [KEY]);
});

test('only a track file of this video is read', async () => {
  assert.equal((await get('evidence/videos/other.mp4/run-1/E1-track.json')).status, 400, "another video's track");
  assert.equal((await get('evidence/videos/v1.mp4/run-2/E1.jpg')).status, 400, 'not a track file');
  assert.equal((await get('evidence/videos/v1.mp4/../x-track.json')).status, 400, 'a path outside the folder');
  assert.equal((await get('')).status, 400);
  assert.equal((await get(KEY, 'nope')).status, 404, 'an unknown video');
  assert.deepEqual(r2Reads, [], 'nothing is read for a refused key');
});

test('a missing or unreadable track file is an error, so the picker keeps its ordinary mode', async () => {
  assert.equal((await get('evidence/videos/v1.mp4/run-2/E2-track.json')).status, 404);
  r2[KEY] = 'not json';
  assert.equal((await get(KEY)).status, 502);
});

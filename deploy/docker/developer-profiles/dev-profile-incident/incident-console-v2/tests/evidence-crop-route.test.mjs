// SPDX-License-Identifier: Apache-2.0

// GET /api/reports/[incidentId]/frame and POST .../evidence-crop, with fake PostgREST, R2 and ffmpeg.

import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const commands = [];
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        commands.push(command);
        if (command.constructor.name === 'HeadObjectCommand') {
          const put = commands.findLast((c) => c.constructor.name === 'PutObjectCommand');
          return Promise.resolve({ ContentLength: put && command.input.Key === put.input.Key ? put.input.ContentLength : 1000 });
        }
        return Promise.resolve({ ETag: '"e"' });
      }
    },
    GetObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    PutObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    HeadObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    DeleteObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
  },
});
mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_c, command) => `https://signed.r2.test/${command.input.Key}` },
});

const spawned = [];
let ffmpegBehaviour = 'ok';
mock.module('node:child_process', {
  namedExports: {
    spawn(command, args) {
      spawned.push({ command, args });
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      child.kill = () => {};
      setImmediate(() => {
        if (ffmpegBehaviour === 'missing') return child.emit('error', Object.assign(new Error('spawn ffmpeg ENOENT'), { code: 'ENOENT' }));
        if (ffmpegBehaviour === 'ok') child.stdout.emit('data', Buffer.from('JPEGBYTES'));
        child.emit('close', ffmpegBehaviour === 'fail' ? 1 : 0);
      });
      return child;
    },
  },
});

const { GET } = await import('../src/app/api/reports/[incidentId]/frame/route.ts');
const { POST } = await import('../src/app/api/reports/[incidentId]/evidence-crop/route.ts');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  commands.length = 0;
  spawned.length = 0;
  ffmpegBehaviour = 'ok';
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
  });
  globalThis.fetch = fakePostgrest({
    incidents: [{ id: 1, official_revision_id: null, official_since: null, created_at: '2026-10-01T00:00:00' }],
    report_revisions: [],
    model_runs: [],
    videos: [
      {
        id: 'v1',
        incident_id: 1,
        filepath: 'videos/v1.mp4',
        uploaded_datetime: '2026-10-01T01:00:00',
        source: null,
        official_revision_id: null,
      },
    ],
  }).fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const params = (videoId) => ({ params: Promise.resolve({ incidentId: videoId }) });
const get = (query, incidentId = '1') => GET(new Request(`http://localhost/api/reports/${incidentId}/frame${query}`), params(incidentId));
const post = (body, videoId = 'v1') =>
  POST(
    new Request('http://localhost/x', { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body) }),
    params(videoId),
  );
const crop = { timestampSeconds: 0, region: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 } };

test('the frame route answers a JPEG decoded from the signed video URL', async () => {
  const response = await get('?video=v1&t=0');
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'image/jpeg');
  assert.equal(await response.text(), 'JPEGBYTES');
  assert.equal((await get('?t=0')).status, 200, 'the only video of the incident is the default');
  assert.match(spawned[0].args[spawned[0].args.indexOf('-i') + 1], /^https:\/\/signed\.r2\.test\/videos\/v1\.mp4$/);
});

test('the frame route refuses a bad t, an unknown video and a missing ffmpeg', async () => {
  assert.equal((await get('?video=v1')).status, 400);
  assert.equal((await get('?video=v1&t=-2')).status, 400);
  assert.equal((await get('?video=v1&t=1', '2')).status, 404, 'an unknown incident');
  assert.equal((await get('?video=other&t=1')).status, 404, 'a video that is not in the incident');
  assert.equal((await get('?video=v1&t=1', 'nope')).status, 400, 'a bad incident id');
  ffmpegBehaviour = 'missing';
  const missing = await get('?video=v1&t=0');
  assert.equal(missing.status, 503);
  assert.match((await missing.json()).error, /ffmpeg is not installed/);
  ffmpegBehaviour = 'empty';
  assert.equal((await get('?video=v1&t=0')).status, 422);
});

test('a crop is answered as JPEG bytes, and nothing is written to R2', async () => {
  const response = await post(crop);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'image/jpeg');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(await response.text(), 'JPEGBYTES');
  assert.ok(spawned[0].args.some((a) => a.startsWith('crop=')));
  assert.equal(
    commands.some((c) => c.constructor.name === 'PutObjectCommand'),
    false,
  );
});

test('a bad crop request is refused before anything is uploaded', async () => {
  assert.equal((await post('not json')).status, 400);
  const outside = await post({ ...crop, region: { x: 0.9, y: 0, w: 0.5, h: 0.5 } });
  assert.equal(outside.status, 422);
  assert.match((await outside.json()).error, /inside the frame/);
  assert.equal((await post(crop, 'nope')).status, 404);
  assert.equal(spawned.length, 0, 'no frame is cut for a refused request');
});

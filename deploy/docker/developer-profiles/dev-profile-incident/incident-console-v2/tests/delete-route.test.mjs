// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const deletedObjects = [];
// The keys an R2 listing returns, by prefix; and keys whose removal fails.
let storedEvidence = [];
let failingKeys = new Set();
const listedPrefixes = [];
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        if (command.constructor.name === 'ListObjectsV2Command') {
          listedPrefixes.push(command.input.Prefix);
          const keys = storedEvidence.filter((key) => key.startsWith(command.input.Prefix));
          return Promise.resolve({
            Contents: keys.map((Key) => ({ Key, LastModified: new Date('2026-10-01T00:00:00Z') })),
            IsTruncated: false,
          });
        }
        if (failingKeys.has(command.input?.Key)) return Promise.reject(new Error('R2 refused'));
        deletedObjects.push(command.input?.Key);
        return Promise.resolve({});
      }
    },
    ListObjectsV2Command: class ListObjectsV2Command {
      constructor(input) {
        this.input = input;
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
    DeleteObjectCommand: class DeleteObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.test/x' } });

const { DELETE } = await import('../src/app/api/reports/[videoId]/delete/route.ts');

// The VST calls the route makes (method, path, streamId header); `vstDeleteStatus` is the answer to a sensor delete.
const vstCalls = [];
let vstDeleteStatus = 204;
/** Serves a VST request from the fake, or null for any other URL. */
function serveVst(url, init = {}) {
  const parsed = new URL(String(url));
  if (parsed.origin !== 'http://vst.test') return null;
  vstCalls.push(`${init.method ?? 'GET'} ${parsed.pathname} streamId=${init.headers?.streamId ?? ''}`);
  if (init.method === 'DELETE') {
    // R2 objects deleted while the camera still stood would be a bug.
    if (deletedObjects.length > 0) throw new Error('an R2 object was deleted before the camera');
    return new Response(null, { status: vstDeleteStatus });
  }
  return Response.json([
    { sensorId: 'sensor-by-name', name: 'v', state: 'online' },
    { sensorId: 'sensor-removed', name: 'v', state: 'removed' },
  ]);
}
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
    INCIDENT_VST_BASE_URL: 'http://vst.test',
  });
  deletedObjects.length = 0;
  vstCalls.length = 0;
  vstDeleteStatus = 204;
  listedPrefixes.length = 0;
  storedEvidence = [];
  failingKeys = new Set();
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const attempt = (id, videoId, status) => ({
  id,
  notes: JSON.stringify({
    incidentConsoleV2: {
      recordType: 'analysis_attempt',
      status,
      contractVersion: 'incident-contract-v3',
      videoId,
      request: {},
      response: null,
      validation: { firstPass: [] },
      repair: null,
    },
  }),
});

const call = () =>
  DELETE(new Request('http://localhost/api/reports/v-target/delete', { method: 'DELETE' }), {
    params: Promise.resolve({ videoId: 'v-target' }),
  });

test('deleting a video removes its objects, the video row, and the run records that name only it and no revision uses', async () => {
  storedEvidence = [
    'evidence/uploads/s/v.mp4/0b9c/E1.jpg',
    'evidence/uploads/s/v.mp4/0b9c/I1.jpg',
    'evidence/uploads/s/v.mp4/7f21/E1.jpg',
    'evidence/uploads/s/v.mp4-2/aa11/E1.jpg',
  ];
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    const vst = serveVst(url, init);
    if (vst) return vst;
    const parsed = new URL(String(url));
    const table = parsed.pathname.replace('/rest/v1/', '');
    if (init.method === 'DELETE') {
      deletes.push(`${table}?${parsed.searchParams}`);
      return new Response(null, { status: 204 });
    }
    if (table === 'videos') return new Response(JSON.stringify([{ id: 'v-target', filepath: 'uploads/s/v.mp4', source: 'sensor-stored' }]));
    if (table === 'model_runs') {
      assert.match(parsed.searchParams.get('notes'), /^like\.\*"videoId":"v-target"\*$/);
      return new Response(
        JSON.stringify([
          attempt('m-failed', 'v-target', 'contract_failed'),
          attempt('m-request', 'v-target', 'request_failed'),
          attempt('m-other-video', 'v-target-2', 'contract_failed'),
          attempt('m-valid', 'v-target', 'valid_first_pass'),
          { id: 'm-legacy', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v-target', incident_type: 'burglary' } } }) },
          { id: 'm-legacy-other', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v-target-2' } } }) },
          {
            id: 'm-mentions',
            notes: JSON.stringify({ incidentConsoleV2: { contractVersion: 'incident-contract-v3', note: '"videoId":"v-target"' } }),
          },
          attempt('m-used', 'v-target', 'valid_first_pass'),
        ]),
      );
    }
    if (table === 'report_revisions') {
      return new Response(JSON.stringify(parsed.searchParams.get('model_run_id') === 'eq.m-used' ? [{ id: 9 }] : []));
    }
    return new Response('[]');
  };

  const response = await call();

  assert.equal(response.status, 200);
  assert.deepEqual(
    vstCalls,
    ['DELETE /vst/api/v1/sensor/sensor-stored streamId=sensor-stored'],
    'the stored camera goes, with no name lookup',
  );
  assert.deepEqual(deletes.filter((d) => d.startsWith('model_runs')).sort(), [
    'model_runs?id=eq.m-failed',
    'model_runs?id=eq.m-legacy',
    'model_runs?id=eq.m-request',
    'model_runs?id=eq.m-valid',
  ]);
  assert.ok(
    deletes.indexOf('videos?id=eq.v-target') < deletes.indexOf('model_runs?id=eq.m-failed'),
    'the video (and its cascaded revisions) goes first',
  );
  assert.deepEqual(listedPrefixes, ['evidence/uploads/s/v.mp4/'], 'the trailing slash keeps a file named v.mp4-2 out');
  assert.deepEqual(
    deletedObjects.sort(),
    [
      'evidence/uploads/s/v.mp4/0b9c/E1.jpg',
      'evidence/uploads/s/v.mp4/0b9c/I1.jpg',
      'evidence/uploads/s/v.mp4/7f21/E1.jpg',
      'thumbnails/uploads/s/v.mp4.webp',
      'uploads/s/v.mp4',
    ],
    'the video object, its thumbnail and every evidence image of the video (known issue 2), and nothing of another video',
  );
});

test('an evidence image that cannot be removed keeps the video row, so the delete can be repeated', async () => {
  storedEvidence = ['evidence/uploads/s/v.mp4/0b9c/E1.jpg', 'evidence/uploads/s/v.mp4/0b9c/I1.jpg'];
  failingKeys = new Set(['evidence/uploads/s/v.mp4/0b9c/E1.jpg']);
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    const vst = serveVst(url, init);
    if (vst) return vst;
    if (init.method === 'DELETE') deletes.push(String(url));
    return new Response(JSON.stringify([{ id: 'v-target', filepath: 'uploads/s/v.mp4', source: null }]));
  };
  const response = await call();
  assert.equal(response.status, 500);
  assert.deepEqual(
    vstCalls,
    ['GET /vst/api/v1/sensor/list streamId=', 'DELETE /vst/api/v1/sensor/sensor-by-name streamId=sensor-by-name'],
    'a row without a sensor id resolves the one live camera named after the file',
  );
  assert.match((await response.json()).error, /1 of 2 evidence images.*evidence\/uploads\/s\/v\.mp4\/0b9c\/E1\.jpg: R2 refused/);
  assert.deepEqual(deletes, [], 'no row is deleted');
  assert.ok(deletedObjects.includes('evidence/uploads/s/v.mp4/0b9c/I1.jpg'), 'the other images are still removed');
});

test('a camera VST refuses to delete keeps the objects and the row; one VST no longer has counts as deleted', async () => {
  storedEvidence = ['evidence/uploads/s/v.mp4/0b9c/E1.jpg'];
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    const vst = serveVst(url, init);
    if (vst) return vst;
    if (init.method === 'DELETE') deletes.push(String(url));
    return new Response(JSON.stringify([{ id: 'v-target', filepath: 'uploads/s/v.mp4', source: 'sensor-stored' }]));
  };
  vstDeleteStatus = 503;
  const refused = await call();
  assert.equal(refused.status, 500);
  assert.match((await refused.json()).error, /VST sensor delete returned HTTP 503/);
  assert.deepEqual(deletedObjects, [], 'no object is removed');
  assert.deepEqual(deletes, [], 'no row is deleted');

  vstDeleteStatus = 404;
  assert.equal((await call()).status, 200, 'a camera VST no longer has lets the delete finish');
  assert.ok(deletedObjects.includes('uploads/s/v.mp4'));
});

test('a video without a stored object is refused and nothing is deleted', async () => {
  const deletes = [];
  globalThis.fetch = async (url, init = {}) => {
    if (init.method === 'DELETE') deletes.push(String(url));
    return new Response(JSON.stringify([{ id: 'v-target', filepath: null }]));
  };
  assert.notEqual((await call()).status, 200);
  assert.deepEqual(deletes, []);
  assert.deepEqual(vstCalls, [], 'no camera is touched for a video that is refused');
});

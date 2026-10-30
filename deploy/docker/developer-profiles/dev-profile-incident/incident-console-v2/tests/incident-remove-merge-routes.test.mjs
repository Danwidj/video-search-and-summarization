// SPDX-License-Identifier: Apache-2.0

// P5.3 routes: delete an incident, remove a video (delete or move), merge two incidents. A fake
// PostgREST stands in for the database and a mocked S3 client for R2, run with R2_KEY_PREFIX=mvp3/.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const deletedObjects = [];
const listedPrefixes = [];
// Physical keys (with the mvp3/ prefix) that exist in the bucket.
let bucket = [];
const command = () =>
  class {
    constructor(args) {
      this.input = args;
    }
  };
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(cmd) {
        if (cmd.constructor.name === 'ListObjectsV2Command') {
          listedPrefixes.push(cmd.input.Prefix);
          return Promise.resolve({
            Contents: bucket.filter((key) => key.startsWith(cmd.input.Prefix)).map((Key) => ({ Key, LastModified: new Date() })),
            IsTruncated: false,
          });
        }
        deletedObjects.push(cmd.input?.Key);
        return Promise.resolve({});
      }
    },
    ListObjectsV2Command: class ListObjectsV2Command {
      constructor(input) {
        this.input = input;
      }
    },
    DeleteObjectCommand: class DeleteObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    GetObjectCommand: command(),
    PutObjectCommand: command(),
    HeadObjectCommand: command(),
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.test/x' } });

const { DELETE } = await import('../src/app/api/reports/[incidentId]/delete/route.ts');
const { POST: merge } = await import('../src/app/api/reports/[incidentId]/merge/route.ts');
const { POST: remove } = await import('../src/app/api/videos/[videoId]/remove/route.ts');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
let db;

// A fake VST in front of the fake PostgREST: its sensor list and sensor delete, recording each call.
const vstCalls = [];
let vstSensors = [];
const fakeVst = (next) => async (input, init) => {
  const url = String(input instanceof Request ? input.url : input);
  if (!url.startsWith('http://vst.test')) return next(input, init);
  const method = init?.method ?? 'GET';
  vstCalls.push(`${method} ${url.slice('http://vst.test'.length)}`);
  if (method === 'GET') return Response.json(vstSensors);
  const sensorId = url.split('/').pop();
  if (init?.headers?.streamId !== sensorId) return new Response('missing streamId', { status: 400 });
  const found = vstSensors.some((sensor) => sensor.sensorId === sensorId);
  vstSensors = vstSensors.filter((sensor) => sensor.sensorId !== sensorId);
  return new Response(found ? null : 'not found', { status: found ? 204 : 404 });
};

beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
    R2_KEY_PREFIX: 'mvp3/',
    INCIDENT_VST_BASE_URL: 'http://vst.test',
  });
  vstCalls.length = 0;
  vstSensors = [
    { sensorId: 'sensor-a', name: 'a' },
    { sensorId: 'sensor-b', name: 'b' },
    { sensorId: 'sensor-c', name: 'c' },
    { sensorId: 'sensor-other', name: 'other' },
  ];
  deletedObjects.length = 0;
  listedPrefixes.length = 0;
  bucket = [];
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

/** remove_video as the migration defines it, over the fake's tables. */
function removeVideoRpc({ p_video_id: videoId, p_mode: mode }, store) {
  const video = store.videos.find((row) => row.id === videoId);
  if (!video) throw new Error(`video ${videoId} does not exist`);
  const incidentId = video.incident_id;
  const count = store.videos.filter((row) => row.incident_id === incidentId).length;
  let newIncidentId = null;
  let incidentDeleted = false;
  let deletedKey = null;
  if (mode === 'move') {
    if (count < 2) throw new Error(`video ${videoId} is the last video of incident ${incidentId}; delete it instead of moving it`);
    newIncidentId = Math.max(0, ...store.incidents.map((row) => row.id)) + 1;
    store.incidents.push({ id: newIncidentId });
    video.incident_id = newIncidentId;
  } else {
    deletedKey = video.filepath;
    store.videos = store.videos.filter((row) => row.id !== videoId);
    if (count < 2) {
      store.incidents = store.incidents.filter((row) => row.id !== incidentId);
      incidentDeleted = true;
    }
  }
  return {
    mode,
    video_id: videoId,
    incident_id: incidentId,
    new_incident_id: newIncidentId,
    incident_deleted: incidentDeleted,
    deleted_video_key: deletedKey,
    deleted_crop_images: [],
  };
}

function mergeRpc({ p_target_incident_id: target, p_source_incident_id: source }, store) {
  if (target === source) throw new Error('an incident cannot be merged into itself');
  const moved = store.videos.filter((row) => row.incident_id === source);
  for (const row of moved) row.incident_id = target;
  store.incidents = store.incidents.filter((row) => row.id !== source);
  return { incident_id: target, source_incident_id: source, moved_video_ids: moved.map((row) => row.id), orphaned_crop_images: [] };
}

function seed() {
  db = fakePostgrest(
    {
      incidents: [{ id: 1 }, { id: 2 }],
      videos: [
        { id: 'a.mp4', incident_id: 1, filepath: 'uploads/a.mp4', source: 'sensor-a' },
        { id: 'b.mp4', incident_id: 1, filepath: 'uploads/b.mp4', source: null },
        { id: 'c.mp4', incident_id: 2, filepath: 'uploads/c.mp4', source: 'sensor-c' },
      ],
    },
    { rpc: { remove_video: removeVideoRpc, merge_incidents: mergeRpc }, identity: { incidents: 'id' } },
  );
  globalThis.fetch = fakeVst(db.fetch);
}

const post = (handler, params, body) =>
  handler(new Request('http://localhost/x', { method: 'POST', body: JSON.stringify(body) }), { params: Promise.resolve(params) });

test('deleting an incident removes each video, thumbnail and evidence image under the prefix, then the incident', async () => {
  seed();
  bucket = [
    'mvp3/uploads/a.mp4',
    'mvp3/evidence/uploads/a.mp4/r1/E1.jpg',
    'mvp3/evidence/uploads/b.mp4/r1/E1.jpg',
    'mvp3/evidence/uploads/c.mp4/r1/E1.jpg',
    'evidence/uploads/a.mp4/outside.jpg',
  ];
  const response = await DELETE(new Request('http://localhost/x', { method: 'DELETE' }), { params: Promise.resolve({ incidentId: '1' }) });
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).deletedVideoIds, ['a.mp4', 'b.mp4']);
  assert.deepEqual(listedPrefixes.sort(), ['mvp3/evidence/uploads/a.mp4/', 'mvp3/evidence/uploads/b.mp4/']);
  assert.deepEqual(deletedObjects.sort(), [
    'mvp3/evidence/uploads/a.mp4/r1/E1.jpg',
    'mvp3/evidence/uploads/b.mp4/r1/E1.jpg',
    'mvp3/thumbnails/uploads/a.mp4.webp',
    'mvp3/thumbnails/uploads/b.mp4.webp',
    'mvp3/uploads/a.mp4',
    'mvp3/uploads/b.mp4',
  ]);
  assert.deepEqual(
    db.store.videos.map((row) => row.id),
    ['c.mp4'],
  );
  assert.deepEqual(db.store.incidents, [{ id: 2 }]);
  assert.deepEqual(vstCalls, ['DELETE /vst/api/v1/sensor/sensor-a', 'GET /vst/api/v1/sensor/list', 'DELETE /vst/api/v1/sensor/sensor-b']);
  assert.deepEqual(
    vstSensors.map((sensor) => sensor.sensorId),
    ['sensor-c', 'sensor-other'],
    "only the two videos' cameras went",
  );
});

test('deleting an unknown or malformed incident is refused without touching R2', async () => {
  seed();
  const call = (incidentId) => DELETE(new Request('http://localhost/x', { method: 'DELETE' }), { params: Promise.resolve({ incidentId }) });
  assert.equal((await call('9')).status, 404);
  assert.equal((await call('abc')).status, 400);
  assert.deepEqual([...deletedObjects, ...listedPrefixes, ...vstCalls], []);
});

test('removing a video entirely deletes its objects, and the incident when it was the last video', async () => {
  seed();
  bucket = ['mvp3/evidence/uploads/c.mp4/r1/E1.jpg'];
  const response = await post(remove, { videoId: 'c.mp4' }, { choice: 'delete' });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    removed: { choice: 'delete', videoId: 'c.mp4', incidentId: 2, incidentDeleted: true, storageKey: 'uploads/c.mp4', cropImages: [] },
  });
  assert.deepEqual(deletedObjects.sort(), [
    'mvp3/evidence/uploads/c.mp4/r1/E1.jpg',
    'mvp3/thumbnails/uploads/c.mp4.webp',
    'mvp3/uploads/c.mp4',
  ]);
  assert.deepEqual(db.store.incidents, [{ id: 1 }]);
  assert.deepEqual(vstCalls, ['DELETE /vst/api/v1/sensor/sensor-c']);
  assert.deepEqual(
    vstSensors.map((sensor) => sensor.sensorId),
    ['sensor-a', 'sensor-b', 'sensor-other'],
  );
});

test('a VST failure keeps the video row, and removing again finishes the job', async () => {
  seed();
  const working = globalThis.fetch;
  globalThis.fetch = async (input, init) =>
    String(input).startsWith('http://vst.test') && init?.method === 'DELETE' ? new Response('down', { status: 503 }) : working(input, init);
  const failed = await post(remove, { videoId: 'c.mp4' }, { choice: 'delete' });
  assert.equal(failed.status, 500);
  assert.equal(
    db.store.videos.some((row) => row.id === 'c.mp4'),
    true,
    'the row, which holds the sensor id, is kept',
  );
  globalThis.fetch = working;
  vstSensors = vstSensors.filter((sensor) => sensor.sensorId !== 'sensor-c');
  const repeated = await post(remove, { videoId: 'c.mp4' }, { choice: 'delete' });
  assert.equal(repeated.status, 200, 'a camera VST no longer has counts as removed');
  assert.equal(
    db.store.videos.some((row) => row.id === 'c.mp4'),
    false,
  );
});

test('moving a video makes a new incident, moves no file, and the last video cannot be moved', async () => {
  seed();
  const moved = await post(remove, { videoId: 'b.mp4' }, { choice: 'move' });
  assert.equal(moved.status, 200);
  assert.deepEqual((await moved.json()).removed, { choice: 'move', videoId: 'b.mp4', incidentId: 1, newIncidentId: 3 });
  assert.deepEqual([...deletedObjects, ...listedPrefixes, ...vstCalls], []);

  const last = await post(remove, { videoId: 'c.mp4' }, { choice: 'move' });
  assert.equal(last.status, 422);
  assert.equal(db.store.videos.find((row) => row.id === 'c.mp4').incident_id, 2);
  assert.equal((await post(remove, { videoId: 'none.mp4' }, { choice: 'move' })).status, 404);
  assert.equal((await post(remove, { videoId: 'a.mp4' }, { choice: 'archive' })).status, 400);
  assert.deepEqual([...deletedObjects, ...listedPrefixes], []);
});

test('merging moves the source videos into the target and touches no file', async () => {
  seed();
  const response = await post(merge, { incidentId: '1' }, { sourceIncidentId: 2 });
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).merged, {
    incidentId: 1,
    sourceIncidentId: 2,
    movedVideoIds: ['c.mp4'],
    orphanedCropImages: [],
  });
  assert.deepEqual([...deletedObjects, ...listedPrefixes], []);
  assert.equal((await post(merge, { incidentId: '1' }, { sourceIncidentId: 'x' })).status, 400);
  assert.equal((await post(merge, { incidentId: '1' }, { sourceIncidentId: 1 })).status, 422);
});

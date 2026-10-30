// SPDX-License-Identifier: Apache-2.0

// POST /api/reports/[incidentId]/evidence-image and .../evidence-sweep for the video a request names, over a fake
// R2 (the S3 client is mocked) and the fake PostgREST. R2_KEY_PREFIX scopes every physical key; database keys stay bare.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const r2 = { objects: new Map(), deleted: [], puts: [], pages: 1 };
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        const { kind, input } = command;
        if (kind === 'delete') {
          r2.deleted.push(input.Key);
          r2.objects.delete(input.Key);
          return Promise.resolve({});
        }
        if (kind === 'put') {
          r2.puts.push(input.Key);
          r2.objects.set(input.Key, new Date());
          return Promise.resolve({});
        }
        if (kind === 'head') {
          if (!r2.objects.has(input.Key)) {
            return Promise.reject(Object.assign(new Error('NotFound'), { name: 'NotFound', $metadata: { httpStatusCode: 404 } }));
          }
          return Promise.resolve({ ContentLength: 4 });
        }
        const all = [...r2.objects].filter(([key]) => key.startsWith(input.Prefix)).map(([Key, LastModified]) => ({ Key, LastModified }));
        const page = Number(input.ContinuationToken ?? 0);
        const size = Math.ceil(all.length / r2.pages) || 1;
        const more = (page + 1) * size < all.length;
        return Promise.resolve({
          Contents: all.slice(page * size, (page + 1) * size),
          IsTruncated: more,
          NextContinuationToken: more ? String(page + 1) : undefined,
        });
      }
    },
    ListObjectsV2Command: class {
      constructor(input) {
        this.kind = 'list';
        this.input = input;
      }
    },
    DeleteObjectCommand: class {
      constructor(input) {
        this.kind = 'delete';
        this.input = input;
      }
    },
    PutObjectCommand: class {
      constructor(input) {
        this.kind = 'put';
        this.input = input;
      }
    },
    HeadObjectCommand: class {
      constructor(input) {
        this.kind = 'head';
        this.input = input;
      }
    },
    GetObjectCommand: class {},
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.test/x' } });

const { POST: sweep } = await import('../src/app/api/reports/[incidentId]/evidence-sweep/route.ts');
const { POST: upload } = await import('../src/app/api/reports/[incidentId]/evidence-image/route.ts');
const { A, B, imageOf, incidentDatabase } = await import('./support/incident-write-fixture.mjs');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
const OLD = new Date(Date.now() - 48 * 3_600_000);
const FRESH = new Date(Date.now() - 60_000);
const PREFIX = 'mvp3/';

beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
    R2_KEY_PREFIX: PREFIX,
  });
  r2.objects = new Map([
    [`${PREFIX}${imageOf(A)}`, OLD], // referenced by the revision
    [`${PREFIX}evidence/${A}/crop-only/E1.jpg`, OLD], // named only by an evidence_crops row
    [`${PREFIX}evidence/${A}/failed-save/E1.jpg`, OLD], // orphan
    [`${PREFIX}evidence/${A}/in-flight/E1.jpg`, FRESH], // unreferenced but too young
    [`${PREFIX}${imageOf(B)}`, OLD], // another video
    [`evidence/${A}/outside-prefix/E1.jpg`, OLD], // outside the prefix: never listed, never deleted
  ]);
  r2.deleted = [];
  r2.puts = [];
  r2.pages = 1;
  const db = incidentDatabase();
  db.store.evidence_crops.push({
    revision_id: 1,
    video_id: A,
    item_type: 'entity',
    item_id: 'E9',
    image: `evidence/${A}/crop-only/E1.jpg`,
  });
  globalThis.fetch = db.fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const params = (id) => ({ params: Promise.resolve({ incidentId: id }) });
const call = (body, id = '1') =>
  sweep(new Request('http://localhost/x', { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }), params(id));

test('a sweep is a dry run by default: the orphan is reported and nothing is deleted', async () => {
  const response = await call({ video: A });
  assert.equal(response.status, 200);
  const report = await response.json();
  assert.deepEqual(
    [report.videoId, report.dryRun, report.orphans, report.removed, report.scanned, report.referenced, report.tooRecent],
    [A, true, [`evidence/${A}/failed-save/E1.jpg`], [], 4, 2, 1],
    'keys are the logical ones, without the prefix',
  );
  assert.deepEqual(r2.deleted, []);
});

test('dryRun false deletes only the old unreferenced object of this video, under the prefix', async () => {
  const response = await call({ video: A, dryRun: false });
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).removed, [`evidence/${A}/failed-save/E1.jpg`]);
  assert.deepEqual(r2.deleted, [`${PREFIX}evidence/${A}/failed-save/E1.jpg`]);
  assert.ok(r2.objects.has(`evidence/${A}/outside-prefix/E1.jpg`), 'an object outside the prefix is untouched');
  assert.ok(r2.objects.has(`${PREFIX}${imageOf(B)}`), 'the other camera is untouched');
});

test('a listing over several pages is read in full before anything is decided', async () => {
  r2.pages = 3;
  const report = await (await call({ video: A, dryRun: false })).json();
  assert.equal(report.scanned, 4);
  assert.deepEqual(r2.deleted, [`${PREFIX}evidence/${A}/failed-save/E1.jpg`]);
});

test('a malformed body is refused and nothing is deleted', async () => {
  for (const body of [undefined, {}, { video: A, dryRun: 'no' }, { video: A, minAgeHours: -1 }, { video: A, apply: true }, [1]]) {
    assert.equal((await call(body)).status, 400, JSON.stringify(body));
  }
  assert.equal((await call({ video: A }, 'abc')).status, 400);
  assert.deepEqual(r2.deleted, []);
});

test('an unknown video, or an unknown incident, is a 404 and nothing is deleted', async () => {
  assert.equal((await call({ video: 'vss-mvp3-p5-6-nope.mp4', dryRun: false })).status, 404);
  assert.equal((await call({ video: A, dryRun: false }, '7')).status, 404);
  assert.deepEqual(r2.deleted, []);
});

test('a video that belongs to another incident is a 404', async () => {
  const db = incidentDatabase();
  db.store.incidents.push({ id: 2, official_revision_id: null, official_since: null, created_at: '2026-10-02T00:00:00' });
  db.store.videos[1].incident_id = 2;
  globalThis.fetch = db.fetch;
  assert.equal((await call({ video: B, dryRun: false })).status, 404);
  assert.deepEqual(r2.deleted, []);
});

test('when the database cannot be read, the sweep fails and nothing is deleted', async () => {
  globalThis.fetch = async () => new Response('down', { status: 503 });
  assert.equal((await call({ video: A, dryRun: false })).status, 500);
  assert.deepEqual(r2.deleted, []);
});

test('without R2 configured the sweep fails before touching anything', async () => {
  delete process.env.R2_BUCKET;
  assert.equal((await call({ video: A, dryRun: false })).status, 500);
  assert.deepEqual(r2.deleted, []);
});

const uploadCall = (fields, id = '1') => {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) form.set(name, value);
  return upload(new Request('http://localhost/x', { method: 'POST', body: form }), params(id));
};
const image = (type = 'image/png', size = 4) => new Blob([new Uint8Array(size)], { type });

test('an uploaded evidence image gets the next free key under evidence/<video key>/edit-<n>/<itemId>.jpg and is never overwritten', async () => {
  const keys = [];
  for (let index = 0; index < 2; index += 1) {
    const response = await uploadCall({ file: image(), itemId: 'E1', video: A });
    assert.equal(response.status, 200);
    keys.push((await response.json()).image);
  }
  assert.deepEqual(keys, [`evidence/${A}/edit-1/E1.jpg`, `evidence/${A}/edit-2/E1.jpg`]);
  assert.deepEqual(
    r2.puts,
    keys.map((key) => `${PREFIX}${key}`),
    'stored under the prefix, answered without it',
  );
  assert.deepEqual(r2.deleted, [], 'nothing is deleted');
});

test('an evidence image upload refuses a missing file, video or item id, a wrong type, an oversized file and a foreign video', async () => {
  assert.equal((await uploadCall({ itemId: 'E1', video: A })).status, 400);
  assert.equal((await uploadCall({ file: image(), itemId: 'E1' })).status, 400);
  assert.equal((await uploadCall({ file: image(), itemId: '../x', video: A })).status, 400);
  assert.equal((await uploadCall({ file: image('image/gif'), itemId: 'E1', video: A })).status, 415);
  assert.equal((await uploadCall({ file: image('image/png', 5 * 1024 * 1024 + 1), itemId: 'E1', video: A })).status, 413);
  assert.equal((await uploadCall({ file: image(), itemId: 'E1', video: 'vss-mvp3-p5-6-nope.mp4' })).status, 404);
  assert.equal((await uploadCall({ file: image(), itemId: 'E1', video: A }, '7')).status, 404);
  assert.equal((await uploadCall({ file: image(), itemId: 'E1', video: A }, 'abc')).status, 400);
  assert.deepEqual(r2.puts, []);
});

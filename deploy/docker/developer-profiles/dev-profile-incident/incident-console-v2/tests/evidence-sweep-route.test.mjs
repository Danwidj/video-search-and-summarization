// SPDX-License-Identifier: Apache-2.0

// POST /api/reports/[videoId]/evidence-sweep over a fake R2 (the S3 client is mocked) and a fake PostgREST.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const r2 = { objects: new Map(), deleted: [], pages: 1 };
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        if (command.kind === 'delete') {
          r2.deleted.push(command.input.Key);
          r2.objects.delete(command.input.Key);
          return Promise.resolve({});
        }
        const all = [...r2.objects]
          .filter(([key]) => key.startsWith(command.input.Prefix))
          .map(([Key, LastModified]) => ({ Key, LastModified }));
        const page = Number(command.input.ContinuationToken ?? 0);
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
    GetObjectCommand: class {},
    PutObjectCommand: class {},
    HeadObjectCommand: class {},
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.test/x' } });

const { POST } = await import('../src/app/api/reports/[videoId]/evidence-sweep/route.ts');
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
const OLD = new Date(Date.now() - 48 * 3_600_000);
const FRESH = new Date(Date.now() - 60_000);

const entry = (image) => ({ item_type: 'entity', item_id: 'E1', image, bounding_box: null, timestamp_seconds: null });

beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
  });
  r2.objects = new Map([
    ['evidence/v-1/run/entities/E1.jpg', OLD], // the AI revision's crop
    ['evidence/v-1/u-1/E1.jpg', OLD], // the latest revision's upload
    ['evidence/v-1/crop-only/E1.jpg', OLD], // named only by an evidence_crops row
    ['evidence/v-1/failed-save/E1.jpg', OLD], // orphan
    ['evidence/v-1/in-flight/E1.jpg', FRESH], // unreferenced but too young
    ['evidence/v-2/other/E1.jpg', OLD], // another video
  ]);
  r2.deleted = [];
  r2.pages = 1;
  globalThis.fetch = fakePostgrest({
    videos: [{ id: 'v-1' }, { id: 'v-2' }],
    report_revisions: [
      { id: 1, video_id: 'v-1', evidence: [entry('evidence/v-1/run/entities/E1.jpg')] },
      { id: 2, video_id: 'v-1', evidence: [entry('evidence/v-1/u-1/E1.jpg')] },
      { id: 3, video_id: 'v-2', evidence: [] },
    ],
    evidence_crops: [{ revision_id: 2, image: 'evidence/v-1/crop-only/E1.jpg' }],
  }).fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const call = (body, videoId = 'v-1') =>
  POST(
    new Request(`http://localhost/api/reports/${videoId}/evidence-sweep`, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
    { params: Promise.resolve({ videoId }) },
  );

test('with no body it is a dry run: the orphan is reported and nothing is deleted', async () => {
  const response = await call();
  assert.equal(response.status, 200);
  const report = await response.json();
  assert.deepEqual(
    [report.dryRun, report.orphans, report.removed, report.scanned, report.referenced, report.tooRecent],
    [true, ['evidence/v-1/failed-save/E1.jpg'], [], 5, 3, 1],
  );
  assert.deepEqual(r2.deleted, []);
});

test('dryRun false deletes only the old unreferenced object of this video', async () => {
  const response = await call({ dryRun: false });
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).removed, ['evidence/v-1/failed-save/E1.jpg']);
  assert.deepEqual(r2.deleted, ['evidence/v-1/failed-save/E1.jpg']);
  assert.deepEqual([...r2.objects.keys()].sort(), [
    'evidence/v-1/crop-only/E1.jpg',
    'evidence/v-1/in-flight/E1.jpg',
    'evidence/v-1/run/entities/E1.jpg',
    'evidence/v-1/u-1/E1.jpg',
    'evidence/v-2/other/E1.jpg',
  ]);
});

test('a listing over several pages is read in full before anything is decided', async () => {
  r2.pages = 3;
  const report = await (await call({ dryRun: false })).json();
  assert.equal(report.scanned, 5);
  assert.deepEqual(r2.deleted, ['evidence/v-1/failed-save/E1.jpg']);
});

test('a malformed body is refused and nothing is deleted', async () => {
  for (const body of [{ dryRun: 'no' }, { minAgeHours: -1 }, { apply: true }, [1]]) {
    assert.equal((await call(body)).status, 400, JSON.stringify(body));
  }
  assert.deepEqual(r2.deleted, []);
});

test('an unknown video is a 404 and nothing is deleted', async () => {
  r2.objects.set('evidence/v-9/x/E1.jpg', OLD);
  const response = await call({ dryRun: false }, 'v-9');
  assert.equal(response.status, 404);
  assert.deepEqual(r2.deleted, []);
});

test('when the database cannot be read, the sweep fails and nothing is deleted', async () => {
  globalThis.fetch = async () => new Response('down', { status: 503 });
  assert.equal((await call({ dryRun: false })).status, 500);
  assert.deepEqual(r2.deleted, []);
});

test('without R2 configured it fails before touching anything', async () => {
  delete process.env.R2_BUCKET;
  assert.equal((await call({ dryRun: false })).status, 500);
  assert.deepEqual(r2.deleted, []);
});

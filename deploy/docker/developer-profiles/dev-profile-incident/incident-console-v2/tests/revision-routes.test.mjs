// SPDX-License-Identifier: Apache-2.0

// The revision History and evidence-image upload routes. An upload gets a new
// readable R2 key and nothing is ever overwritten or deleted.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const r2Commands = [];
const r2Stored = new Set();
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        r2Commands.push({ name: command.constructor.name, input: command.input });
        if (command.constructor.name === 'PutObjectCommand') r2Stored.add(command.input.Key);
        if (command.constructor.name !== 'HeadObjectCommand') return Promise.resolve({});
        if (!r2Stored.has(command.input.Key))
          return Promise.reject(Object.assign(new Error('NotFound'), { name: 'NotFound', $metadata: { httpStatusCode: 404 } }));
        return Promise.resolve({ ContentLength: command.input.size ?? 4 });
      }
    },
    GetObjectCommand: class GetObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    PutObjectCommand: class PutObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    HeadObjectCommand: class HeadObjectCommand {
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
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.r2.test/x' } });

const { GET: history } = await import('../src/app/api/reports/[incidentId]/revisions/route.ts');
const { POST: uploadImage } = await import('../src/app/api/reports/[incidentId]/evidence-image/route.ts');
const { aiRevisionRow } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { revisionRpcs } = await import('./support/revisions-database.mjs');

const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const V = repaired.videoId;
const params = { params: Promise.resolve({ incidentId: V }) };
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  r2Commands.length = 0;
  r2Stored.clear();
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
  });
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

function database() {
  const db = fakePostgrest(
    {
      videos: [{ ...repaired.video, official_revision_id: 1 }],
      model_runs: [repaired.modelRun],
      report_revisions: [aiRevisionRow(repaired)],
    },
    { rpc: revisionRpcs, identity: { report_revisions: 'id' } },
  );
  globalThis.fetch = db.fetch;
  return db;
}
const upload = (fields) => {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) form.set(name, value);
  return uploadImage(new Request(`http://localhost/api/reports/${V}/evidence-image`, { method: 'POST', body: form }), params);
};
const image = (type = 'image/png', size = 4) => new Blob([new Uint8Array(size)], { type });

test('History lists every revision newest first with kind, author, time, note and the official flag', async () => {
  const db = database();
  db.store.report_revisions.push({
    ...aiRevisionRow(repaired),
    id: 2,
    revision_no: 2,
    kind: 'human',
    parent_id: 1,
    created_by: 'Lead',
    note: 'Edited by hand',
  });
  const response = await history(new Request(`http://localhost/api/reports/${V}/revisions`), params);
  assert.equal(response.status, 200);
  const { revisions } = await response.json();
  assert.deepEqual(
    revisions.map((r) => [r.revisionNo, r.kind, r.createdBy, r.isOfficial]),
    [
      [2, 'human', 'Lead', false],
      [1, 'ai', null, true],
    ],
  );
  assert.equal(revisions[0].note, 'Edited by hand');
  assert.equal(revisions[1].model, repaired.modelRun.model_name);
  assert.ok(
    revisions.every((r) => r.createdAt),
    'each revision carries its time',
  );
  assert.equal(db.store.report_revisions.length, 2);
});

test('an uploaded evidence image gets the next free key under evidence/<video key>/edit-<n>/<itemId>.jpg and is never overwritten', async () => {
  database();
  const keys = [];
  for (let index = 0; index < 2; index += 1) {
    const response = await upload({ file: image(), itemId: 'E1' });
    assert.equal(response.status, 200);
    keys.push((await response.json()).image);
  }
  const videoKey = repaired.video.filepath;
  assert.deepEqual(keys, [`evidence/${videoKey}/edit-1/E1.jpg`, `evidence/${videoKey}/edit-2/E1.jpg`]);
  const puts = r2Commands.filter((c) => c.name === 'PutObjectCommand');
  assert.deepEqual(
    puts.map((c) => c.input.Key),
    keys,
  );
  assert.ok(!r2Commands.some((c) => c.name === 'DeleteObjectCommand'), 'nothing is deleted');
});

test('an evidence image upload refuses a missing file, a bad item id, a wrong type and an oversized file', async () => {
  assert.equal((await upload({ itemId: 'E1' })).status, 400);
  assert.equal((await upload({ file: image(), itemId: '../x' })).status, 400);
  assert.equal((await upload({ file: image('image/gif'), itemId: 'E1' })).status, 415);
  assert.equal((await upload({ file: image('image/png', 5 * 1024 * 1024 + 1), itemId: 'E1' })).status, 413);
  assert.equal(r2Commands.length, 0);
});

// SPDX-License-Identifier: Apache-2.0

// The revision History, Restore and evidence-image upload routes. A restore
// appends a human revision; an upload gets a new unique R2 key and nothing is
// ever overwritten or deleted.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const r2Commands = [];
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        r2Commands.push({ name: command.constructor.name, input: command.input });
        return Promise.resolve(command.constructor.name === 'HeadObjectCommand' ? { ContentLength: command.input.size ?? 4 } : {});
      }
    },
    GetObjectCommand: class GetObjectCommand { constructor(input) { this.input = input; } },
    PutObjectCommand: class PutObjectCommand { constructor(input) { this.input = input; } },
    HeadObjectCommand: class HeadObjectCommand { constructor(input) { this.input = input; } },
    DeleteObjectCommand: class DeleteObjectCommand { constructor(input) { this.input = input; } },
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.r2.test/x' } });

const { GET: history } = await import('../app/api/reports/[videoId]/revisions/route.ts');
const { POST: restore } = await import('../app/api/reports/[videoId]/restore/route.ts');
const { POST: uploadImage } = await import('../app/api/reports/[videoId]/evidence-image/route.ts');
const { aiRevisionRow } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { revisionRpcs } = await import('./support/revisions-database.mjs');

const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const V = repaired.videoId;
const params = { params: Promise.resolve({ videoId: V }) };
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  r2Commands.length = 0;
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a', R2_ACCESS_KEY: 'b', R2_SECRET_KEY: 'c', R2_BUCKET: 'd',
  });
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

function database() {
  const db = fakePostgrest(
    { videos: [{ ...repaired.video, official_revision_id: 1 }], model_runs: [repaired.modelRun], report_revisions: [aiRevisionRow(repaired)] },
    { rpc: revisionRpcs, identity: { report_revisions: 'id' } },
  );
  globalThis.fetch = db.fetch;
  return db;
}
const restoreRequest = (body) => restore(new Request(`http://localhost/api/reports/${V}/restore`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), params);
const upload = (fields) => {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) form.set(name, value);
  return uploadImage(new Request(`http://localhost/api/reports/${V}/evidence-image`, { method: 'POST', body: form }), params);
};
const image = (type = 'image/png', size = 4) => new Blob([new Uint8Array(size)], { type });

test('History lists every revision newest first with kind, author, time, note and the official flag', async () => {
  const db = database();
  assert.equal((await restoreRequest({ revisionId: 1, restoredBy: 'Lead' })).status, 200);
  const response = await history(new Request(`http://localhost/api/reports/${V}/revisions`), params);
  assert.equal(response.status, 200);
  const { revisions } = await response.json();
  assert.deepEqual(revisions.map((r) => [r.revisionNo, r.kind, r.createdBy, r.isOfficial]), [[2, 'human', 'Lead', false], [1, 'ai', null, true]]);
  assert.equal(revisions[0].note, 'Restored revision 1');
  assert.equal(revisions[1].model, repaired.modelRun.model_name);
  assert.ok(revisions.every((r) => r.createdAt), 'each revision carries its time');
  assert.equal(db.store.report_revisions.length, 2);
});

test('Restore appends a human revision copying the chosen one; the original and the official mark are untouched', async () => {
  const db = database();
  const before = JSON.stringify(db.store.report_revisions[0]);
  const response = await restoreRequest({ revisionId: 1, restoredBy: 'Lead' });
  assert.equal(response.status, 200);
  const { restored, revision } = await response.json();
  assert.equal(restored, true);
  assert.deepEqual([revision.revisionNo, revision.kind, revision.parentId, revision.createdBy], [2, 'human', 1, 'Lead']);
  const [original, copy] = db.store.report_revisions;
  assert.equal(JSON.stringify(original), before);
  assert.deepEqual([copy.payload, copy.evidence], [original.payload, original.evidence]);
  assert.equal(db.store.videos[0].official_revision_id, 1);
  assert.deepEqual(db.requests.filter((r) => r.method !== 'GET').map((r) => r.path), ['rpc/save_human_revision']);
});

test('Restore refuses a malformed body (400) and an unknown revision (404) without writing', async () => {
  const db = database();
  for (const bad of [{}, { revisionId: 1 }, { revisionId: '1', restoredBy: 'x' }, { revisionId: 1, restoredBy: 'x', extra: true }]) {
    assert.equal((await restoreRequest(bad)).status, 400);
  }
  assert.equal((await restoreRequest({ revisionId: 99, restoredBy: 'Lead' })).status, 404);
  assert.deepEqual(db.requests.filter((r) => r.method !== 'GET'), []);
});

test('an uploaded evidence image gets a new unique key under evidence/<videoId>/<uuid>/<itemId>.jpg and is never overwritten', async () => {
  const keys = [];
  for (let index = 0; index < 2; index += 1) {
    const response = await upload({ file: image(), itemId: 'E1' });
    assert.equal(response.status, 200);
    keys.push((await response.json()).image);
  }
  for (const key of keys) assert.match(key, new RegExp(`^evidence/${V}/[0-9a-f-]{36}/E1\\.jpg$`));
  assert.notEqual(keys[0], keys[1], 'the same item uploaded twice gets two keys');
  const puts = r2Commands.filter((c) => c.name === 'PutObjectCommand');
  assert.deepEqual(puts.map((c) => c.input.Key), keys);
  assert.ok(!r2Commands.some((c) => c.name === 'DeleteObjectCommand'), 'nothing is deleted');
});

test('an evidence image upload refuses a missing file, a bad item id, a wrong type and an oversized file', async () => {
  assert.equal((await upload({ itemId: 'E1' })).status, 400);
  assert.equal((await upload({ file: image(), itemId: '../x' })).status, 400);
  assert.equal((await upload({ file: image('image/gif'), itemId: 'E1' })).status, 415);
  assert.equal((await upload({ file: image('image/png', 5 * 1024 * 1024 + 1), itemId: 'E1' })).status, 413);
  assert.equal(r2Commands.length, 0);
});

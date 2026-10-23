// SPDX-License-Identifier: Apache-2.0

// PATCH /api/reports/[videoId]/edit: Save appends a human revision; model_runs is never written.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../src/app/api/reports/[videoId]/edit/route.ts');
const { aiRevisionRow, unchangedEdit } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { revisionRpcs } = await import('./support/revisions-database.mjs');

const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const baseEdit = () => unchangedEdit(repaired);
const patch = (body, videoId = repaired.videoId) => PATCH(new Request(`http://localhost/api/reports/${videoId}/edit`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
}), { params: Promise.resolve({ videoId }) });
const request = (edit, extra = {}) => ({ parentId: 1, editedBy: 'Rev', edit, ...extra });

function database() {
  const db = fakePostgrest(
    { videos: [{ ...repaired.video, official_revision_id: null }], model_runs: [repaired.modelRun], report_revisions: [aiRevisionRow(repaired)] },
    { rpc: revisionRpcs, identity: { report_revisions: 'id' } },
  );
  globalThis.fetch = db.fetch;
  return db;
}
const writes = (db) => db.requests.filter((r) => r.method !== 'GET');

test('a valid edit goes to save_human_revision only; model_runs (notes) is never written', async () => {
  const db = database();
  const edit = baseEdit();
  edit.incident.severity_level = 2;

  const response = await patch(request(edit, { note: 'Lowered' }));

  assert.equal(response.status, 200);
  const { saved, revision, searchable } = await response.json();
  assert.equal(saved, true);
  assert.deepEqual([revision.revisionNo, revision.kind, revision.parentId, revision.createdBy, revision.note], [2, 'human', 1, 'Rev', 'Lowered']);
  assert.deepEqual(writes(db).map((r) => r.path), ['rpc/save_human_revision', 'rpc/set_revision_crops']);
  assert.deepEqual(writes(db)[1].body, { p_video_id: repaired.videoId, p_revision_id: revision.revisionId, p_crops: [] }, 'the new searchable revision has no images, so its crops are cleared');
  assert.deepEqual(searchable, { crops: 0 });
  const [{ body }] = writes(db);
  assert.deepEqual([body.p_video_id, body.p_parent_id, body.p_created_by, body.p_note], [repaired.videoId, 1, 'Rev', 'Lowered']);
  assert.equal(body.p_payload.incident.severity_level, 2);
  assert.equal(db.store.report_revisions[1].severity_level, 2, 'the facet columns follow the saved payload');
  assert.ok(!writes(db).some((r) => r.path === 'model_runs'), 'the edit path never writes model_runs');
  assert.deepEqual(db.store.model_runs, [repaired.modelRun], 'the run notes are unchanged');
  assert.equal(db.store.report_revisions[0].payload.incident.severity_level, aiRevisionRow(repaired).payload.incident.severity_level, 'the AI revision is untouched');
});

test('with an official revision, Save does not touch the evidence crops', async () => {
  const db = database();
  db.store.videos[0].official_revision_id = 1;
  const response = await patch(request(baseEdit()));
  assert.equal(response.status, 200);
  assert.deepEqual(writes(db).map((r) => r.path), ['rpc/save_human_revision']);
  assert.deepEqual((await response.json()).searchable, { crops: null });
});

test('a crops failure does not fail Save: the revision is kept and the error is reported', async () => {
  const db = database();
  globalThis.fetch = async (url, init) => (String(url).includes('rpc/set_revision_crops') ? new Response('{"message":"boom"}', { status: 500 }) : db.fetch(url, init));
  const response = await patch(request(baseEdit()));
  assert.equal(response.status, 200);
  const { saved, searchable } = await response.json();
  assert.equal(saved, true);
  assert.equal(searchable.crops, null);
  assert.match(searchable.error, /boom|500/);
  assert.equal(db.store.report_revisions.length, 2);
});

test('Class B/C fields are rejected with 400 before any database call', async () => {
  const db = database();
  const edit = baseEdit();
  edit.incident.severity_reason = 'Reviewer rationale';
  const response = await patch(request(edit));
  assert.equal(response.status, 400);
  assert.deepEqual((await response.json()).notEditable, ['incident.severity_reason']);
  assert.equal(db.requests.length, 0);
});

test('contract violations are rejected with 422 before any database call', async () => {
  const db = database();
  const edit = baseEdit();
  edit.instruments[0].entity_id = 'E7';
  const response = await patch(request(edit));
  assert.equal(response.status, 422);
  assert.match((await response.json()).violations[0].message, /unknown entity_id E7/);
  assert.equal(db.requests.length, 0);
});

test('an editor name and a parent revision are required and unknown request keys are refused', async () => {
  const db = database();
  assert.equal((await patch(request(baseEdit(), { editedBy: '  ' }))).status, 400);
  assert.equal((await patch(request(baseEdit(), { parentId: 0 }))).status, 400);
  assert.equal((await patch({ editedBy: 'Rev', edit: baseEdit() })).status, 400);
  assert.equal((await patch(request(baseEdit(), { notes: '{}' }))).status, 400);
  assert.equal(db.requests.length, 0);
});

test('an edit of a revision that does not exist is a 404 and nothing is written', async () => {
  const db = database();
  const response = await patch(request(baseEdit(), { parentId: 77 }));
  assert.equal(response.status, 404);
  assert.deepEqual(writes(db), []);
});

test('an item without a source_id is refused with 422 before any database call', async () => {
  const db = database();
  const edit = baseEdit();
  delete edit.entities[0].source_id;
  const response = await patch(request(edit));
  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /source_id/);
  assert.equal(db.requests.length, 0);
});

test('an image that is not one of the incident\'s own is refused with 422 and nothing is written', async () => {
  const db = database();
  const edit = baseEdit();
  edit.entities[0].image = 'evidence/another-video/u/E1.jpg';
  const response = await patch(request(edit));
  assert.equal(response.status, 422);
  assert.deepEqual(writes(db), []);
});

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
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const baseEdit = () => unchangedEdit(repaired);
const patch = (body, videoId = repaired.videoId) =>
  PATCH(
    new Request(`http://localhost/api/reports/${videoId}/edit`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ videoId }) },
  );
const request = (edit, extra = {}) => ({ parentId: 1, editedBy: 'Rev', edit, ...extra });

function database() {
  const db = fakePostgrest(
    {
      videos: [{ ...repaired.video, official_revision_id: null }],
      model_runs: [repaired.modelRun],
      report_revisions: [aiRevisionRow(repaired)],
    },
    { rpc: revisionRpcs, identity: { report_revisions: 'id' } },
  );
  globalThis.fetch = db.fetch;
  return db;
}
const writes = (db) => db.requests.filter((r) => r.method !== 'GET');

test('a valid edit goes to save_human_revision_with_crops only; model_runs (notes) is never written', async () => {
  const db = database();
  const edit = baseEdit();
  edit.incident.severity_level = 2;

  const response = await patch(request(edit, { note: 'Lowered' }));

  assert.equal(response.status, 200);
  const { saved, revision } = await response.json();
  assert.equal(saved, true);
  assert.deepEqual(
    [revision.revisionNo, revision.kind, revision.parentId, revision.createdBy, revision.note],
    [2, 'human', 1, 'Rev', 'Lowered'],
  );
  assert.deepEqual(
    writes(db).map((r) => r.path),
    ['rpc/save_human_revision_with_crops'],
  );
  const [{ body }] = writes(db);
  assert.deepEqual([body.p_video_id, body.p_parent_id, body.p_created_by, body.p_note], [repaired.videoId, 1, 'Rev', 'Lowered']);
  assert.deepEqual(body.p_crops, [], 'the edit has no images, so the new searchable revision has no crops');
  assert.equal(body.p_payload.incident.severity_level, 2);
  assert.equal(db.store.report_revisions[1].severity_level, 2, 'the facet columns follow the saved payload');
  assert.ok(!writes(db).some((r) => r.path === 'model_runs'), 'the edit path never writes model_runs');
  assert.deepEqual(db.store.model_runs, [repaired.modelRun], 'the run notes are unchanged');
  assert.equal(
    db.store.report_revisions[0].payload.incident.severity_level,
    aiRevisionRow(repaired).payload.incident.severity_level,
    'the AI revision is untouched',
  );
});

test('with an official revision, Save writes no crops', async () => {
  const db = database();
  db.store.videos[0].official_revision_id = 1;
  const response = await patch(request(baseEdit()));
  assert.equal(response.status, 200);
  assert.deepEqual(
    writes(db).map((r) => r.path),
    ['rpc/save_human_revision_with_crops'],
  );
  assert.deepEqual(writes(db)[0].body.p_crops, [], 'the official revision keeps its own crops');
});

test('an embedding failure stops Save: no revision is written and the reviewer is told why', async () => {
  const db = database();
  process.env.INCIDENT_AGENT_BASE_URL = 'https://agent.test';
  globalThis.fetch = async (url, init) =>
    String(url).startsWith('https://agent.test/') ? new Response('{"detail":"down"}', { status: 502 }) : db.fetch(url, init);
  const edit = baseEdit();
  assert.ok(edit.entities.length > 0, 'the fixture has an entity to give an image');
  edit.entities[0].image = `evidence/${repaired.video.filepath}/edit-1/${edit.entities[0].entity_id}.jpg`;

  const response = await patch(request(edit, { note: 'Added a crop' }));

  assert.equal(response.status, 502);
  assert.match((await response.json()).error, /could not be made searchable \(The agent returned HTTP 502.*Try Save again/);
  assert.equal(writes(db).length, 0, 'the save RPC is never reached');
  assert.equal(db.store.report_revisions.length, 1, 'no revision was written');
});

test('an edit with an image is embedded first, and its crop is written with the revision in one call', async () => {
  const db = database();
  process.env.INCIDENT_AGENT_BASE_URL = 'https://agent.test';
  const posted = [];
  globalThis.fetch = async (url, init) => {
    if (!String(url).startsWith('https://agent.test/')) return db.fetch(url, init);
    posted.push(JSON.parse(init.body));
    return new Response(JSON.stringify([{ item_type: 'entity', item_id: 'E1', embedding: Array(1024).fill(0.25) }]), { status: 200 });
  };
  const edit = baseEdit();
  const key = `evidence/${repaired.video.filepath}/edit-1/${edit.entities[0].entity_id}.jpg`;
  edit.entities[0].image = key;

  const response = await patch(request(edit));

  assert.equal(response.status, 200);
  assert.deepEqual(
    posted.map((body) => body.evidence.map((item) => [item.item_type, item.item_id])),
    [[['entity', 'E1']]],
    'the agent embeds the new evidence, not a stored revision',
  );
  assert.deepEqual(
    writes(db).map((r) => r.path),
    ['rpc/save_human_revision_with_crops'],
    'the crop is not written in a separate call',
  );
  const [{ body }] = writes(db);
  assert.deepEqual(
    body.p_crops.map((crop) => [crop.item_type, crop.item_id, crop.image, crop.embedding.length]),
    [['entity', 'E1', key, 1024]],
  );
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

test("an image that is not one of the incident's own is refused with 422 and nothing is written", async () => {
  const db = database();
  const edit = baseEdit();
  edit.entities[0].image = 'evidence/another-video/u/E1.jpg';
  const response = await patch(request(edit));
  assert.equal(response.status, 422);
  assert.deepEqual(writes(db), []);
});

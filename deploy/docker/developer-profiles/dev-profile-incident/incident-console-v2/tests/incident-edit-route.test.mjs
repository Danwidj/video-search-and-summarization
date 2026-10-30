// SPDX-License-Identifier: Apache-2.0

// PATCH /api/reports/[incidentId]/edit: Save appends a human revision of the whole report with one camera or the
// overview edited; the parent's coverage is kept and model_runs is never written.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../src/app/api/reports/[incidentId]/edit/route.ts');
const { unchangedEdit } = await import('./support/report-view.mjs');
const { A, B, editKeepingImage, imageOf, incidentDatabase, repaired, withAgent, writes } = await import(
  './support/incident-write-fixture.mjs'
);

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'test-key',
    INCIDENT_AGENT_BASE_URL: 'http://agent.test:8000/',
  });
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const patch = (body, incidentId = '1') =>
  PATCH(
    new Request(`http://localhost/api/reports/${incidentId}/edit`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ incidentId }) },
  );
const request = (extra) => ({ parentId: 1, editedBy: 'Rev', ...extra });

function setup(options) {
  const db = incidentDatabase(options);
  const agentCalls = withAgent(db);
  return { db, agentCalls };
}

test('a camera edit saves the whole report with that camera changed, the other untouched, and the parent coverage', async () => {
  const { db } = setup({ official: 1 });
  const edit = editKeepingImage(A);
  edit.incident.severity_level = 2;

  const response = await patch(request({ camera: A, edit, note: 'Lowered' }));

  assert.equal(response.status, 200);
  const { saved, revision } = await response.json();
  assert.equal(saved, true);
  assert.deepEqual(
    [revision.revisionNo, revision.kind, revision.parentId, revision.createdBy, revision.note, revision.videoNames],
    [2, 'human', 1, 'Rev', 'Lowered', [A, B]],
  );
  assert.deepEqual(
    writes(db).map((r) => r.path),
    ['rpc/save_human_revision_with_crops'],
  );
  const [saved2] = db.store.report_revisions.slice(-1);
  const [cameraA, cameraB] = saved2.payload.cameras;
  assert.equal(cameraA.video, A);
  assert.equal(cameraA.report.incident.severity_level, 2);
  assert.deepEqual(cameraB, db.store.report_revisions[0].payload.cameras[1], 'the other camera is byte-for-byte the parent');
  assert.deepEqual(saved2.payload.overview, db.store.report_revisions[0].payload.overview);
  assert.deepEqual(
    saved2.evidence.map((item) => [item.item_id, item.image]),
    [
      ['E1', imageOf(B)],
      ['E1', imageOf(A)],
    ],
    'the other camera keeps its evidence, the edited camera keeps the image it had',
  );
  assert.deepEqual(db.store.model_runs.length, 1);
  assert.ok(!writes(db).some((r) => r.path === 'model_runs'), 'the edit path never writes model_runs');
  assert.equal(db.store.report_revisions[0].payload.cameras[0].report.incident.severity_level, 3, 'the AI revision is untouched');
});

test('with no official revision, the new revision is searchable: one embedding call per camera, crops tagged with their video', async () => {
  const { db, agentCalls } = setup();

  const response = await patch(request({ camera: A, edit: editKeepingImage(A) }));

  assert.equal(response.status, 200);
  assert.equal(agentCalls.length, 2, 'item ids repeat across cameras, so each camera is embedded on its own');
  const { body } = writes(db)[0];
  assert.deepEqual(
    body.p_crops.map((crop) => [crop.video_id, crop.item_id, crop.image]).sort(),
    [
      [A, 'E1', imageOf(A)],
      [B, 'E1', imageOf(B)],
    ].sort(),
  );
  assert.deepEqual(
    db.store.evidence_crops.map((crop) => [crop.revision_id, crop.video_id]).sort(),
    [
      [2, A],
      [2, B],
    ],
    'the crops belong to the new revision only',
  );
});

test('with an official revision, Save embeds nothing and writes no crops', async () => {
  const { db, agentCalls } = setup({ official: 1 });
  const response = await patch(request({ camera: B, edit: editKeepingImage(B) }));
  assert.equal(response.status, 200);
  assert.equal(agentCalls.length, 0);
  assert.deepEqual(writes(db)[0].body.p_crops, [], 'the official revision keeps its own crops');
});

test('an overview edit replaces the overview only', async () => {
  const { db } = setup({ official: 1 });
  const response = await patch(
    request({ overview: { title: 'Renamed', type: 'assault', severity_level: 4, description: 'New', location: 'Dock' } }),
  );
  assert.equal(response.status, 200);
  const [, saved] = db.store.report_revisions;
  assert.deepEqual(saved.payload.overview, { title: 'Renamed', type: 'assault', severity_level: 4, description: 'New', location: 'Dock' });
  assert.deepEqual(saved.payload.cameras, db.store.report_revisions[0].payload.cameras);
  assert.deepEqual(saved.evidence, db.store.report_revisions[0].evidence);
  assert.deepEqual(saved.video_names, [A, B]);
});

test('an embedding failure stops Save: no revision is written and the reviewer is told why', async () => {
  const { db } = setup();
  withAgent(db, { agent: () => new Response('{"detail":"down"}', { status: 502 }) });
  const response = await patch(request({ camera: A, edit: editKeepingImage(A) }));
  assert.equal(response.status, 502);
  assert.match((await response.json()).error, /could not be made searchable \(The agent returned HTTP 502.*Try Save again/);
  assert.equal(writes(db).length, 0, 'the save RPC is never reached');
  assert.equal(db.store.report_revisions.length, 1);
});

test('a camera the parent does not cover, or an unknown one, is refused and nothing is written', async () => {
  const { db } = setup();
  db.store.report_revisions[0].video_names = [B];
  const uncovered = await patch(request({ camera: A, edit: editKeepingImage(A) }));
  assert.equal(uncovered.status, 422);
  const unknown = await patch(request({ camera: 'vss-mvp3-p5-6-nope.mp4', edit: unchangedEdit(repaired) }));
  assert.equal(unknown.status, 422);
  assert.equal(writes(db).length, 0);
});

test('a parent or an incident that does not exist is a 404', async () => {
  const { db } = setup();
  assert.equal((await patch(request({ parentId: 9, camera: A, edit: unchangedEdit(repaired) }))).status, 404);
  assert.equal((await patch(request({ camera: A, edit: unchangedEdit(repaired) }), '7')).status, 404);
  assert.equal(writes(db).length, 0);
});

test('a malformed body or incident id is a 400 and nothing is written', async () => {
  const { db } = setup();
  for (const body of [
    request({}),
    request({ camera: A }),
    request({ edit: unchangedEdit(repaired) }),
    request({ camera: A, edit: unchangedEdit(repaired), overview: { title: 'x' } }),
    request({ overview: { severity_level: 9 } }),
    request({ overview: { colour: 'red' } }),
    { parentId: 1, camera: A, edit: unchangedEdit(repaired) },
  ]) {
    assert.equal((await patch(body)).status, 400, JSON.stringify(body).slice(0, 80));
  }
  assert.equal((await patch(request({ camera: A, edit: unchangedEdit(repaired) }), 'abc')).status, 400);
  assert.equal(writes(db).length, 0);
});

test('Class B/C fields and contract violations are refused before any database call', async () => {
  const { db } = setup();
  const classB = unchangedEdit(repaired);
  classB.incident.confidence = 0.9;
  const rejected = await patch(request({ camera: A, edit: classB }));
  assert.ok([400, 422].includes(rejected.status));
  const invalid = unchangedEdit(repaired);
  invalid.incident.severity_level = 9;
  assert.equal((await patch(request({ camera: A, edit: invalid }))).status, 422);
  assert.equal(writes(db).length, 0);
});

test('an image that is not the camera own is refused with 422; another camera folder does not count', async () => {
  const { db } = setup();
  const edit = unchangedEdit(repaired);
  edit.entities[0].image = imageOf(B);
  edit.entities[0].source_id = 'E1';
  // B's image is a known image of the revision, so it passes; a key in a third video's folder does not.
  edit.entities[1].image = 'evidence/vss-mvp3-p5-6-other.mp4/edit-1/E2.jpg';
  const response = await patch(request({ camera: A, edit }));
  assert.equal(response.status, 422);
  assert.equal(writes(db).length, 0);
});

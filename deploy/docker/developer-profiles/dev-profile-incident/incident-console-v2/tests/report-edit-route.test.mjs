// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../app/api/reports/[videoId]/edit/route.ts');
const { draftFromView, editFromDraft } = await import('../lib/reports/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const baseEdit = () => editFromDraft(draftFromView(buildReportView({ ...clone(repaired), playbackUrl: 'x' })));
const patch = (body, videoId = repaired.videoId) => PATCH(new Request(`http://localhost/api/reports/${videoId}/edit`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
}), { params: Promise.resolve({ videoId }) });

function recordingFetch(calls, { incidentExists = true, refusal = null } = {}) {
  return async (url, init = {}) => {
    const parsed = new URL(String(url));
    calls.push({ table: parsed.pathname.replace('/rest/v1/', ''), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined });
    if (parsed.pathname.endsWith('/incidents')) return new Response(JSON.stringify(incidentExists ? [{ incident_id: repaired.videoId }] : []));
    if (parsed.pathname.endsWith('/rpc/save_human_report_edit')) {
      if (refusal) return new Response(JSON.stringify({ code: 'P0001', details: null, hint: null, message: refusal }), { status: 400 });
      return new Response(JSON.stringify({ incidentId: repaired.videoId, modelRunId: repaired.modelRunId, editedBy: 'Rev', editedAt: '2026-10-21T01:00:00', duration: 12, revision: 2, status: 'under review' }));
    }
    return new Response('[]');
  };
}

test('a valid edit goes to the reviewer-version RPC only; model_runs (notes) is never written', async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls);
  const edit = baseEdit();
  edit.incident.severity_level = 2;

  const response = await patch({ modelRunId: repaired.modelRunId, editedBy: 'Rev', edit });

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    saved: true,
    result: { incidentId: repaired.videoId, modelRunId: repaired.modelRunId, editedBy: 'Rev', editedAt: '2026-10-21T01:00:00', duration: 12, revision: 2, status: 'under review' },
  });
  const writes = calls.filter((c) => c.method !== 'GET');
  assert.deepEqual(writes.map((c) => c.table), ['rpc/save_human_report_edit']);
  assert.deepEqual(writes[0].body, { p_incident_id: repaired.videoId, p_model_run_id: repaired.modelRunId, p_edit: edit, p_edited_by: 'Rev' });
  assert.deepEqual(writes[0].body.p_edit.instruments.map((i) => i.source_id), ['I1', 'I2'], 'each item names its AI origin');
  assert.ok(!calls.some((c) => c.table === 'model_runs'), 'the edit path never touches model_runs');
});

test('Class B/C fields are rejected with 400 before any database call', async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls);
  const edit = baseEdit();
  edit.incident.severity_reason = 'Reviewer rationale';
  const response = await patch({ modelRunId: repaired.modelRunId, editedBy: 'Rev', edit });
  assert.equal(response.status, 400);
  assert.deepEqual((await response.json()).notEditable, ['incident.severity_reason']);
  assert.equal(calls.length, 0);
});

test('contract violations are rejected with 422 before any database call', async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls);
  const edit = baseEdit();
  edit.instruments[0].entity_id = 'E7';
  const response = await patch({ modelRunId: repaired.modelRunId, editedBy: 'Rev', edit });
  assert.equal(response.status, 422);
  assert.match((await response.json()).violations[0].message, /unknown entity_id E7/);
  assert.equal(calls.length, 0);
});

test('an editor name is required and unknown request keys are refused', async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls);
  assert.equal((await patch({ modelRunId: repaired.modelRunId, editedBy: '  ', edit: baseEdit() })).status, 400);
  assert.equal((await patch({ modelRunId: repaired.modelRunId, editedBy: 'Rev', edit: baseEdit(), notes: '{}' })).status, 400);
  assert.equal(calls.length, 0);
});

test('an edit for a run without an incident is a 404 and nothing is written', async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls, { incidentExists: false });
  const response = await patch({ modelRunId: 'm-failed-attempt', editedBy: 'Rev', edit: baseEdit() });
  assert.equal(response.status, 404);
  assert.ok(!calls.some((c) => c.method !== 'GET'));
});

test("the database's refusal of an edit is a 422 with its reason", async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls, { refusal: 'I1 names source_id "I9", which is not an AI instrument of this run' });
  const response = await patch({ modelRunId: repaired.modelRunId, editedBy: 'Rev', edit: baseEdit() });
  assert.equal(response.status, 422);
  assert.deepEqual(await response.json(), { error: 'I1 names source_id "I9", which is not an AI instrument of this run' });
});

test('an edit item without a source_id is refused with 422 before any database call', async () => {
  const calls = [];
  globalThis.fetch = recordingFetch(calls);
  const edit = baseEdit();
  delete edit.entities[0].source_id;
  const response = await patch({ modelRunId: repaired.modelRunId, editedBy: 'Rev', edit });
  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /source_id/);
  assert.equal(calls.length, 0);
});

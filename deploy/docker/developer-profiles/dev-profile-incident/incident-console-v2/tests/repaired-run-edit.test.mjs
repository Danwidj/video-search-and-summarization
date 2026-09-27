// SPDX-License-Identifier: Apache-2.0

// Requested proof for the repaired run m811cf2b237f50ff9812: an edit changes
// its relational values while its original response, repair operations,
// repaired report and valid_after_structural_repair outcome stay byte-for-byte
// unchanged. The database half (the SQL function itself) is exercised by the
// transactional dry run of 20260927160000_apply_structured_report_edit.sql.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../app/api/reports/[videoId]/edit/route.ts');
const { draftFromView, editFromDraft } = await import('../lib/reports/edit-draft.ts');
const { buildReportView } = await import('../lib/reports/view.ts');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));

/** In-memory stand-in for the rows, applying the edit exactly as apply_structured_report_edit does. */
function applyEditToRows(rows, edit, editedBy) {
  const { incident } = edit;
  return {
    ...rows,
    incident: { ...rows.incident, type: incident.type, start_timestamp: String(incident.start_timestamp), end_timestamp: String(incident.end_timestamp), duration: incident.end_timestamp - incident.start_timestamp, description: incident.description, severity_level: incident.severity_level },
    entities: edit.entities.map((e) => ({ incident_id: rows.videoId, model_run_id: rows.modelRunId, ...e, image: null })),
    instruments: edit.instruments.map((i) => ({ incident_id: rows.videoId, model_run_id: rows.modelRunId, ...i, image: null })),
    assets: edit.assets.map((a) => ({ incident_id: rows.videoId, model_run_id: rows.modelRunId, ...a, image: null })),
    review: { ...rows.review, edited_by: editedBy, edited_at: '2026-09-27T12:00:00' },
  };
}

test('editing repaired run m811cf2b237f50ff9812 changes only the relational projection; its notes stay byte-for-byte identical', async () => {
  const rows = clone(fixture);
  const notesBefore = rows.modelRun.notes;
  const before = JSON.parse(notesBefore).incidentConsoleV2;

  // Reviewer lowers severity 3 -> 2, moves the end to 12 s, retypes E2 and adds an asset.
  const edit = editFromDraft(draftFromView(buildReportView({ ...clone(rows), playbackUrl: 'x' })));
  edit.incident.severity_level = 2;
  edit.incident.end_timestamp = 12;
  edit.entities[1].type = 'unknown';
  edit.assets.push({ asset_id: 'A1', name: 'white van', description: 'Parked van beside the sidewalk.' });

  const calls = [];
  const originalFetch = globalThis.fetch;
  Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' });
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(String(url)).pathname.replace('/rest/v1/', '');
    calls.push({ path, method: init.method || 'GET' });
    if (path === 'incidents') return new Response(JSON.stringify([{ incident_id: rows.videoId }]));
    return new Response(JSON.stringify({ duration: 11 }));
  };
  try {
    const response = await PATCH(new Request('http://localhost/x', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ modelRunId: rows.modelRunId, editedBy: 'Reviewer A', edit }) }), { params: Promise.resolve({ videoId: rows.videoId }) });
    assert.equal(response.status, 200);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.ok(!calls.some((c) => c.path === 'model_runs'), 'no read or write of model_runs on the edit path');

  const edited = applyEditToRows(rows, edit, 'Reviewer A');
  // The notes string is untouched: same bytes, same outcome, same original response, same repair, same repaired report.
  assert.equal(edited.modelRun.notes, notesBefore);
  const after = JSON.parse(edited.modelRun.notes).incidentConsoleV2;
  assert.equal(after.status, 'valid_after_structural_repair');
  assert.equal(after.response.content, before.response.content);
  assert.deepEqual(after.repair.operations, [
    { op: 'reorder', collection: 'entities', from: ['E2', 'E1'], to: ['E1', 'E2'] },
    { op: 'rename-id', collection: 'instruments', from: ',', to: 'I2' },
  ]);
  assert.equal(JSON.stringify(after.report), JSON.stringify(before.report));

  const view = buildReportView({ ...edited, playbackUrl: 'x' });
  // Class A reflects the edit...
  assert.equal(view.structured.incident.severityLevel, 2);
  assert.equal(view.structured.incident.endSeconds, 12);
  assert.equal(view.structured.incident.duration, 11);
  assert.equal(view.structured.entities[1].type, 'unknown');
  assert.deepEqual(view.structured.assets.map((a) => a.assetId), ['A1']);
  // ...Class B and the outcome remain the model's, and the difference is explicit.
  assert.equal(view.run.status, 'valid_after_structural_repair');
  assert.equal(view.modelOutput.original.severityLevel, 3);
  assert.equal(view.modelOutput.severityReason, before.report.incident.severity_reason);
  assert.deepEqual(view.differences.severity, { model: 3, current: 2 });
  assert.deepEqual(view.differences.fields.sort(), ['assets', 'entities', 'incident window', 'severity'].sort());
  assert.equal(view.review.editedBy, 'Reviewer A');
});

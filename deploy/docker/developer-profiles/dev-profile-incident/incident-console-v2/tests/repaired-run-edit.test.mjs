// SPDX-License-Identifier: Apache-2.0

// Requested proof for the repaired run m811cf2b237f50ff9812: saving an edit
// appends a human revision with the new values while the run's original
// response, repair operations, repaired report and valid_after_structural_repair
// outcome stay byte-for-byte unchanged, and the AI revision is not modified.
// The database half (save_human_revision, append-only trigger) is exercised by
// the SQL harness under supabase/tests.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PATCH } = await import('../app/api/reports/[videoId]/edit/route.ts');
const { SupabaseIncidentAdapter } = await import('../lib/adapters/supabase/incidents.ts');
const { PostgrestClient } = await import('../lib/postgrest/client.ts');
const { toReportView } = await import('../lib/reports/view.ts');
const { aiRevisionRow, unchangedEdit } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { revisionRpcs } = await import('./support/revisions-database.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));

test('editing repaired run m811cf2b237f50ff9812 adds a human revision; the run notes and the AI revision stay byte-for-byte identical', async () => {
  const notesBefore = fixture.modelRun.notes;
  const before = JSON.parse(notesBefore).incidentConsoleV2;
  const aiBefore = JSON.stringify(aiRevisionRow(fixture));

  // Reviewer lowers severity 3 -> 2, moves the end to 12 s, retypes E2 and adds an asset.
  const edit = unchangedEdit(fixture);
  edit.incident.severity_level = 2;
  edit.incident.end_timestamp = 12;
  edit.entities[1].type = 'unknown';
  edit.assets.push({ asset_id: 'A1', source_id: null, name: 'white van', description: 'Parked van beside the sidewalk.', timestamp_seconds: 1, label: '', image: null });

  const db = fakePostgrest(
    { videos: [{ ...fixture.video, official_revision_id: null }], model_runs: [structuredClone(fixture.modelRun)], report_revisions: [aiRevisionRow(fixture)] },
    { rpc: revisionRpcs },
  );
  const originalFetch = globalThis.fetch;
  Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' });
  globalThis.fetch = db.fetch;
  try {
    const response = await PATCH(new Request('http://localhost/x', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parentId: 1, editedBy: 'Reviewer A', edit }) }), { params: Promise.resolve({ videoId: fixture.videoId }) });
    assert.equal(response.status, 200);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.ok(!db.requests.some((r) => r.method !== 'GET' && r.path === 'model_runs'), 'no write of model_runs on the edit path');

  // The run notes and the AI revision are untouched: same bytes, same outcome, same original response, same repair.
  assert.equal(db.store.model_runs[0].notes, notesBefore);
  assert.equal(JSON.stringify(db.store.report_revisions[0]), aiBefore);
  const after = JSON.parse(db.store.model_runs[0].notes).incidentConsoleV2;
  assert.equal(after.status, 'valid_after_structural_repair');
  assert.equal(after.response.content, before.response.content);
  assert.deepEqual(after.repair.operations, [
    { op: 'reorder', collection: 'entities', from: ['E2', 'E1'], to: ['E1', 'E2'] },
    { op: 'rename-id', collection: 'instruments', from: ',', to: 'I2' },
  ]);
  assert.equal(JSON.stringify(after.report), JSON.stringify(before.report));

  // The new human revision, read back through the adapter, carries the edit.
  globalThis.fetch = db.fetch;
  let view;
  try {
    view = toReportView(await new SupabaseIncidentAdapter(new PostgrestClient('https://supabase.test', 'k')).getRevision(fixture.videoId, 2), 'x');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual([view.revision.kind, view.revision.createdBy, view.revision.parentId], ['human', 'Reviewer A', 1]);
  assert.equal(view.structured.incident.severityLevel, 2);
  assert.equal(view.structured.incident.endSeconds, 12);
  assert.equal(view.structured.entities[1].type, 'unknown');
  assert.deepEqual(view.structured.assets.map((a) => a.assetId), ['A1']);
  // Class B and the outcome remain the model's, and the difference is explicit.
  assert.equal(view.run.status, 'valid_after_structural_repair');
  assert.equal(view.modelOutput.original.severityLevel, 3);
  assert.equal(view.modelOutput.severityReason, before.report.incident.severity_reason);
  assert.deepEqual(view.differences.severity, { model: 3, current: 2 });
  assert.deepEqual(view.differences.fields.sort(), ['assets', 'entities', 'incident window', 'severity'].sort());
});

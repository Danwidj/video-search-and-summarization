// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { buildReportView, reportHeading } = await import('../lib/reports/view.ts');
const { parseRunNotes } = await import('../lib/reports/run-notes.ts');
const { canonicalEntityType, canonicalIncidentType, formatClock, parseTimestamp } = await import('../lib/reports/normalize.ts');

// Real rows of the live smoke-test run (see the fixture's description).
const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));
const rowsFrom = (fixture) => ({ ...clone(fixture), playbackUrl: 'https://signed.example/video.mp4' });

test('contract-v2 smoke run: Class A from rows, Class B from notes, Class C from run metadata', () => {
  const view = buildReportView(rowsFrom(smoke));
  const notes = JSON.parse(smoke.modelRun.notes).incidentConsoleV2;

  assert.deepEqual(view.structured.incident, {
    type: 'assault', startSeconds: 1, endSeconds: 11, duration: 10,
    description: smoke.incident.description, severityLevel: 2, confidenceScore: null,
  });
  assert.deepEqual(view.structured.entities.map((e) => [e.entityId, e.type]), [['E1', 'human'], ['E2', 'human']]);
  assert.deepEqual(view.structured.instruments, []);
  assert.deepEqual(view.structured.assets.map((a) => a.assetId), ['A1', 'A2']);

  assert.equal(view.modelOutput.source, 'contract');
  assert.equal(view.modelOutput.title, notes.report.incident.title);
  assert.equal(view.modelOutput.severityReason, notes.report.incident.severity_reason);
  assert.equal(view.modelOutput.location, notes.report.incident.location);
  assert.equal(view.modelOutput.timeline.length, notes.report.timeline.length);
  assert.deepEqual(view.modelOutput.uncertainties, notes.report.uncertainties);
  assert.equal(reportHeading(view), 'Person falls on sidewalk while walking.');

  assert.equal(view.run.notesKind, 'contract');
  assert.equal(view.run.model, 'nvidia/cosmos-3-nano-reasoner');
  assert.equal(view.run.promptVersion, 'incident-contract-v2');
  assert.equal(view.run.reportId, 'r03ba684293caa75f533');
  assert.equal(view.run.request.additionalInstruction, null);
  assert.deepEqual(view.run.request.inferenceConfig, { temperature: 0, max_tokens: 16384, media_io_kwargs: { video: { num_frames: 64 } } });
  assert.equal(view.run.response.finishReason, 'stop');
  assert.equal(view.run.rawModelOutput, notes.response.content);
  assert.deepEqual(view.run.originalReport, notes.report);

  assert.deepEqual(view.differences, { fields: [] }, 'unedited run: projection equals the original model output');
  assert.equal(view.review.status, 'unreviewed');
});

test('an edited structured severity is reported against the model severity; the rationale stays the model original', () => {
  const edited = clone(smoke);
  edited.incident.severity_level = 4;
  const view = buildReportView(rowsFrom(edited));
  assert.equal(view.structured.incident.severityLevel, 4);
  assert.deepEqual(view.differences.severity, { model: 2, current: 4 });
  assert.equal(view.modelOutput.original.severityLevel, 2);
  assert.equal(view.modelOutput.severityReason, JSON.parse(smoke.modelRun.notes).incidentConsoleV2.report.incident.severity_reason);
});

test('edits to type, window and evidence are listed as reviewer edits', () => {
  const edited = clone(smoke);
  edited.incident.type = 'road accident';
  edited.incident.end_timestamp = '12';
  edited.assets = edited.assets.slice(0, 1);
  const view = buildReportView(rowsFrom(edited));
  assert.deepEqual(view.differences.type, { model: 'assault', current: 'road accident' });
  assert.deepEqual(view.differences.fields.sort(), ['assets', 'incident window', 'type'].sort());
});

test('Class B is never taken from the rows and Class A never from notes', () => {
  const edited = clone(smoke);
  edited.incident.description = 'Reviewer-corrected summary.';
  const view = buildReportView(rowsFrom(edited));
  assert.equal(view.structured.incident.description, 'Reviewer-corrected summary.');
  assert.equal(view.modelOutput.original.description, smoke.incident.description);
  assert.ok(view.differences.fields.includes('description'));
});

test('a tampered contract record is shown as unverifiable, not trusted', () => {
  const tampered = clone(smoke);
  const notes = JSON.parse(tampered.modelRun.notes);
  notes.incidentConsoleV2.report.incident.type = 'fighting';
  tampered.modelRun.notes = JSON.stringify(notes);
  const view = buildReportView(rowsFrom(tampered));
  assert.equal(view.run.notesKind, 'invalid-contract');
  assert.equal(view.modelOutput, null);
  assert.match(view.run.notesError, /schema violation/);
  assert.equal(view.structured.incident.type, 'assault', 'Class A still renders from rows');
});

const legacyRows = (notes) => ({
  videoId: 'v-legacy', modelRunId: 'm-legacy', playbackUrl: 'https://signed.example/legacy.mp4',
  video: { id: 'v-legacy', filepath: 'uploads/s/legacy.mp4' },
  modelRun: { id: 'm-legacy', model_name: 'nvidia/cosmos-3-nano-reasoner', prompt_version: 'incident-v2-snake', run_datetime: '2026-09-20T10:00:00', notes },
  incident: { incident_id: 'v-legacy', model_run_id: 'm-legacy', type: 'fighting', start_timestamp: '0:15', end_timestamp: '1:02:03', duration: 30, description: 'Two people fight.', severity_level: 3, confidence_score: 0.7 },
  entities: [{ entity_id: 'e02', type: 'person', description: 'Person B' }, { entity_id: 'e01', type: 'person', description: 'Person A punching' }],
  instruments: [{ instrument_id: 'i01', entity_id: null, name: 'Bottle', description: 'Swung', threat_level: null }],
  assets: [],
  review: { status: 'verified', verified_by: 'Rev' },
  reportRow: { id: 'r-legacy', generated_datetime: '2026-09-20T10:00:00' },
});

test('legacy run: normalised Class A, best-effort Class B, earlier reviewer edits surfaced read-only', () => {
  const notes = JSON.stringify({ incidentConsoleV2: {
    report: { videoId: 'v-legacy', title: 'Street fight', incident_type: 'fighting', description: 'Two people fight.', severity: 3, severity_reason: 'Punches thrown.', location: 'Main St', timeline: [{ start_seconds: 15.6, end_seconds: null, description: 'Fight starts' }], uncertainties: ['Cause unclear'], rawModelOutput: '{"legacy":true}' },
    editedReport: { title: 'Street fight near bus stop' },
  } });
  const view = buildReportView(legacyRows(notes));
  assert.equal(view.structured.incident.type, 'assault');
  assert.equal(view.structured.incident.startSeconds, 15);
  assert.equal(view.structured.incident.endSeconds, 3723);
  assert.deepEqual(view.structured.entities.map((e) => [e.entityId, e.type]), [['e01', 'human'], ['e02', 'human']]);
  assert.equal(view.structured.instruments[0].threatLevel, null);
  assert.equal(view.modelOutput.source, 'legacy');
  assert.equal(view.modelOutput.title, 'Street fight');
  assert.equal(view.modelOutput.severityReason, 'Punches thrown.');
  assert.deepEqual(view.modelOutput.timeline, [{ startSeconds: 15, endSeconds: null, description: 'Fight starts' }]);
  assert.equal(view.run.notesKind, 'legacy');
  assert.equal(view.run.rawModelOutput, '{"legacy":true}');
  assert.deepEqual(view.run.legacyReviewerEdits, { title: 'Street fight near bus stop' });
  assert.equal(view.review.status, 'verified');
});

test('runs without readable notes still render their structured rows', () => {
  for (const notes of [null, '', 'eval run notes, not JSON', JSON.stringify({ other: true })]) {
    const view = buildReportView(legacyRows(notes));
    assert.equal(view.modelOutput, null);
    assert.equal(view.run.notesKind, 'none');
    assert.equal(view.structured.incident.description, 'Two people fight.');
    assert.equal(reportHeading(view), 'Assault report');
  }
});

test('parseRunNotes distinguishes contract, legacy and absent notes', () => {
  assert.equal(parseRunNotes(smoke.modelRun.notes).kind, 'contract');
  assert.equal(parseRunNotes(JSON.stringify({ incidentConsoleV2: { videoId: 'x', incident_type: 'burglary' } })).kind, 'legacy');
  assert.equal(parseRunNotes(undefined).kind, 'none');
});

test('normalisers handle both data generations', () => {
  assert.equal(parseTimestamp('11'), 11);
  assert.equal(parseTimestamp(7), 7);
  assert.equal(parseTimestamp('1:05'), 65);
  assert.equal(parseTimestamp('00:01:15'), 75);
  assert.equal(parseTimestamp('soon'), null);
  assert.equal(parseTimestamp(null), null);
  assert.equal(formatClock(65), '1:05');
  assert.equal(formatClock(3723), '1:02:03');
  assert.equal(canonicalIncidentType('fighting'), 'assault');
  assert.equal(canonicalIncidentType('Animal'), 'animal attack');
  assert.equal(canonicalIncidentType('burglary'), 'burglary');
  assert.equal(canonicalIncidentType(''), null);
  assert.equal(canonicalEntityType('person'), 'human');
  assert.equal(canonicalEntityType(null), 'unknown');
});

test('the stage-1 smoke run predates recorded outcomes and is shown as valid_first_pass (inferred)', () => {
  const view = buildReportView(rowsFrom(smoke));
  assert.equal(view.run.status, 'valid_first_pass');
  assert.equal(view.run.statusInferred, true);
});

test('a structurally repaired run stays distinguishable from a first-pass one, with its operations', () => {
  const repaired = clone(smoke);
  const notes = JSON.parse(repaired.modelRun.notes);
  Object.assign(notes.incidentConsoleV2, {
    recordType: 'analysis_attempt',
    status: 'valid_after_structural_repair',
    validation: { firstPass: [{ code: 'ID_NOT_SEQUENTIAL_ENTITY', path: 'entities', message: 'entity_id values ["E2","E1"] are not sequential ["E1","E2"]' }] },
    repair: { eligible: true, ruleSet: 'id-normalization-v1', operations: [{ op: 'reorder', collection: 'entities', from: ['E2', 'E1'], to: ['E1', 'E2'] }], revalidation: [] },
  });
  repaired.modelRun.notes = JSON.stringify(notes);
  const view = buildReportView(rowsFrom(repaired));
  assert.equal(view.run.status, 'valid_after_structural_repair');
  assert.equal(view.run.statusInferred, false);
  assert.equal(view.run.firstPassViolations[0].code, 'ID_NOT_SEQUENTIAL_ENTITY');
  assert.equal(view.run.repair.ruleSet, 'id-normalization-v1');
  assert.equal(view.modelOutput.source, 'contract');
});

test('failed attempt notes are recognised and never treated as a report', () => {
  const notes = JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status: 'contract_failed', stage: 'contract_validation', contractVersion: 'incident-contract-v2', videoId: 'v-1', failure: { code: 'TIMELINE_START_OUTSIDE_WINDOW', message: 'x' }, request: { model: 'm' }, response: { content: '{}' }, validation: { firstPass: [] }, repair: null } });
  const parsed = parseRunNotes(notes);
  assert.equal(parsed.kind, 'failed-attempt');
  assert.equal(parsed.status, 'contract_failed');
  assert.equal(parsed.videoId, 'v-1');
  const view = buildReportView(legacyRows(notes));
  assert.equal(view.modelOutput, null, 'no report content is derived from a failed attempt');
  assert.equal(view.run.status, 'contract_failed');
});

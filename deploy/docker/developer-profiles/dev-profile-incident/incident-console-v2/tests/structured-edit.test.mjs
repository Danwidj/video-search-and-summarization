// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { StructuredEditError, validateStructuredEdit } = await import('../lib/contract/structured-edit.ts');
const { draftFromView, draftProblems, editFromDraft } = await import('../lib/reports/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = (name) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', name), 'utf8'));
const repaired = fixture('contract-v2-repaired-run.json');
const smoke = fixture('contract-v2-smoke-run.json');
const view = (rows) => buildReportView({ ...JSON.parse(JSON.stringify(rows)), playbackUrl: 'https://signed.example/v.mp4' });
const clone = (value) => JSON.parse(JSON.stringify(value));

function expectError(edit, status, pattern) {
  assert.throws(() => validateStructuredEdit(edit), (error) => {
    assert.ok(error instanceof StructuredEditError);
    assert.equal(error.status, status);
    if (pattern) assert.match(error.message, pattern);
    return true;
  });
}

test('an unchanged draft of each real contract-v2 run is a valid edit with the same values', () => {
  for (const rows of [repaired, smoke]) {
    const edit = editFromDraft(draftFromView(view(rows)));
    assert.deepEqual(validateStructuredEdit(edit), edit);
    assert.deepEqual(Object.keys(edit).sort(), ['assets', 'entities', 'incident', 'instruments']);
    assert.deepEqual(Object.keys(edit.incident).sort(), ['description', 'end_timestamp', 'severity_level', 'start_timestamp', 'type']);
  }
  const edit = editFromDraft(draftFromView(view(repaired)));
  assert.deepEqual(edit.instruments.map((i) => [i.instrument_id, i.entity_id, i.name]), [['I1', 'E1', 'bag'], ['I2', null, 'white van']]);
});

test('Class B and Class C fields cannot be part of an edit (400)', () => {
  const base = editFromDraft(draftFromView(view(repaired)));
  for (const [path, value] of [['incident.title', 'x'], ['incident.severity_reason', 'x'], ['incident.location', 'x'], ['incident.confidence_score', 0.5], ['incident.duration', 3], ['timeline', []], ['uncertainties', []], ['response', {}]]) {
    const edit = clone(base);
    const [head, tail] = path.split('.');
    if (tail) edit[head][tail] = value; else edit[head] = value;
    expectError(edit, 400, /not editable/);
  }
});

test('type, severity, timestamps, IDs and holders are validated against the contract (422)', () => {
  const base = editFromDraft(draftFromView(view(repaired)));
  const cases = [
    [(e) => { e.incident.type = 'fighting'; }, /incident\/type/],
    [(e) => { e.incident.severity_level = 6; }, /severity_level/],
    [(e) => { e.incident.start_timestamp = 1.5; }, /start_timestamp/],
    [(e) => { e.incident.end_timestamp = 0; e.incident.start_timestamp = 5; }, /before start_timestamp/],
    [(e) => { e.entities[1].entity_id = 'E3'; }, /not sequential/],
    [(e) => { e.instruments[1].instrument_id = ','; }, /not sequential/],
    [(e) => { e.instruments[0].entity_id = 'E9'; }, /unknown entity_id/],
    [(e) => { e.instruments[0].threat_level = null; }, /threat_level/],
    [(e) => { e.entities[0].type = 'person'; }, /type/],
    [(e) => { e.incident.description = 42; }, /description/],
    [(e) => { e.assets.push({ asset_id: 'A1', name: 'van', description: 'x', extra: 1 }); }, /additional/],
  ];
  for (const [mutate, pattern] of cases) {
    const edit = clone(base);
    mutate(edit);
    expectError(edit, 422, pattern);
  }
});

test('an empty summary is accepted, as incident-contract-v2 allows any string', () => {
  const edit = editFromDraft(draftFromView(view(repaired)));
  edit.incident.description = '';
  assert.doesNotThrow(() => validateStructuredEdit(edit));
  assert.deepEqual(draftProblems({ ...draftFromView(view(repaired)), incident: { ...draftFromView(view(repaired)).incident, description: '' } }), []);
});

test('the editor renumbers IDs by position and carries holders with their entity', () => {
  const draft = draftFromView(view(repaired));
  draft.entities.reverse();
  const edit = editFromDraft(draft);
  assert.deepEqual(edit.entities.map((e) => [e.entity_id, e.description.slice(0, 15)]), [['E1', 'Person walking '], ['E2', 'Person attackin']]);
  assert.equal(edit.instruments.find((i) => i.name === 'bag').entity_id, 'E2', 'the bag stays with the attacker, now E2');
  assert.doesNotThrow(() => validateStructuredEdit(edit));
});

test('each item keeps the AI item it came from through a delete, a reorder and an added item', () => {
  const draft = draftFromView(view(repaired));
  draft.entities.shift();
  draft.instruments.reverse();
  draft.instruments.push({ key: 'instrument-new', sourceId: null, timestampSeconds: 4, label: '', image: null, imageUrl: null, holderKey: null, name: 'phone', description: 'Dropped', threat_level: 1 });
  draft.assets.push({ key: 'asset-new', sourceId: null, timestampSeconds: 4, label: '', image: null, imageUrl: null, name: 'bench', description: 'Nearby' });
  const edit = editFromDraft(draft);
  assert.deepEqual(edit.entities.map((e) => [e.entity_id, e.source_id]), [['E1', 'E2']], 'the walker, AI E2, is now E1 and still names E2');
  assert.deepEqual(edit.instruments.map((i) => [i.instrument_id, i.source_id, i.name]), [['I1', 'I2', 'white van'], ['I2', 'I1', 'bag'], ['I3', null, 'phone']]);
  assert.deepEqual(edit.assets.map((a) => [a.asset_id, a.source_id]), [['A1', null]]);
  assert.doesNotThrow(() => validateStructuredEdit(edit));
});

test('every item names its source_id: null for an added item, otherwise a stored AI ID (422)', () => {
  const base = editFromDraft(draftFromView(view(repaired)));
  const keylessEntity = clone(base);
  delete keylessEntity.entities[0].source_id;
  expectError(keylessEntity, 422, /source_id/);
  const keylessInstrument = clone(base);
  delete keylessInstrument.instruments[1].source_id;
  expectError(keylessInstrument, 422, /source_id/);
  const keylessAsset = clone(base);
  keylessAsset.assets = [{ asset_id: 'A1', name: 'bench', description: 'Nearby' }];
  expectError(keylessAsset, 422, /source_id/);
  const added = clone(base);
  added.entities[0].source_id = null;
  assert.doesNotThrow(() => validateStructuredEdit(added));
  for (const value of [7, '', 'x'.repeat(21)]) {
    const edit = clone(base);
    edit.entities[0].source_id = value;
    expectError(edit, 422, /source_id/);
  }
});

test('a legacy run is normalised for the edit: contract type, seconds, E#/I# IDs; unmappable values must be chosen', () => {
  const legacyView = buildReportView({
    videoId: 'v-legacy', modelRunId: 'm-legacy', playbackUrl: 'https://signed.example/l.mp4',
    video: { id: 'v-legacy', filepath: 'uploads/s/l.mp4' },
    modelRun: { id: 'm-legacy', model_name: 'm', prompt_version: 'incident-v2-snake', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v-legacy', title: 'Old', incident_type: 'fighting' } } }) },
    incident: { type: 'fighting', start_timestamp: '0:15', end_timestamp: '1:05', duration: 50, description: 'Two people fight.', severity_level: 3, confidence_score: 0.7 },
    entities: [{ entity_id: 'e02', type: 'person', description: 'B' }, { entity_id: 'e01', type: 'person', description: 'A' }],
    instruments: [{ instrument_id: 'i01', entity_id: 'e01', name: 'Bottle', description: 'Swung', threat_level: null }],
    assets: [], review: null, reportRow: null,
  });
  const draft = draftFromView(legacyView);
  assert.equal(draft.incident.type, 'assault');
  assert.equal(draft.incident.start_timestamp, 15);
  assert.equal(draft.incident.end_timestamp, 65);
  assert.deepEqual(draftProblems(draft), ['Rate the threat level of every instrument (1-5).']);
  draft.instruments[0].threat_level = 2;
  const edit = editFromDraft(draft);
  assert.deepEqual(edit.entities.map((e) => [e.entity_id, e.type, e.description]), [['E1', 'human', 'A'], ['E2', 'human', 'B']]);
  assert.equal(edit.instruments[0].entity_id, 'E1', 'the bottle stays with legacy e01, now E1');
  assert.deepEqual([...edit.entities, ...edit.instruments].map((item) => item.source_id), ['e01', 'e02', 'i01'], 'legacy IDs are kept as the source');
  assert.doesNotThrow(() => validateStructuredEdit(edit));

  const unknownType = buildReportView({ ...JSON.parse(JSON.stringify({ videoId: 'v', modelRunId: 'm', playbackUrl: 'x', video: {}, modelRun: {}, incident: { type: 'other', start_timestamp: 'soon', end_timestamp: null, description: 'd', severity_level: 2 }, entities: [], instruments: [], assets: [], review: null, reportRow: null })) });
  assert.deepEqual(draftProblems(draftFromView(unknownType)), ['Choose an incident type.', 'Enter the incident start and end in seconds.']);
});

test('an entity span must be ordered and contain the most-visible second; a draft of a v2 run starts from that second', () => {
  const base = editFromDraft(draftFromView(view(repaired)));
  assert.ok(base.entities.every((e) => e.first_seen_seconds === e.timestamp_seconds && e.last_seen_seconds === e.timestamp_seconds));
  for (const mutate of [(e) => { e.entities[0].first_seen_seconds = e.entities[0].timestamp_seconds + 2; e.entities[0].last_seen_seconds = e.entities[0].timestamp_seconds + 1; },
    (e) => { e.entities[0].last_seen_seconds = e.entities[0].timestamp_seconds - 1; e.entities[0].first_seen_seconds = 0; }]) {
    const edit = clone(base);
    mutate(edit);
    expectError(edit, 422, /first_seen_seconds/);
  }
  const missing = clone(base);
  delete missing.entities[0].first_seen_seconds;
  expectError(missing, 422, /first_seen_seconds/);
  const draft = draftFromView(view(repaired));
  draft.entities[0].lastSeenSeconds = draft.entities[0].timestampSeconds - 1;
  draft.entities[0].firstSeenSeconds = draft.entities[0].timestampSeconds + 1;
  assert.match(draftProblems(draft).join(' '), /last seen must not be before/);
});

test('a drawn image\'s second and box are validated when present', () => {
  const base = editFromDraft(draftFromView(view(repaired)));
  const ok = clone(base);
  Object.assign(ok.assets[0] ?? ok.entities[0], { image_timestamp_seconds: 2, image_box: [0, 0, 500, 500] });
  assert.doesNotThrow(() => validateStructuredEdit(ok));
  const bad = clone(base);
  Object.assign(bad.entities[0], { image_box: [0, 0, 5000, 500] });
  expectError(bad, 422, /image_box/);
});

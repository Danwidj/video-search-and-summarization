// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { applyAgentActions } = await import('../src/lib/edits/apply-agent-actions.ts');
const { draftFromView, draftProblems } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' });
const base = () => draftFromView(view);

const act = (tool, args, id = `${tool}-${Math.random().toString(36).slice(2, 7)}`) => ({ id, tool, args });

test('applies every action to a copy and leaves the input draft unchanged', () => {
  const draft = base();
  const before = structuredClone(draft);
  const entity = draft.entities[0];
  const result = applyAgentActions(draft, [
    act('set_incident_fields', { title: '  New title  ', severity: '4' }, 'a1'),
    act('set_timeline_item', { itemKey: entity.key, label: 'Relabelled' }, 'a2'),
  ]);
  assert.deepEqual(
    result.applied.map((item) => item.id),
    ['a1', 'a2'],
  );
  assert.deepEqual(result.skipped, []);
  assert.equal(result.draft.incident.title, 'New title');
  assert.equal(result.draft.incident.severity_level, 4);
  assert.equal(result.draft.entities[0].label, 'Relabelled');
  assert.deepEqual(draft, before);
});

test('skips and reports an unknown tool, unknown keys and invalid arguments, and still applies the rest', () => {
  const draft = applyAgentActions(base(), [act('upsert_asset', { op: 'add', name: 'Car' })]).draft;
  const asset = draft.assets.at(-1);
  const result = applyAgentActions(draft, [
    act('delete_everything', {}, 'x1'),
    act('upsert_entity', { op: 'edit', itemKey: 'entity-missing', name: 'x' }, 'x2'),
    act('upsert_asset', { op: 'edit', itemKey: asset.key, threatLevel: 3 }, 'x3'),
    act('set_incident_fields', { severity: '9' }, 'x4'),
    act('set_incident_fields', { title: 'Kept' }, 'x5'),
  ]);
  assert.deepEqual(
    result.skipped.map((item) => item.id),
    ['x1', 'x2', 'x3', 'x4'],
  );
  assert.match(result.skipped[0].reason, /unknown tool/);
  assert.match(result.skipped[1].reason, /no entity with key "entity-missing"/);
  assert.match(result.skipped[2].reason, /threatLevel/);
  assert.equal(result.draft.incident.title, 'Kept');
});

test('a tool name that is a prototype property is unknown, not a handler', () => {
  const result = applyAgentActions(base(), [act('constructor', {}, 'p1'), act('toString', {}, 'p2')]);
  assert.deepEqual(
    result.skipped.map((item) => item.id),
    ['p1', 'p2'],
  );
  assert.deepEqual(result.applied, []);
});

test('deleting an entity removes the instruments it held and says so', () => {
  const draft = base();
  const holder = draft.entities.find((entity) => draft.instruments.some((instrument) => instrument.holderKey === entity.key));
  assert.ok(holder, 'fixture needs an entity that holds an instrument');
  const held = draft.instruments.filter((instrument) => instrument.holderKey === holder.key).length;
  const result = applyAgentActions(draft, [act('upsert_entity', { op: 'delete', itemKey: holder.key }, 'd1')]);
  assert.equal(result.applied[0].note, `also removed the ${held} instrument${held === 1 ? '' : 's'} it held`);
  assert.equal(
    result.draft.entities.some((entity) => entity.key === holder.key),
    false,
  );
  assert.equal(result.draft.instruments.length, draft.instruments.length - held);
});

test('an instrument holder must be an existing entity key, or null for nobody', () => {
  const draft = base();
  const instrument = draft.instruments[0];
  const result = applyAgentActions(draft, [
    act('set_instrument_holder', { instrumentKey: instrument.key, holderKey: 'entity-nope' }, 'h1'),
    act('set_instrument_holder', { instrumentKey: instrument.key, holderKey: null }, 'h2'),
  ]);
  assert.equal(result.skipped[0].id, 'h1');
  assert.equal(result.draft.instruments[0].holderKey, null);
});

test('add actions create items with the defaults the editor uses', () => {
  const draft = base();
  const result = applyAgentActions(draft, [
    act('upsert_entity', { op: 'add', entityType: 'human', name: 'Person A', firstSeenSeconds: 2, lastSeenSeconds: 5 }, 'n1'),
    act('upsert_instrument', { op: 'add', name: 'Knife', threatLevel: 4 }, 'n2'),
    act('upsert_asset', { op: 'add', name: 'Car' }, 'n3'),
  ]);
  assert.equal(result.skipped.length, 0);
  const entity = result.draft.entities.at(-1);
  assert.equal(entity.type, 'human');
  assert.equal(entity.label, 'Person A');
  assert.equal(entity.firstSeenSeconds, 2);
  assert.equal(entity.lastSeenSeconds, 5);
  assert.equal(result.draft.instruments.at(-1).threat_level, 4);
  assert.equal(result.draft.instruments.at(-1).holderKey, null);
  assert.equal(result.draft.assets.at(-1).name, 'Car');
});

test('an instrument takes its holder on add and edit, and an unknown holder is skipped', () => {
  const draft = base();
  const holder = draft.entities[0];
  const edited = draft.instruments[0].key;
  const result = applyAgentActions(draft, [
    act('upsert_instrument', { op: 'add', name: 'Knife', threatLevel: 4, holderKey: holder.key }, 'k1'),
    act('upsert_instrument', { op: 'add', name: 'Rope', threatLevel: 2, holderKey: 'entity-nope' }, 'k2'),
    act('upsert_instrument', { op: 'edit', itemKey: edited, holderKey: holder.key }, 'k3'),
  ]);
  assert.equal(result.skipped[0].id, 'k2');
  assert.equal(result.skipped.length, 1);
  assert.equal(result.draft.instruments.at(-1).name, 'Knife');
  assert.equal(result.draft.instruments.at(-1).holderKey, holder.key);
  assert.equal(result.draft.instruments.find((instrument) => instrument.key === edited).holderKey, holder.key);
});

test('the result reports draftProblems for the draft it returns', () => {
  const draft = base();
  const result = applyAgentActions(draft, [act('upsert_entity', { op: 'add', name: 'No type yet' }, 'q1')]);
  assert.deepEqual(result.problems, draftProblems(result.draft));
  assert.ok(result.problems.includes('Choose Human or Animal for every entity.'));
});

test('evidence actions are skipped, never applied', () => {
  const draft = base();
  const result = applyAgentActions(draft, [
    act('change_evidence', { op: 'retrack', itemKey: draft.entities[0].key, seconds: 1, box: [0, 0, 10, 10] }, 'e1'),
    act('add_evidence', { op: 'add_item', seconds: 1, box: [0, 0, 10, 10] }, 'e2'),
  ]);
  assert.deepEqual(result.applied, []);
  assert.deepEqual(
    result.skipped.map((item) => item.id),
    ['e1', 'e2'],
  );
  assert.deepEqual(result.draft, draft);
});

test('an empty action list returns the same content with nothing applied', () => {
  const draft = base();
  const result = applyAgentActions(draft, []);
  assert.deepEqual(result.draft, draft);
  assert.deepEqual(result.applied, []);
  assert.deepEqual(result.skipped, []);
});

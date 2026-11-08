// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { applyChatEdit, draftSnapshot, labelDraftKeys, toApplierActions, INCIDENT_HIGHLIGHT_KEY } = await import(
  '../src/lib/edits/chat-edit.ts'
);
const { draftFromView } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' });
const base = () => draftFromView(view);
const propose = (tool, args) => ({ tool: `propose_${tool}`, args });

test('the snapshot carries every item by its draft key, in the agent snake_case shape', () => {
  const draft = base();
  const snapshot = draftSnapshot(draft);
  assert.deepEqual(
    snapshot.entities.map((item) => item.key),
    draft.entities.map((item) => item.key),
  );
  assert.equal(snapshot.incident.title, draft.incident.title);
  assert.ok('first_seen_seconds' in snapshot.entities[0]);
  assert.ok(!('sourceId' in snapshot.entities[0]));
});

test('proposals become applier actions: names, severity as text, and a delete found by its key', () => {
  const draft = base();
  const entity = draft.entities[0];
  const actions = toApplierActions(draft, [
    propose('set_incident_fields', { severity_level: 4, start_timestamp: 2 }),
    propose('delete_item', { item_key: entity.key }),
    propose('set_instrument_holder', { instrument_key: 'i', holder_key: null }),
  ]);
  assert.deepEqual(actions[0].args, { startSeconds: 2, severity: '4' });
  assert.deepEqual(actions[1], { id: 'chat-2', tool: 'upsert_entity', args: { op: 'delete', itemKey: entity.key } });
  assert.deepEqual(actions[2].args, { instrumentKey: 'i', holderKey: null });
});

test('an instrument proposal names its holder in the applier action, and the applied add keeps it', () => {
  const draft = base();
  const entity = draft.entities[0];
  const proposal = propose('upsert_instrument', { op: 'add', name: 'Knife', threat_level: 4, holder_key: entity.key });
  const actions = toApplierActions(draft, [proposal]);
  assert.deepEqual(actions[0].args, { op: 'add', name: 'Knife', threatLevel: 4, holderKey: entity.key });
  const result = applyChatEdit(draft, draft, [proposal]);
  assert.equal(result.skipped.length, 0);
  assert.equal(result.draft.instruments.at(-1).holderKey, entity.key);
});

test('an applied edit lists the keys it changed, and the input draft is untouched', () => {
  const draft = base();
  const before = structuredClone(draft);
  const entity = draft.entities[0];
  const result = applyChatEdit(draft, draft, [
    propose('set_incident_fields', { severity_level: 5 }),
    propose('set_timeline_item', { item_key: entity.key, label: 'Renamed' }),
  ]);
  assert.equal(result.skipped.length, 0);
  assert.equal(result.draft.incident.severity_level, 5);
  assert.deepEqual(result.changedKeys.sort(), [INCIDENT_HIGHLIGHT_KEY, entity.key].sort());
  assert.deepEqual(draft, before);
});

test('an action on an item the reviewer changed during the request is skipped, the rest apply', () => {
  const sent = base();
  const entity = sent.entities[0];
  const now = {
    ...sent,
    entities: sent.entities.map((item) => (item.key === entity.key ? { ...item, label: 'Mine' } : item)),
  };
  const result = applyChatEdit(now, sent, [
    propose('set_timeline_item', { item_key: entity.key, label: 'Theirs' }),
    propose('set_incident_fields', { title: 'New title' }),
  ]);
  assert.equal(result.draft.entities[0].label, 'Mine');
  assert.equal(result.draft.incident.title, 'New title');
  assert.match(result.skipped[0].reason, /you changed this/);
  assert.deepEqual(result.changedKeys, [INCIDENT_HIGHLIGHT_KEY]);
});

test('a key the agent invented is skipped with a reason and changes nothing', () => {
  const draft = base();
  const result = applyChatEdit(draft, draft, [propose('delete_item', { item_key: 'E1' })]);
  assert.equal(result.applied.length, 0);
  assert.equal(result.skipped.length, 1);
  assert.deepEqual(result.changedKeys, []);
});

test('a delete-only request removes the item, reports it as a removed change, and names it as a delete', () => {
  const draft = base();
  const entity = draft.entities[0];
  const result = applyChatEdit(draft, draft, [propose('delete_item', { item_key: entity.key })]);
  assert.equal(
    result.draft.entities.some((item) => item.key === entity.key),
    false,
  );
  assert.equal(result.skipped.length, 0);
  const held = draft.instruments.filter((item) => item.holderKey === entity.key).map((item) => item.key);
  assert.deepEqual(result.removedKeys, [entity.key, ...held]);
  assert.equal(result.applied[0].tool, 'delete_item');
  assert.match(result.applied[0].note, new RegExp(`^deleted "${entity.label || entity.key}"`));
});

test('a delete plus a rename of another item applies both as one result', () => {
  const draft = base();
  const [removed, renamed] = draft.entities;
  const result = applyChatEdit(draft, draft, [
    propose('delete_item', { item_key: removed.key }),
    propose('set_timeline_item', { item_key: renamed.key, label: 'Renamed' }),
  ]);
  assert.equal(
    result.draft.entities.some((item) => item.key === removed.key),
    false,
  );
  assert.equal(result.draft.entities.find((item) => item.key === renamed.key).label, 'Renamed');
  const held = draft.instruments.filter((item) => item.holderKey === removed.key).map((item) => item.key);
  assert.deepEqual(result.removedKeys, [removed.key, ...held]);
  assert.deepEqual(result.changedKeys, [renamed.key]);
  assert.deepEqual(
    result.applied.map((action) => action.tool),
    ['delete_item', 'set_timeline_item'],
  );
});

test('a no-op action is skipped with its reason, not reported as applied', () => {
  const draft = base();
  const result = applyChatEdit(draft, draft, [propose('set_incident_fields', { title: draft.incident.title })]);
  assert.equal(result.applied.length, 0);
  assert.deepEqual(
    result.skipped.map((action) => action.reason),
    ['no change: the draft already had this'],
  );
  assert.deepEqual(result.changedKeys, []);
  assert.deepEqual(result.removedKeys, []);
});

test('the snapshot gives each item its reviewer label (E1, I1, A1) and name, not just its key', () => {
  const draft = base();
  const snapshot = draftSnapshot(draft);
  assert.equal(snapshot.entities[0].reviewer_label, draft.entities[0].sourceId);
  assert.equal(snapshot.entities[0].reviewer_name, draft.entities[0].label);
});

test('a new item has no reviewer label yet, so its name stands in for it', () => {
  const draft = base();
  draft.entities.push({ ...draft.entities[0], key: 'entity-new', sourceId: null, label: 'person in red' });
  const entity = draftSnapshot(draft).entities.at(-1);
  assert.equal(entity.reviewer_label, '');
  assert.equal(entity.reviewer_name, 'person in red');
});

test('the reply shows a draft key as its item label, and a whole key only', () => {
  const snapshot = {
    entities: [{ key: 'entity-0', reviewer_label: 'E1', reviewer_name: 'person in purple' }],
    instruments: [{ key: 'instrument-a', reviewer_label: 'I1', reviewer_name: 'knife' }],
    assets: [],
  };
  assert.equal(
    labelDraftKeys('Opened the box tool on entity-0 and instrument-a. entity-01 and xentity-0 stay.', snapshot),
    'Opened the box tool on E1 and I1. entity-01 and xentity-0 stay.',
  );
});

test('a key with no label shows its name, and a new item with neither shows as a new item', () => {
  const snapshot = {
    entities: [
      { key: 'entity-0', reviewer_label: '', reviewer_name: 'person in purple' },
      { key: 'entity-1', reviewer_label: '', reviewer_name: '' },
    ],
  };
  assert.equal(labelDraftKeys('entity-0 and entity-1', snapshot), 'person in purple and the new item');
});

test('a reply with no key, or a snapshot with no items, is unchanged', () => {
  assert.equal(labelDraftKeys('Nothing to change.', { entities: [] }), 'Nothing to change.');
  assert.equal(labelDraftKeys('entity-0 is still here.', {}), 'entity-0 is still here.');
});

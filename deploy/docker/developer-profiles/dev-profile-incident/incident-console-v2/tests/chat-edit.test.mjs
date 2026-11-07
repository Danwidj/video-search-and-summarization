// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { applyChatEdit, draftSnapshot, toApplierActions, INCIDENT_HIGHLIGHT_KEY } = await import('../src/lib/edits/chat-edit.ts');
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

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { deleteDraftItem, draftChangeCount, draftToStructured, pairReport, revertBlocked, revertDraftItem, rowDiffers } = await import('../src/lib/reports/compare.ts');
const { draftFromView } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' });
const base = () => draftFromView(view);
const rowOf = (pairing, kind, name) => pairing.rows.find((row) => row.kind === kind && (row.b?.name === name || row.b?.description === name));

test('an unchanged draft pairs every A item with B, groups holders, and shows no changes', () => {
  const pairing = pairReport(view.structured, base());
  assert.equal(pairing.rows.length, 4);
  assert.equal(pairing.liveCount, 4);
  assert.deepEqual(pairing.units.map((unit) => unit.kind), ['entity', 'entity', 'loose']);
  assert.deepEqual(pairing.units[0].rows.map((row) => row.b.name), ['bag'], 'the bag sits under the entity that holds it');
  assert.deepEqual(pairing.units[2].rows.map((row) => row.b.name), ['white van'], 'an instrument without a holder is loose');
  assert.equal(draftChangeCount(view.structured, base()), 0);
  assert.ok(pairing.rows.every((row) => !rowDiffers(row, base())));
});

test('editing a field or an item counts as one change', () => {
  const draft = base();
  draft.incident.description = 'Rewritten summary';
  assert.equal(draftChangeCount(view.structured, draft), 1);
  draft.entities[0].description = 'Rewritten entity';
  assert.equal(draftChangeCount(view.structured, draft), 2);
  const pairing = pairReport(view.structured, draft);
  assert.ok(rowDiffers(pairing.rows[0], draft));
  assert.ok(!rowDiffers(pairing.rows[1], draft));
});

test('deleting an entity deletes the instruments it holds and can be reverted whole', () => {
  const draft = base();
  const entity = draft.entities.find((row) => row.description.startsWith('Person attacking'));
  const deleted = deleteDraftItem(draft, 'entity', entity.key);
  assert.equal(deleted.entities.length, 1);
  assert.equal(deleted.instruments.length, 1, 'the held bag went with its entity');
  assert.equal(deleted.instruments[0].name, 'white van');

  const pairing = pairReport(view.structured, deleted);
  const deletedEntity = pairing.rows.find((row) => row.kind === 'entity' && row.b === null);
  const deletedBag = pairing.rows.find((row) => row.kind === 'instrument' && row.b === null);
  assert.equal(draftChangeCount(view.structured, deleted), 2);
  assert.equal(revertBlocked(deletedBag, deleted), true, 'the bag waits for its holder');

  const restored = revertDraftItem(deleted, view.structured, deletedEntity);
  assert.equal(restored.entities.length, 2);
  assert.equal(restored.instruments.length, 2, 'reverting the entity brings the bag back');
  assert.equal(draftChangeCount(view.structured, restored), 0);
});

test('reverting an edited or deleted item puts A values back', () => {
  const draft = base();
  draft.instruments[1].name = 'blue van';
  draft.instruments[1].threat_level = 5;
  let pairing = pairReport(view.structured, draft);
  const van = rowOf(pairing, 'instrument', 'blue van');
  const reverted = revertDraftItem(draft, view.structured, van);
  assert.equal(reverted.instruments.find((item) => item.sourceId === 'I2').name, 'white van');
  assert.equal(draftChangeCount(view.structured, reverted), 0);

  const withoutBag = deleteDraftItem(reverted, 'instrument', reverted.instruments[0].key);
  pairing = pairReport(view.structured, withoutBag);
  const bag = pairing.rows.find((row) => row.kind === 'instrument' && row.b === null);
  const back = revertDraftItem(withoutBag, view.structured, bag);
  assert.equal(back.instruments.find((item) => item.sourceId === 'I1').name, 'bag');
  assert.equal(back.instruments.find((item) => item.sourceId === 'I1').holderKey, back.entities[0].key);
});

test('an item the draft adds is new in B, not a deleted A row', () => {
  const draft = base();
  draft.instruments.push({ key: 'instrument-new', sourceId: null, timestampSeconds: 1, label: '', image: null, imageUrl: null, holderKey: draft.entities[1].key, name: 'phone', description: 'Dropped', threat_level: 1 });
  const pairing = pairReport(view.structured, draft);
  const added = pairing.rows.find((row) => row.b?.key === 'instrument-new');
  assert.equal(added.a, null);
  assert.equal(pairing.liveCount, 5);
  assert.equal(draftChangeCount(view.structured, draft), 1);
  assert.equal(pairing.units[1].rows.some((row) => row.b?.key === 'instrument-new'), true, 'it groups under its holder');
});

test('the draft renders as structured evidence with its holder names resolved', () => {
  const draft = base();
  draft.instruments.find((item) => item.sourceId === 'I1').holderKey = draft.entities[1].key;
  const structured = draftToStructured(draft);
  assert.equal(structured.entities.length, 2);
  assert.equal(structured.instruments.find((item) => item.instrumentId === draft.instruments[0].key).entityId, draft.entities[1].key);
  assert.equal(structured.incident.severityLevel, 3);
  assert.equal(structured.incident.startSeconds, view.structured.incident.startSeconds);
});

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { deleteDraftItem, draftChangeCount, draftToStructured, pairReport, revertBlocked, revertDraftItem, rowDiffers } = await import(
  '../src/lib/reports/compare.ts'
);
const { draftFromView, editFromDraft, nextCanonicalEntityId, newEntityDraft } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildTimelineLanes } = await import('../src/lib/reports/timeline-lanes.ts');
const { buildReportView, aiRevisionRow } = await import('./support/report-view.mjs');
const { humanRevisionContent } = await import('../src/modules/reports/domain/revision.ts');
const { revisionRecordFromRows } = await import('../src/modules/reports/infrastructure/supabase/mappers/report.ts');
const { toReportView } = await import('../src/modules/reports/application/report-view.ts');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' });
const base = () => draftFromView(view);
const rowOf = (pairing, kind, name) =>
  pairing.rows.find((row) => row.kind === kind && (row.b?.name === name || row.b?.description === name));

test('an unchanged draft pairs every A item with B, groups holders, and shows no changes', () => {
  const pairing = pairReport(view.structured, base());
  assert.equal(pairing.rows.length, 4);
  assert.equal(pairing.liveCount, 4);
  assert.deepEqual(
    pairing.units.map((unit) => unit.kind),
    ['entity', 'entity', 'loose'],
  );
  assert.deepEqual(
    pairing.units[0].rows.map((row) => row.b.name),
    ['bag'],
    'the bag sits under the entity that holds it',
  );
  assert.deepEqual(
    pairing.units[2].rows.map((row) => row.b.name),
    ['white van'],
    'an instrument without a holder is loose',
  );
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
  draft.instruments.push({
    key: 'instrument-new',
    sourceId: null,
    timestampSeconds: 1,
    label: '',
    image: null,
    imageUrl: null,
    holderKey: draft.entities[1].key,
    name: 'phone',
    description: 'Dropped',
    threat_level: 1,
  });
  const pairing = pairReport(view.structured, draft);
  const added = pairing.rows.find((row) => row.b?.key === 'instrument-new');
  assert.equal(added.a, null);
  assert.equal(pairing.liveCount, 5);
  assert.equal(draftChangeCount(view.structured, draft), 1);
  assert.equal(
    pairing.units[1].rows.some((row) => row.b?.key === 'instrument-new'),
    true,
    'it groups under its holder',
  );
});

test('the draft renders as structured evidence with its holder names resolved', () => {
  const draft = base();
  draft.instruments.find((item) => item.sourceId === 'I1').holderKey = draft.entities[1].key;
  const structured = draftToStructured(draft);
  assert.equal(structured.entities.length, 2);
  assert.equal(structured.entities[0].entityId, 'E1');
  assert.equal(structured.entities[1].entityId, 'E2');
  assert.equal(structured.instruments.find((item) => item.instrumentId === draft.instruments[0].key).entityId, 'E2');
  assert.equal(structured.incident.severityLevel, 3);
  assert.equal(structured.incident.startSeconds, view.structured.incident.startSeconds);
});

test('draftFromView keeps canonical entity ids as a first-class field', () => {
  const draft = base();
  assert.equal(draft.entities[0].canonicalId, 'E1');
  assert.equal(draft.entities[1].canonicalId, 'E2');
  assert.equal(draft.entities[0].key, 'entity-0');
  assert.equal(draft.entities[1].key, 'entity-1');
});

test('pairCollection preserves canonical entity order instead of re-sorting by timestamp', () => {
  const draft = base();
  // Reverse entity timestamps so E2 has earlier timestamp than E1
  draft.entities[0].timestampSeconds = 12; // E1 at 12s
  draft.entities[1].timestampSeconds = 2; // E2 at 2s
  const pairing = pairReport(view.structured, draft);
  const entityRows = pairing.rows.filter((r) => r.kind === 'entity');
  assert.equal(entityRows.length, 2);
  assert.equal(entityRows[0].b?.canonicalId, 'E1');
  assert.equal(entityRows[1].b?.canonicalId, 'E2');
});

test('pairCollection keeps canonical entity order when an entity is deleted', () => {
  const draft = base();
  // Delete the first entity (E1)
  const withoutE1 = deleteDraftItem(draft, 'entity', draft.entities[0].key);
  const pairing = pairReport(view.structured, withoutE1);
  const entityRows = pairing.rows.filter((r) => r.kind === 'entity');
  assert.equal(entityRows.length, 2);
  assert.equal(entityRows[0].a?.entityId, 'E1');
  assert.equal(entityRows[0].b, null, 'E1 is marked deleted in B');
  assert.equal(entityRows[1].b?.canonicalId, 'E2');
});

test('nextCanonicalEntityId produces next non-colliding ID even with gaps', () => {
  assert.equal(nextCanonicalEntityId([]), 'E1');
  assert.equal(nextCanonicalEntityId([{ canonicalId: 'E1' }, { canonicalId: 'E2' }]), 'E3');
  assert.equal(nextCanonicalEntityId([{ canonicalId: 'E1' }, { canonicalId: 'E5' }]), 'E6');
  assert.equal(nextCanonicalEntityId([{ sourceId: 'E3' }]), 'E4');
});

test('newEntityDraft creates a draft entity with a non-colliding canonical ID', () => {
  const draft = base();
  const added = newEntityDraft(draft, { description: 'New bystander' });
  assert.equal(added.canonicalId, 'E3');
  assert.equal(added.description, 'New bystander');
  assert.equal(added.sourceId, null);
  assert.ok(added.key.startsWith('entity-'));
});

test('timeline lane titles read E1 · label in both View and Edit modes', () => {
  const draft = base();
  draft.entities[0].label = 'attacker';
  draft.entities[1].label = 'victim';
  const viewStructured = {
    ...view.structured,
    entities: [
      { ...view.structured.entities[0], label: 'attacker' },
      { ...view.structured.entities[1], label: 'victim' },
    ],
  };
  const viewLanes = buildTimelineLanes(viewStructured);
  const editLanes = buildTimelineLanes(draftToStructured(draft));
  assert.equal(viewLanes[0].title, 'E1 · attacker');
  assert.equal(viewLanes[1].title, 'E2 · victim');
  assert.equal(editLanes[0].title, viewLanes[0].title);
  assert.equal(editLanes[1].title, viewLanes[1].title);
  assert.deepEqual(
    viewLanes.map((l) => l.title),
    editLanes.map((l) => l.title),
  );
});

test('View to Edit to View round trip keeps entity IDs, lane titles and order identical', () => {
  // 1. Start from View
  const initialView = view;
  const initialEntities = initialView.structured.entities;
  assert.deepEqual(
    initialEntities.map((e) => e.entityId),
    ['E1', 'E2'],
  );

  // 2. Open in Edit mode (draft)
  const draft = draftFromView(initialView);
  assert.deepEqual(
    draft.entities.map((e) => e.canonicalId),
    ['E1', 'E2'],
  );

  // In Edit mode, draftToStructured produces matching canonical entity IDs
  const editStructured = draftToStructured(draft);
  assert.deepEqual(
    editStructured.entities.map((e) => e.entityId),
    ['E1', 'E2'],
  );

  // 3. Save as new human revision
  const edit = editFromDraft(draft);
  assert.deepEqual(
    edit.entities.map((e) => e.entity_id),
    ['E1', 'E2'],
  );

  const parentRevision = aiRevisionRow(structuredClone(fixture));
  const { payload, evidence } = humanRevisionContent(parentRevision, edit);

  const humanRevision = {
    ...parentRevision,
    id: 2,
    revision_no: 2,
    kind: 'human',
    parent_id: parentRevision.id,
    payload,
    evidence,
  };
  const roundTripReport = revisionRecordFromRows({
    video: fixture.video,
    revision: humanRevision,
    modelRun: fixture.modelRun,
  });
  const roundTripView = toReportView(roundTripReport, 'https://signed.example/v.mp4');

  // 4. Returned View structured matches initial View in IDs, labels, and order
  assert.deepEqual(
    roundTripView.structured.entities.map((e) => e.entityId),
    ['E1', 'E2'],
  );
  assert.deepEqual(
    roundTripView.structured.entities.map((e) => e.label || e.type),
    initialEntities.map((e) => e.label || e.type),
  );
  assert.deepEqual(
    buildTimelineLanes(roundTripView.structured).map((l) => l.title),
    buildTimelineLanes(initialView.structured).map((l) => l.title),
  );
});

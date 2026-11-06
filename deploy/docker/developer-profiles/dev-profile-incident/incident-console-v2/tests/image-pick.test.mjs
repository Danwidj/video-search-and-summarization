// SPDX-License-Identifier: Apache-2.0

// Set image in Edit mode: the seconds a reviewer may pick, where the dialog opens, and the edit a pick produces.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const pick = await import('../src/lib/evidence/image-pick.ts');
const { validateStructuredEdit, StructuredEditError } = await import('../src/modules/contract/domain/structured-edit.ts');
const { draftFromView, editFromDraft } = await import('../src/modules/reports/domain/edit-draft.ts');
const { rowDiffers, pairReport } = await import('../src/lib/reports/compare.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = () => buildReportView({ ...JSON.parse(JSON.stringify(repaired)), playbackUrl: 'https://signed.example/v.mp4' });

test('a pick never goes below zero or past the video end, which the frame route would refuse', () => {
  assert.equal(pick.pickCeiling(12), 11.9);
  assert.equal(pick.pickCeiling(null), null);
  assert.equal(pick.movePick(0, -0.1, 12), 0);
  assert.equal(pick.movePick(11.9, 0.1, 12), 11.9);
  assert.equal(pick.movePick(7.5, 0.1, 12), 7.6);
  assert.equal(pick.movePick(7.5, -1, null), 6.5, 'before the length is known it only floors at zero');
  assert.equal(pick.roundPick(7.60000001), 7.6);
});

test('the dialog opens at the pick, else the track, else the saved frame, else the most-visible second with no box', () => {
  const box = [100, 200, 300, 400];
  const none = { imagePick: null, reviewer: null, image: 'a.jpg', timestampSeconds: 5 };
  const saved = { image: 'a.jpg', located: true, boxSeconds: 4.5, boundingBox: box };
  assert.deepEqual(pick.pickSeed({ ...none, imagePick: { seconds: 2.5, box } }, saved), { seconds: 2.5, box });
  const reviewer = { track: { samples: [{ t: 7.6, box }] } };
  assert.deepEqual(pick.pickSeed({ ...none, reviewer }, saved), { seconds: 7.6, box });
  assert.deepEqual(pick.pickSeed({ ...none, reviewer: { track: null, stillSeconds: 3, stillBox: box } }, saved), { seconds: 3, box });
  assert.deepEqual(pick.pickSeed(none, saved), { seconds: 4.5, box });
  assert.deepEqual(pick.pickSeed(none, { ...saved, located: false }), { seconds: 4.5, box: null }, 'a detector miss opens unboxed');
  assert.deepEqual(pick.pickSeed({ ...none, image: null }, saved), { seconds: 5, box: null }, 'a different image is not the saved one');
  assert.deepEqual(pick.pickSeed(none, null), { seconds: 5, box: null });
});

test('setting an image touches only that item and is a visible change; the sent edit carries the pick', () => {
  const base = draftFromView(view());
  const target = base.entities[0];
  const chosen = { seconds: 3.25, box: [100, 150, 500, 450] };
  const draft = pick.setImagePick(base, 'entity', target.key, chosen);
  assert.deepEqual(draft.entities[0].imagePick, chosen);
  assert.equal(draft.entities[0].label, target.label);
  assert.equal(draft.entities[0].timestampSeconds, target.timestampSeconds);
  assert.ok(draft.entities.slice(1).every((entity) => entity.imagePick === null));
  assert.ok([...draft.instruments, ...draft.assets].every((entry) => entry.imagePick === null));

  const edit = editFromDraft(draft);
  assert.deepEqual(edit.entities[0].image_pick, chosen);
  assert.equal('image_pick' in edit.entities[1], false, 'an item without a pick sends none');
  assert.deepEqual(validateStructuredEdit(edit), edit);

  const row = pairReport(base, draft).rows.find((entry) => entry.b?.key === target.key);
  assert.equal(rowDiffers(row, draft), true);
});

test('the contract refuses a pick that is not a second and a 0-1000 box', () => {
  const edit = editFromDraft(draftFromView(view()));
  const withPick = (value) => ({
    ...edit,
    entities: edit.entities.map((entity, index) => (index === 0 ? { ...entity, image_pick: value } : entity)),
  });
  for (const bad of [
    { seconds: -1, box: [0, 0, 10, 10] },
    { seconds: 1, box: [0, 0, 10] },
    { seconds: 1, box: [0, 0, 10, 1001] },
    { seconds: 1, box: [0, 0, 10, 10], extra: true },
    { box: [0, 0, 10, 10] },
  ])
    assert.throws(() => validateStructuredEdit(withPick(bad)), StructuredEditError);
  assert.doesNotThrow(() => validateStructuredEdit(withPick(null)));
});

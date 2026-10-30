// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { assetDetail, entityDetail, evidenceDetailLines, instrumentDetail } = await import(
  '../src/modules/reports/domain/evidence-detail.ts'
);

const evidence = (timestampSeconds) => ({
  image: null,
  imageUrl: null,
  frame: null,
  frameUrl: null,
  located: null,
  boxSeconds: null,
  imageGap: null,
  boundingBox: null,
  timestampSeconds,
  uploaded: false,
});
const entity = (over = {}) => ({
  entityId: 'E1',
  type: 'person',
  label: 'man in red',
  description: 'Walks in from the left.',
  timestampSeconds: 4,
  firstSeenSeconds: 2,
  lastSeenSeconds: 69,
  evidence: null,
  ...over,
});
const instrument = (over = {}) => ({
  instrumentId: 'I1',
  entityId: 'E1',
  name: 'knife',
  label: 'knife',
  description: 'A short blade.',
  threatLevel: 4,
  timestampSeconds: 6,
  evidence: null,
  ...over,
});
const asset = (over = {}) => ({
  assetId: 'A1',
  name: 'car',
  label: 'car',
  description: 'Parked.',
  timestampSeconds: null,
  evidence: null,
  ...over,
});

test('an entity names what it holds and its on-screen span, never a holder or threat', () => {
  const lines = evidenceDetailLines(entityDetail(entity(), [instrument(), instrument({ instrumentId: 'I2', name: 'bat' })]));
  assert.equal(lines.holds, 'knife, bat');
  assert.equal(lines.onScreen, 'On screen 0:02–1:09');
  assert.equal(lines.heldBy, null);
  assert.equal(lines.threat, null);
  assert.equal(lines.time, '0:04');
  assert.equal(lines.playNote, null);
});

test('an entity holding nothing, with no recorded span, shows neither line', () => {
  const lines = evidenceDetailLines(entityDetail(entity({ firstSeenSeconds: null }), [instrument({ entityId: 'E2' })]));
  assert.equal(lines.holds, null);
  assert.equal(lines.onScreen, null);
});

test('an entity without a label is titled by its type', () => {
  assert.equal(entityDetail(entity({ label: '' }), []).title, 'person');
});

test('an instrument names its holder and threat; unheld and unrated say so', () => {
  const held = evidenceDetailLines(instrumentDetail(instrument(), [entity()]));
  assert.equal(held.heldBy, 'E1 · man in red');
  assert.equal(held.threat, 'Threat 4/5');
  assert.equal(held.holds, null);
  assert.equal(held.onScreen, null);

  const loose = evidenceDetailLines(instrumentDetail(instrument({ entityId: null, threatLevel: null }), [entity()]));
  assert.equal(loose.heldBy, 'unknown');
  assert.equal(loose.threat, 'Threat unrated');
});

test('an asset has no holder, holds, threat or span lines', () => {
  const lines = evidenceDetailLines(assetDetail(asset({ timestampSeconds: 12 })));
  assert.deepEqual([lines.holds, lines.heldBy, lines.threat, lines.onScreen], [null, null, null, null]);
  assert.equal(lines.time, '0:12');
});

test('an empty description reads "No description was recorded."', () => {
  assert.equal(evidenceDetailLines(assetDetail(asset({ description: '  ' }))).description, 'No description was recorded.');
  assert.equal(evidenceDetailLines(assetDetail(asset())).description, 'Parked.');
});

test("the time falls back to the evidence's; with neither, Play from here is disabled with a note", () => {
  const fromEvidence = assetDetail(asset({ evidence: evidence(9) }));
  assert.equal(fromEvidence.seconds, 9);
  assert.equal(evidenceDetailLines(fromEvidence).playNote, null);

  const timeless = assetDetail(asset());
  assert.equal(timeless.seconds, null);
  const lines = evidenceDetailLines(timeless);
  assert.equal(lines.time, null);
  assert.match(lines.playNote, /No time was recorded/);
});

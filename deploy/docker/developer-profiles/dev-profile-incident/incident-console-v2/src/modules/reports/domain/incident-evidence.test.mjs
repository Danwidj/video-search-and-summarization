// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('../../../../tests/support/alias-loader.mjs', import.meta.url);

const { cameraEvidenceItems } = await import('@/modules/reports/domain/incident-evidence');

const evidence = (image, timestampSeconds = null) => ({ image, imageUrl: null, boundingBox: null, timestampSeconds, uploaded: false });
const structured = {
  incident: {},
  entities: [
    {
      entityId: 'E1',
      type: 'person',
      label: 'Man in red',
      description: 'd1',
      timestampSeconds: 9,
      firstSeenSeconds: 2,
      lastSeenSeconds: 12,
      evidence: null,
    },
    {
      entityId: 'E2',
      type: 'vehicle',
      label: '',
      description: 'd2',
      timestampSeconds: null,
      firstSeenSeconds: null,
      lastSeenSeconds: null,
      evidence: evidence('k', 4),
    },
  ],
  instruments: [
    { instrumentId: 'I1', entityId: 'E1', name: 'Crowbar', description: 'd3', timestampSeconds: 3, threatLevel: 4, evidence: null },
    { instrumentId: 'I2', entityId: null, name: 'Knife', description: 'd4', timestampSeconds: null, threatLevel: null, evidence: null },
  ],
  assets: [{ assetId: 'A1', name: 'Safe', description: 'd5', timestampSeconds: 3, evidence: null }],
};

test('cameraEvidenceItems puts items in time order, untimed last, ties in entity, instrument, asset order', () => {
  const items = cameraEvidenceItems('a.mp4', true, structured);
  assert.deepEqual(
    items.map((item) => item.id),
    ['I1', 'A1', 'E2', 'E1', 'I2'],
  );
});

test('cameraEvidenceItems names the video, falls back to the evidence crop time and to the type for a blank label', () => {
  const items = cameraEvidenceItems('a.mp4', false, structured);
  assert.ok(items.every((item) => item.video === 'a.mp4' && item.playable === false));
  const vehicle = items.find((item) => item.id === 'E2');
  assert.equal(vehicle.seconds, 4);
  assert.equal(vehicle.title, 'vehicle');
});

test('cameraEvidenceItems carries what each kind shows: held instruments, holder, threat and time on screen', () => {
  const byId = Object.fromEntries(cameraEvidenceItems('a.mp4', true, structured).map((item) => [item.id, item]));
  assert.deepEqual(byId.E1.holds, ['Crowbar']);
  assert.deepEqual(byId.E1.onScreen, { firstSeenSeconds: 2, lastSeenSeconds: 12 });
  assert.equal(byId.E2.onScreen, null);
  assert.equal(byId.I1.holder, 'E1 · Man in red');
  assert.equal(byId.I1.threatLevel, 4);
  assert.equal(byId.I2.holder, null);
});

test('an asset shows who last handled it and when; an asset without a handler shows nothing', () => {
  const withHandler = {
    ...structured,
    assets: [
      { assetId: 'A1', name: 'Bag', description: 'd', timestampSeconds: 3, lastHandledBy: { entityId: 'E1', seconds: 7 }, evidence: null },
      { assetId: 'A2', name: 'Box', description: 'd', timestampSeconds: 5, evidence: null },
    ],
  };
  const items = cameraEvidenceItems('v.mp4', true, withHandler).filter((item) => item.kind === 'asset');
  assert.deepEqual(items[0].lastHandledBy, { who: 'E1 (Man in red)', seconds: 7 });
  assert.equal(items[1].lastHandledBy, null);
});

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { boxRegion } = await import('../src/lib/evidence/frame-geometry.ts');
const { dragRegion, pickSeconds, regionBox } = await import('../src/lib/evidence/frame-picker.ts');
const { parseRegion, parseItemId, ITEM_ID } = await import('../src/lib/evidence/frame-request.ts');
const components = new URL('../src/sections/', import.meta.url);

test('a drag in either direction becomes one rectangle clipped to the frame', () => {
  assert.deepEqual(dragRegion({ x: 0.25, y: 0.125 }, { x: 0.75, y: 0.375 }), { x: 0.25, y: 0.125, w: 0.5, h: 0.25 });
  assert.deepEqual(dragRegion({ x: 0.75, y: 0.375 }, { x: 0.25, y: 0.125 }), { x: 0.25, y: 0.125, w: 0.5, h: 0.25 }, 'dragging up and left gives the same rectangle');
  assert.deepEqual(dragRegion({ x: -0.3, y: 0.5 }, { x: 0.4, y: 1.4 }), { x: 0, y: 0.5, w: 0.4, h: 0.5 }, 'a drag past the frame edge is clipped');
});

test('a stray click or a sliver under the crop minimum gives no region', () => {
  assert.equal(dragRegion({ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 }), null);
  assert.equal(dragRegion({ x: 0.5, y: 0.2 }, { x: 0.505, y: 0.6 }), null, 'a width under 1% is refused');
});

test('a region becomes the stored [ymin, xmin, ymax, xmax] box on the 0-1000 grid and reads back the same', () => {
  const region = dragRegion({ x: 0.25, y: 0.125 }, { x: 0.75, y: 0.375 });
  assert.deepEqual(regionBox(region), [125, 250, 375, 750]);
  assert.deepEqual(boxRegion(regionBox(region)), region);
});

test('the drawn region passes the crop route rules, so the server accepts what the picker sends', () => {
  const region = dragRegion({ x: 0.75, y: 0.5 }, { x: 0.25, y: 0.125 });
  assert.deepEqual(parseRegion(region), region);
  assert.equal(parseItemId('entity-m1abc-3'), 'entity-m1abc-3', 'draft keys are valid item IDs');
  assert.ok(ITEM_ID.test('instrument-m2-12'));
});

test('a picked second is never negative and never past the end of the video', () => {
  assert.equal(pickSeconds(-2, 60), 0);
  assert.equal(pickSeconds(72.4, 60), 60);
  assert.equal(pickSeconds(12.5, 60), 12.5);
  assert.equal(pickSeconds(12.5, null), 12.5, 'an unknown length leaves only the lower bound');
});

test('the picker is a dialog that crops through the evidence-crop route and hands back the frame second and box', async () => {
  const picker = await readFile(new URL('evidence/components/EvidenceFramePicker/EvidenceFramePicker.tsx', components), 'utf8');
  assert.match(picker, /role="dialog"/);
  assert.match(picker, /\/api\/reports\/\$\{encodeURIComponent\(videoId\)\}\/evidence-crop/);
  assert.match(picker, /body: JSON\.stringify\(\{ itemId, timestampSeconds: seconds, region \}\)/);
  assert.match(picker, /onPick\(\{ image: body\.image, imageUrl: body\.imageUrl, timestampSeconds: seconds, box: regionBox\(region\) \}\)/);
  assert.match(picker, /Escape/, 'Escape closes the picker unless a crop is running');
});

test('Edit mode offers Replace image on each draft card and applies the pick to the draft item', async () => {
  const pane = await readFile(new URL('reports/components/ReportEditPane/ReportEditPane.tsx', components), 'utf8');
  assert.match(pane, />Replace image</);
  assert.match(pane, /<EvidenceFramePicker/);
  assert.match(pane, /imageTimestampSeconds: pick\.timestampSeconds, imageBox: pick\.box/, 'the frame second and box are stored for the save path');
  assert.match(pane, /timestampSeconds: pick\.timestampSeconds/, 'the picked frame becomes the item\'s most visible second');
  const page = await readFile(new URL('reports/components/ReportPage/ReportPage.tsx', components), 'utf8');
  assert.match(page, /videoSrc=\{report\.run\.playbackUrl\}/);
});

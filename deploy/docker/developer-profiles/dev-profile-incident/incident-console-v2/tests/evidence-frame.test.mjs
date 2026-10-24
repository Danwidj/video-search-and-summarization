// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { boxRegion, boxStyle, cropImageStyle, cropRegion, evidenceFrameState } = await import('../src/lib/evidence/frame-geometry.ts');
const components = new URL('../src/sections/', import.meta.url);

test('a [ymin, xmin, ymax, xmax] box on the 0-1000 grid becomes frame fractions and CSS percentages', () => {
  assert.deepEqual(boxRegion([100, 200, 300, 600]), { x: 0.2, y: 0.1, w: 0.4, h: 0.2 });
  assert.deepEqual(boxStyle([100, 200, 300, 600]), { left: '20%', top: '10%', width: '40%', height: '20%' });
  assert.deepEqual(boxRegion([-50, 0, 1200, 1000]), { x: 0, y: 0, w: 1, h: 1 }, 'out-of-range values are clamped to the frame');
});

test('a box without usable geometry gives no region', () => {
  for (const box of [null, undefined, [], [1, 2, 3], [10, 10, 10, 50], [50, 40, 20, 40], [0, 0, NaN, 10], ['a', 0, 1, 1]]) {
    assert.equal(boxRegion(box), null, JSON.stringify(box));
    assert.equal(boxStyle(box), null);
    assert.equal(cropRegion(box, 16 / 9, 4 / 3), null);
  }
});

test('a crop region keeps the tile aspect, contains the box and stays inside the frame', () => {
  const frameAspect = 16 / 9;
  const tileAspect = 4 / 3;
  for (const box of [
    [400, 400, 600, 500],
    [0, 0, 100, 60],
    [900, 940, 1000, 1000],
    [100, 100, 900, 900],
  ]) {
    const region = cropRegion(box, frameAspect, tileAspect, 0);
    assert.ok(region, JSON.stringify(box));
    assert.ok(Math.abs((region.w * frameAspect) / region.h - tileAspect) < 1e-9, 'not stretched');
    assert.ok(region.x >= 0 && region.y >= 0 && region.x + region.w <= 1 + 1e-9 && region.y + region.h <= 1 + 1e-9, 'inside the frame');
  }
  const small = cropRegion([400, 400, 600, 500], frameAspect, tileAspect, 0);
  const inner = boxRegion([400, 400, 600, 500]);
  assert.ok(
    small.x <= inner.x && small.y <= inner.y && small.x + small.w >= inner.x + inner.w && small.y + small.h >= inner.y + inner.h,
    'contains the box',
  );
});

test('a box as large as the frame shows the largest region of the tile aspect', () => {
  assert.deepEqual(cropRegion([0, 0, 1000, 1000], 4 / 3, 4 / 3), { x: 0, y: 0, w: 1, h: 1 });
});

test('the crop image style scales and offsets the full frame behind the tile', () => {
  assert.deepEqual(cropImageStyle({ x: 0.25, y: 0.5, w: 0.5, h: 0.25 }), { width: '200%', height: '400%', left: '-50%', top: '-200%' });
});

test('an evidence tile prefers the stored image, then a frame crop, then a placeholder', () => {
  const box = [100, 100, 200, 200];
  assert.equal(evidenceFrameState({ src: 'https://x/crop.jpg', frameSrc: 'https://x/f.jpg', box }), 'image');
  assert.equal(evidenceFrameState({ frameSrc: 'https://x/f.jpg', box }), 'frame-crop');
  assert.equal(evidenceFrameState({ frameSrc: 'https://x/f.jpg', box: null }), 'missing', 'a frame without a box cannot be cropped');
  assert.equal(evidenceFrameState({ pending: true }), 'pending');
  assert.equal(evidenceFrameState({}), 'missing');
  assert.equal(
    evidenceFrameState({ src: 'https://x/crop.jpg', failed: true, pending: true }),
    'pending',
    'a failed image falls back to the placeholder',
  );
});

test('EvidenceFrame and FrameViewer render the states and boxes the report page needs', async () => {
  const frame = await readFile(new URL('evidence/components/EvidenceFrame/EvidenceFrame.tsx', components), 'utf8');
  assert.match(frame, /export function EvidenceFrame/);
  assert.match(frame, /export \{ EvidenceFrame as CropImage \}/);
  assert.match(frame, /Cropping frame/);
  assert.match(frame, /Image unavailable/);
  assert.match(frame, /onError/, 'a broken image falls back to the placeholder');

  const viewer = await readFile(new URL('evidence/components/FrameViewer/FrameViewer.tsx', components), 'utf8');
  assert.match(viewer, /export function FrameViewer/);
  assert.match(viewer, /boxStyle\(item\.box\)/);
  assert.match(viewer, /Frame unavailable/);
  assert.match(viewer, /aria-pressed/);
  assert.match(viewer, /onSelect/);
});

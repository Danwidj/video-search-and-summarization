// SPDX-License-Identifier: Apache-2.0

// The report workspace's video panel is sized to the column width at the video's aspect ratio, so the player is flush
// with no bars. The timeline and versions split what is left; the video keeps between 20% and 70% of the column.

import assert from 'node:assert/strict';
import test from 'node:test';

const { videoFitLayout, VIDEO_MIN_PERCENT, VIDEO_MAX_PERCENT } = await import('../src/lib/ui/video-fit.ts');

const sum = ({ video, timeline, versions }) => video + timeline + versions;

test('a column exactly the video shape gives the video its full share and splits the rest evenly', () => {
  // A 16:9 video in a 1600 px wide column is 900 px tall; in a 1800 px tall column that is exactly 50%.
  const layout = videoFitLayout(1600, 1800, 16 / 9);
  assert.ok(Math.abs(layout.video - 50) < 1e-9, String(layout.video));
  assert.ok(Math.abs(layout.timeline - 25) < 1e-9);
  assert.ok(Math.abs(layout.versions - 25) < 1e-9);
});

test('the video panel height follows the column width at the aspect ratio', () => {
  const narrow = videoFitLayout(800, 1000, 16 / 9);
  const wide = videoFitLayout(1200, 1000, 16 / 9);
  assert.ok(wide.video > narrow.video, 'a wider column needs a taller video');
});

test('a portrait video takes more height at the same width', () => {
  const landscape = videoFitLayout(800, 1000, 16 / 9);
  const portrait = videoFitLayout(800, 1000, 9 / 16);
  assert.ok(portrait.video > landscape.video);
});

test('the three panels always fill the column', () => {
  for (const [width, height, aspect] of [
    [700, 900, 16 / 9],
    [1300, 800, 4 / 3],
    [500, 1200, 9 / 16],
  ]) {
    assert.ok(Math.abs(sum(videoFitLayout(width, height, aspect)) - 100) < 1e-9);
  }
});

test('the video is clamped so the timeline and versions keep their minimums', () => {
  const tooTall = videoFitLayout(2000, 400, 16 / 9);
  assert.equal(tooTall.video, VIDEO_MAX_PERCENT);
  assert.ok(tooTall.timeline >= 15 && tooTall.versions >= 15);
  const tooShort = videoFitLayout(100, 2000, 16 / 9);
  assert.equal(tooShort.video, VIDEO_MIN_PERCENT);
});

test('a column with no size gives no layout, so nothing is set while it is hidden', () => {
  for (const [width, height] of [
    [0, 900],
    [800, 0],
    [Number.NaN, 900],
  ]) {
    assert.equal(videoFitLayout(width, height, 16 / 9), null);
  }
  assert.equal(videoFitLayout(800, 900, 0), null);
});

test('the timeline takes the height its lanes need and versions take the rest', async () => {
  const { timelinePanelHeight } = await import('../src/lib/ui/video-fit.ts');
  const layout = videoFitLayout(1600, 1800, 16 / 9, 270);
  assert.ok(Math.abs(layout.timeline - 15) < 1e-9, String(layout.timeline));
  assert.ok(Math.abs(sum(layout) - 100) < 1e-9);
  assert.ok(timelinePanelHeight(6) > timelinePanelHeight(2));
  const tall = videoFitLayout(1600, 1800, 16 / 9, 10_000);
  assert.ok(Math.abs(tall.versions - 15) < 1e-9, String(tall.versions));
});

// SPDX-License-Identifier: Apache-2.0

// Save's reviewer items: what the new entry keeps from the entry it replaces, and what it drops because the new image,
// frame and track make it stale.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { storeReviewerItems } = await import('../src/modules/reports/application/store-reviewer-items/index.ts');

// A JPEG header with a start-of-frame marker: all the Save use case reads from a frame is its size.
const jpeg = (width, height) =>
  Buffer.from([
    0xff,
    0xd8,
    0xff,
    0xc0,
    0,
    17,
    8,
    height >> 8,
    height & 255,
    width >> 8,
    width & 255,
    3,
    1,
    0x22,
    0,
    2,
    0x11,
    1,
    3,
    0x11,
    1,
    0xff,
    0xd9,
  ]);

const fakeStore = () => {
  const frames = [];
  const puts = [];
  return {
    frames,
    puts,
    frame: async (_videoKey, seconds, region, scaleTo = null) => {
      frames.push({ seconds, region, scaleTo });
      return jpeg(1920, 1080);
    },
    exists: async () => false,
    put: async (key) => {
      puts.push(key);
    },
  };
};

const retracked = {
  entities: [
    {
      entity_id: 'E1',
      source_id: 'E1',
      reviewer: {
        ai_proposal: null,
        track: {
          source: 'reviewer',
          samples: [
            { t: 7.6, box: [100, 100, 500, 400] },
            { t: 7.85, box: [110, 110, 510, 410] },
          ],
          span: [7.6, 7.85],
          partial: false,
          lostAt: null,
        },
        still_seconds: null,
        still_box: null,
      },
    },
  ],
  instruments: [],
  assets: [],
};

const aiEntry = {
  item_type: 'entity',
  item_id: 'E1',
  timestamp_seconds: 8,
  label: 'man in red',
  image: 'evidence/v.mp4/run-1/E1.jpg',
  frame: 'evidence/v.mp4/run-1/E1-frame.jpg',
  bounding_box: [90, 90, 520, 420],
  detected_box: [100, 100, 500, 400],
  box_seconds: 8,
  located: true,
  image_gap: null,
  track_gap: "no person track overlapped this person's box",
  zoom_checked: true,
  zoom_confidence: 0.9,
  zoom_seen: { frame: 'a man', close_up: 'a man in red' },
  name_before: 'person',
  description_before: 'a person',
  zoom_gap: null,
};

test("a re-tracked item drops the old crop's box, second look and gaps, and cuts at the first sample's exact second", async () => {
  const store = fakeStore();
  const entries = await storeReviewerItems(store, 'v.mp4', retracked, [aiEntry]);
  const entry = entries.get('entity:E1');
  for (const field of [
    'detected_box',
    'zoom_checked',
    'zoom_confidence',
    'zoom_seen',
    'zoom_gap',
    'name_before',
    'description_before',
    'image_gap',
    'track_gap',
  ])
    assert.equal(field in entry, false, `${field} described the old crop`);
  assert.equal(entry.label, 'man in red', 'what is not about the image is kept');
  assert.equal(entry.box_seconds, 7.6);
  assert.deepEqual(entry.bounding_box, [100, 100, 500, 400]);
  assert.equal(entry.track_source, 'reviewer');
  assert.ok(entry.image.includes('edit-') && entry.frame !== aiEntry.frame, 'a new image and frame, nothing overwritten');
  assert.deepEqual(
    store.frames.map((frame) => [frame.seconds, frame.region === null ? 'frame' : 'crop']),
    [
      [7.6, 'frame'],
      [7.6, 'crop'],
    ],
    "frame and crop are cut sequentially at the first sample's exact second",
  );
});

const picked = (pick, extra = {}) => ({
  entities: [{ entity_id: 'E1', source_id: 'E1', reviewer: null, image_pick: pick, ...extra }],
  instruments: [],
  assets: [],
});
const trackedEntry = {
  ...aiEntry,
  track: 'evidence/v.mp4/run-1/E1-track.json',
  track_first_seen_seconds: 6,
  track_last_seen_seconds: 12,
  track_source: 'ai',
  track_partial: false,
  source: 'upload',
};

test('a picked image is cut at the picked second and box, keeps the track, and drops the old crop facts', async () => {
  const store = fakeStore();
  const pick = { seconds: 9.35, box: [200, 300, 600, 700] };
  const entries = await storeReviewerItems(store, 'v.mp4', picked(pick), [trackedEntry]);
  const entry = entries.get('entity:E1');
  assert.equal(entry.box_seconds, 9.35);
  assert.equal(entry.timestamp_seconds, 9);
  assert.deepEqual(entry.bounding_box, pick.box);
  assert.equal(entry.located, true);
  assert.ok(entry.image.includes('edit-') && entry.frame.includes('edit-') && entry.image !== aiEntry.image);
  for (const field of ['detected_box', 'zoom_checked', 'zoom_seen', 'name_before', 'image_gap'])
    assert.equal(field in entry, false, `${field} described the old crop`);
  assert.equal(entry.track, trackedEntry.track, 'the item keeps its stored track');
  assert.equal(entry.track_first_seen_seconds, 6);
  assert.equal(entry.track_last_seen_seconds, 12);
  assert.equal(entry.track_source, 'ai');
  assert.equal(entry.track_gap, aiEntry.track_gap, 'what is not about the image is kept');
  assert.equal(entry.source, 'upload', 'the entry keeps the source it had');
  assert.equal(entry.label, 'man in red');
  assert.deepEqual(
    store.frames.map((frame) => [frame.seconds, frame.region === null ? 'frame' : 'crop']),
    [
      [9.35, 'frame'],
      [9.35, 'crop'],
    ],
  );
  assert.equal(
    store.puts.some((key) => key.endsWith('-track.json')),
    false,
    'no track file is written for a pick alone',
  );
});

test('an item with no stored entry (the detector missed it) gets an image, frame and box from a pick', async () => {
  const store = fakeStore();
  const pick = { seconds: 2, box: [10, 20, 400, 300] };
  const entries = await storeReviewerItems(store, 'v.mp4', picked(pick, { source_id: 'E2', entity_id: 'E2' }), [
    { item_type: 'entity', item_id: 'E2', frame: 'evidence/v.mp4/run-1/E2-frame.jpg', located: false, image_gap: 'detector failed' },
  ]);
  const entry = entries.get('entity:E2');
  assert.equal(entry.located, true);
  assert.equal(entry.image_gap === undefined, true, 'the gap no longer applies');
  assert.deepEqual(entry.bounding_box, pick.box);
  assert.ok(entry.image && entry.frame !== 'evidence/v.mp4/run-1/E2-frame.jpg');
});

test('a pick wins over the first sample of a re-tracked item, and the track is still stored', async () => {
  const store = fakeStore();
  const pick = { seconds: 7.85, box: [1, 2, 300, 400] };
  const entries = await storeReviewerItems(
    store,
    'v.mp4',
    {
      ...retracked,
      entities: retracked.entities.map((entity) => ({ ...entity, image_pick: pick })),
    },
    [aiEntry],
  );
  const entry = entries.get('entity:E1');
  assert.equal(entry.box_seconds, 7.85);
  assert.deepEqual(entry.bounding_box, pick.box);
  assert.equal(entry.track_source, 'reviewer');
  assert.equal(entry.track_first_seen_seconds, 7.6);
  assert.equal(
    store.puts.some((key) => key.endsWith('-track.json')),
    true,
  );
});

test('a pick marks the entry as the reviewer image, and a later re-track without a pick keeps that image', async () => {
  const pick = { seconds: 9.35, box: [200, 300, 600, 700] };
  const first = (await storeReviewerItems(fakeStore(), 'v.mp4', picked(pick), [trackedEntry])).get('entity:E1');
  assert.equal(first.image_source, 'reviewer');
  const store = fakeStore();
  const next = (await storeReviewerItems(store, 'v.mp4', retracked, [first])).get('entity:E1');
  assert.equal(next.image, first.image, "the reviewer's image survives a re-track");
  assert.equal(next.frame, first.frame);
  assert.deepEqual(next.bounding_box, pick.box);
  assert.equal(next.box_seconds, 9.35);
  assert.equal(next.image_source, 'reviewer');
  assert.equal(next.track_first_seen_seconds, 7.6, 'the track itself is the new one');
  assert.deepEqual(store.frames, [], 'nothing is cut again');
  assert.equal(
    store.puts.every((key) => key.endsWith('-track.json')),
    true,
    'only the track file is written',
  );
});

test('a re-track of an item whose image was not set by a reviewer takes the new track first frame', async () => {
  const entry = (await storeReviewerItems(fakeStore(), 'v.mp4', retracked, [{ ...aiEntry, image_source: undefined }])).get('entity:E1');
  assert.equal(entry.box_seconds, 7.6);
  assert.equal('image_source' in entry && entry.image_source !== undefined, false);
});

test('a small box is cut with a wider margin and enlarged; the stored box stays exact', async () => {
  const store = fakeStore();
  const pick = { seconds: 2, box: [500, 500, 560, 530] };
  const entry = (await storeReviewerItems(store, 'v.mp4', picked(pick), [trackedEntry])).get('entity:E1');
  const crop = store.frames.find((frame) => frame.region !== null);
  assert.ok(crop.scaleTo && Math.min(crop.scaleTo.w, crop.scaleTo.h) >= 192, 'enlarged to a readable size');
  assert.ok(crop.region.w > 0.03 && crop.region.h > 0.06, 'the context margin is wider than the box');
  assert.deepEqual(entry.bounding_box, pick.box);
});

test('a box of ordinary size is cut as drawn and not enlarged', async () => {
  const store = fakeStore();
  await storeReviewerItems(store, 'v.mp4', picked({ seconds: 2, box: [100, 100, 600, 500] }), [trackedEntry]);
  assert.equal(store.frames.find((frame) => frame.region !== null).scaleTo, null);
});

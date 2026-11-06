// SPDX-License-Identifier: Apache-2.0

// Save's reviewer items: what the new entry keeps from the entry it replaces, and what it drops because the new image,
// frame and track make it stale.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { storeReviewerItems } = await import('../src/modules/reports/application/store-reviewer-items/index.ts');

const fakeStore = () => {
  const frames = [];
  const puts = [];
  return {
    frames,
    puts,
    frame: async (_videoKey, seconds, region) => {
      frames.push({ seconds, region });
      return Buffer.from('jpeg');
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
      [7.6, 'crop'],
      [7.6, 'frame'],
    ],
    "crop and frame are cut sequentially at the first sample's exact second",
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
      [9.35, 'crop'],
      [9.35, 'frame'],
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

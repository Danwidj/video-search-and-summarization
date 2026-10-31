// SPDX-License-Identifier: Apache-2.0

// Edit mode's track scrubber: the track file read once and checked, a scrubber value as a whole second inside the
// track, the box at that second, and the pick saved through the unchanged human revision path.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { parseTrack, trackBoxAt, trackSecond, trackSpan } = await import('../src/lib/evidence/track.ts');
const { boxRegion } = await import('../src/lib/evidence/frame-geometry.ts');
const { parseRegion } = await import('../src/lib/evidence/frame-request.ts');
const { editFromDraft } = await import('../src/modules/reports/domain/edit-draft.ts');
const { humanRevisionContent } = await import('../src/modules/reports/domain/revision.ts');
const { structuredFromPayload } = await import('../src/modules/reports/domain/payload-view.ts');
const components = new URL('../src/sections/', import.meta.url);

// A track as the agent stores it: [{t, box, score}], box [top, left, bottom, right] on 0..1000.
const TRACK = [
  { t: 80.4, box: [100, 200, 500, 300], score: 0.9 },
  { t: 81.2, box: [110, 220, 510, 320], score: 0.92 },
  { t: 82.0, box: [300, 240, 700, 400], score: -0.1 },
  { t: 84.6, box: [320, 260, 720, 420], score: 0.88 },
];

test('a track file reads as its samples, oldest first, without the score', () => {
  const samples = parseTrack([TRACK[2], TRACK[0], TRACK[3], TRACK[1]]);
  assert.deepEqual(
    samples.map((sample) => sample.t),
    [80.4, 81.2, 82, 84.6],
  );
  assert.deepEqual(samples[0], { t: 80.4, box: [100, 200, 500, 300] });
});

test('a malformed track file is ignored as a whole, so the picker falls back to today', () => {
  assert.equal(parseTrack(null), null);
  assert.equal(parseTrack({ t: 1, box: [1, 2, 3, 4] }), null, 'not a list');
  assert.equal(parseTrack([]), null, 'an empty track');
  assert.equal(parseTrack([...TRACK, { t: 'x', box: [1, 2, 3, 4] }]), null, 'a sample without a numeric second');
  assert.equal(parseTrack([...TRACK, { t: 90, box: [1, 2, 3] }]), null, 'a box with three numbers');
  assert.equal(parseTrack([...TRACK, { t: 90, box: [500, 2, 100, 4] }]), null, 'a box with no height');
  assert.equal(parseTrack([...TRACK, { t: -1, box: [1, 2, 3, 4] }]), null, 'a negative second');
  assert.equal(parseTrack([...TRACK, null]), null);
});

test('the scrubber spans the whole seconds inside the track', () => {
  assert.deepEqual(trackSpan(parseTrack(TRACK)), { first: 81, last: 84 });
  assert.deepEqual(trackSpan(parseTrack([{ t: 3, box: [1, 2, 3, 4] }])), { first: 3, last: 3 });
  assert.deepEqual(
    trackSpan(parseTrack([TRACK[0], { t: 80.8, box: [1, 2, 3, 4] }])),
    { first: 81, last: 81 },
    'a track inside one second stops at its nearest whole second',
  );
});

test('a scrubber value becomes a whole second, clamped at the track ends', () => {
  const span = { first: 81, last: 84 };
  assert.equal(trackSecond(82.4, span), 82);
  assert.equal(trackSecond(82.6, span), 83);
  assert.equal(trackSecond(10, span), 81, 'before the track starts: its first second');
  assert.equal(trackSecond(200, span), 84, 'after the track ends: its last second');
  assert.equal(trackSecond(Number.NaN, span), 81);
});

test("the box at a second is the nearest sample's, held between samples", () => {
  const samples = parseTrack(TRACK);
  assert.deepEqual(trackBoxAt(samples, 81), [110, 220, 510, 320], '81 s is nearest the 81.2 s sample');
  assert.deepEqual(trackBoxAt(samples, 82), [300, 240, 700, 400], 'a tracked-only sample still gives the box');
  assert.deepEqual(trackBoxAt(samples, 83), [300, 240, 700, 400], 'held across the gap until a nearer sample');
  assert.deepEqual(trackBoxAt(samples, 84), [320, 260, 720, 420]);
  assert.deepEqual(trackBoxAt(samples, 0), [100, 200, 500, 300], 'never extrapolated past the ends');
});

test('the track box at a second is a crop region the crop route accepts', () => {
  const region = boxRegion(trackBoxAt(parseTrack(TRACK), 82));
  assert.deepEqual(parseRegion(region), region);
});

test('the evidence entry carries its track key and span into the view; an entry without one carries nulls', () => {
  const payload = {
    entities: [
      { entity_id: 'E1', type: 'human' },
      { entity_id: 'E2', type: 'human' },
    ],
  };
  const evidence = [
    {
      item_type: 'entity',
      item_id: 'E1',
      image: 'evidence/v/run-1/E1.jpg',
      bounding_box: [1, 2, 3, 4],
      timestamp_seconds: 82,
      track: 'evidence/v/run-1/E1-track.json',
      track_first_seen_seconds: 80.4,
      track_last_seen_seconds: 84.6,
    },
    { item_type: 'entity', item_id: 'E2', image: 'evidence/v/run-1/E2.jpg', bounding_box: [1, 2, 3, 4], timestamp_seconds: 82 },
  ];
  const [tracked, plain] = structuredFromPayload(payload, evidence).entities;
  assert.equal(tracked.evidence.track, 'evidence/v/run-1/E1-track.json');
  assert.equal(tracked.evidence.trackUrl, null, 'signed later by getReport');
  assert.equal(tracked.evidence.trackFirstSeenSeconds, 80.4);
  assert.equal(tracked.evidence.trackLastSeenSeconds, 84.6);
  assert.equal(plain.evidence.track, null);
  assert.equal(plain.evidence.trackFirstSeenSeconds, null);
});

test('a second and box picked on the track are saved as a new human revision, as a drawn frame is', () => {
  const parent = {
    payload: { incident: { type: 'assault' }, entities: [{ entity_id: 'E1', type: 'human' }] },
    evidence: [
      {
        item_type: 'entity',
        item_id: 'E1',
        image: 'evidence/v/run-1/E1.jpg',
        bounding_box: [100, 200, 500, 300],
        timestamp_seconds: 82,
        box_seconds: 81.2,
        track: 'evidence/v/run-1/E1-track.json',
      },
    ],
  };
  const box = trackBoxAt(parseTrack(TRACK), 84);
  const item = {
    key: 'entity-0',
    sourceId: 'E1',
    timestampSeconds: 82,
    label: 'man',
    image: 'evidence/v/edit-1/entity-0.jpg',
    imageUrl: null,
    pendingImage: null,
    imageTimestampSeconds: 84,
    imageBox: [...box],
    canonicalId: 'E1',
    type: 'human',
    description: 'A man.',
    firstSeenSeconds: 80,
    lastSeenSeconds: 85,
  };
  const draft = {
    incident: { type: 'assault', start_timestamp: 80, end_timestamp: 86, description: 'A fall.', severity_level: 2 },
    entities: [item],
    instruments: [],
    assets: [],
  };
  const { evidence } = humanRevisionContent(parent, editFromDraft(draft));
  assert.deepEqual(evidence, [
    {
      item_type: 'entity',
      item_id: 'E1',
      image: 'evidence/v/edit-1/entity-0.jpg',
      bounding_box: [320, 260, 720, 420],
      timestamp_seconds: 84,
      source: 'upload',
    },
  ]);
});

test('the picker loads the track once per item and scrubs it in whole seconds through the frame route', async () => {
  const picker = await readFile(new URL('evidence/components/EvidenceFramePicker/EvidenceFramePicker.tsx', components), 'utf8');
  assert.match(picker, /const trackFiles = new Map<string, Promise<TrackSample\[\] \| null>>\(\);/, 'one load per track key');
  assert.match(picker, /\.then\(parseTrack\)/, 'the file is checked before use');
  assert.match(picker, /\.catch\(\(\) => null\)/, 'a failed load leaves the ordinary picker');
  assert.match(picker, /src=\{videoFrameUrl\(videoId, frameSeconds\)\}/, 'the frame comes from the frame route');
  assert.match(picker, /aria-label="Track second"[\s\S]*?step=\{1\}/, 'the scrubber moves in whole seconds');
  assert.match(picker, /const box = !drawn && trackBox \? \[\.\.\.trackBox\] : regionBox\(region\);/);
  const pane = await readFile(new URL('reports/components/ReportEditPane/ReportEditPane.tsx', components), 'utf8');
  assert.match(pane, /track=\{pickingTrack\}/);
  assert.match(pane, /saved\?\.track && saved\.trackUrl \? \{ key: saved\.track, url: saved\.trackUrl \} : null/);
});

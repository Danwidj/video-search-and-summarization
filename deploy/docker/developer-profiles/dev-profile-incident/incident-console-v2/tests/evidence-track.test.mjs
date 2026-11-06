// SPDX-License-Identifier: Apache-2.0

// Person tracks in the report: reading the track file, the overlay's box at a second under contain-fit, the presence bar,
// the view mapping of an evidence entry's track, and the track use case's key handling.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const {
  containedBoxStyle,
  parseTrackSamples,
  presenceRegion,
  presenceSeekSeconds,
  draftOverlay,
  STILL_BOX_LEAD_SECONDS,
  STILL_BOX_WINDOW_SECONDS,
  stillBoxesFor,
  stillBoxFor,
  stillBoxShows,
  trackBoxAt,
  trackColour,
  trackedReportItems,
  TRACK_COLOURS,
  TRACK_TOLERANCE_SECONDS,
} = await import('../src/modules/reports/domain/track.ts');
const { structuredFromPayload } = await import('../src/modules/reports/domain/payload-view.ts');
const { entityDetail, evidenceDetailLines } = await import('../src/modules/reports/domain/evidence-detail.ts');
const { getEvidenceTrack } = await import('../src/modules/reports/application/get-evidence-track/index.ts');
const { evidenceTrackUrl, getReport } = await import('../src/modules/reports/application/get-report/index.ts');
const { InMemoryIncidentRepository } = await import('../src/modules/reports/infrastructure/memory/incidents.ts');
const { aiRunReport } = await import('./support/report-view.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const TRACK_KEY = 'evidence/uploads/v.mp4/run-1/E1-track.json';
const samples = [
  { t: 10, box: [100, 100, 300, 200] },
  { t: 10.2, box: [100, 120, 300, 220] },
  { t: 10.4, box: [100, 140, 300, 240] },
];

test('a track file is read leniently: malformed samples dropped, sorted by time, anything but a list is null', () => {
  assert.equal(parseTrackSamples({ t: 1 }), null);
  assert.equal(parseTrackSamples(null), null);
  assert.deepEqual(
    parseTrackSamples([
      { t: 2, box: [0, 0, 10, 10], score: 0.9 },
      { t: 1, box: [0, 0, 10, 10], score: -0.1 },
      { t: 'x', box: [0, 0, 10, 10] },
      { t: 3, box: [0, 0, 10] },
      { t: 4, box: [10, 10, 5, 5] },
      { t: -1, box: [0, 0, 10, 10] },
      null,
    ]),
    [
      { t: 1, box: [0, 0, 10, 10] },
      { t: 2, box: [0, 0, 10, 10] },
    ],
  );
});

test('the box at a second interpolates between close samples and holds the nearest at the span ends', () => {
  assert.deepEqual(trackBoxAt(samples, 10.1), [100, 110, 300, 210]);
  assert.deepEqual(trackBoxAt(samples, 10.2), [100, 120, 300, 220]);
  assert.deepEqual(trackBoxAt(samples, 10.4 + TRACK_TOLERANCE_SECONDS), [100, 140, 300, 240]);
  assert.deepEqual(trackBoxAt(samples, 10 - TRACK_TOLERANCE_SECONDS), [100, 100, 300, 200]);
});

test('the box is hidden outside the track span plus the tolerance, and inside a gap the tracker lost the person', () => {
  assert.equal(trackBoxAt(samples, 9.4), null);
  assert.equal(trackBoxAt(samples, 11), null);
  assert.equal(trackBoxAt([], 10), null);
  const gapped = [
    { t: 1, box: [0, 0, 100, 100] },
    { t: 5, box: [0, 400, 100, 500] },
  ];
  assert.equal(trackBoxAt(gapped, 3), null, 'never drawn sliding across a four-second gap');
  assert.deepEqual(trackBoxAt(gapped, 1.3), [0, 0, 100, 100]);
});

test('under contain-fit a wide frame is letterboxed and a tall frame pillarboxed, and the box follows the picture', () => {
  const box = [0, 0, 500, 500];
  // A 16:9 frame in a square tile fills the width and 9/16 of the height, centred.
  assert.deepEqual(containedBoxStyle(box, 16 / 9, 1), { left: '0%', top: '21.875%', width: '50%', height: '28.125%' });
  // A 9:16 frame in a 16:9 tile fills the height and (9/16)/(16/9) of the width, centred.
  const fit = 9 / 16 / (16 / 9);
  const style = containedBoxStyle([500, 500, 1000, 1000], 9 / 16, 16 / 9);
  assert.equal(style.top, '50%');
  assert.equal(style.height, '50%');
  assert.equal(style.left, `${+(((1 - fit) / 2 + 0.5 * fit) * 100).toFixed(3)}%`);
  assert.equal(style.width, `${+(0.5 * fit * 100).toFixed(3)}%`);
  // A tile of the frame's own shape is the plain box.
  assert.deepEqual(containedBoxStyle([100, 200, 300, 400], 16 / 9, 16 / 9), { left: '20%', top: '10%', width: '20%', height: '20%' });
  assert.equal(containedBoxStyle(null, 1, 1), null);
});

test('the presence bar places the span over the clip, keeps a short span visible and seeks into the span', () => {
  const near = (actual, expected) => {
    assert.ok(Math.abs(actual.left - expected.left) < 1e-9 && Math.abs(actual.width - expected.width) < 1e-9, JSON.stringify(actual));
  };
  near(presenceRegion(20, 60, 100), { left: 0.2, width: 0.4 });
  near(presenceRegion(50, 50, 100), { left: 0.5, width: 0.01 });
  near(presenceRegion(99.9, 100, 100), { left: 0.99, width: 0.01 });
  near(presenceRegion(80, 140, 100), { left: 0.8, width: 0.2 });
  assert.equal(presenceRegion(20, 60, null), null);
  assert.equal(presenceRegion(60, 20, 100), null);
  assert.equal(presenceRegion(120, 130, 100), null);
  assert.equal(presenceSeekSeconds(0.25, 80, 15, 30), 20, 'a click on the span seeks to the second under it');
  assert.equal(presenceSeekSeconds(0.9, 80, 15, 30), 15, 'a click on empty clip seeks to the span start');
  assert.equal(presenceSeekSeconds(-1, 80, 15, 30), 15, 'a key press seeks to the span start');
});

const payload = {
  incident: {},
  entities: [
    { entity_id: 'E1', type: 'human', label: 'man in red', timestamp_seconds: 82, first_seen_seconds: 80, last_seen_seconds: 90 },
    { entity_id: 'E2', type: 'human', label: 'man in blue', timestamp_seconds: 82 },
    { entity_id: 'E3', type: 'human', label: 'woman', timestamp_seconds: 30 },
  ],
  instruments: [],
  assets: [],
};
const entry = (id, extra = {}) => ({ item_type: 'entity', item_id: id, image: null, bounding_box: null, timestamp_seconds: 82, ...extra });

test('the view carries a track when the entry has its key and both span ends, and nothing otherwise', () => {
  const { entities } = structuredFromPayload(payload, [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 78.2, track_last_seen_seconds: 95.6 }),
    entry('E2'),
    entry('E3', { track: TRACK_KEY.replace('E1', 'E3'), track_first_seen_seconds: 'x', track_last_seen_seconds: 40 }),
  ]);
  const track = ({ evidence }) => ({
    track: evidence.track,
    trackUrl: evidence.trackUrl,
    first: evidence.trackFirstSeenSeconds,
    last: evidence.trackLastSeenSeconds,
  });
  assert.deepEqual(track(entities[0]), { track: TRACK_KEY, trackUrl: null, first: 78.2, last: 95.6 });
  const none = { track: null, trackUrl: null, first: null, last: null };
  assert.deepEqual(track(entities[1]), none, 'an entry without a track behaves as before');
  assert.deepEqual(track(entities[2]), none, 'a malformed span reads as no track');

  const lines = entities.map((entity) => evidenceDetailLines(entityDetail(entity, [])));
  assert.equal(lines[0].onScreen, 'On screen 1:20–1:30', "the report's own span is never rewritten");
  assert.equal(lines[0].trackedOnScreen, 'On screen 1:18–1:35 (tracked)');
  assert.equal(lines[1].trackedOnScreen, null);
});

test('an untracked item holds its stored box at the second it was found; a tracked or box-less one holds nothing', () => {
  const item = (evidence) => ({ id: 'E2', title: 'man in blue', evidence });
  const found = { track: null, located: true, boxSeconds: 12.5, boundingBox: [100, 200, 600, 700] };
  assert.deepEqual(stillBoxFor(item(found)), { id: 'E2', label: 'man in blue', box: [100, 200, 600, 700], seconds: 12.5 });
  assert.equal(stillBoxFor(item({ ...found, located: null }))?.seconds, 12.5, 'an entry that predates the flag still holds');
  assert.equal(stillBoxFor(item({ ...found, track: TRACK_KEY })), null, 'a tracked item draws its track');
  assert.equal(stillBoxFor(item({ ...found, located: false })), null, 'the detector found nothing');
  assert.equal(stillBoxFor(item({ ...found, boxSeconds: null })), null);
  assert.equal(stillBoxFor(item({ ...found, boundingBox: null })), null);
  assert.equal(stillBoxFor(item({ ...found, boundingBox: [0, 0, 0, 0] })), null, 'an empty box');
  assert.equal(stillBoxFor(item(null)), null);
});

test('a still box shows for 2 s from its second, and from a seek that lands just short of it', () => {
  const still = { id: 'E2', label: 'man in blue', box: [100, 200, 600, 700], seconds: 12.5 };
  assert.equal(STILL_BOX_WINDOW_SECONDS, 2);
  assert.equal(STILL_BOX_LEAD_SECONDS, 0.25);
  assert.equal(stillBoxShows(still, 12.5), true);
  assert.equal(stillBoxShows(still, 12.25), true, 'the lead edge');
  assert.equal(stillBoxShows(still, 12.24), false);
  assert.equal(stillBoxShows(still, 14.5), true, 'the end of the window');
  assert.equal(stillBoxShows(still, 14.51), false);
  assert.equal(stillBoxShows(still, 3), false);
});

test('every untracked item with a stored box has a still box, named as the player names it, and a tracked one has none', () => {
  const structured = structuredFromPayload(payload, [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 78, track_last_seen_seconds: 95 }),
    entry('E2', { box_seconds: 12, bounding_box: [100, 200, 600, 700], located: true }),
    entry('E3', { box_seconds: 12, bounding_box: [100, 200, 600, 700], located: false }),
  ]);
  assert.deepEqual(
    stillBoxesFor(structured).map(({ id, label, seconds }) => [id, label, seconds]),
    [['E2', structured.entities[1].label || structured.entities[1].type, 12]],
  );
});

test('overlapping still boxes are all drawn, and neither a play nor a seek clears them', async () => {
  const overlay = await readFile(new URL('../src/sections/reports/components/TrackOverlay/TrackOverlay.tsx', import.meta.url), 'utf8');
  assert.match(overlay, /stills\s*\.filter\(\(still\) => stillBoxShows\(still, seconds\)\)\s*\.map/);
  assert.doesNotMatch(overlay, /onStillDone/);
  assert.match(overlay, /const selected = still\.id === selectedId;/, 'the selected card is emphasised, as a track is');
});

test('a person the run did not track says why, on the card and the pop-up lines, and a tracked one does not', () => {
  const { entities } = structuredFromPayload(payload, [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 78.2, track_last_seen_seconds: 95.6, track_gap: 'stale' }),
    entry('E2', { track_gap: 'no frames from perception' }),
    entry('E3'),
  ]);
  const lines = entities.map((entity) => evidenceDetailLines(entityDetail(entity, [])));
  assert.equal(entities[1].evidence.trackGap, 'no frames from perception');
  assert.equal(lines[1].notTracked, 'Not tracked: no frames from perception');
  assert.equal(lines[0].notTracked, null, 'a track wins over a stale reason');
  assert.equal(lines[2].notTracked, null, 'an entry without a reason shows nothing');
});

test('a person whose box came from a track that fits the report seconds carries a "Matched by time" badge', () => {
  const { entities } = structuredFromPayload(payload, [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 21, track_last_seen_seconds: 47, box_source: 'track-time' }),
    entry('E2', { track: TRACK_KEY, track_first_seen_seconds: 21, track_last_seen_seconds: 47 }),
    entry('E3', { box_source: 'something-new' }),
  ]);
  const badges = entities.map((entity) => evidenceDetailLines(entityDetail(entity, [])).badges);
  assert.equal(entities[0].evidence.boxSource, 'track-time');
  assert.deepEqual(badges[0], ['Matched by time']);
  assert.equal(entities[1].evidence.boxSource, null, 'a detector box has no source');
  assert.equal(entities[2].evidence.boxSource, null, 'an unknown source is ignored');
  assert.deepEqual([badges[1], badges[2]], [[], []]);
});

test('only tracked items are drawn, each with its own colour in id order', () => {
  const structured = structuredFromPayload(payload, [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 78, track_last_seen_seconds: 95 }),
    entry('E2'),
    entry('E3', { track: TRACK_KEY.replace('E1', 'E3'), track_first_seen_seconds: 20, track_last_seen_seconds: 40 }),
  ]);
  for (const entity of structured.entities) if (entity.evidence?.track) entity.evidence.trackUrl = `/t/${entity.entityId}`;
  const items = trackedReportItems(structured);
  assert.deepEqual(
    items.map(({ id, colour, firstSeconds, lastSeconds, label }) => [id, colour, firstSeconds, lastSeconds, label]),
    [
      ['E1', trackColour(0), 78, 95, 'man in red'],
      ['E3', trackColour(1), 20, 40, 'woman'],
    ],
  );
  assert.notEqual(trackColour(0), trackColour(1));
});

test('the colour pool has ten distinct colours and the eleventh item reuses the first', () => {
  assert.equal(TRACK_COLOURS.length, 10);
  assert.equal(new Set(TRACK_COLOURS).size, 10);
  assert.deepEqual(
    Array.from({ length: 10 }, (_, i) => trackColour(i)),
    [...TRACK_COLOURS],
  );
  assert.equal(trackColour(10), trackColour(0));
});

test('a track label is the item name, falling back to its id only when it has no name', () => {
  const structured = structuredFromPayload(payload, [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 78, track_last_seen_seconds: 95 }),
  ]);
  structured.entities[0].evidence.trackUrl = '/t/E1';
  structured.entities[0].label = '';
  structured.entities[0].type = '';
  assert.equal(trackedReportItems(structured)[0].label, 'E1');
  structured.entities[0].label = 'man in red';
  assert.equal(trackedReportItems(structured)[0].label, 'man in red');
});

function trackedRecord() {
  const record = aiRunReport(smoke);
  record.evidence = [
    entry('E1', { track: TRACK_KEY, track_first_seen_seconds: 1, track_last_seen_seconds: 9 }),
    entry('E2', { track: 'uploads/v.mp4' }),
  ];
  const view = structuredFromPayload(record.payload, record.evidence);
  record.entities = view.entities;
  return record;
}

test('getReport points a tracked item at the console track route and leaves the others without one', async () => {
  const incidents = new InMemoryIncidentRepository([trackedRecord()]);
  const view = await getReport(incidents, smoke.videoId, null, async (key) => `https://signed/${key}`);
  const [e1, e2] = view.structured.entities;
  assert.equal(e1.evidence.trackUrl, evidenceTrackUrl(smoke.videoId, view.revisionId, 'entity', 'E1'));
  assert.match(e1.evidence.trackUrl, /^\/api\/reports\/[^?]+\/track\?revision=\d+&type=entity&item=E1$/);
  assert.equal(e2.evidence?.trackUrl ?? null, null);
});

test('the track use case reads only the key the revision names, and a malformed file is an empty track', async () => {
  const incidents = new InMemoryIncidentRepository([trackedRecord()]);
  const { revisionId } = (await incidents.getRevision(smoke.videoId, null)).revision;
  const read = [];
  const store = (body) => async (key) => {
    read.push(key);
    return body;
  };
  const request = { videoId: smoke.videoId, revisionId, itemType: 'entity', itemId: 'E1' };
  assert.deepEqual(await getEvidenceTrack(incidents, store([{ t: 1, box: [0, 0, 10, 10], score: 0.9 }]), request), [
    { t: 1, box: [0, 0, 10, 10] },
  ]);
  assert.deepEqual(read, [TRACK_KEY]);
  assert.deepEqual(await getEvidenceTrack(incidents, store({ not: 'a list' }), request), []);
  // A reviewer's track file is an object ({source, samples, span, ...}); it used to read back as empty.
  assert.deepEqual(
    await getEvidenceTrack(
      incidents,
      store({ source: 'reviewer', samples: [{ t: 2, box: [1, 2, 30, 40], conf: 0.8 }], span: [2, 2] }),
      request,
    ),
    [{ t: 2, box: [1, 2, 30, 40] }],
  );
  assert.deepEqual(await getEvidenceTrack(incidents, store({ source: 'reviewer', samples: 'x' }), request), []);
  assert.equal(await getEvidenceTrack(incidents, store([]), { ...request, itemId: 'E2' }), null, 'not a track key');
  assert.equal(await getEvidenceTrack(incidents, store([]), { ...request, itemId: 'E9' }), null);
  assert.equal(await getEvidenceTrack(incidents, store([]), { ...request, revisionId: revisionId + 50 }), null);
  assert.deepEqual(read, [TRACK_KEY, TRACK_KEY, TRACK_KEY, TRACK_KEY]);
});

// The draft the Edit mode overlay reads: an item's saved evidence is found through its source id.
const savedEvidence = (id, fields) => ({
  track: null,
  trackUrl: null,
  trackFirstSeenSeconds: null,
  trackLastSeenSeconds: null,
  located: true,
  boxSeconds: null,
  boundingBox: null,
  ...fields,
  id,
});
const tracked = (id) => savedEvidence(id, { track: `${id}.json`, trackUrl: `/t/${id}`, trackFirstSeenSeconds: 1, trackLastSeenSeconds: 9 });
const stored = (id) => savedEvidence(id, { boxSeconds: 4, boundingBox: [100, 100, 300, 300] });
const draftBase = {
  entities: [
    { entityId: 'E1', label: 'man', type: 'human', evidence: tracked('E1') },
    { entityId: 'E2', label: 'woman', type: 'human', evidence: stored('E2') },
  ],
  instruments: [{ instrumentId: 'I1', name: 'knife', evidence: tracked('I1') }],
  assets: [{ assetId: 'A1', name: 'car', evidence: tracked('A1') }],
};
const details = (key, sourceId, extra = {}) => ({ key, sourceId, reviewer: null, imagePick: null, ...extra });
const baseDraft = () => ({
  incident: {},
  entities: [
    { ...details('e1', 'E1'), label: 'man', type: 'human', canonicalId: 'E1' },
    { ...details('e2', 'E2'), label: 'woman', type: 'human', canonicalId: 'E2' },
  ],
  instruments: [{ ...details('i1', 'I1'), name: 'knife' }],
  assets: [{ ...details('a1', 'A1'), name: 'car' }],
});
const heldSamples = [{ t: 2, box: [10, 10, 200, 200] }];
const colours = (overlay) => Object.fromEntries(overlay.tracks.map((item) => [item.id, item.colour]));

test('an unchanged draft shows what the saved version shows, in the same colours', () => {
  const overlay = draftOverlay(baseDraft(), draftBase);
  assert.deepEqual(
    overlay.tracks.map(({ id, label, trackUrl, samples: own }) => [id, label, trackUrl, own]),
    [
      ['e1', 'man', '/t/E1', undefined],
      ['i1', 'knife', '/t/I1', undefined],
      ['a1', 'car', '/t/A1', undefined],
    ],
  );
  assert.deepEqual(
    overlay.tracks.map((item) => item.colour),
    trackedReportItems(draftBase).map((item) => item.colour),
  );
  assert.deepEqual(overlay.stills, [{ id: 'e2', label: 'woman', box: [100, 100, 300, 300], seconds: 4 }]);
});

test('a re-tracked item draws the samples held in the draft, and a still item that gains a track stops being a still', () => {
  const draft = baseDraft();
  draft.entities[0].reviewer = { track: { samples: heldSamples } };
  draft.entities[1].reviewer = { track: { samples: heldSamples } };
  const overlay = draftOverlay(draft, draftBase);
  assert.deepEqual(overlay.tracks[0].samples, heldSamples);
  assert.equal(overlay.tracks[0].trackUrl, null);
  assert.deepEqual(overlay.tracks[1].samples, heldSamples);
  assert.deepEqual(overlay.stills, []);
});

test('a reviewer still and a picked image move the stored box; a pick on a tracked item keeps its track', () => {
  const draft = baseDraft();
  draft.entities[0].reviewer = { track: null, stillSeconds: 7, stillBox: [1, 2, 30, 40] };
  draft.entities[1].imagePick = { seconds: 5.5, box: [5, 5, 50, 50] };
  draft.instruments[0].imagePick = { seconds: 6, box: [6, 6, 60, 60] };
  const overlay = draftOverlay(draft, draftBase);
  assert.deepEqual(
    overlay.stills.map(({ id, seconds, box }) => [id, seconds, box]),
    [
      ['e1', 7, [1, 2, 30, 40]],
      ['e2', 5.5, [5, 5, 50, 50]],
    ],
  );
  assert.deepEqual(
    overlay.tracks.map((item) => item.id),
    ['i1', 'a1'],
  );
});

test('a deleted item draws nothing, and an item with no box and no track draws nothing', () => {
  const draft = baseDraft();
  draft.assets = [];
  draft.entities = draft.entities.filter((entity) => entity.key !== 'e2');
  draft.instruments.push({ ...details('i2', null), name: '' });
  const overlay = draftOverlay(draft, draftBase);
  assert.deepEqual(
    overlay.tracks.map((item) => item.id),
    ['e1', 'i1'],
  );
  assert.deepEqual(overlay.stills, []);
});

test("a new item keeps other items' colours where it can: it joins the end of its kind, and only later kinds' tracks shift, as Save will store them", () => {
  const before = colours(draftOverlay(baseDraft(), draftBase));
  const reviewer = { track: { samples: heldSamples } };

  const withAsset = baseDraft();
  withAsset.assets.push({ ...details('a2', null), name: 'bag', reviewer });
  const afterAsset = colours(draftOverlay(withAsset, draftBase));
  assert.deepEqual({ ...afterAsset, a2: undefined }, { ...before, a2: undefined }, 'a new last item moves nobody');
  assert.equal(new Set(Object.values(afterAsset)).size, 4, 'and takes a colour of its own');

  const withStill = baseDraft();
  withStill.entities.push({
    ...details('e3', null),
    label: 'dog',
    type: 'animal',
    reviewer: { track: null, stillSeconds: 3, stillBox: [1, 1, 9, 9] },
  });
  assert.deepEqual(colours(draftOverlay(withStill, draftBase)), before, 'a new still takes no colour');

  const withEntity = baseDraft();
  withEntity.entities.push({ ...details('e3', null), label: 'dog', type: 'animal', reviewer });
  const afterEntity = colours(draftOverlay(withEntity, draftBase));
  assert.equal(afterEntity.e1, before.e1, 'an earlier item of its kind keeps its colour');
  assert.equal(afterEntity.e3, trackColour(1));
  assert.equal(afterEntity.i1, trackColour(2), 'a tracked item of a later kind takes the colour it will have once saved');
});

test('Edit mode feeds the overlay from the draft and hides the item whose Edit track dialog is open', async () => {
  const page = await readFile(new URL('../src/sections/reports/components/ReportPage/ReportPage.tsx', import.meta.url), 'utf8');
  assert.match(page, /draftOverlay\(draft, editBase\.report\.structured\)/);
  assert.match(page, /tracks\.filter\(\(item\) => item\.id !== editingTrackKey\)/);
  assert.match(page, /stills\.filter\(\(item\) => item\.id !== editingTrackKey\)/);
  assert.doesNotMatch(page, /mode === 'view' && !inPip/, 'the overlay is not View-only any more');
  assert.match(page, /onEditingTrack=\{setEditingTrackKey\}/);
});

// SPDX-License-Identifier: Apache-2.0

// Use cases tested against the in-memory fakes: no fetch, no PostgREST, no R2.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../lib/adapters/memory/incidents.ts');
const { InMemoryVideoRepository } = await import('../lib/adapters/memory/videos.ts');
const { StoreRejection } = await import('../lib/ports/index.ts');
const { deleteVideoAndReports, getReport, listRevisions, saveHumanEdit, setOfficialRevision, storeSearchableCrops } = await import('../lib/application/reports.ts');
const { aiRunReport } = await import('./support/report-view.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const V = smoke.videoId;
const withImage = (image) => {
  const record = aiRunReport(smoke);
  record.evidence = [{ item_type: 'entity', item_id: 'E1', image, bounding_box: [1, 2, 3, 4], timestamp_seconds: 2 }];
  record.entities[0].evidence = { image, imageUrl: null, boundingBox: [1, 2, 3, 4], timestampSeconds: 2, uploaded: false };
  return record;
};

/** The edit a reviewer makes in the form: the revision's items kept, severity lowered, E1 keeping the record's image. */
function editOf(record) {
  const details = (sourceId, image = null) => ({ source_id: sourceId, timestamp_seconds: 2, label: '', image });
  return {
    incident: { type: 'assault', start_timestamp: 1, end_timestamp: 11, description: 'Edited summary.', severity_level: 4 },
    entities: [{ entity_id: 'E1', type: 'human', description: 'A person.', ...details('E1', record.evidence[0]?.image ?? null) }],
    instruments: [],
    assets: [{ asset_id: 'A1', name: 'white van', description: 'A van.', ...details('A1') }],
  };
}

test('getReport signs the stored video key and the item images, and refuses a revision without a video object', async () => {
  const incidents = new InMemoryIncidentRepository([withImage('evidence/v/u/E1.jpg')]);
  const signed = [];
  const view = await getReport(incidents, V, null, async (key) => { signed.push(key); return `https://signed/${key}`; });
  assert.deepEqual(signed.sort(), ['evidence/v/u/E1.jpg', smoke.video.filepath].sort());
  assert.equal(view.run.playbackUrl, `https://signed/${smoke.video.filepath}`);
  assert.equal(view.structured.entities[0].evidence.imageUrl, 'https://signed/evidence/v/u/E1.jpg');
  assert.equal(await getReport(incidents, V, 99, async () => 'unused'), null);
  assert.equal(await getReport(incidents, 'v-none', null, async () => 'unused'), null);

  const noVideo = new InMemoryIncidentRepository([aiRunReport({ ...smoke, video: { ...smoke.video, filepath: '' } })]);
  await assert.rejects(getReport(noVideo, V, null, async () => 'unused'), /The report has no linked R2 video/);
});

test('an image that cannot be signed is shown as missing, not as an error', async () => {
  const incidents = new InMemoryIncidentRepository([withImage('evidence/v/u/E1.jpg')]);
  const view = await getReport(incidents, V, 1, async (key) => { if (key.startsWith('evidence/')) throw new Error('gone'); return 'https://signed/video'; });
  assert.equal(view.structured.entities[0].evidence.imageUrl, null);
});

test('saving an edit appends a human revision whose parent is the opened one; the History lists both', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const incidents = new InMemoryIncidentRepository([record]);
  const saved = await saveHumanEdit(incidents, { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor', note: ' tweaked ' });
  assert.deepEqual([saved.revisionNo, saved.kind, saved.parentId, saved.createdBy, saved.note], [2, 'human', 1, 'Editor', 'tweaked']);
  const stored = await incidents.getRevision(V, 2);
  assert.equal(stored.incident.severityLevel, 4);
  assert.deepEqual(stored.evidence.map((entry) => [entry.item_id, entry.image, entry.bounding_box]), [['E1', 'evidence/v/u/E1.jpg', [1, 2, 3, 4]]], 'the crop details follow the unchanged image');
  assert.deepEqual((await listRevisions(incidents, V)).map((row) => row.revisionNo), [2, 1]);
  assert.equal((await incidents.getRevision(V, 1)).incident.severityLevel, 2, 'the opened revision is untouched');
});

test('a replaced image is a new upload entry; an image from another video is refused', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const incidents = new InMemoryIncidentRepository([record]);
  const replaced = editOf(record);
  replaced.entities[0].image = `evidence/${V}/new-uuid/E1.jpg`;
  await saveHumanEdit(incidents, { videoId: V, parentId: 1, edit: replaced, createdBy: 'Editor' });
  const [entry] = (await incidents.getRevision(V, 2)).evidence;
  assert.deepEqual([entry.image, entry.source, entry.bounding_box], [`evidence/${V}/new-uuid/E1.jpg`, 'upload', null]);

  const foreign = editOf(record);
  foreign.entities[0].image = 'evidence/other-video/u/E1.jpg';
  await assert.rejects(saveHumanEdit(incidents, { videoId: V, parentId: 1, edit: foreign, createdBy: 'Editor' }), (error) => error instanceof StoreRejection && error.reason === 'invalid');
  assert.equal((await listRevisions(incidents, V)).length, 2);
});

test('saving against a missing revision is a not-found rejection', async () => {
  const incidents = new InMemoryIncidentRepository([aiRunReport(smoke)]);
  await assert.rejects(saveHumanEdit(incidents, { videoId: V, parentId: 7, edit: editOf(aiRunReport(smoke)), createdBy: 'Editor' }), (error) => error instanceof StoreRejection && error.reason === 'not-found');
});

function official(revisionRecords) {
  const incidents = new InMemoryIncidentRepository(revisionRecords);
  const videos = new InMemoryVideoRepository([{ videoId: V, storageKey: smoke.video.filepath, uploadedAt: null, source: null, officialRevisionId: null, revisionIds: revisionRecords.map((r) => r.revision.revisionId) }]);
  return { incidents, videos };
}

test('marking official embeds the revision evidence through the agent and hands the vectors to the store', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  const asked = [];
  const embedding = { itemType: 'entity', itemId: 'E1', embedding: [0.5] };
  assert.deepEqual(await setOfficialRevision(ports, V, 1, async (id) => { asked.push(id); return [embedding]; }), { videoId: V, officialRevisionId: 1, crops: 1 });
  assert.deepEqual(asked, [1]);
  assert.deepEqual(ports.videos.officialCalls.map((call) => [call.videoId, call.revisionId, call.crops]), [[V, 1, [{
    item_type: 'entity', item_id: 'E1', image: 'evidence/v/u/E1.jpg', bounding_box: [1, 2, 3, 4], timestamp_seconds: 2,
    item_name: 'human', description: 'A person wearing dark clothing and carrying a bag, walking on the sidewalk.',
    threat_level: null, holder_entity_id: null, embedding: [0.5],
  }]]]);
});

test('a revision with no images is marked official without calling the agent; clearing never calls it', async () => {
  const ports = official([aiRunReport(smoke)]);
  const embed = async () => assert.fail('nothing to embed');
  assert.equal((await setOfficialRevision(ports, V, 1, embed)).crops, 0);
  assert.equal((await setOfficialRevision(ports, V, null, embed)).officialRevisionId, null);
});

test('an agent failure leaves the previous official revision in place', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  await assert.rejects(setOfficialRevision(ports, V, 1, async () => { throw new Error('agent down'); }), /agent down/);
  assert.equal((await ports.videos.getVideo(V)).officialRevisionId, null);
  assert.deepEqual(ports.videos.officialCalls, []);
  await assert.rejects(setOfficialRevision(ports, V, 9, async () => []), (error) => error instanceof StoreRejection && error.reason === 'not-found');
});

test('a new revision of a video with no official revision gets its crops from the agent embeddings', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  const asked = [];
  const embedding = { itemType: 'entity', itemId: 'E1', embedding: [0.5] };
  assert.deepEqual(await storeSearchableCrops(ports, V, 1, async (id) => { asked.push(id); return [embedding]; }), { crops: 1 });
  assert.deepEqual(asked, [1]);
  assert.deepEqual(ports.videos.cropCalls.map((call) => [call.videoId, call.revisionId, call.crops.map((crop) => [crop.item_id, crop.image, crop.embedding])]), [[V, 1, [['E1', 'evidence/v/u/E1.jpg', [0.5]]]]]);
  assert.equal((await ports.videos.getVideo(V)).officialRevisionId, null, 'the official pointer is not changed');
  assert.deepEqual(ports.videos.officialCalls, []);
});

test('a new revision with no images clears the crops without calling the agent', async () => {
  const ports = official([aiRunReport(smoke)]);
  assert.deepEqual(await storeSearchableCrops(ports, V, 1, async () => assert.fail('nothing to embed')), { crops: 0 });
  assert.deepEqual(ports.videos.cropCalls.map((call) => call.crops), [[]]);
});

test('an official revision stays the searched one, so a new revision stores no crops', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  await ports.videos.setOfficialRevision(V, 1, []);
  assert.deepEqual(await storeSearchableCrops(ports, V, 1, async () => assert.fail('official crops are untouched')), { crops: null });
  assert.deepEqual(ports.videos.cropCalls, []);
});

test('a crops failure is returned, not thrown, because the revision is already saved', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  const log = mock.method(console, 'error', () => {});
  try {
    assert.deepEqual(await storeSearchableCrops(ports, V, 1, async () => { throw new Error('agent down'); }), { crops: null, error: 'agent down' });
    assert.match(log.mock.calls[0].arguments[0], /agent down/);
  } finally {
    log.mock.restore();
  }
  assert.deepEqual(ports.videos.cropCalls, []);
  assert.deepEqual(await storeSearchableCrops(ports, 'v-none', 1, async () => []), { crops: null }, 'an unknown video is skipped');
});

test('deleting a video removes its stored objects before the video row', async () => {
  const { videos } = official([aiRunReport(smoke)]);
  const removed = [];
  await deleteVideoAndReports(videos, V, async (storageKey) => {
    removed.push({ storageKey, videoStillStored: Boolean(await videos.getVideo(V)) });
  });
  assert.deepEqual(removed, [{ storageKey: smoke.video.filepath, videoStillStored: true }]);
  assert.equal(await videos.getVideo(V), null);
});

test('a video without a stored object is refused and nothing is deleted', async () => {
  const videos = new InMemoryVideoRepository([{ videoId: V, storageKey: null, uploadedAt: null, source: null, officialRevisionId: null, revisionIds: [] }]);
  await assert.rejects(deleteVideoAndReports(videos, V, async () => assert.fail('nothing to remove')), /Video has no R2 object key/);
  assert.notEqual(await videos.getVideo(V), null);
  await assert.rejects(deleteVideoAndReports(videos, 'v-none', async () => undefined), /Video has no R2 object key/);
});

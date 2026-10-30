// SPDX-License-Identifier: Apache-2.0

// Use cases tested against the in-memory fakes: no fetch, no PostgREST, no R2.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { mock, test } from 'node:test';

register('../../../../tests/support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../../../../src/modules/reports/infrastructure/memory/incidents.ts');
const { InMemoryVideoRepository } = await import('../../../../src/modules/videos/infrastructure/memory/videos.ts');
const { StoreRejection } = await import('../../../../src/modules/shared/domain/common.ts');
const { getReport } = await import('@/modules/reports/application/get-report');
const { listRevisions } = await import('@/modules/reports/application/list-revisions');
const { saveHumanEdit, SearchableStepError } = await import('@/modules/reports/application/save-human-edit');
const { setOfficialRevision } = await import('@/modules/reports/application/set-official-revision');
const { storeSearchableCrops } = await import('@/modules/reports/application/store-searchable-crops');
const { deleteVideoAndReports } = await import('@/modules/reports/application/delete-video-and-reports');
const { aiRunReport } = await import('../../../../tests/support/report-view.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const V = smoke.videoId;
const K = smoke.video.filepath;
const withImage = (image) => {
  const record = aiRunReport(smoke);
  record.evidence = [{ item_type: 'entity', item_id: 'E1', image, bounding_box: [1, 2, 3, 4], timestamp_seconds: 2 }];
  record.entities[0].evidence = { image, imageUrl: null, boundingBox: [1, 2, 3, 4], timestampSeconds: 2, uploaded: false };
  return record;
};

/** Embeds each evidence entry with a fixed vector, as the agent would. */
const fakeEmbeddings = async (evidence) =>
  evidence.map((entry) => ({ itemType: entry.item_type, itemId: entry.item_id, embedding: [0.5] }));
const noEmbed = async () => assert.fail('nothing to embed');

/** The edit a reviewer makes in the form: the revision's items kept, severity lowered, E1 keeping the record's image. */
function editOf(record) {
  const details = (sourceId, image = null) => ({ source_id: sourceId, timestamp_seconds: 2, label: '', image });
  return {
    incident: { type: 'assault', start_timestamp: 1, end_timestamp: 11, description: 'Edited summary.', severity_level: 4 },
    entities: [
      {
        entity_id: 'E1',
        type: 'human',
        description: 'A person.',
        first_seen_seconds: 1,
        last_seen_seconds: 3,
        ...details('E1', record.evidence[0]?.image ?? null),
      },
    ],
    instruments: [],
    assets: [{ asset_id: 'A1', name: 'white van', description: 'A van.', ...details('A1') }],
  };
}

test('getReport signs the stored video key and the item images, and refuses a revision without a video object', async () => {
  const incidents = new InMemoryIncidentRepository([withImage('evidence/v/u/E1.jpg')]);
  const signed = [];
  const view = await getReport(incidents, V, null, async (key) => {
    signed.push(key);
    return `https://signed/${key}`;
  });
  assert.deepEqual(signed.sort(), ['evidence/v/u/E1.jpg', smoke.video.filepath].sort());
  assert.equal(view.run.playbackUrl, `https://signed/${smoke.video.filepath}`);
  assert.equal(view.structured.entities[0].evidence.imageUrl, 'https://signed/evidence/v/u/E1.jpg');
  assert.equal(await getReport(incidents, V, 99, async () => 'unused'), null);
  assert.equal(await getReport(incidents, 'v-none', null, async () => 'unused'), null);

  const noVideo = new InMemoryIncidentRepository([aiRunReport({ ...smoke, video: { ...smoke.video, filepath: '' } })]);
  await assert.rejects(
    getReport(noVideo, V, null, async () => 'unused'),
    /The report has no linked R2 video/,
  );
});

test('an image that cannot be signed is shown as missing, not as an error', async () => {
  const incidents = new InMemoryIncidentRepository([withImage('evidence/v/u/E1.jpg')]);
  const view = await getReport(incidents, V, 1, async (key) => {
    if (key.startsWith('evidence/')) throw new Error('gone');
    return 'https://signed/video';
  });
  assert.equal(view.structured.entities[0].evidence.imageUrl, null);
});

test('saving an edit appends a human revision whose parent is the opened one; the History lists both', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const ports = official([record]);
  const { incidents } = ports;
  const saved = await saveHumanEdit(
    ports,
    { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor', note: ' tweaked ' },
    fakeEmbeddings,
  );
  assert.deepEqual(
    incidents.saved.at(-1).crops.map((crop) => crop.item_id),
    ['E1'],
    'the crops are written with the revision',
  );
  assert.deepEqual([saved.revisionNo, saved.kind, saved.parentId, saved.createdBy, saved.note], [2, 'human', 1, 'Editor', 'tweaked']);
  const stored = await incidents.getRevision(V, 2);
  assert.equal(stored.incident.severityLevel, 4);
  assert.deepEqual(
    stored.evidence.map((entry) => [entry.item_id, entry.image, entry.bounding_box]),
    [['E1', 'evidence/v/u/E1.jpg', [1, 2, 3, 4]]],
    'the crop details follow the unchanged image',
  );
  assert.deepEqual(
    (await listRevisions(incidents, V)).map((row) => row.revisionNo),
    [2, 1],
  );
  assert.equal((await incidents.getRevision(V, 1)).incident.severityLevel, 2, 'the opened revision is untouched');
});

test('a replaced image is a new upload entry; an image from another video is refused', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const ports = official([record]);
  const { incidents } = ports;
  const replaced = editOf(record);
  replaced.entities[0].image = `evidence/${K}/edit-1/E1.jpg`;
  await saveHumanEdit(ports, { videoId: V, parentId: 1, edit: replaced, createdBy: 'Editor' }, fakeEmbeddings);
  const [entry] = (await incidents.getRevision(V, 2)).evidence;
  assert.deepEqual([entry.image, entry.source, entry.bounding_box], [`evidence/${K}/edit-1/E1.jpg`, 'upload', null]);

  const foreign = editOf(record);
  foreign.entities[0].image = 'evidence/other-video/u/E1.jpg';
  await assert.rejects(
    saveHumanEdit(ports, { videoId: V, parentId: 1, edit: foreign, createdBy: 'Editor' }, noEmbed),
    (error) => error instanceof StoreRejection && error.reason === 'invalid',
  );
  assert.equal((await listRevisions(incidents, V)).length, 2);
});

test('saving against a missing revision is a not-found rejection', async () => {
  const ports = official([aiRunReport(smoke)]);
  await assert.rejects(
    saveHumanEdit(ports, { videoId: V, parentId: 7, edit: editOf(aiRunReport(smoke)), createdBy: 'Editor' }, noEmbed),
    (error) => error instanceof StoreRejection && error.reason === 'not-found',
  );
});

function official(revisionRecords) {
  const incidents = new InMemoryIncidentRepository(revisionRecords);
  const videos = new InMemoryVideoRepository([
    {
      videoId: V,
      storageKey: smoke.video.filepath,
      uploadedAt: null,
      source: null,
      officialRevisionId: null,
      revisionIds: revisionRecords.map((r) => r.revision.revisionId),
    },
  ]);
  return { incidents, videos };
}

test('marking official embeds the revision evidence through the agent and hands the vectors to the store', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  const asked = [];
  const embedding = { itemType: 'entity', itemId: 'E1', embedding: [0.5] };
  assert.deepEqual(
    await setOfficialRevision(ports, V, 1, async (id) => {
      asked.push(id);
      return [embedding];
    }),
    { videoId: V, officialRevisionId: 1, crops: 1 },
  );
  assert.deepEqual(asked, [1]);
  assert.deepEqual(
    ports.videos.officialCalls.map((call) => [call.videoId, call.revisionId, call.crops]),
    [
      [
        V,
        1,
        [
          {
            item_type: 'entity',
            item_id: 'E1',
            image: 'evidence/v/u/E1.jpg',
            bounding_box: [1, 2, 3, 4],
            timestamp_seconds: 2,
            item_name: 'human',
            description: 'A person wearing dark clothing and carrying a bag, walking on the sidewalk.',
            threat_level: null,
            holder_entity_id: null,
            embedding: [0.5],
          },
        ],
      ],
    ],
  );
});

test('a revision with no images is marked official without calling the agent; clearing never calls it', async () => {
  const ports = official([aiRunReport(smoke)]);
  const embed = async () => assert.fail('nothing to embed');
  assert.equal((await setOfficialRevision(ports, V, 1, embed)).crops, 0);
  assert.equal((await setOfficialRevision(ports, V, null, embed)).officialRevisionId, null);
});

test('an agent failure leaves the previous official revision in place', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  await assert.rejects(
    setOfficialRevision(ports, V, 1, async () => {
      throw new Error('agent down');
    }),
    /agent down/,
  );
  assert.equal((await ports.videos.getVideo(V)).officialRevisionId, null);
  assert.deepEqual(ports.videos.officialCalls, []);
  await assert.rejects(
    setOfficialRevision(ports, V, 9, async () => []),
    (error) => error instanceof StoreRejection && error.reason === 'not-found',
  );
});

test('a new revision of a video with no official revision gets its crops from the agent embeddings', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  const asked = [];
  const embedding = { itemType: 'entity', itemId: 'E1', embedding: [0.5] };
  assert.deepEqual(
    await storeSearchableCrops(ports, V, 1, async (id) => {
      asked.push(id);
      return [embedding];
    }),
    { crops: 1 },
  );
  assert.deepEqual(asked, [1]);
  assert.deepEqual(
    ports.videos.cropCalls.map((call) => [
      call.videoId,
      call.revisionId,
      call.crops.map((crop) => [crop.item_id, crop.image, crop.embedding]),
    ]),
    [[V, 1, [['E1', 'evidence/v/u/E1.jpg', [0.5]]]]],
  );
  assert.equal((await ports.videos.getVideo(V)).officialRevisionId, null, 'the official pointer is not changed');
  assert.deepEqual(ports.videos.officialCalls, []);
});

test('a new revision with no images clears the crops without calling the agent', async () => {
  const ports = official([aiRunReport(smoke)]);
  assert.deepEqual(await storeSearchableCrops(ports, V, 1, async () => assert.fail('nothing to embed')), { crops: 0 });
  assert.deepEqual(
    ports.videos.cropCalls.map((call) => call.crops),
    [[]],
  );
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
    assert.deepEqual(
      await storeSearchableCrops(ports, V, 1, async () => {
        throw new Error('agent down');
      }),
      { crops: null, error: 'agent down' },
    );
    assert.match(log.mock.calls[0].arguments[0], /agent down/);
  } finally {
    log.mock.restore();
  }
  assert.deepEqual(ports.videos.cropCalls, []);
  assert.deepEqual(await storeSearchableCrops(ports, 'v-none', 1, async () => []), { crops: null }, 'an unknown video is skipped');
});

/** An in-memory EvidenceObjectStore that records each removal and whether the video row still existed. */
function evidenceStore(keys, videos, { failing = [] } = {}) {
  const removed = [];
  return {
    removed,
    async list(prefix) {
      return keys.filter((key) => key.startsWith(prefix)).map((key) => ({ key, lastModified: null }));
    },
    async remove(key) {
      if (failing.includes(key)) throw new Error('R2 refused');
      removed.push({ key, videoStillStored: Boolean(await videos.getVideo(V)) });
    },
  };
}

/** A RemoveVstSensor that records each call and whether the video row still existed. */
const noCamera = async () => undefined;

test('deleting a video removes its VST camera before its stored objects, and both before the video row', async () => {
  const { videos } = official([aiRunReport(smoke)]);
  const evidence = evidenceStore([`evidence/${K}/run-u1/E1.jpg`], videos);
  const order = [];
  await deleteVideoAndReports(
    videos,
    evidence,
    V,
    async (storageKey) => order.push({ step: 'objects', storageKey }),
    async (camera) => order.push({ step: 'camera', ...camera, videoStillStored: Boolean(await videos.getVideo(V)) }),
  );
  assert.deepEqual(order, [
    { step: 'camera', videoId: V, sensorId: null, fileName: K.split('/').pop(), videoStillStored: true },
    { step: 'objects', storageKey: K },
  ]);
  assert.deepEqual(evidence.removed, [{ key: `evidence/${K}/run-u1/E1.jpg`, videoStillStored: true }]);
  assert.equal(await videos.getVideo(V), null);
});

test('a stored sensor id is passed to the camera removal, and a VST failure stops the delete before anything is gone', async () => {
  const videos = new InMemoryVideoRepository([
    { videoId: V, storageKey: K, uploadedAt: null, source: 'sensor-1', officialRevisionId: null, revisionIds: [] },
  ]);
  const evidence = evidenceStore([`evidence/${K}/run-u1/E1.jpg`], videos);
  const cameras = [];
  await assert.rejects(
    deleteVideoAndReports(
      videos,
      evidence,
      V,
      async () => assert.fail('no object is removed when the camera stays'),
      async (camera) => {
        cameras.push(camera);
        throw new Error('VST sensor delete returned HTTP 503');
      },
    ),
    /VST sensor delete returned HTTP 503/,
  );
  assert.deepEqual(cameras, [{ videoId: V, sensorId: 'sensor-1', fileName: K.split('/').pop() }]);
  assert.deepEqual(evidence.removed, []);
  assert.notEqual(await videos.getVideo(V), null, 'the row stays as the handle for a retry');
});

test('deleting a video removes its stored objects and evidence images before the video row', async () => {
  const { videos } = official([aiRunReport(smoke)]);
  const evidence = evidenceStore([`evidence/${K}/run-u1/E1.jpg`, `evidence/${K}/run-u2/A1.jpg`, `evidence/${K}2/u3/E1.jpg`], videos);
  const removed = [];
  await deleteVideoAndReports(
    videos,
    evidence,
    V,
    async (storageKey) => {
      removed.push({ storageKey, videoStillStored: Boolean(await videos.getVideo(V)) });
    },
    noCamera,
  );
  assert.deepEqual(removed, [{ storageKey: smoke.video.filepath, videoStillStored: true }]);
  assert.deepEqual(evidence.removed, [
    { key: `evidence/${K}/run-u1/E1.jpg`, videoStillStored: true },
    { key: `evidence/${K}/run-u2/A1.jpg`, videoStillStored: true },
  ]);
  assert.equal(await videos.getVideo(V), null);
});

test('a failed evidence removal or listing keeps the video row', async () => {
  const { videos } = official([aiRunReport(smoke)]);
  const evidence = evidenceStore([`evidence/${K}/run-u1/E1.jpg`, `evidence/${K}/run-u2/A1.jpg`], videos, {
    failing: [`evidence/${K}/run-u1/E1.jpg`],
  });
  await assert.rejects(
    deleteVideoAndReports(videos, evidence, V, async () => undefined, noCamera),
    /Could not remove 1 of 2 evidence images, so the video was kept/,
  );
  assert.deepEqual(
    evidence.removed.map(({ key }) => key),
    [`evidence/${K}/run-u2/A1.jpg`],
  );
  assert.notEqual(await videos.getVideo(V), null);

  const unlistable = {
    list: async () => {
      throw new Error('R2 listing was cut short');
    },
    remove: async () => assert.fail('nothing listed'),
  };
  await assert.rejects(
    deleteVideoAndReports(videos, unlistable, V, async () => undefined, noCamera),
    /R2 listing was cut short/,
  );
  assert.notEqual(await videos.getVideo(V), null);
});

test('a delete that failed part-way can be repeated until the video and all its images are gone', async () => {
  const { videos } = official([aiRunReport(smoke)]);
  // An object store that forgets what it removed, refuses one key once, and treats an absent key as removed (as R2 does).
  const stored = new Set([`evidence/${K}/run-u1/E1.jpg`, `evidence/${K}/run-u2/A1.jpg`, `evidence/${K}/run-u3/I1.jpg`]);
  const refuseOnce = new Set([`evidence/${K}/run-u2/A1.jpg`]);
  const evidence = {
    async list(prefix) {
      return [...stored].filter((key) => key.startsWith(prefix)).map((key) => ({ key, lastModified: null }));
    },
    async remove(key) {
      if (refuseOnce.delete(key)) throw new Error('R2 refused');
      stored.delete(key);
    },
  };
  const videoRemovals = [];
  const removeStoredVideo = async (storageKey) => videoRemovals.push(storageKey);

  await assert.rejects(deleteVideoAndReports(videos, evidence, V, removeStoredVideo, noCamera), /Could not remove 1 of 3 evidence images/);
  assert.deepEqual([...stored], [`evidence/${K}/run-u2/A1.jpg`], 'the other images were removed');
  assert.notEqual(await videos.getVideo(V), null, 'the row stays as the handle for a retry');

  await deleteVideoAndReports(videos, evidence, V, removeStoredVideo, noCamera);
  assert.deepEqual([...stored], []);
  assert.equal(await videos.getVideo(V), null);
  assert.deepEqual(videoRemovals, [smoke.video.filepath, smoke.video.filepath], 'removing the already-removed video again is harmless');
});

test('a video without a stored object is refused and nothing is deleted', async () => {
  const videos = new InMemoryVideoRepository([
    { videoId: V, storageKey: null, uploadedAt: null, source: null, officialRevisionId: null, revisionIds: [] },
  ]);
  const evidence = evidenceStore([`evidence/${K}/run-u1/E1.jpg`], videos);
  await assert.rejects(
    deleteVideoAndReports(
      videos,
      evidence,
      V,
      async () => assert.fail('nothing to remove'),
      async () => assert.fail('no camera to remove'),
    ),
    /Video has no R2 object key/,
  );
  assert.deepEqual(evidence.removed, []);
  assert.notEqual(await videos.getVideo(V), null);
  await assert.rejects(
    deleteVideoAndReports(videos, evidence, 'v-none', async () => undefined, noCamera),
    /Video has no R2 object key/,
  );
});

test("a saved human revision keeps each entity's first and last seen, and a drawn image keeps its second and box", async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const ports = official([record]);
  const { incidents } = ports;
  const edit = editOf(record);
  Object.assign(edit.entities[0], {
    first_seen_seconds: 2,
    last_seen_seconds: 5,
    image: `evidence/${K}/edit-1/E1.jpg`,
    image_timestamp_seconds: 3,
    image_box: [100, 200, 300, 400],
  });
  await saveHumanEdit(ports, { videoId: V, parentId: 1, edit, createdBy: 'Editor' }, fakeEmbeddings);
  const stored = await incidents.getRevision(V, 2);
  assert.deepEqual(
    stored.payload.entities.map((e) => [e.first_seen_seconds, e.last_seen_seconds]),
    [[2, 5]],
  );
  assert.ok(
    !('image_box' in stored.payload.entities[0]) && !('image_timestamp_seconds' in stored.payload.entities[0]),
    'the crop details live in evidence only',
  );
  assert.deepEqual(
    stored.evidence.map((e) => [e.source, e.timestamp_seconds, e.bounding_box]),
    [['upload', 3, [100, 200, 300, 400]]],
  );
});

test('a saved item missing a contract v4 required field is rejected before anything is written', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const ports = official([record]);
  const edit = editOf(record);
  delete edit.entities[0].last_seen_seconds;
  await assert.rejects(
    saveHumanEdit(ports, { videoId: V, parentId: 1, edit, createdBy: 'Editor' }, noEmbed),
    (error) => error instanceof StoreRejection && error.reason === 'invalid' && /last_seen_seconds/.test(error.message),
  );
  assert.equal((await listRevisions(ports.incidents, V)).length, 1);
});

test('an embedding failure stops the save: no revision is written and the reviewer is told why', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const ports = official([record]);
  await assert.rejects(
    saveHumanEdit(ports, { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor' }, async () => {
      throw new Error('agent down');
    }),
    (error) => error instanceof SearchableStepError && /agent down/.test(error.message) && /Try Save again/.test(error.message),
  );
  assert.deepEqual(
    (await listRevisions(ports.incidents, V)).map((row) => row.revisionNo),
    [1],
    'the revision was not written',
  );
  assert.deepEqual(ports.incidents.saved, []);
});

test('a video with an official revision saves without embedding and passes no crops', async () => {
  const record = withImage('evidence/v/u/E1.jpg');
  const ports = official([record]);
  await ports.videos.setOfficialRevision(V, 1, []);
  await saveHumanEdit(ports, { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor' }, noEmbed);
  assert.deepEqual(
    ports.incidents.saved.map((input) => input.crops),
    [[]],
  );
});

test('a revision with no images is saved without calling the agent, and clears the searchable crops', async () => {
  const ports = official([aiRunReport(smoke)]);
  await saveHumanEdit(ports, { videoId: V, parentId: 1, edit: editOf(aiRunReport(smoke)), createdBy: 'Editor' }, noEmbed);
  assert.deepEqual(
    ports.incidents.saved.map((input) => input.crops),
    [[]],
  );
});

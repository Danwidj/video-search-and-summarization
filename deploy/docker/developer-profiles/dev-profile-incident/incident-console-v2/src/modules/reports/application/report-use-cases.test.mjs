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
const { repairMissingCrops } = await import('@/modules/reports/application/repair-missing-crops');
const { repairMissingEmbeddings } = await import('@/modules/reports/application/repair-missing-embeddings');
const { officialCrops, evidenceSlice } = await import('@/modules/reports/domain/revision');
const { confirmedSpans } = await import('@/modules/reports/application/confirmed-spans');
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
    incident: {
      type: 'assault',
      start_timestamp: 1,
      end_timestamp: 11,
      description: 'Edited summary.',
      severity_level: 4,
      severity_reason: 'Edited rationale.',
    },
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
            slice_start_seconds: 0,
            slice_end_seconds: 5,
            frame: null,
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

test('deleting a video removes its stored objects and evidence images before the video row', async () => {
  const { videos } = official([aiRunReport(smoke)]);
  const evidence = evidenceStore([`evidence/${K}/run-u1/E1.jpg`, `evidence/${K}/run-u2/A1.jpg`, `evidence/${K}2/u3/E1.jpg`], videos);
  const removed = [];
  await deleteVideoAndReports(videos, evidence, V, async (storageKey) => {
    removed.push({ storageKey, videoStillStored: Boolean(await videos.getVideo(V)) });
  });
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
    deleteVideoAndReports(videos, evidence, V, async () => undefined),
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
    deleteVideoAndReports(videos, unlistable, V, async () => undefined),
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

  await assert.rejects(deleteVideoAndReports(videos, evidence, V, removeStoredVideo), /Could not remove 1 of 3 evidence images/);
  assert.deepEqual([...stored], [`evidence/${K}/run-u2/A1.jpg`], 'the other images were removed');
  assert.notEqual(await videos.getVideo(V), null, 'the row stays as the handle for a retry');

  await deleteVideoAndReports(videos, evidence, V, removeStoredVideo);
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
    deleteVideoAndReports(videos, evidence, V, async () => assert.fail('nothing to remove')),
    /Video has no R2 object key/,
  );
  assert.deepEqual(evidence.removed, []);
  assert.notEqual(await videos.getVideo(V), null);
  await assert.rejects(
    deleteVideoAndReports(videos, evidence, 'v-none', async () => undefined),
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

test('repair stores the crops of a searchable revision that has none, official or not, and a dry run stores nothing', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  ports.videos.missingCrops = [{ videoId: V, revisionId: 1 }];
  const embedding = { itemType: 'entity', itemId: 'E1', embedding: [0.5] };
  const dry = await repairMissingCrops(ports, async () => assert.fail('a dry run does not embed'));
  assert.deepEqual(dry, { dryRun: true, revisions: [{ videoId: V, revisionId: 1, crops: null }] });
  assert.deepEqual(ports.videos.cropCalls, []);
  const report = await repairMissingCrops(ports, async () => [embedding], { dryRun: false });
  assert.deepEqual(report, { dryRun: false, revisions: [{ videoId: V, revisionId: 1, crops: 1 }] });
  assert.deepEqual(
    ports.videos.cropCalls.map((call) => [call.videoId, call.revisionId, call.crops.map((crop) => crop.item_id)]),
    [[V, 1, ['E1']]],
  );
  assert.deepEqual(await repairMissingCrops(ports, async () => [], { videoId: 'other', dryRun: false }), { dryRun: false, revisions: [] });
});

test('repair reports a failing revision and carries on with the rest', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  ports.videos.missingCrops = [
    { videoId: V, revisionId: 9 },
    { videoId: V, revisionId: 1 },
  ];
  const report = await repairMissingCrops(ports, async () => [{ itemType: 'entity', itemId: 'E1', embedding: [0.5] }], { dryRun: false });
  assert.deepEqual(report.revisions, [
    { videoId: V, revisionId: 9, crops: null, error: 'Revision not found' },
    { videoId: V, revisionId: 1, crops: 1 },
  ]);
});

test('a human Save stores the summary vector of the new title and description, and saves without one when embedding fails', async () => {
  const record = aiRunReport(smoke);
  const asked = [];
  const embedSummary = async (summary) => {
    asked.push(summary);
    return [0.25, 0.5];
  };
  const ports = official([record]);
  await saveHumanEdit(
    ports,
    { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor' },
    noEmbed,
    undefined,
    undefined,
    embedSummary,
  );
  assert.deepEqual(
    ports.incidents.saved.map((input) => input.embedding),
    [[0.25, 0.5]],
  );
  assert.equal(asked[0].description, 'Edited summary.', 'the text is the saved incident description');
  assert.equal(asked[0].incidentType, 'assault', 'the incident type goes with it');

  const down = official([record]);
  await saveHumanEdit(
    down,
    { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor' },
    noEmbed,
    undefined,
    undefined,
    async () => {
      throw new Error('agent down');
    },
  );
  assert.deepEqual(
    down.incidents.saved.map((input) => input.embedding),
    [null],
    'the Save still succeeds, with no vector',
  );

  const plain = official([record]);
  await saveHumanEdit(plain, { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor' }, noEmbed);
  assert.deepEqual(
    plain.incidents.saved.map((input) => input.embedding),
    [null],
    'no embedding seam, no vector',
  );
});

test('a Save on a video with an official revision does not embed the summary of a version that is not searchable', async () => {
  const record = aiRunReport(smoke);
  const ports = official([record]);
  await ports.videos.setOfficialRevision(V, 1, []);
  await saveHumanEdit(
    ports,
    { videoId: V, parentId: 1, edit: editOf(record), createdBy: 'Editor' },
    noEmbed,
    undefined,
    undefined,
    async () => assert.fail('not searchable, nothing to embed'),
  );
  assert.deepEqual(
    ports.incidents.saved.map((input) => input.embedding),
    [null],
  );
});

test('repair skips a revision that is no longer the searchable one or already has crops, and writes nothing', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  ports.videos.missingCrops = [{ videoId: V, revisionId: 1 }];
  await ports.videos.setOfficialRevision(V, null, []);
  ports.videos.missingCrops = [{ videoId: V, revisionId: 1 }];
  ports.videos.videos.get(V).revisionIds.push(2); // a newer version was saved meanwhile: revision 1 is not searchable
  const report = await repairMissingCrops(ports, async () => [{ itemType: 'entity', itemId: 'E1', embedding: [0.5] }], { dryRun: false });
  assert.deepEqual(report.revisions, [{ videoId: V, revisionId: 1, crops: null, skipped: true }]);
  assert.deepEqual(ports.videos.cropCalls, []);
});

test('summary repair embeds the title and description of a searchable revision with no vector, and only into an empty slot', async () => {
  const ports = official([withImage('evidence/v/u/E1.jpg')]);
  ports.videos.missingEmbeddings = [
    { videoId: V, revisionId: 1, incidentType: 'assault', title: 'Fight', description: 'Two people fight.' },
    { videoId: V, revisionId: 7, title: 'Gone', description: null },
  ];
  const asked = [];
  const embed = async (summary) => {
    asked.push(summary);
    return [0.1];
  };
  const dry = await repairMissingEmbeddings(ports, embed);
  assert.deepEqual(
    dry.revisions.map((item) => item.stored),
    [false, false],
  );
  assert.deepEqual(asked, [], 'a dry run does not embed');
  const report = await repairMissingEmbeddings(ports, embed, { dryRun: false, limit: 1 });
  assert.deepEqual(report.revisions, [{ videoId: V, revisionId: 1, stored: true }]);
  assert.deepEqual(
    asked,
    [{ incidentType: 'assault', title: 'Fight', description: 'Two people fight.' }],
    'the repair embeds the type too',
  );
  assert.deepEqual(
    ports.videos.embeddingCalls.map((call) => [call.revisionId, call.embedding]),
    [[1, [0.1]]],
  );
  const second = await repairMissingEmbeddings(ports, embed, { dryRun: false });
  assert.equal(second.revisions[0].revisionId, 7);
  assert.match(second.revisions[0].error, /not the searchable revision/);
});

test('a crop stores the box second with its fraction and a slice, not the item whole second (audit cases 15.33 s and 2.27 s)', () => {
  const entry = (box_seconds, timestamp_seconds, extra = {}) => ({
    item_type: 'entity',
    item_id: 'E1',
    image: 'evidence/v/u/E1.jpg',
    bounding_box: [1, 2, 3, 4],
    box_seconds,
    timestamp_seconds,
    ...extra,
  });
  const embeddings = [{ itemType: 'entity', itemId: 'E1', embedding: [0.5] }];
  const crop = (e, duration = null) => officialCrops({ incident: {} }, [e], embeddings, duration)[0];
  const at = (e) => [crop(e).timestamp_seconds, crop(e).slice_start_seconds, crop(e).slice_end_seconds];
  assert.deepEqual(at(entry(15.33, 18)), [15.33, 12.33, 18.33], 'was stored as 18');
  assert.deepEqual(at(entry(2.27, 22)), [2.27, 0, 5.27], 'was stored as 22; the slice is clamped at 0');
  assert.deepEqual(at(entry(null, 7)), [7, 4, 10], 'no box second: the item second');
  const tracked = { track: 'evidence/v/u/E1-track.json', track_first_seen_seconds: 15.33, track_last_seen_seconds: 18.8 };
  assert.deepEqual(at(entry(15.33, 18, tracked)), [15.33, 15.33, 18.8], 'a track gives first to last seen');
  assert.deepEqual(at(entry(15.33, 18, { ...tracked, track: null })), [15.33, 12.33, 18.33], 'a window with no track is not a track');
  assert.deepEqual([crop(entry(15.33, 18), 16).slice_end_seconds], [16], 'clamped to the video length');
  assert.equal(crop(entry(1, 1, { frame: 'evidence/v/u/E1-frame.jpg' })).frame, 'evidence/v/u/E1-frame.jpg');
  assert.equal(crop(entry(1, 1)).frame, null);
});

test('a searchable crop is named by the item label, not the type or the second look name', () => {
  const rows = (entries, payload = { incident: {} }) =>
    officialCrops(
      payload,
      entries,
      entries.map((e) => ({ itemType: e.item_type, itemId: e.item_id, embedding: [0.5] })),
    );
  const base = { image: 'evidence/v/run-1/x.jpg', bounding_box: [1, 2, 3, 4], timestamp_seconds: 1 };
  // revision 135 E1 and revision 126 A1 on finals
  const [bear, register, bare, payloadLabel] = rows(
    [
      { ...base, item_type: 'entity', item_id: 'E1', item_name: 'animal', label: 'black bear' },
      { ...base, item_type: 'asset', item_id: 'A1', item_name: 'high heel shoe', label: 'cash register' },
      { ...base, item_type: 'asset', item_id: 'A2', item_name: 'deck', label: '  ' },
      { ...base, item_type: 'entity', item_id: 'E2', item_name: 'human' },
    ],
    { incident: {}, entities: [{ entity_id: 'E2', type: 'human', label: 'man in a white shirt' }] },
  );
  assert.equal(bear.item_name, 'black bear');
  assert.equal(register.item_name, 'cash register');
  assert.equal(bare.item_name, 'deck', 'a blank label falls back to the name');
  assert.equal(payloadLabel.item_name, 'man in a white shirt', 'the payload item label backs up an entry without one');
  assert.equal(rows([{ ...base, item_type: 'instrument', item_id: 'I1' }])[0].item_name, 'instrument', 'no label or name: the type');
});

test('an object slice runs first to last detector-confirmed sample; a person keeps first to last seen (audit finding 3)', async () => {
  const track = 'evidence/v/u/A1-track.json';
  const entry = (item_type, extra = {}) => ({
    item_type,
    item_id: item_type === 'entity' ? 'E1' : 'A1',
    image: `evidence/v/u/${item_type}.jpg`,
    bounding_box: [1, 2, 3, 4],
    timestamp_seconds: 5,
    box_seconds: 5,
    track,
    track_first_seen_seconds: 0,
    track_last_seen_seconds: 12,
    ...extra,
  });
  // 117 A1: the tracker ran 0 to 12 s but the detector confirmed samples only up to 10.667 s (-0.1 is tracker-only).
  const samples = (...rows) => rows.map(([t, score]) => ({ t, box: [1, 2, 3, 4], score }));
  const files = {
    [track]: samples([0, 0.9], [4, -0.1], [10.667, 0.8], [12, -0.1]),
  };
  const read = async (key) => files[key];
  const crops = async (entries, reader = read) => {
    const spans = await confirmedSpans(entries, reader);
    return officialCrops(
      { incident: {} },
      entries,
      entries.map((e) => ({ itemType: e.item_type, itemId: e.item_id, embedding: [0.5] })),
      null,
      spans,
    );
  };
  const range = (crop) => [crop.slice_start_seconds, crop.slice_end_seconds];

  assert.deepEqual(range((await crops([entry('asset')]))[0]), [0, 10.667], '117 A1: 0 to 10.7 s, not 0 to 12 s');
  assert.deepEqual(range((await crops([entry('entity', { track: 'evidence/v/u/E1-track.json' })]))[0]), [0, 12], 'a person is unchanged');

  files[track] = samples([1, -0.1], [9, -0.1]);
  assert.deepEqual(range((await crops([entry('instrument')]))[0]), [2, 8], 'no confirmed sample: 3 s either side of the box second');
  assert.deepEqual(range((await crops([entry('asset', { box_seconds: 1 })]))[0]), [0, 4], 'clamped at 0');
  assert.deepEqual(range((await crops([entry('asset')], undefined))[0]), [2, 8], 'no reader: the box second');
  assert.deepEqual(
    range((await crops([entry('asset')], async () => Promise.reject(new Error('r2 down'))))[0]),
    [2, 8],
    'an unreadable track: the box second',
  );

  files[track] = samples([6, 0.9], [6.5, 0.9]);
  assert.deepEqual(
    range((await crops([entry('asset', { box_seconds: 6 })]))[0]),
    [5.25, 7.25],
    'a span under 2 s is widened to 2 s around its middle',
  );
  assert.deepEqual(range((await crops([entry('asset')]))[0]), [5, 7.25], 'the box second (5) is inside the slice');
  // 137 A1: the box was found at 0.07 s but the detector confirmed the object only from 2.4 s.
  files[track] = samples([2.4, 0.9], [2.9, 0.9]);
  assert.deepEqual(
    range((await crops([entry('asset', { box_seconds: 0.07 })]))[0]),
    [0.07, 3.65],
    '137 A1: the slice includes the box second',
  );
  files[track] = samples([2, 0.9], [4, 0.9]);
  assert.deepEqual(
    range((await crops([entry('instrument', { box_seconds: 9 })]))[0]),
    [2, 9],
    'a box second after the confirmed span extends the end',
  );
  assert.deepEqual(
    evidenceSlice(entry('asset', { box_seconds: 9 }), 8, { first: 2, last: 4 }),
    { start: 2, end: 8 },
    'clamped to the video length when it is known',
  );
  files[track] = samples([0, 0.9]);
  assert.deepEqual(range((await crops([entry('asset', { box_seconds: 0.5 })]))[0]), [0, 1], 'a widened span is clamped at 0');
  files[track] = samples([6, 0.9]);
  assert.deepEqual(range((await crops([entry('asset', { track: undefined })]))[0]), [2, 8], 'an object with no track: the box second');
});

test('marking official reads an object track from storage, so its slice is the confirmed span', async () => {
  const record = withImage('evidence/v/u/A1.jpg');
  record.evidence = [
    {
      item_type: 'asset',
      item_id: 'A1',
      image: 'evidence/v/u/A1.jpg',
      bounding_box: [1, 2, 3, 4],
      timestamp_seconds: 5,
      track: 'evidence/v/u/A1-track.json',
      track_first_seen_seconds: 0,
      track_last_seen_seconds: 12,
    },
  ];
  const ports = official([record]);
  const read = async (key) =>
    key === 'evidence/v/u/A1-track.json'
      ? [
          { t: 3, box: [1, 2, 3, 4], score: 0.9 },
          { t: 9, box: [1, 2, 3, 4], score: -0.1 },
        ]
      : assert.fail(key);
  await setOfficialRevision(ports, V, 1, async () => [{ itemType: 'asset', itemId: 'A1', embedding: [0.5] }], read);
  const [crop] = ports.videos.officialCalls[0].crops;
  assert.deepEqual([crop.slice_start_seconds, crop.slice_end_seconds], [2, 5], 'the widened span, extended to the box second (5)');
});

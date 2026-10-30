// SPDX-License-Identifier: Apache-2.0

// One IncidentReportRepository contract, run against the in-memory fake and
// the Supabase adapter (over a fake PostgREST), so use-case tests that rely on
// the fake are testing behaviour the real adapter has. The RPC models come
// from tests/support/incident-database.mjs; the library listing is the SQL's
// own and is pinned by supabase/tests, so the fake answers it from the stored
// state with paging only.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';
import { incidentRpcs } from './support/incident-database.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentReportRepository } = await import('../src/modules/reports/infrastructure/memory/incident-reports.ts');
const { SupabaseIncidentReportAdapter } = await import('../src/modules/reports/infrastructure/supabase/incident-reports.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const A = 'p42-a.mp4';
const B = 'p42-b.mp4';
const C = 'p42-c.mp4';
const RUN = 'p42-run-1';

const envelope = (names, overrides = {}) => ({
  overview: { title: 'Two vans', type: 'Theft', severity_level: 2, description: 'Combined', location: null, ...overrides },
  cameras: names.map((video) => ({
    video,
    report: { incident: { type: 'theft', start_timestamp: 1, end_timestamp: 9, severity_level: 2, description: video } },
  })),
});

const crop = (video, itemId, overrides = {}) => ({
  video_id: video,
  item_type: 'entity',
  item_id: itemId,
  image: `evidence/${video}/${itemId}.jpg`,
  bounding_box: [0, 0, 100, 100],
  timestamp_seconds: 1,
  item_name: itemId,
  description: '',
  threat_level: null,
  holder_entity_id: null,
  embedding: [],
  ...overrides,
});

const LIBRARY = {
  page: 1,
  pageSize: 10,
  search: null,
  type: null,
  severity: null,
  kind: null,
  generatedAfter: null,
  generatedBefore: null,
  timeFrom: null,
  timeTo: null,
  entities: null,
  instruments: null,
  assets: null,
  dayOfWeek: null,
  sort: 'newest',
  scope: 'all',
  entityTypes: null,
  evidenceMatch: 'contains',
  timezone: 'UTC',
};

// Incident 1 holds A and B; its one AI revision (id 1, run RUN) covers A only, and A has one crop. Incident 2 holds C.
const seed = {
  incidents: [
    { id: 1, official_revision_id: null, official_since: null, created_at: '2026-10-01T00:00:00' },
    { id: 2, official_revision_id: null, official_since: null, created_at: '2026-10-02T00:00:00' },
  ],
  videos: [
    { id: A, incident_id: 1, filepath: A, uploaded_datetime: '2026-10-01T01:00:00', recorded_at: null, duration: 10, source: 'upload' },
    { id: B, incident_id: 1, filepath: B, uploaded_datetime: '2026-10-01T02:00:00', recorded_at: null, duration: 12, source: 'upload' },
    { id: C, incident_id: 2, filepath: C, uploaded_datetime: '2026-10-02T01:00:00', recorded_at: null, duration: 8, source: 'upload' },
  ],
  model_runs: [{ id: RUN, model_name: 'model-x', prompt_version: 'v4', run_datetime: '2026-10-01T03:00:00', notes: null }],
  report_revisions: [
    {
      id: 1,
      incident_id: 1,
      revision_no: 1,
      kind: 'ai',
      model_run_id: RUN,
      parent_id: null,
      payload: envelope([A]),
      evidence: [{ item_type: 'entity', item_id: 'E1', image: `evidence/${A}/E1.jpg` }],
      video_names: [A],
      created_by: null,
      created_at: '2026-10-01T03:00:00',
      note: null,
    },
  ],
  evidence_crops: [{ ...crop(A, 'E1'), revision_id: 1 }],
};

const implementations = {
  memory: () => {
    const repo = new InMemoryIncidentReportRepository({
      incidents: seed.incidents.map((row) => ({
        incidentId: row.id,
        officialRevisionId: null,
        officialSince: null,
        createdAt: row.created_at,
      })),
      videos: seed.videos.map((row) => ({
        incidentId: row.incident_id,
        videoId: row.id,
        storageKey: row.filepath,
        uploadedAt: row.uploaded_datetime,
        recordedAt: null,
        durationSeconds: row.duration,
        source: row.source,
      })),
      revisions: seed.report_revisions.map((row) => ({
        revision: {
          revisionId: row.id,
          incidentId: row.incident_id,
          revisionNo: row.revision_no,
          kind: row.kind,
          createdBy: null,
          createdAt: row.created_at,
          note: null,
          parentId: null,
          modelRunId: row.model_run_id,
          model: 'model-x',
          videoNames: row.video_names,
        },
        payload: row.payload,
        evidence: row.evidence,
      })),
      crops: seed.evidence_crops.map((row) => ({ ...row, revisionId: row.revision_id })),
      modelRuns: { [RUN]: 'model-x' },
    });
    return { repo, crops: () => repo.crops.map((row) => ({ revision: row.revisionId, video: row.video_id, item: row.item_id })) };
  },
  supabase: () => {
    const db = fakePostgrest(structuredClone(seed), {
      rpc: {
        ...incidentRpcs,
        list_incident_report_summaries: () => ({ reports: [], totalItems: 0, incidentTypes: [] }),
      },
      identity: { report_revisions: 'id' },
    });
    globalThis.fetch = db.fetch;
    return {
      repo: new SupabaseIncidentReportAdapter(new PostgrestClient('https://supabase.test', 'k')),
      crops: () => db.store.evidence_crops.map((row) => ({ revision: row.revision_id, video: row.video_id, item: row.item_id })),
      db,
    };
  },
};

const humanInput = (overrides = {}) => ({
  incidentId: 1,
  parentId: 1,
  payload: envelope([A], { title: 'Edited' }),
  evidence: [],
  crops: [],
  createdBy: ' Editor ',
  note: ' Fixed the title ',
  ...overrides,
});

const rejects = (promise, reason) =>
  assert.rejects(promise, (error) => error instanceof StoreRejection && error.reason === reason, `expected a ${reason} rejection`);

for (const [name, make] of Object.entries(implementations)) {
  describe(`IncidentReportRepository contract: ${name}`, () => {
    test('an incident comes with its videos (earliest upload first) and its revisions with coverage names', async () => {
      const { repo } = make();
      assert.equal(await repo.getIncident(99), null);
      const incident = await repo.getIncident(1);
      assert.deepEqual(
        incident.videos.map((video) => [video.videoId, video.storageKey, video.durationSeconds]),
        [
          [A, A, 10],
          [B, B, 12],
        ],
      );
      assert.deepEqual(
        incident.revisions.map((revision) => [
          revision.revisionId,
          revision.revisionNo,
          revision.kind,
          revision.videoNames,
          revision.model,
          revision.isOfficial,
        ]),
        [[1, 1, 'ai', [A], 'model-x', false]],
      );
      assert.equal(incident.officialRevisionId, null);
    });

    test('a revision is read by id; with none asked for, the official one, else the newest', async () => {
      const { repo } = make();
      assert.equal(await repo.getRevision(99, null), null);
      assert.equal(await repo.getRevision(1, 99), null);
      assert.equal(await repo.getRevision(2, 1), null, 'a revision of another incident');
      const first = await repo.getRevision(1, 1);
      assert.equal(first.envelope.cameras[0].video, A);
      assert.equal(first.envelope.overview.title, 'Two vans');
      assert.equal(first.modelRun.modelName, 'model-x');
      const saved = await repo.saveHumanRevision(humanInput());
      assert.equal((await repo.getRevision(1, null)).revision.revisionId, saved.revisionId, 'newest when none is official');
      await repo.setOfficialRevision(1, 1);
      assert.equal((await repo.getRevision(1, null)).revision.revisionId, 1, 'the official one, not the newest');
    });

    test('marking and clearing the official revision', async () => {
      const { repo } = make();
      const marked = await repo.setOfficialRevision(1, 1);
      assert.deepEqual([marked.incidentId, marked.officialRevisionId, typeof marked.officialSince], [1, 1, 'string']);
      assert.equal((await repo.setOfficialRevision(1, 1)).officialSince, marked.officialSince, 'marking again keeps the original time');
      assert.equal((await repo.getIncident(1)).revisions[0].isOfficial, true);
      assert.deepEqual(await repo.setOfficialRevision(1, null), { incidentId: 1, officialRevisionId: null, officialSince: null });
      await rejects(repo.setOfficialRevision(99, 1), 'not-found');
      await rejects(repo.setOfficialRevision(2, 1), 'not-found');
    });

    test('a human revision is appended with the next number, the parent, its run and its coverage', async () => {
      const { repo } = make();
      const saved = await repo.saveHumanRevision(humanInput());
      assert.deepEqual(
        { ...saved, createdAt: typeof saved.createdAt, model: undefined },
        {
          revisionId: 2,
          incidentId: 1,
          revisionNo: 2,
          kind: 'human',
          createdBy: 'Editor',
          createdAt: 'string',
          note: 'Fixed the title',
          parentId: 1,
          modelRunId: RUN,
          model: undefined,
          isOfficial: false,
          videoNames: [A],
        },
      );
      const record = await repo.getRevision(1, 2);
      assert.equal(record.envelope.overview.title, 'Edited');
      assert.equal((await repo.getRevision(1, 1)).envelope.overview.title, 'Two vans', 'the earlier revision is unchanged');
    });

    test('a human revision stores its crops; one from an uncovered video refuses the whole save', async () => {
      const { repo, crops } = make();
      const saved = await repo.saveHumanRevision(humanInput({ crops: [crop(A, 'E1'), crop(A, 'E2')] }));
      assert.deepEqual(
        crops().filter((row) => row.revision === saved.revisionId),
        [
          { revision: saved.revisionId, video: A, item: 'E1' },
          { revision: saved.revisionId, video: A, item: 'E2' },
        ],
      );
      const before = (await repo.getIncident(1)).revisions.length;
      await rejects(repo.saveHumanRevision(humanInput({ crops: [crop(B, 'E9')] })), 'invalid');
      await rejects(repo.saveHumanRevision(humanInput({ crops: [crop(C, 'E9')] })), 'invalid');
      assert.equal((await repo.getIncident(1)).revisions.length, before, 'nothing was appended');
    });

    test('a human revision is refused for an unknown incident, a foreign parent or an empty reviewer name', async () => {
      const { repo } = make();
      await rejects(repo.saveHumanRevision(humanInput({ incidentId: 99 })), 'not-found');
      await rejects(repo.saveHumanRevision(humanInput({ incidentId: 2, parentId: 1 })), 'not-found');
      await rejects(repo.saveHumanRevision(humanInput({ parentId: 99 })), 'not-found');
      await rejects(repo.saveHumanRevision(humanInput({ createdBy: '  ' })), 'invalid');
    });

    test("an AI revision covers exactly the named videos and carries the covered videos' latest crops", async () => {
      const { repo, crops } = make();
      const created = await repo.createAiRevision({
        incidentId: 1,
        modelRunId: RUN,
        note: null,
        payload: envelope([A, B]),
        evidence: [],
        videoNames: [A, B],
        embedding: null,
      });
      assert.deepEqual(created, { revisionId: 2, revisionNo: 2, crops: 1 });
      assert.deepEqual((await repo.getIncident(1)).revisions[0].videoNames, [A, B]);
      assert.deepEqual(
        crops().filter((row) => row.revision === 2),
        [{ revision: 2, video: A, item: 'E1' }],
      );
      const withVector = await repo.createAiRevision({
        incidentId: 1,
        modelRunId: RUN,
        note: 'again',
        payload: envelope([B]),
        evidence: [],
        videoNames: [B],
        embedding: [0.5, 0.25],
      });
      assert.equal(withVector.revisionNo, 3);
    });

    test('an AI revision is refused for an unknown incident, no coverage, a foreign video or a missing run', async () => {
      const { repo } = make();
      const input = { incidentId: 1, modelRunId: RUN, note: null, payload: envelope([A]), evidence: [], videoNames: [A], embedding: null };
      await rejects(repo.createAiRevision({ ...input, incidentId: 99 }), 'not-found');
      await rejects(repo.createAiRevision({ ...input, videoNames: [] }), 'invalid');
      await rejects(repo.createAiRevision({ ...input, videoNames: [C] }), 'invalid');
      await rejects(repo.createAiRevision({ ...input, modelRunId: 'p42-missing' }), 'not-found');
      assert.equal((await repo.getIncident(1)).revisions.length, 1);
    });

    test('crops are replaced for the searchable revision only, and only with videos of the incident', async () => {
      const { repo, crops } = make();
      assert.equal(await repo.setRevisionCrops(1, 1, [crop(A, 'E7'), crop(B, 'E8')]), 2);
      assert.deepEqual(
        crops().map((row) => row.item),
        ['E7', 'E8'],
      );
      await repo.saveHumanRevision(humanInput());
      await rejects(repo.setRevisionCrops(1, 1, []), 'invalid');
      await rejects(repo.setRevisionCrops(1, 2, [crop(C, 'E1')]), 'invalid');
      await rejects(repo.setRevisionCrops(99, 1, []), 'not-found');
    });

    test("one video's crops are replaced without touching the others; a null revision only deletes", async () => {
      const { repo, crops } = make();
      await repo.setRevisionCrops(1, 1, [crop(A, 'E1'), crop(B, 'E2')]);
      assert.equal(await repo.replaceVideoCrops(1, A, 1, [crop(A, 'E5')]), 1);
      assert.deepEqual(
        crops()
          .map((row) => `${row.video}:${row.item}`)
          .sort(),
        [`${A}:E5`, `${B}:E2`],
      );
      assert.equal(await repo.replaceVideoCrops(1, A, null, []), 0);
      assert.deepEqual(
        crops().map((row) => row.video),
        [B],
      );
      await rejects(repo.replaceVideoCrops(1, C, 1, []), 'invalid');
      await rejects(repo.replaceVideoCrops(1, A, 99, []), 'invalid');
    });

    test('the evidence a video can still show is listed from its crops and its folder in any revision', async () => {
      const { repo } = make();
      assert.equal(await repo.listReferencedEvidenceImages(1, 'p42-none.mp4'), null);
      assert.equal(await repo.listReferencedEvidenceImages(2, A), null, 'a video of another incident');
      await repo.saveHumanRevision(
        humanInput({ evidence: [{ item_type: 'entity', item_id: 'E3', image: `evidence/${A}/edit-1/E3.jpg` }] }),
      );
      await repo.replaceVideoCrops(1, A, 1, [crop(A, 'E1')]);
      assert.deepEqual((await repo.listReferencedEvidenceImages(1, A)).sort(), [`evidence/${A}/E1.jpg`, `evidence/${A}/edit-1/E3.jpg`]);
      assert.deepEqual(await repo.listReferencedEvidenceImages(1, B), []);
    });

    test("a merge moves the source's videos into the target and deletes the source with its revisions and crops", async () => {
      const { repo, crops } = make();
      const result = await repo.mergeIncidents(2, 1);
      assert.deepEqual(result, {
        incidentId: 2,
        sourceIncidentId: 1,
        movedVideoIds: [A, B],
        orphanedCropImages: [`evidence/${A}/E1.jpg`],
      });
      assert.equal(await repo.getIncident(1), null);
      assert.deepEqual(
        (await repo.getIncident(2)).videos.map((video) => video.videoId),
        [A, B, C],
      );
      assert.deepEqual(crops(), []);
      await rejects(repo.mergeIncidents(2, 2), 'invalid');
      await rejects(repo.mergeIncidents(2, 99), 'not-found');
    });
  });
}

describe('SupabaseIncidentReportAdapter wire format', () => {
  test('the incident functions get p_* arguments and a vector in its text form', async () => {
    const { repo, db } = implementations.supabase();
    await repo.createAiRevision({
      incidentId: 1,
      modelRunId: RUN,
      note: 'n',
      payload: envelope([A]),
      evidence: [],
      videoNames: [A],
      embedding: [0.5, 0.25],
    });
    await repo.saveHumanRevision(humanInput());
    const calls = Object.fromEntries(
      db.requests.filter((request) => request.path.startsWith('rpc/')).map((request) => [request.path, request.body]),
    );
    assert.equal(calls['rpc/create_ai_revision'].p_embedding, '[0.5,0.25]');
    assert.deepEqual(
      [
        calls['rpc/create_ai_revision'].p_incident_type,
        calls['rpc/create_ai_revision'].p_severity_level,
        calls['rpc/create_ai_revision'].p_start_seconds,
      ],
      ['theft', 2, 1],
    );
    assert.equal(calls['rpc/save_human_revision_with_crops'].p_parent_id, 1);
    assert.equal(calls['rpc/save_human_revision_with_crops'].p_created_by, ' Editor ');
  });

  test('a crop with no embedding is sent as null, which the SQL accepts (an empty list is refused)', async () => {
    const { repo, db } = implementations.supabase();
    await repo.saveHumanRevision(humanInput({ crops: [crop(A, 'E1')] }));
    const call = db.requests.find((request) => request.path === 'rpc/save_human_revision_with_crops').body;
    assert.equal(call.p_crops[0].embedding, null);
  });

  test('a multi-camera revision has no single timeline', async () => {
    const { repo, db } = implementations.supabase();
    await repo.createAiRevision({
      incidentId: 1,
      modelRunId: RUN,
      note: null,
      payload: envelope([A, B]),
      evidence: [],
      videoNames: [A, B],
      embedding: null,
    });
    const call = db.requests.find((request) => request.path === 'rpc/create_ai_revision').body;
    assert.deepEqual([call.p_start_seconds, call.p_end_seconds, call.p_embedding], [null, null, null]);
  });

  test("the library is the SQL's own: the query maps to p_* arguments and the cards map back", async () => {
    const db = fakePostgrest(structuredClone(seed), {
      rpc: {
        list_incident_report_summaries: () => ({
          reports: [
            {
              incidentId: 1,
              revisionId: null,
              title: 'T',
              severity: null,
              isOfficial: false,
              coverage: [A],
              missingVideos: [B],
              removedVideos: [],
              versionCount: 0,
              videoCount: 2,
            },
          ],
          totalItems: 1,
          incidentTypes: ['theft'],
        }),
      },
    });
    globalThis.fetch = db.fetch;
    const repo = new SupabaseIncidentReportAdapter(new PostgrestClient('https://supabase.test', 'k'));
    const list = await repo.listIncidents(LIBRARY);
    assert.deepEqual([list.totalItems, list.incidentTypes], [1, ['theft']]);
    assert.deepEqual(
      [list.items[0].incidentId, list.items[0].revisionId, list.items[0].severity, list.items[0].missingVideos],
      [1, null, 1, [B]],
    );
    assert.equal(db.requests[0].body.p_page_size, 10);
  });
});

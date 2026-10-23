// SPDX-License-Identifier: Apache-2.0

// One IncidentRepository contract, run against the in-memory fake and the
// Supabase adapter (over a fake PostgREST), so use-case tests that rely on the
// fake are testing behaviour the real adapter has. The fake PostgREST's
// list_incident_report_summaries applies paging, scope, kind and
// newest/oldest order to SQL-shaped summaries; the other filters run in SQL
// and are pinned by the reports route tests. Its save_human_revision RPC comes
// from tests/support/revisions-database.mjs.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';
import { revisionRpcs } from './support/revisions-database.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../lib/adapters/memory/incidents.ts');
const { StoreRejection } = await import('../lib/ports/index.ts');
const { SupabaseIncidentAdapter } = await import('../lib/adapters/supabase/incidents.ts');
const { savedRevisionFromRpc } = await import('../lib/adapters/supabase/mappers/report.ts');
const { reportListFromRpc, reportListRpcArgs } = await import('../lib/adapters/supabase/mappers/report-library.ts');
const { PostgrestClient } = await import('../lib/postgrest/client.ts');
const { humanRevisionContent } = await import('../lib/reports/revision.ts');
const { aiRevisionRow, aiRunReport } = await import('./support/report-view.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const summaries = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'report-summaries-rpc.json'), 'utf8'));
const [HUMAN, LEGACY, REPAIRED] = summaries.reports;
const LIBRARY = {
  page: 1, pageSize: 6, search: null, type: null, severity: null, kind: null, generatedAfter: null, generatedBefore: null,
  timeFrom: null, timeTo: null, entities: null, instruments: null, assets: null, dayOfWeek: null,
  sort: 'newest', scope: 'all', entityTypes: null, evidenceMatch: 'contains', timezone: 'UTC',
};
const VIDEO_ID = smoke.videoId;
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function listSummaries(args) {
  const direction = args.p_sort === 'oldest' ? 1 : -1;
  const matching = summaries.reports
    .filter((report) => (args.p_scope !== 'official' || report.isOfficial) && (args.p_kind === null || report.kind === args.p_kind))
    .sort((a, b) => direction * a.generatedAt.localeCompare(b.generatedAt) || a.revisionId - b.revisionId);
  const size = Math.min(Math.max(args.p_page_size, 1), 1000);
  const start = (Math.max(args.p_page, 1) - 1) * size;
  return { reports: matching.slice(start, start + size), totalItems: matching.length, incidentTypes: summaries.incidentTypes };
}

/** An edit of the smoke run: a new description and severity, entity E2 dropped, asset A1 renamed; every item names its source item. */
function smokeEdit() {
  const details = (sourceId) => ({ source_id: sourceId, timestamp_seconds: 1, label: '', image: null });
  return {
    incident: { type: 'assault', start_timestamp: 1, end_timestamp: 9, description: 'Reviewer: one person pushes the other over.', severity_level: 3 },
    entities: [{ entity_id: 'E1', type: 'human', description: smoke.entities[0].description, first_seen_seconds: 1, last_seen_seconds: 3, ...details('E1') }],
    instruments: [],
    assets: smoke.assets.map((asset, index) => ({
      asset_id: asset.asset_id, name: index === 0 ? 'white delivery van' : asset.name, description: asset.description, ...details(asset.asset_id),
    })),
  };
}

const humanInput = (record, overrides = {}) => ({
  videoId: VIDEO_ID, parentId: record.revision.revisionId, createdBy: ' Editor ', note: ' Corrected the severity ',
  ...humanRevisionContent(record, smokeEdit()), ...overrides,
});

// Each implementation seeds the smoke run's one AI revision (id 1); officialRevisionId marks one official.
const implementations = {
  memory: (officialRevisionId = null) => {
    const record = aiRunReport(smoke);
    record.video.officialRevisionId = officialRevisionId;
    const repo = new InMemoryIncidentRepository([record], summaries.reports);
    return { repo, ai: () => structuredClone(repo.revisions[0]) };
  },
  supabase: (officialRevisionId = null, rpc = {}) => {
    const db = fakePostgrest({
      videos: [{ ...smoke.video, official_revision_id: officialRevisionId }], model_runs: [smoke.modelRun], report_revisions: [aiRevisionRow(smoke)],
    }, { rpc: { list_incident_report_summaries: listSummaries, ...revisionRpcs, ...rpc }, identity: { report_revisions: 'id' } });
    globalThis.fetch = db.fetch;
    return { repo: new SupabaseIncidentAdapter(new PostgrestClient('https://supabase.test', 'k')), ai: () => structuredClone(db.store.report_revisions[0]), db };
  },
};

for (const [name, make] of Object.entries(implementations)) {
  describe(`IncidentRepository contract: ${name}`, () => {
    test('a revision is found by video and id; its AI run notes come with it', async () => {
      const { repo } = make();
      assert.equal(await repo.getRevision('v-none', null), null);
      assert.equal(await repo.getRevision(VIDEO_ID, 99), null);
      const record = await repo.getRevision(VIDEO_ID, 1);
      assert.deepEqual([record.revision.revisionId, record.revision.revisionNo, record.revision.kind, record.revision.modelRunId], [1, 1, 'ai', smoke.modelRunId]);
      assert.equal(record.modelRun.notes.kind, 'contract');
      assert.deepEqual(record.entities.map((entity) => entity.entityId), ['E1', 'E2']);
      assert.equal(record.video.officialRevisionId, null);
    });

    test('with no revision asked for, the newest is read when none is official, else the official one', async () => {
      const unmarked = make();
      await unmarked.repo.saveHumanRevision(humanInput(await unmarked.repo.getRevision(VIDEO_ID, 1)));
      assert.equal((await unmarked.repo.getRevision(VIDEO_ID, null)).revision.revisionNo, 2, 'newest, never inferred as official');
      assert.equal((await unmarked.repo.getRevision(VIDEO_ID, null)).revision.isOfficial, false);
      const marked = make(1);
      await marked.repo.saveHumanRevision(humanInput(await marked.repo.getRevision(VIDEO_ID, 1)));
      const shown = await marked.repo.getRevision(VIDEO_ID, null);
      assert.deepEqual([shown.revision.revisionId, shown.revision.isOfficial], [1, true]);
      assert.equal((await marked.repo.getRevision(VIDEO_ID, 2)).revision.isOfficial, false);
    });

    test('a save appends a human revision with the next number and the opened revision as parent; the AI revision is unchanged', async () => {
      const { repo, ai } = make();
      const aiBefore = ai();
      const saved = await repo.saveHumanRevision(humanInput(await repo.getRevision(VIDEO_ID, 1)));
      assert.deepEqual({ ...saved, createdAt: typeof saved.createdAt, model: undefined }, {
        revisionId: 2, videoId: VIDEO_ID, revisionNo: 2, kind: 'human', createdBy: 'Editor', createdAt: 'string', note: 'Corrected the severity',
        parentId: 1, modelRunId: smoke.modelRunId, model: undefined, isOfficial: false,
      });
      const record = await repo.getRevision(VIDEO_ID, 2);
      assert.deepEqual(record.incident, {
        type: 'assault', startSeconds: 1, endSeconds: 9, duration: 8, description: 'Reviewer: one person pushes the other over.', severityLevel: 3,
        confidenceScore: null,
      });
      assert.deepEqual(record.entities.map((entity) => entity.entityId), ['E1']);
      assert.deepEqual(record.assets.map((asset) => asset.name), ['white delivery van', 'blue car']);
      assert.deepEqual(ai(), aiBefore);
      const second = await repo.saveHumanRevision(humanInput(record, { note: null }));
      assert.deepEqual([second.revisionNo, second.parentId, second.note], [3, 2, null]);
    });

    test('the History lists every revision newest first, marking the official one', async () => {
      const { repo } = make(1);
      assert.deepEqual(await repo.listRevisions('v-none'), []);
      await repo.saveHumanRevision(humanInput(await repo.getRevision(VIDEO_ID, 1)));
      const history = await repo.listRevisions(VIDEO_ID);
      assert.deepEqual(history.map((row) => [row.revisionId, row.kind, row.createdBy, row.isOfficial, row.parentId]), [
        [2, 'human', 'Editor', false, 1], [1, 'ai', null, true, null],
      ]);
      assert.equal(history[1].model, 'nvidia/cosmos-3-nano-reasoner');
    });

    test('a save for a missing video or parent, or without a reviewer name, is refused and writes nothing', async () => {
      const { repo } = make();
      const record = await repo.getRevision(VIDEO_ID, 1);
      const refusal = (reason, message) => (error) => error instanceof StoreRejection && error.reason === reason && message.test(error.message);
      await assert.rejects(repo.saveHumanRevision(humanInput(record, { videoId: 'v-none' })), refusal('not-found', /Video not found/));
      await assert.rejects(repo.saveHumanRevision(humanInput(record, { parentId: 99 })), refusal('not-found', /Revision not found/));
      await assert.rejects(repo.saveHumanRevision(humanInput(record, { createdBy: '  ' })), refusal('invalid', /reviewer name/));
      assert.equal((await repo.listRevisions(VIDEO_ID)).length, 1);
    });

    test('the library comes in pages with the exact total, newest first, field for field', async () => {
      const { repo } = make();
      assert.deepEqual(await repo.listReports({ ...LIBRARY, pageSize: 2 }), { items: [HUMAN, REPAIRED], totalItems: 3, incidentTypes: ['assault', 'road accident'] });
      assert.deepEqual((await repo.listReports({ ...LIBRARY, page: 2, pageSize: 2 })).items, [LEGACY]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, sort: 'oldest' })).items, [LEGACY, REPAIRED, HUMAN]);
    });

    test('official scope and a revision kind narrow the library', async () => {
      const { repo } = make();
      const official = await repo.listReports({ ...LIBRARY, scope: 'official' });
      assert.deepEqual([official.items, official.totalItems], [[HUMAN], 1]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, kind: 'human' })).items, [HUMAN]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, kind: 'ai' })).items, [REPAIRED, LEGACY]);
    });
  });
}

describe('Supabase adapter: revisions', () => {
  test('a revision is read from report_revisions and its run; nothing else is touched', async () => {
    const { repo, db } = implementations.supabase();
    await repo.getRevision(VIDEO_ID, 1);
    assert.deepEqual(db.requests.map((request) => `${request.method} ${request.path}`), ['GET videos', 'GET report_revisions', 'GET model_runs']);
  });

  test('a save is one save_human_revision call and nothing else is written', async () => {
    const { repo, db } = implementations.supabase();
    const input = humanInput(await repo.getRevision(VIDEO_ID, 1));
    db.requests.length = 0;
    await repo.saveHumanRevision(input);
    assert.deepEqual(db.requests, [{
      method: 'POST', path: 'rpc/save_human_revision',
      body: {
        p_video_id: VIDEO_ID, p_parent_id: 1, p_created_by: ' Editor ', p_note: ' Corrected the severity ',
        p_payload: input.payload, p_evidence: input.evidence,
        p_incident_type: 'assault', p_severity_level: 3, p_start_seconds: 1, p_end_seconds: 9,
      },
    }]);
  });

  test("an RPC's RAISE is a StoreRejection with its message; any other failure is rethrown", async () => {
    const refusing = implementations.supabase(null, {
      save_human_revision: () => { throw new Error('The report payload must be an object with an incident'); },
    });
    await assert.rejects(refusing.repo.saveHumanRevision(humanInput(await refusing.repo.getRevision(VIDEO_ID, 1))), (error) => {
      assert.ok(error instanceof StoreRejection, `${error}`);
      assert.deepEqual([error.reason, error.message], ['invalid', 'The report payload must be an object with an incident']);
      return true;
    });
    const record = await refusing.repo.getRevision(VIDEO_ID, 1);
    globalThis.fetch = async () => new Response(JSON.stringify({ code: '42501', message: 'permission denied for function save_human_revision' }), { status: 401 });
    await assert.rejects(refusing.repo.saveHumanRevision(humanInput(record)), (error) => !(error instanceof StoreRejection) && /HTTP 401.*permission denied/.test(error.message));
  });

  test('a malformed RPC result maps to safe values', () => {
    assert.deepEqual(savedRevisionFromRpc(null), {
      revisionId: NaN, videoId: 'undefined', revisionNo: NaN, kind: 'ai', createdBy: null, createdAt: null, note: null, parentId: null, modelRunId: null, model: null, isOfficial: false,
    });
  });
});

describe('list_incident_report_summaries mapping', () => {
  test('the query becomes the nineteen RPC arguments', () => {
    assert.deepEqual(reportListRpcArgs({
      ...LIBRARY, page: 2, search: 'blade', type: 'assault', severity: '4', kind: 'human', generatedAfter: '2026-09-01T00:00:00',
      generatedBefore: '2026-09-28T00:00:00', timeFrom: '08:00', timeTo: '17:30', entities: ['person'], instruments: ['knife'], assets: ['door'],
      dayOfWeek: 1, sort: 'severity-high', scope: 'official', entityTypes: ['human'], evidenceMatch: 'exact', timezone: 'Asia/Singapore',
    }), {
      p_page: 2, p_page_size: 6, p_search: 'blade', p_type: 'assault', p_severity: '4', p_kind: 'human',
      p_generated_after: '2026-09-01T00:00:00', p_generated_before: '2026-09-28T00:00:00', p_time_from: '08:00', p_time_to: '17:30',
      p_entities: ['person'], p_instruments: ['knife'], p_assets: ['door'], p_day_of_week: 1, p_sort: 'severity-high', p_scope: 'official',
      p_entity_types: ['human'], p_evidence_match: 'exact', p_timezone: 'Asia/Singapore',
    });
  });

  test('a malformed result lists what it can with every field the library reads', () => {
    assert.deepEqual(reportListFromRpc(null), { items: [], totalItems: 0, incidentTypes: [] });
    const { items } = reportListFromRpc({ reports: [{ revisionId: 7, isOfficial: 'yes' }], incidentTypes: ['assault', 7] });
    assert.deepEqual(items[0], {
      revisionId: 7, revisionNo: 0, videoId: '', modelRunId: null, kind: 'ai', createdBy: null, note: null, title: '', filename: '', incident_type: '',
      description: '', severity: 1, confidence: null, generatedAt: null, uploadedAt: null, model: '', outcome: null, isOfficial: false, officialSince: null, versionCount: 0, evidenceCount: 0, thumbnail: null, r2Key: null, sensorId: null,
    });
    assert.deepEqual(reportListFromRpc({ incidentTypes: ['assault', 7] }).incidentTypes, ['assault']);
  });
});

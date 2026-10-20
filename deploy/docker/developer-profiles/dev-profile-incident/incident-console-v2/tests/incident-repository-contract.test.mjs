// SPDX-License-Identifier: Apache-2.0

// One IncidentRepository contract, run against the in-memory fake and the
// Supabase adapter (over a fake PostgREST), so use-case tests that rely on the
// fake are testing behaviour the real adapter has. The fake PostgREST's
// list_incident_report_summaries applies paging, scope, status and
// newest/oldest order to SQL-shaped summaries; the other filters run in SQL
// and are pinned by the reports route tests. Its reviewer-version views and
// RPCs come from tests/support/finals-database.mjs.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';
import { effectiveViews, reviewerRpcs } from './support/finals-database.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../lib/adapters/memory/incidents.ts');
const { SupabaseIncidentAdapter } = await import('../lib/adapters/supabase/incidents.ts');
const { reviewTransitionFromRpc, runReportFromRows, structuredEditResultFromRpc } = await import('../lib/adapters/supabase/mappers/report.ts');
const { reportListFromRpc, reportListRpcArgs } = await import('../lib/adapters/supabase/mappers/report-library.ts');
const { PostgrestClient } = await import('../lib/postgrest/client.ts');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const summaries = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'report-summaries-rpc.json'), 'utf8'));
const [ASSAULT, LEGACY, REPAIRED] = summaries.reports;
const LIBRARY = {
  page: 1, pageSize: 6, search: null, type: null, severity: null, status: null, generatedAfter: null, generatedBefore: null,
  timeFrom: null, timeTo: null, entities: null, instruments: null, assets: null, dayOfWeek: null,
  sort: 'newest', scope: 'all', entityTypes: null, evidenceMatch: 'contains', timezone: 'UTC',
};
const KEY = { videoId: smoke.videoId, modelRunId: smoke.modelRunId };
const OTHER_RUN = { videoId: smoke.videoId, modelRunId: 'm-other' };
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function listSummaries(args) {
  const direction = args.p_sort === 'oldest' ? 1 : -1;
  const matching = summaries.reports
    .filter((report) => (args.p_scope !== 'official' || report.isOfficial) && (args.p_status === null || report.status === args.p_status))
    .sort((a, b) => direction * a.generatedAt.localeCompare(b.generatedAt) || a.reportId.localeCompare(b.reportId));
  const size = Math.min(Math.max(args.p_page_size, 1), 1000);
  const start = (Math.max(args.p_page, 1) - 1) * size;
  return { reports: matching.slice(start, start + size), totalItems: matching.length, incidentTypes: summaries.incidentTypes };
}

/** An edit of the smoke run: a new description and severity, entity E2 dropped, asset A1 renamed. */
function smokeEdit() {
  return {
    incident: { type: 'assault', start_timestamp: 1, end_timestamp: 9, description: 'Reviewer: one person pushes the other over.', severity_level: 3 },
    entities: [{ entity_id: 'E1', type: 'human', description: smoke.entities[0].description }],
    instruments: [],
    assets: smoke.assets.map((asset, index) => ({ asset_id: asset.asset_id, name: index === 0 ? 'white delivery van' : asset.name, description: asset.description })),
  };
}

// Each implementation also exposes the stored AI report, which no edit or verification may change.
const implementations = {
  memory: () => {
    const repo = new InMemoryIncidentRepository([runReportFromRows(smoke)], summaries.reports);
    const ai = () => {
      const { incident, entities, instruments, assets } = repo.runs.get(`${KEY.videoId}\u0000${KEY.modelRunId}`);
      return { incident, entities, instruments, assets };
    };
    return { repo, ai };
  },
  supabase: () => {
    const db = fakePostgrest({
      videos: [smoke.video], model_runs: [smoke.modelRun], incidents: [smoke.incident], review_status: [smoke.review],
      entities: smoke.entities, instruments: smoke.instruments, assets: smoke.assets, reports: [smoke.reportRow],
    }, { rpc: { list_incident_report_summaries: listSummaries, ...reviewerRpcs }, views: effectiveViews });
    globalThis.fetch = db.fetch;
    const ai = () => ({ incident: db.store.incidents, entities: db.store.entities, instruments: db.store.instruments, assets: db.store.assets });
    return { repo: new SupabaseIncidentAdapter(new PostgrestClient('https://supabase.test', 'k')), ai, db };
  },
};

for (const [name, make] of Object.entries(implementations)) {
  describe(`IncidentRepository contract: ${name}`, () => {
    test('a run is found by its full key only', async () => {
      const { repo } = make();
      assert.equal(await repo.runExists(KEY), true);
      assert.equal(await repo.runExists(OTHER_RUN), false);
      assert.equal(await repo.getRunReport(OTHER_RUN), null);
      const record = await repo.getRunReport(KEY);
      assert.deepEqual(record.key, KEY);
      assert.equal(record.modelRun.notes.kind, 'contract');
      assert.deepEqual(record.entities.map((entity) => entity.entityId), ['E1', 'E2']);
    });

    test('verifying stamps the verifier, keeps the edit stamps and is a no-op when repeated', async () => {
      const { repo } = make();
      const edited = await repo.applyStructuredEdit(KEY, smokeEdit(), 'Editor');
      const verified = await repo.setReviewStatus(KEY, 'verified', ' Lead ');
      assert.deepEqual({ ...verified, verifiedAt: typeof verified.verifiedAt }, {
        changed: true, status: 'verified', verifiedBy: 'Lead', verifiedAt: 'string', humanVersionCreated: false,
      });
      const review = { status: 'verified', verifiedBy: 'Lead', verifiedAt: verified.verifiedAt, editedBy: 'Editor', editedAt: edited.editedAt };
      assert.deepEqual(await repo.getReview(KEY), review);
      assert.deepEqual((await repo.getRunReport(KEY)).review, review);
      assert.deepEqual(await repo.setReviewStatus(KEY, 'verified', 'Someone else'), {
        changed: false, status: 'verified', verifiedBy: null, verifiedAt: null, humanVersionCreated: false,
      });
      assert.deepEqual(await repo.getReview(KEY), review);
      assert.equal(await repo.getReview(OTHER_RUN), null);
    });

    test('a status other than verified clears the verifier and never stamps an edit', async () => {
      const { repo } = make();
      await repo.setReviewStatus(KEY, 'verified', 'Lead');
      const reset = await repo.setReviewStatus(KEY, 'unreviewed', 'Lead');
      assert.deepEqual(reset, { changed: true, status: 'unreviewed', verifiedBy: null, verifiedAt: null, humanVersionCreated: false });
      assert.deepEqual(await repo.getReview(KEY), { status: 'unreviewed', verifiedBy: null, verifiedAt: null, editedBy: null, editedAt: null });
    });

    test('verifying without an edit copies the AI report into the reviewer version; the report reads the same', async () => {
      const { repo, ai } = make();
      const before = await repo.getRunReport(KEY);
      const aiBefore = structuredClone(ai());
      assert.equal((await repo.setReviewStatus(KEY, 'verified', 'Lead')).humanVersionCreated, true);
      const after = await repo.getRunReport(KEY);
      assert.deepEqual({ ...after, review: null }, { ...before, review: null });
      assert.deepEqual(ai(), aiBefore);
      await repo.setReviewStatus(KEY, 'under review', 'Lead');
      assert.equal((await repo.setReviewStatus(KEY, 'verified', 'Lead')).humanVersionCreated, false);
    });

    test('an edit saves the reviewer version, which the report then reads; the AI report is unchanged', async () => {
      const { repo, ai } = make();
      const aiBefore = structuredClone(ai());
      const first = await repo.applyStructuredEdit(KEY, smokeEdit(), ' Editor ');
      assert.deepEqual({ ...first, editedAt: typeof first.editedAt }, {
        incidentId: KEY.videoId, modelRunId: KEY.modelRunId, editedBy: 'Editor', editedAt: 'string', duration: 8, revision: 1, status: 'unreviewed',
      });
      const record = await repo.getRunReport(KEY);
      assert.deepEqual(record.incident, {
        type: 'assault', startSeconds: 1, endSeconds: 9, duration: 8, description: 'Reviewer: one person pushes the other over.', severityLevel: 3,
        confidenceScore: null,
      });
      assert.deepEqual(record.entities.map((entity) => entity.entityId), ['E1']);
      assert.deepEqual(record.assets.map((asset) => asset.name), ['white delivery van', 'blue car']);
      assert.deepEqual(record.review, { status: 'unreviewed', verifiedBy: null, verifiedAt: null, editedBy: 'Editor', editedAt: first.editedAt });
      assert.deepEqual(ai(), aiBefore);
      assert.equal((await repo.applyStructuredEdit(KEY, smokeEdit(), 'Editor')).revision, 2);
    });

    test('editing a verified report sends it back to under review and clears the verifier', async () => {
      const { repo } = make();
      await repo.setReviewStatus(KEY, 'verified', 'Lead');
      const result = await repo.applyStructuredEdit(KEY, smokeEdit(), 'Editor');
      assert.equal(result.status, 'under review');
      assert.equal(result.revision, 2, 'verifying created revision 1');
      assert.deepEqual(await repo.getReview(KEY), { status: 'under review', verifiedBy: null, verifiedAt: null, editedBy: 'Editor', editedAt: result.editedAt });
    });

    test('a review change or an edit of a missing run is refused', async () => {
      const { repo } = make();
      await assert.rejects(repo.setReviewStatus(OTHER_RUN, 'verified', 'Lead'), /Report not found/);
      await assert.rejects(repo.applyStructuredEdit(OTHER_RUN, smokeEdit(), 'Editor'), /Report not found/);
      assert.equal(await repo.getReview(OTHER_RUN), null);
    });

    test('deleting a run removes its report and review', async () => {
      const { repo } = make();
      await repo.deleteRun(KEY);
      assert.equal(await repo.runExists(KEY), false);
      assert.equal(await repo.getRunReport(KEY), null);
    });

    test('the library comes in pages with the exact total, newest first, field for field', async () => {
      const { repo } = make();
      assert.deepEqual(await repo.listReports({ ...LIBRARY, pageSize: 2 }), { items: [ASSAULT, REPAIRED], totalItems: 3, incidentTypes: ['assault', 'road accident'] });
      assert.deepEqual((await repo.listReports({ ...LIBRARY, page: 2, pageSize: 2 })).items, [LEGACY]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, sort: 'oldest' })).items, [LEGACY, REPAIRED, ASSAULT]);
    });

    test('official scope and a review status narrow the library', async () => {
      const { repo } = make();
      const official = await repo.listReports({ ...LIBRARY, scope: 'official' });
      assert.deepEqual([official.items, official.totalItems], [[ASSAULT], 1]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, status: 'under review' })).items, [REPAIRED]);
      assert.equal((await repo.listReports({ ...LIBRARY, status: 'rejected' })).totalItems, 0);
    });
  });
}

describe('Supabase adapter: reviewer version', () => {
  test('a run report is read from the effective views, never the AI tables', async () => {
    const { repo, db } = implementations.supabase();
    // A reviewer version stored without the console, as the midterm-to-finals copy writes it.
    db.store.human_reports = [{ incident_id: KEY.videoId, model_run_id: KEY.modelRunId, type: 'assault', start_seconds: 2, end_seconds: 6, description: 'Copied reviewer text', severity_level: 4, revision: 1 }];
    db.store.human_report_entities = [{ incident_id: KEY.videoId, model_run_id: KEY.modelRunId, entity_id: 'E1', source_entity_id: 'E2', type: 'human', description: 'Copied entity' }];
    const record = await repo.getRunReport(KEY);
    assert.deepEqual([record.incident.description, record.incident.startSeconds, record.incident.duration, record.incident.severityLevel], ['Copied reviewer text', 2, 4, 4]);
    assert.deepEqual(record.entities, [{ entityId: 'E1', type: 'human', description: 'Copied entity' }]);
    assert.deepEqual(record.assets, []);
    const read = db.requests.map((request) => request.path);
    assert.deepEqual(read.filter((path) => path.startsWith('effective_')).sort(), ['effective_assets', 'effective_entities', 'effective_incidents', 'effective_instruments']);
    for (const table of ['incidents', 'entities', 'instruments', 'assets']) assert.ok(!read.includes(table), `getRunReport reads ${table}`);
  });

  test('a review change is one set_review_status call and nothing else is written', async () => {
    const { repo, db } = implementations.supabase();
    await repo.setReviewStatus(KEY, 'under review', 'Lead');
    assert.deepEqual(db.requests, [{
      method: 'POST', path: 'rpc/set_review_status',
      body: { p_incident_id: KEY.videoId, p_model_run_id: KEY.modelRunId, p_status: 'under review', p_reviewer: 'Lead' },
    }]);
  });

  test('an edit is one save_human_report_edit call, not the apply_structured_report_edit shim', async () => {
    const { repo, db } = implementations.supabase();
    const edit = smokeEdit();
    await repo.applyStructuredEdit(KEY, edit, 'Editor');
    assert.deepEqual(db.requests, [{
      method: 'POST', path: 'rpc/save_human_report_edit',
      body: { p_incident_id: KEY.videoId, p_model_run_id: KEY.modelRunId, p_edit: edit, p_edited_by: 'Editor' },
    }]);
  });

  test('malformed RPC results map to safe values', () => {
    assert.deepEqual(reviewTransitionFromRpc(null, 'verified'), { changed: false, status: 'verified', verifiedBy: null, verifiedAt: null, humanVersionCreated: false });
    assert.deepEqual(structuredEditResultFromRpc({ status: 'rejected' }, KEY, smokeEdit(), ' Editor '), {
      incidentId: KEY.videoId, modelRunId: KEY.modelRunId, editedBy: 'Editor', editedAt: '', duration: 8, revision: 1, status: 'unreviewed',
    });
  });
});

describe('list_incident_report_summaries mapping', () => {
  test('the query becomes the nineteen RPC arguments', () => {
    assert.deepEqual(reportListRpcArgs({
      ...LIBRARY, page: 2, search: 'blade', type: 'assault', severity: '4', status: 'verified', generatedAfter: '2026-09-01T00:00:00',
      generatedBefore: '2026-09-28T00:00:00', timeFrom: '08:00', timeTo: '17:30', entities: ['person'], instruments: ['knife'], assets: ['door'],
      dayOfWeek: 1, sort: 'severity-high', scope: 'official', entityTypes: ['human'], evidenceMatch: 'exact', timezone: 'Asia/Singapore',
    }), {
      p_page: 2, p_page_size: 6, p_search: 'blade', p_type: 'assault', p_severity: '4', p_status: 'verified',
      p_generated_after: '2026-09-01T00:00:00', p_generated_before: '2026-09-28T00:00:00', p_time_from: '08:00', p_time_to: '17:30',
      p_entities: ['person'], p_instruments: ['knife'], p_assets: ['door'], p_day_of_week: 1, p_sort: 'severity-high', p_scope: 'official',
      p_entity_types: ['human'], p_evidence_match: 'exact', p_timezone: 'Asia/Singapore',
    });
  });

  test('a malformed result lists what it can with every field the library reads', () => {
    assert.deepEqual(reportListFromRpc(null), { items: [], totalItems: 0, incidentTypes: [] });
    const { items } = reportListFromRpc({ reports: [{ reportId: 'r1', isOfficial: 'yes' }], incidentTypes: ['assault', 7] });
    assert.deepEqual(items[0], {
      reportId: 'r1', videoId: '', modelRunId: '', title: '', filename: '', incident_type: '', description: '', severity: 1, confidence: null,
      generatedAt: null, uploadedAt: null, model: '', status: 'unreviewed', outcome: 'legacy', isOfficial: false,
      verifiedBy: null, verifiedAt: null, editedBy: null, editedAt: null, r2Key: null, sensorId: null,
    });
    assert.deepEqual(reportListFromRpc({ incidentTypes: ['assault', 7] }).incidentTypes, ['assault']);
  });
});

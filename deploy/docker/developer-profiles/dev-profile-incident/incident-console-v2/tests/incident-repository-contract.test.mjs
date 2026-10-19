// SPDX-License-Identifier: Apache-2.0

// One IncidentRepository contract, run against the in-memory fake and the
// Supabase adapter (over a fake PostgREST), so use-case tests that rely on the
// fake are testing behaviour the real adapter has. The fake PostgREST's
// list_incident_report_summaries applies paging, scope, status and
// newest/oldest order to SQL-shaped summaries; the other filters run in SQL
// and are pinned by the reports route tests.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../lib/adapters/memory/incidents.ts');
const { SupabaseIncidentAdapter } = await import('../lib/adapters/supabase/incidents.ts');
const { runReportFromRows } = await import('../lib/adapters/supabase/mappers/report.ts');
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

const implementations = {
  memory: () => new InMemoryIncidentRepository([runReportFromRows(smoke)], summaries.reports),
  supabase: () => {
    const db = fakePostgrest({
      videos: [smoke.video], model_runs: [smoke.modelRun], incidents: [smoke.incident], review_status: [smoke.review],
      entities: smoke.entities, instruments: smoke.instruments, assets: smoke.assets, reports: [smoke.reportRow],
    }, { rpc: { list_incident_report_summaries: listSummaries } });
    globalThis.fetch = db.fetch;
    return new SupabaseIncidentAdapter(new PostgrestClient('https://supabase.test', 'k'));
  },
};

for (const [name, make] of Object.entries(implementations)) {
  describe(`IncidentRepository contract: ${name}`, () => {
    test('a run is found by its full key only', async () => {
      const repo = make();
      assert.equal(await repo.runExists(KEY), true);
      assert.equal(await repo.runExists(OTHER_RUN), false);
      assert.equal(await repo.getRunReport(OTHER_RUN), null);
      const record = await repo.getRunReport(KEY);
      assert.deepEqual(record.key, KEY);
      assert.equal(record.modelRun.notes.kind, 'contract');
      assert.deepEqual(record.entities.map((entity) => entity.entityId), ['E1', 'E2']);
    });

    test('a saved review is read back exactly and stays scoped to its run', async () => {
      const repo = make();
      const review = { status: 'verified', verifiedBy: 'Lead', verifiedAt: '2026-10-17T01:00:00', editedBy: 'Lead', editedAt: '2026-10-17T01:00:00' };
      await repo.saveReview(KEY, review);
      assert.deepEqual(await repo.getReview(KEY), review);
      assert.deepEqual((await repo.getRunReport(KEY)).review, review);
      assert.equal(await repo.getReview(OTHER_RUN), null);
    });

    test('deleting a run removes its report and review', async () => {
      const repo = make();
      await repo.deleteRun(KEY);
      assert.equal(await repo.runExists(KEY), false);
      assert.equal(await repo.getRunReport(KEY), null);
    });

    test('the library comes in pages with the exact total, newest first, field for field', async () => {
      const repo = make();
      assert.deepEqual(await repo.listReports({ ...LIBRARY, pageSize: 2 }), { items: [ASSAULT, REPAIRED], totalItems: 3, incidentTypes: ['assault', 'road accident'] });
      assert.deepEqual((await repo.listReports({ ...LIBRARY, page: 2, pageSize: 2 })).items, [LEGACY]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, sort: 'oldest' })).items, [LEGACY, REPAIRED, ASSAULT]);
    });

    test('official scope and a review status narrow the library', async () => {
      const repo = make();
      const official = await repo.listReports({ ...LIBRARY, scope: 'official' });
      assert.deepEqual([official.items, official.totalItems], [[ASSAULT], 1]);
      assert.deepEqual((await repo.listReports({ ...LIBRARY, status: 'under review' })).items, [REPAIRED]);
      assert.equal((await repo.listReports({ ...LIBRARY, status: 'rejected' })).totalItems, 0);
    });
  });
}

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

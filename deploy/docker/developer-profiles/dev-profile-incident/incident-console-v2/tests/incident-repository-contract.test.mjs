// SPDX-License-Identifier: Apache-2.0

// One IncidentRepository contract, run against the in-memory fake and the
// Supabase adapter (over a fake PostgREST), so use-case tests that rely on the
// fake are testing behaviour the real adapter has.

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
const { PostgrestClient } = await import('../lib/postgrest/client.ts');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const KEY = { videoId: smoke.videoId, modelRunId: smoke.modelRunId };
const OTHER_RUN = { videoId: smoke.videoId, modelRunId: 'm-other' };
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const implementations = {
  memory: () => new InMemoryIncidentRepository([runReportFromRows(smoke)]),
  supabase: () => {
    const db = fakePostgrest({
      videos: [smoke.video], model_runs: [smoke.modelRun], incidents: [smoke.incident], review_status: [smoke.review],
      entities: smoke.entities, instruments: smoke.instruments, assets: smoke.assets, reports: [smoke.reportRow],
    });
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
  });
}

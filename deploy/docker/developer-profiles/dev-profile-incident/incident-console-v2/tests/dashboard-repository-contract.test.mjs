// SPDX-License-Identifier: Apache-2.0

// One DashboardRepository contract, run against the in-memory fake and the
// Supabase adapter over a fake PostgREST whose get_incident_dashboard keeps
// the SQL's period rule (no previous-period comparison without both bounds).
// The analytics themselves are computed in SQL; the route tests pin them.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryDashboardRepository } = await import('../src/modules/dashboard/infrastructure/memory/dashboard.ts');
const { SupabaseDashboardAdapter } = await import('../src/modules/dashboard/infrastructure/supabase/dashboard.ts');
const { dashboardFromRpc, dashboardRpcArgs } = await import('../src/modules/dashboard/infrastructure/supabase/mappers/dashboard.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');

const analytics = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const BOUNDED = {
  periodStart: new Date('2026-08-30T00:00:00.000Z'),
  periodEnd: new Date('2026-09-29T00:00:00.000Z'),
  type: null,
  severity: null,
  dayOfWeek: null,
  hour: null,
  timezone: 'UTC',
  scope: 'all',
};
const ALL_TIME = { ...BOUNDED, periodStart: null, periodEnd: null };

const implementations = {
  memory: () => new InMemoryDashboardRepository(analytics),
  supabase: () => {
    const db = fakePostgrest(
      {},
      {
        rpc: {
          get_incident_dashboard: (args) => ({
            ...analytics,
            previous: args.p_period_start === null || args.p_period_end === null ? null : analytics.previous,
          }),
        },
      },
    );
    globalThis.fetch = db.fetch;
    return new SupabaseDashboardAdapter(new PostgrestClient('https://supabase.test', 'k'));
  },
};

for (const [name, make] of Object.entries(implementations)) {
  describe(`DashboardRepository contract: ${name}`, () => {
    test('every section of the analytics comes back for a bounded period', async () => {
      assert.deepEqual(await make().getDashboard(BOUNDED), analytics);
    });

    test('a report-status query keeps its scope', async () => {
      const repository = make();
      assert.deepEqual(await repository.getDashboard({ ...BOUNDED, scope: 'not_official' }), analytics);
    });

    test('an all-time query has no previous-period comparison', async () => {
      assert.deepEqual(await make().getDashboard(ALL_TIME), { ...analytics, previous: null });
    });
  });
}

describe('get_incident_dashboard mapping', () => {
  test('the query becomes the eight RPC arguments, with the period as naive UTC', () => {
    assert.deepEqual(
      dashboardRpcArgs({
        ...BOUNDED,
        type: 'assault',
        severity: 'high',
        dayOfWeek: 2,
        hour: 23,
        timezone: 'Asia/Singapore',
        scope: 'official',
      }),
      {
        p_period_start: '2026-08-30T00:00:00.000',
        p_period_end: '2026-09-29T00:00:00.000',
        p_type: 'assault',
        p_severity: 'high',
        p_day_of_week: 2,
        p_hour: 23,
        p_timezone: 'Asia/Singapore',
        p_scope: 'official',
      },
    );
    assert.deepEqual(dashboardRpcArgs(ALL_TIME), {
      p_period_start: null,
      p_period_end: null,
      p_type: null,
      p_severity: null,
      p_day_of_week: null,
      p_hour: null,
      p_timezone: 'UTC',
      p_scope: 'all',
    });
  });

  test('a malformed result still has every section the dashboard reads', () => {
    const mapped = dashboardFromRpc({ total: 4, types: [{ type: 'assault' }], heatmap: [{ count: 2 }] });
    assert.equal(mapped.total, 4);
    assert.deepEqual(mapped.videos, { uploaded: 0, withOfficial: 0, awaitingSelection: 0, withoutReport: 0 });
    assert.equal(mapped.previous, null);
    assert.deepEqual(mapped.revisions, { ai: 0, human: 0 });
    assert.deepEqual(mapped.types, [
      {
        type: 'assault',
        count: 0,
        official: 0,
        notOfficial: 0,
        severity: { low: 0, medium: 0, high: 0 },
        entities: [],
        instruments: [],
        assets: [],
      },
    ]);
    assert.deepEqual(mapped.heatmap, [{ day: null, hour: null, count: 2, official: 0, notOfficial: 0 }]);
    assert.deepEqual(mapped.modelCoverage, []);
    assert.deepEqual(dashboardFromRpc(null).trend, []);
    assert.deepEqual(dashboardFromRpc(null).severityByScope.notOfficial, { low: 0, medium: 0, high: 0 });
    assert.equal(dashboardFromRpc(null).official, 0);
  });
});

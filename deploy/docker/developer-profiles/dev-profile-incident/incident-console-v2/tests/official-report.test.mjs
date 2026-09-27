// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { PUT, DELETE } = await import('../app/api/videos/[videoId]/official/route.ts');
const { buildReportView } = await import('../lib/reports/view.ts');
const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => { Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' }); });
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const call = (handler, body) => handler(new Request('http://localhost/x', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { params: Promise.resolve({ videoId: repaired.videoId }) });

test('selecting an official report calls only the explicit RPC with the reviewer name', async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => { calls.push({ path: new URL(String(url)).pathname, body: JSON.parse(String(init.body)) }); return new Response(JSON.stringify({ officialRunId: repaired.modelRunId })); };
  const response = await call(PUT, { modelRunId: repaired.modelRunId, selectedBy: 'Reviewer' });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [{ path: '/rest/v1/rpc/select_official_report', body: { p_video_id: repaired.videoId, p_model_run_id: repaired.modelRunId, p_selected_by: 'Reviewer' } }]);
});

test('the database refusal for a failed attempt surfaces as 422; missing names are 400', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ code: 'P0001', message: 'Only a successful analysis of this video that has a report can be the official report' }), { status: 400 });
  const refused = await call(PUT, { modelRunId: 'm-failed', selectedBy: 'Reviewer' });
  assert.equal(refused.status, 422);
  assert.match((await refused.json()).error, /successful analysis/);
  assert.equal((await call(PUT, { modelRunId: 'm1' })).status, 400);
  assert.equal((await call(DELETE, {})).status, 400);
});

test('clearing uses the clear RPC', async () => {
  const calls = [];
  globalThis.fetch = async (url) => { calls.push(new URL(String(url)).pathname); return new Response('{}'); };
  assert.equal((await call(DELETE, { clearedBy: 'Reviewer' })).status, 200);
  assert.deepEqual(calls, ['/rest/v1/rpc/clear_official_report']);
});

test('the report view marks the official run explicitly and never infers it from recency', () => {
  const none = buildReportView({ ...clone(repaired), playbackUrl: 'x' });
  assert.deepEqual(none.official, { officialRunId: null, selectedBy: null, selectedAt: null, isOfficial: false });
  const rows = clone(repaired);
  rows.video.selected_model_run_id = 'm86a5c319e26659804b0';
  rows.video.selected_by = 'Reviewer';
  rows.video.selected_at = '2026-09-27T12:00:00';
  const other = buildReportView({ ...rows, playbackUrl: 'x' });
  assert.equal(other.official.isOfficial, false, 'a newer run is not official just because it is newer');
  rows.video.selected_model_run_id = repaired.modelRunId;
  const official = buildReportView({ ...rows, playbackUrl: 'x' });
  assert.equal(official.official.isOfficial, true);
  assert.equal(official.official.selectedBy, 'Reviewer');
});

test('analysis code never writes the official-selection columns', async () => {
  const { readFile } = await import('node:fs/promises');
  for (const file of ['lib/analysis/persistence.ts', 'lib/analysis/run-contract-analysis.ts', 'app/api/analysis/route.ts', 'app/api/videos/[videoId]/runs/route.ts']) {
    const source = await readFile(join(process.cwd(), file), 'utf8');
    // No object key assigning the column (reads such as `video.selected_model_run_id` are fine) and no selection RPC.
    assert.doesNotMatch(source, /[{,]\s*selected_(model_run_id|by|at):|select_official_report/, file);
  }
});

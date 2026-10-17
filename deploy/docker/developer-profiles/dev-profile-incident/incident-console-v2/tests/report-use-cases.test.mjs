// SPDX-License-Identifier: Apache-2.0

// Use cases tested against the in-memory fake: no fetch, no PostgREST, no R2.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentRepository } = await import('../lib/adapters/memory/incidents.ts');
const { runReportFromRows } = await import('../lib/adapters/supabase/mappers/report.ts');
const { changeReviewStatus, getReport } = await import('../lib/application/reports.ts');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const KEY = { videoId: smoke.videoId, modelRunId: smoke.modelRunId };
const clock = () => new Date('2026-10-17T02:00:00.000Z');

test('verifying a run records reviewer and time once; repeating it changes nothing', async () => {
  const incidents = new InMemoryIncidentRepository([runReportFromRows({ ...smoke, review: null })]);
  assert.deepEqual(await changeReviewStatus(incidents, KEY, 'verified', 'Lead', clock), { kind: 'changed', at: '2026-10-17T02:00:00.000Z' });
  assert.deepEqual(await incidents.getReview(KEY), { status: 'verified', editedBy: 'Lead', editedAt: '2026-10-17T02:00:00.000Z', verifiedBy: 'Lead', verifiedAt: '2026-10-17T02:00:00.000Z' });
  assert.deepEqual(await changeReviewStatus(incidents, KEY, 'verified', 'Someone else', clock), { kind: 'unchanged' });
  assert.deepEqual(await changeReviewStatus(incidents, { ...KEY, modelRunId: 'm-none' }, 'verified', 'Lead', clock), { kind: 'not-found' });
});

test('getReport signs the stored key and refuses a run without one', async () => {
  const incidents = new InMemoryIncidentRepository([runReportFromRows(smoke)]);
  const signed = [];
  const view = await getReport(incidents, KEY, async (key) => { signed.push(key); return 'https://signed/x'; });
  assert.deepEqual(signed, [smoke.video.filepath]);
  assert.equal(view.run.playbackUrl, 'https://signed/x');
  assert.equal(await getReport(incidents, { ...KEY, modelRunId: 'm-none' }, async () => 'unused'), null);

  const noVideo = new InMemoryIncidentRepository([runReportFromRows({ ...smoke, video: { ...smoke.video, filepath: '' } })]);
  await assert.rejects(getReport(noVideo, KEY, async () => 'unused'), /The report has no linked R2 video/);
});

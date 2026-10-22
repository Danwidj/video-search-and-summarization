// SPDX-License-Identifier: Apache-2.0

// One VideoRepository contract, run against the in-memory fake and the Supabase
// adapter over a fake PostgREST whose RPCs mimic select_official_report /
// clear_official_report (20261020000000_finals_baseline.sql).
// listVideos' embedded select is covered by tests/videos-route.test.mjs.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryVideoRepository } = await import('../lib/adapters/memory/videos.ts');
const { SupabaseVideoAdapter } = await import('../lib/adapters/supabase/videos.ts');
const { StoreRejection } = await import('../lib/ports/common.ts');
const { PostgrestClient } = await import('../lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const VIDEO = { videoId: 'v1', storageKey: 'uploads/sensor-1/v1.mp4', uploadedAt: '2026-10-01T08:00:00', source: 'sensor-1', officialRunId: null };
const attempt = (id, videoId, status) => ({ id, notes: JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status, videoId } }) });

function officialRpcs() {
  const reviewer = (name) => { if (!name || !name.trim()) throw new Error('A reviewer name is required'); return name.trim(); };
  return {
    select_official_report: ({ p_video_id, p_model_run_id, p_selected_by }, store) => {
      const selectedBy = reviewer(p_selected_by);
      const video = store.videos.find((row) => row.id === p_video_id);
      if (!video) throw new Error('Video not found');
      const reported = store.reports.some((row) => row.incident_id === p_video_id && row.model_run_id === p_model_run_id)
        && store.incidents.some((row) => row.incident_id === p_video_id && row.model_run_id === p_model_run_id);
      if (!reported) throw new Error('Only a successful analysis of this video that has a report can be the official report');
      Object.assign(video, { selected_model_run_id: p_model_run_id, selected_by: selectedBy, selected_at: '2026-10-17T02:00:00' });
      return { videoId: p_video_id, officialRunId: p_model_run_id, selectedBy, selectedAt: '2026-10-17T02:00:00' };
    },
    clear_official_report: ({ p_video_id, p_cleared_by }, store) => {
      const clearedBy = reviewer(p_cleared_by);
      const video = store.videos.find((row) => row.id === p_video_id);
      if (!video) throw new Error('Video not found');
      Object.assign(video, { selected_model_run_id: null, selected_by: null, selected_at: null });
      return { videoId: p_video_id, officialRunId: null, clearedBy };
    },
  };
}

const implementations = {
  memory: () => ({ repo: new InMemoryVideoRepository([{ ...VIDEO, runsWithReport: ['m1'] }]) }),
  supabase: () => {
    const db = fakePostgrest({
      videos: [{ id: 'v1', filepath: VIDEO.storageKey, uploaded_datetime: VIDEO.uploadedAt, source: VIDEO.source, selected_model_run_id: null }],
      incidents: [{ incident_id: 'v1', model_run_id: 'm1' }],
      reports: [{ id: 'r1', incident_id: 'v1', model_run_id: 'm1' }],
      model_runs: [attempt('m-failed', 'v1', 'contract_failed'), attempt('m-other', 'v2', 'contract_failed'), attempt('m1', 'v1', 'valid_first_pass')],
    }, { rpc: officialRpcs() });
    globalThis.fetch = db.fetch;
    return { repo: new SupabaseVideoAdapter(new PostgrestClient('https://supabase.test', 'k')), store: db.store };
  },
};

const rejection = (reason, message) => (error) => error instanceof StoreRejection && error.reason === reason && message.test(error.message);

for (const [name, make] of Object.entries(implementations)) {
  describe(`VideoRepository contract: ${name}`, () => {
    test('a video is read by id; an unknown one is null', async () => {
      const { repo } = make();
      assert.deepEqual(await repo.getVideo('v1'), VIDEO);
      assert.equal(await repo.getVideo('v-none'), null);
    });

    test('a run with a report becomes official and can be cleared', async () => {
      const { repo } = make();
      const selection = await repo.selectOfficialRun('v1', 'm1', ' Lead ');
      assert.equal(selection.videoId, 'v1');
      assert.equal(selection.officialRunId, 'm1');
      assert.equal(selection.selectedBy, 'Lead');
      assert.match(selection.selectedAt, /^\d{4}-\d\d-\d\dT/);
      assert.equal((await repo.getVideo('v1')).officialRunId, 'm1');
      assert.deepEqual(await repo.clearOfficialRun('v1', 'Lead'), { videoId: 'v1', officialRunId: null, clearedBy: 'Lead' });
      assert.equal((await repo.getVideo('v1')).officialRunId, null);
    });

    test('refusals are domain rejections, not transport errors', async () => {
      const { repo } = make();
      await assert.rejects(repo.selectOfficialRun('v1', 'm-failed', 'Lead'), rejection('invalid', /successful analysis/));
      await assert.rejects(repo.selectOfficialRun('v-none', 'm1', 'Lead'), rejection('not-found', /Video not found/));
      await assert.rejects(repo.selectOfficialRun('v1', 'm1', '  '), rejection('invalid', /reviewer name/));
      await assert.rejects(repo.clearOfficialRun('v-none', 'Lead'), rejection('not-found', /Video not found/));
    });

    test('a deleted video is gone', async () => {
      const { repo } = make();
      await repo.deleteVideo('v1');
      assert.equal(await repo.getVideo('v1'), null);
    });
  });
}

describe('SupabaseVideoAdapter', () => {
  test('deleting a video removes only the incident-less run records that name it', async () => {
    const { repo, store } = implementations.supabase();
    store.incidents = [];
    await repo.deleteVideo('v1');
    assert.deepEqual(store.model_runs.map((row) => row.id), ['m-other']);
  });

  test('other PostgREST failures are not turned into rejections', async () => {
    globalThis.fetch = async () => new Response('{"message":"permission denied"}', { status: 401 });
    const repo = new SupabaseVideoAdapter(new PostgrestClient('https://supabase.test', 'k'));
    await assert.rejects(repo.selectOfficialRun('v1', 'm1', 'Lead'), (error) => !(error instanceof StoreRejection) && /HTTP 401/.test(error.message));
  });
});

// listRuns: the fake PostgREST does not embed, so the run's model_runs and
// reports rows sit on its incident row; effective_incidents comes from
// tests/support/finals-database.mjs. The fake video stores the same history
// as entries, so both are held to one order, count and official mark.
const { effectiveViews } = await import('./support/finals-database.mjs');
const failedNotes = { recordType: 'analysis_attempt', status: 'contract_failed', contractVersion: 'incident-contract-v3', videoId: 'v1', attemptedAt: '2026-10-02T09:00:00.000Z', stage: 'contract_validation', failure: { code: 'WINDOW_END_BEFORE_START', message: 'x' }, request: { model: 'nvidia/cosmos-3-super-reasoner', additionalInstruction: null }, response: null, validation: { firstPass: [] }, repair: null };
const historyEntry = (modelRunId, outcome, attemptedAt, report) => ({
  modelRunId, model: 'nvidia/cosmos-3-super-reasoner', attemptedAt, outcome, outcomeInferred: outcome === 'legacy', source: 'other', report, reportRemoved: false,
  additionalInstruction: null, failure: null, repair: null,
});

const runHistoryImplementations = {
  memory: () => new InMemoryVideoRepository([{
    ...VIDEO, officialRunId: 'm1', runsWithReport: ['m1'],
    history: [
      historyEntry('m1', 'legacy', '2026-10-01T09:00:00', { reportId: 'r1', type: 'assault', severityLevel: 3 }),
      historyEntry('m-failed', 'contract_failed', '2026-10-02T09:00:00.000Z', null),
    ],
  }]),
  supabase: () => {
    const modelRun = { id: 'm1', model_name: 'nvidia/cosmos-3-super-reasoner', run_datetime: '2026-10-01T09:00:00', notes: null };
    const db = fakePostgrest({
      videos: [{ id: 'v1', filepath: VIDEO.storageKey, uploaded_datetime: VIDEO.uploadedAt, source: VIDEO.source, selected_model_run_id: 'm1' }],
      incidents: [{ incident_id: 'v1', model_run_id: 'm1', type: 'assault', severity_level: 3, model_runs: modelRun, reports: [{ id: 'r1', generated_datetime: '2026-10-01T09:00:00' }] }],
      model_runs: [modelRun, { id: 'm-failed', model_name: 'nvidia/cosmos-3-super-reasoner', run_datetime: '2026-10-02T09:00:00', notes: JSON.stringify({ incidentConsoleV2: failedNotes }) }, attempt('m-other', 'v2', 'contract_failed')],
    }, { views: effectiveViews });
    globalThis.fetch = db.fetch;
    return new SupabaseVideoAdapter(new PostgrestClient('https://supabase.test', 'k'));
  },
};

for (const [name, make] of Object.entries(runHistoryImplementations)) {
  describe(`VideoRepository.listRuns contract: ${name}`, () => {
    test("a video's runs are newest first, counted by outcome, with the official run marked", async () => {
      const found = await make().listRuns('v1');
      assert.deepEqual(found.video, { ...VIDEO, officialRunId: 'm1' });
      assert.deepEqual(found.runs.map((run) => [run.modelRunId, run.outcome, run.report?.reportId ?? null, run.isOfficial]), [
        ['m-failed', 'contract_failed', null, false],
        ['m1', 'legacy', 'r1', true],
      ]);
      assert.deepEqual(found.runs[1].report, { reportId: 'r1', type: 'assault', severityLevel: 3 });
      assert.deepEqual(found.counts, { attempts: 2, withReport: 1, valid_first_pass: 0, valid_after_structural_repair: 0, contract_failed: 1, request_failed: 0, legacy: 1 });
    });

    test('an unknown video has no history', async () => {
      assert.equal(await make().listRuns('v-none'), null);
    });
  });
}

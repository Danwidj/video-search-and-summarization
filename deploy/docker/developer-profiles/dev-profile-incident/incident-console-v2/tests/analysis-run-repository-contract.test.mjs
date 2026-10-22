// SPDX-License-Identifier: Apache-2.0

// One AnalysisRunRepository contract, run against the in-memory fake and the
// Supabase adapter over a fake PostgREST whose insert_incident RPC creates the
// incident and its review_status row, as the finals baseline does. What each
// store holds afterwards is read back through a per-implementation peek().

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';
import { officialSelectionWrites } from './support/official-selection.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryAnalysisRunRepository } = await import('../lib/adapters/memory/analysis-runs.ts');
const { SupabaseAnalysisRunAdapter, attemptNotes } = await import('../lib/adapters/supabase/analysis-runs.ts');
const { withDerivedFields } = await import('../lib/contract/validate.ts');
const { PostgrestClient } = await import('../lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const report = withDerivedFields(JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'full-report.json'), 'utf8')));
const VIDEO = { videoId: 'v1', r2Key: 'uploads/sensor-1/clip.mp4', sensorId: 'sensor-1', uploadedAt: '2026-10-22T08:00:00.000Z' };

const attempt = (modelRunId, status, extra = {}) => ({
  status,
  stage: status === 'request_failed' ? 'gateway' : status === 'contract_failed' ? 'contract_validation' : null,
  failure: status.startsWith('valid') ? null : { code: 'X', message: 'x' },
  contractVersion: 'incident-contract-v3',
  videoId: VIDEO.videoId,
  r2Key: VIDEO.r2Key,
  modelRunId,
  attemptedAt: '2026-10-22T09:00:00.000Z',
  request: { model: 'nvidia/cosmos-3-super-reasoner', inferenceConfig: {}, additionalInstruction: null, promptSha256: 'p', schemaSha256: 's', videoDurationSeconds: 12 },
  response: { content: '{}' },
  validation: { firstPass: [] },
  repair: null,
  ...extra,
});
const validRun = (modelRunId, extra = {}) => attempt(modelRunId, 'valid_first_pass', { reportId: `r-${modelRunId}`, generatedAt: '2026-10-22T09:00:00.000Z', report, ...extra });

function insertIncident(args, store) {
  (store.incidents ??= []).push({ incident_id: args.p_incident_id, model_run_id: args.p_model_run_id, type: args.p_type, severity_level: args.p_severity_level });
  (store.review_status ??= []).push({ incident_id: args.p_incident_id, model_run_id: args.p_model_run_id, status: 'unreviewed' });
}

const implementations = {
  memory: () => {
    const repo = new InMemoryAnalysisRunRepository();
    return {
      repo,
      peek: () => ({
        videos: Object.fromEntries([...repo.videos.values()].map((video) => [video.videoId, [video.r2Key, video.uploadedAt]])),
        attempts: [...repo.attempts.keys()].sort(),
        reported: [...repo.runs.keys()].sort(),
      }),
    };
  },
  supabase: () => {
    const db = fakePostgrest({ videos: [], model_runs: [], incidents: [], reports: [] }, { rpc: { insert_incident: insertIncident } });
    globalThis.fetch = db.fetch;
    return {
      repo: new SupabaseAnalysisRunAdapter(new PostgrestClient('https://supabase.test', 'k')),
      db,
      peek: () => ({
        videos: Object.fromEntries(db.store.videos.map((row) => [row.id, [row.filepath, row.uploaded_datetime]])),
        attempts: db.store.model_runs.map((row) => row.id).sort(),
        reported: db.store.reports.map((row) => row.model_run_id).sort(),
      }),
    };
  },
};

for (const [name, make] of Object.entries(implementations)) {
  describe(`AnalysisRunRepository contract: ${name}`, () => {
    test('an uploaded video is recorded once; a later record never resets it', async () => {
      const { repo, peek } = make();
      await repo.recordUploadedVideo(VIDEO);
      await repo.recordUploadedVideo({ ...VIDEO, r2Key: 'uploads/sensor-1/other.mp4', uploadedAt: '2026-10-23T08:00:00.000Z' });
      assert.deepEqual(peek().videos, { v1: [VIDEO.r2Key, VIDEO.uploadedAt] });
    });

    test('a failed attempt is a run record only, never a report', async () => {
      const { repo, peek } = make();
      await repo.recordUploadedVideo(VIDEO);
      await repo.saveFailedAttempt(attempt('m-cf', 'contract_failed'));
      await repo.saveFailedAttempt(attempt('m-rf', 'request_failed', { response: null }));
      assert.deepEqual(peek(), { videos: { v1: [VIDEO.r2Key, VIDEO.uploadedAt] }, attempts: ['m-cf', 'm-rf'], reported: [] });
    });

    test('a valid attempt cannot be saved as a failure', async () => {
      const { repo, peek } = make();
      await assert.rejects(repo.saveFailedAttempt(validRun('m1')), /saveFailedAttempt called with a valid_first_pass attempt/);
      assert.deepEqual(peek().attempts, []);
    });

    test('a valid run is saved whole and read back, reporting each step', async () => {
      const { repo, peek } = make();
      await repo.recordUploadedVideo(VIDEO);
      const steps = [];
      await repo.saveRun(validRun('m1'), (step) => steps.push(step));
      assert.deepEqual(peek(), { videos: { v1: [VIDEO.r2Key, VIDEO.uploadedAt] }, attempts: ['m1'], reported: ['m1'] });
      assert.ok(steps.length >= 2);
      assert.match(steps.at(-1), /^verifying/);
    });

    test('the read-back refuses a run whose video is missing or stored under another key', async () => {
      const { repo } = make();
      await assert.rejects(repo.saveRun(validRun('m1')), /persistence verification found missing rows: videos/);
      await repo.recordUploadedVideo(VIDEO);
      await assert.rejects(repo.saveRun(validRun('m2', { r2Key: 'uploads/sensor-1/elsewhere.mp4' })), /unexpected videos\.filepath/);
    });
  });
}

describe('SupabaseAnalysisRunAdapter', () => {
  test('a valid run is written in order: run record, incident RPC, evidence, report, then the read-back', async () => {
    const { repo, db } = implementations.supabase();
    await repo.recordUploadedVideo(VIDEO);
    const run = validRun('m1');
    await repo.saveRun(run);
    const writes = db.requests.filter((request) => request.method === 'POST').map((request) => request.path);
    assert.deepEqual(writes, ['videos', 'model_runs', 'rpc/insert_incident', 'entities', 'instruments', 'assets', 'reports']);
    const modelRun = db.store.model_runs[0];
    assert.equal(modelRun.notes, attemptNotes(run), 'the immutable attempt record is the notes');
    assert.equal(JSON.parse(modelRun.notes).incidentConsoleV2.recordType, 'analysis_attempt');
    const incident = db.requests.find((request) => request.path === 'rpc/insert_incident').body;
    assert.equal(incident.p_start_timestamp, String(report.incident.start_timestamp), 'timestamps are stored as text seconds');
    assert.equal(incident.p_duration, report.incident.duration);
    assert.deepEqual(db.store.review_status.map((row) => row.model_run_id), ['m1']);
    assert.deepEqual(db.store.entities.map((row) => [row.entity_id, row.image]), report.entities.map((entity) => [entity.entity_id, null]));
  });

  test('empty evidence lists are not written', async () => {
    const { repo, db } = implementations.supabase();
    await repo.recordUploadedVideo(VIDEO);
    await repo.saveRun(validRun('m1', { report: { ...report, entities: [], instruments: [], assets: [] } }));
    const writes = db.requests.filter((request) => request.method === 'POST').map((request) => request.path);
    assert.deepEqual(writes, ['videos', 'model_runs', 'rpc/insert_incident', 'reports']);
  });

  test('recording a video, failed attempts and a valid run never sets or clears the official report', async () => {
    const { repo, db } = implementations.supabase();
    db.store.videos.push({ id: 'v0', filepath: 'uploads/sensor-1/old.mp4', selected_model_run_id: 'm0', selected_by: 'Reviewer', selected_at: '2026-10-21T08:00:00.000Z' });
    await repo.recordUploadedVideo(VIDEO);
    await repo.recordUploadedVideo({ ...VIDEO, videoId: 'v0', r2Key: 'uploads/sensor-1/old.mp4' });
    await repo.saveFailedAttempt(attempt('m-cf', 'contract_failed'));
    await repo.saveFailedAttempt(attempt('m-rf', 'request_failed', { response: null }));
    await repo.saveRun(validRun('m1'));
    await repo.saveRun(validRun('m2', { videoId: 'v0', r2Key: 'uploads/sensor-1/old.mp4' }));
    assert.deepEqual(officialSelectionWrites(db.requests), []);
    assert.deepEqual(db.store.videos.map((row) => [row.id, row.selected_model_run_id ?? null]), [['v0', 'm0'], ['v1', null]]);
  });

  test('a failed attempt is stored with its attempt time and notes', async () => {
    const { repo, db } = implementations.supabase();
    const failed = attempt('m-cf', 'contract_failed');
    await repo.saveFailedAttempt(failed);
    assert.deepEqual(db.store.model_runs, [{
      id: 'm-cf', model_name: failed.request.model, model_version: null, prompt_version: failed.contractVersion, run_datetime: failed.attemptedAt, notes: attemptNotes(failed),
    }]);
  });
});

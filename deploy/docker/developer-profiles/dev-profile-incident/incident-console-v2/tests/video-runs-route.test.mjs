// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class { send(command) { return Promise.resolve(command.constructor.name === 'HeadObjectCommand' ? { ContentLength: 2048 } : {}); } },
    GetObjectCommand: class { constructor(input) { this.input = input; } },
    PutObjectCommand: class { constructor(input) { this.input = input; } },
    HeadObjectCommand: class HeadObjectCommand { constructor(input) { this.input = input; } },
    DeleteObjectCommand: class { constructor(input) { this.input = input; } },
  },
});
mock.module('@aws-sdk/s3-request-presigner', { namedExports: { getSignedUrl: async () => 'https://signed.r2.test/stored.mp4' } });

const { GET, POST } = await import('../app/api/videos/[videoId]/runs/route.ts');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { aiRevisionRow } = await import('./support/report-view.mjs');
const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const validReport = readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'full-report.json'), 'utf8');
const timelineFailure = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-failures', 'cosmos-3-super-timeline-window.json'), 'utf8')).rawContent;
const coreFailure = readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'invalid', 'cross-end-before-start.json'), 'utf8');
const V = repaired.videoId;
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  Object.assign(process.env, {
    ANALYSIS_MODE: 'gateway', VLM_GATEWAY_URL: 'http://gateway.test:8600', INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a', R2_ACCESS_KEY: 'b', R2_SECRET_KEY: 'c', R2_BUCKET: 'd',
  });
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

/** The repaired video with its AI revision (and optionally the failed attempt), plus a gateway that answers with `completionContent`. */
function services(completionContent, { extraRuns = [], official = null } = {}) {
  const gatewayCalls = [];
  const db = fakePostgrest(
    { videos: [{ ...repaired.video, official_revision_id: official }], model_runs: [repaired.modelRun, ...extraRuns], report_revisions: [aiRevisionRow(repaired)] },
    { identity: { report_revisions: 'id' } },
  );
  globalThis.fetch = async (url, init = {}) => {
    if (String(url).includes('/v1/chat/completions')) {
      gatewayCalls.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ choices: [{ message: { content: completionContent }, finish_reason: 'stop' }], usage: {} }));
    }
    return db.fetch(url, init);
  };
  return { db, gatewayCalls };
}
const post = (body) => POST(new Request(`http://localhost/api/videos/${V}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { params: Promise.resolve({ videoId: V }) });
const history = () => GET(new Request(`http://localhost/api/videos/${V}/runs`), { params: Promise.resolve({ videoId: V }) });
const writes = (db) => db.requests.filter((r) => r.method !== 'GET');

test('re-analysis uses the stored video object, creates a new run and a new AI revision, and never writes the videos row', async () => {
  const { db, gatewayCalls } = services(validReport);
  const response = await post({ model: 'nvidia/cosmos-3-super-reasoner', additionalInstruction: 'Pay particular attention to the person entering from the left side of the frame.' });
  assert.equal(response.status, 200);
  const { run } = await response.json();
  assert.equal(run.videoId, V);
  assert.notEqual(run.modelRunId, repaired.modelRunId);
  assert.equal(run.outcome, 'valid_first_pass');
  assert.equal(run.revisionId, 2);
  assert.ok(!writes(db).some((r) => r.path === 'videos'), 'the video row (and its upload time) is never written by a re-run');
  assert.equal(gatewayCalls[0].model, 'nvidia/cosmos-3-super-reasoner');
  assert.equal(gatewayCalls[0].messages[0].content.length, 3, 'canonical video + prompt parts, plus the fenced instruction');
  assert.match(gatewayCalls[0].messages[0].content[2].text, /<<<\nPay particular attention/);
  const modelRun = db.store.model_runs.find((row) => row.id === run.modelRunId);
  const notes = JSON.parse(modelRun.notes).incidentConsoleV2;
  assert.equal(notes.request.additionalInstruction, 'Pay particular attention to the person entering from the left side of the frame.');
  assert.equal(notes.videoId, V);
  const revision = db.store.report_revisions.find((row) => row.id === 2);
  assert.deepEqual([revision.video_id, revision.revision_no, revision.kind, revision.model_run_id, revision.parent_id], [V, 2, 'ai', run.modelRunId, null]);
  assert.deepEqual(db.store.report_revisions[0], aiRevisionRow(repaired), 'the earlier revision is untouched; edits are not carried across');
  assert.equal(db.store.videos[0].official_revision_id, null, 'the new version is not made official');
});

test('a failed re-run is recorded in history only and returns its reason', async () => {
  const { db } = services(coreFailure);
  const response = await post({ model: 'nvidia/cosmos-3-super-reasoner' });
  assert.equal(response.status, 422);
  const payload = await response.json();
  assert.equal(payload.outcome, 'contract_failed');
  assert.deepEqual(payload.codes, ['WINDOW_END_BEFORE_START'], 'the failure names the core violation only');
  assert.deepEqual(writes(db).map((r) => r.path), ['model_runs'], 'only the attempt record; no revision, evidence or video rows');
  assert.equal(db.store.report_revisions.length, 1);
});

test('a re-run whose only problem is its timeline gets its own revision (core-scored-v1)', async () => {
  const { db } = services(timelineFailure);
  const response = await post({ model: 'nvidia/cosmos-3-super-reasoner' });
  assert.equal(response.status, 200);
  assert.deepEqual(writes(db).map((r) => r.path), ['model_runs', 'report_revisions']);
  const notes = JSON.parse(db.store.model_runs.at(-1).notes).incidentConsoleV2;
  assert.equal(notes.status, 'valid_first_pass');
  assert.equal(notes.validation.fullContractValid, false);
  assert.equal(notes.response.content, timelineFailure);
});

test('re-analysis refuses unknown models, other models in agent mode and a missing video', async () => {
  const { gatewayCalls, db } = services(validReport);
  assert.equal((await post({ model: 'some/other-model' })).status, 400);
  process.env.ANALYSIS_MODE = 'agent';
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000';
  assert.equal((await post({ model: 'nvidia/cosmos-3-super-reasoner' })).status, 409, 'the agent runs its configured model (nano by default)');
  assert.equal(gatewayCalls.length, 0);
  process.env.ANALYSIS_MODE = 'gateway';
  db.store.videos.length = 0;
  assert.equal((await post({ model: 'nvidia/cosmos-3-super-reasoner' })).status, 404);
  assert.deepEqual(writes(db), []);
});

test('history GET combines revision-backed runs with explicitly associated attempts', async () => {
  const failed = { id: 'm-cf', model_name: 'nvidia/cosmos-3-super-reasoner', run_datetime: '2026-09-27T12:00:00', notes: JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status: 'contract_failed', contractVersion: 'incident-contract-v2', videoId: V, attemptedAt: '2026-09-27T12:00:00Z', stage: 'contract_validation', failure: { code: 'TIMELINE_START_OUTSIDE_WINDOW', message: 'x' }, request: { model: 'nvidia/cosmos-3-super-reasoner' }, validation: { firstPass: [] }, repair: null } }) };
  // The fake PostgREST does not embed, so the run's model_runs row sits on its revision row.
  const { db } = services(validReport, { extraRuns: [failed], official: 1 });
  db.store.report_revisions[0].model_runs = repaired.modelRun;
  const response = await history();
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.video.uploadedAt, repaired.video.uploaded_datetime);
  assert.deepEqual(body.runs.map((run) => [run.modelRunId, run.outcome, run.revision?.revisionId ?? null, run.isOfficial]), [['m-cf', 'contract_failed', null, false], [repaired.modelRunId, 'valid_after_structural_repair', 1, true]]);
  assert.equal(body.counts.withReport, 1);
  assert.equal(body.officialRevisionId, 1);
});

test('history of an unknown video is 404', async () => {
  const { db } = services(validReport);
  db.store.videos.length = 0;
  assert.equal((await history()).status, 404);
});

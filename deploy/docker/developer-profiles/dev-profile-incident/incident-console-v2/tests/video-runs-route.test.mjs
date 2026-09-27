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
const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const validReport = readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'full-report.json'), 'utf8');
const timelineFailure = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-failures', 'cosmos-3-super-timeline-window.json'), 'utf8')).rawContent;
const V = repaired.videoId;
const R2_KEY = repaired.video.filepath;
const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

beforeEach(() => {
  Object.assign(process.env, {
    ANALYSIS_MODE: 'gateway', VLM_GATEWAY_URL: 'http://gateway.test:8600', INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a', R2_ACCESS_KEY: 'b', R2_SECRET_KEY: 'c', R2_BUCKET: 'd',
  });
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

function db(calls, completionContent) {
  return async (url, init = {}) => {
    const parsed = new URL(String(url));
    const path = parsed.pathname.replace('/rest/v1/', '');
    calls.push({ path, method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined, params: parsed.searchParams });
    if (String(url).includes('/v1/chat/completions')) {
      return new Response(JSON.stringify({ choices: [{ message: { content: completionContent }, finish_reason: 'stop' }], usage: {} }));
    }
    if (path === 'videos') return new Response(JSON.stringify([{ ...repaired.video }]));
    if (path === 'model_runs' && (init.method || 'GET') === 'GET') return new Response(JSON.stringify([{ id: parsed.searchParams.get('id')?.replace('eq.', '') }]));
    if (path === 'incidents') return new Response(JSON.stringify([{ incident_id: V, model_run_id: parsed.searchParams.get('model_run_id')?.replace('eq.', '') }]));
    if (path === 'reports') return new Response(JSON.stringify([{ id: 'r', incident_id: V, model_run_id: 'x' }]));
    return new Response(JSON.stringify([{ ok: true }]));
  };
}
const post = (body) => POST(new Request(`http://localhost/api/videos/${V}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { params: Promise.resolve({ videoId: V }) });

test('re-analysis uses the stored video object, creates a new run and never writes the videos row', async () => {
  const calls = [];
  globalThis.fetch = db(calls, validReport);
  const response = await post({ model: 'nvidia/cosmos-3-super-reasoner', additionalInstruction: 'Pay particular attention to the person entering from the left side of the frame.' });
  assert.equal(response.status, 200);
  const { run } = await response.json();
  assert.equal(run.videoId, V);
  assert.notEqual(run.modelRunId, repaired.modelRunId);
  assert.equal(run.outcome, 'valid_first_pass');
  const writes = calls.filter((c) => c.method !== 'GET' && !c.path.endsWith('chat/completions'));
  assert.ok(!writes.some((c) => c.path === 'videos'), 'the video row (and its upload time) is never written by a re-run');
  const gateway = calls.find((c) => c.path.endsWith('chat/completions'));
  assert.equal(gateway.body.model, 'nvidia/cosmos-3-super-reasoner');
  assert.equal(gateway.body.messages[0].content.length, 3, 'canonical video + prompt parts, plus the fenced instruction');
  assert.match(gateway.body.messages[0].content[2].text, /<<<\nPay particular attention/);
  const modelRun = writes.find((c) => c.path === 'model_runs');
  const notes = JSON.parse(modelRun.body.notes).incidentConsoleV2;
  assert.equal(notes.request.additionalInstruction, 'Pay particular attention to the person entering from the left side of the frame.');
  assert.equal(notes.videoId, V);
  assert.ok(writes.some((c) => c.path === 'rpc/insert_incident'), 'a successful re-run gets its own report rows');
});

test('a failed re-run is recorded in history only and returns its reason', async () => {
  const calls = [];
  globalThis.fetch = db(calls, timelineFailure);
  const response = await post({ model: 'nvidia/cosmos-3-super-reasoner' });
  assert.equal(response.status, 422);
  const payload = await response.json();
  assert.equal(payload.outcome, 'contract_failed');
  assert.deepEqual(payload.codes.sort(), ['TIMELINE_END_OUTSIDE_WINDOW', 'TIMELINE_START_OUTSIDE_WINDOW']);
  const writes = calls.filter((c) => c.method !== 'GET' && !c.path.endsWith('chat/completions')).map((c) => c.path);
  assert.deepEqual(writes, ['model_runs'], 'only the attempt record; no report, incident, evidence, review or video rows');
});

test('re-analysis refuses unknown models, missing videos and agent mode', async () => {
  const calls = [];
  globalThis.fetch = db(calls, validReport);
  assert.equal((await post({ model: 'some/other-model' })).status, 400);
  process.env.ANALYSIS_MODE = 'agent';
  assert.equal((await post({ model: 'nvidia/cosmos-3-nano-reasoner' })).status, 409);
  assert.ok(!calls.some((c) => c.path.endsWith('chat/completions')));
});

test('history GET combines incident-backed runs with explicitly associated attempts', async () => {
  const failed = { id: 'm-cf', model_name: 'nvidia/cosmos-3-super-reasoner', run_datetime: '2026-09-27T12:00:00', notes: JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status: 'contract_failed', contractVersion: 'incident-contract-v2', videoId: V, attemptedAt: '2026-09-27T12:00:00Z', stage: 'contract_validation', failure: { code: 'TIMELINE_START_OUTSIDE_WINDOW', message: 'x' }, request: { model: 'nvidia/cosmos-3-super-reasoner' }, validation: { firstPass: [] }, repair: null } }) };
  globalThis.fetch = async (url) => {
    const parsed = new URL(String(url));
    const path = parsed.pathname.replace('/rest/v1/', '');
    if (path === 'videos') return new Response(JSON.stringify([{ ...repaired.video }]));
    if (path === 'incidents' && parsed.searchParams.get('incident_id')) {
      assert.match(parsed.searchParams.get('select'), /model_runs\(/);
      return new Response(JSON.stringify([{ model_run_id: repaired.modelRunId, type: 'assault', severity_level: 3, model_runs: repaired.modelRun, reports: [repaired.reportRow] }]));
    }
    if (path === 'incidents') return new Response(JSON.stringify([{ model_run_id: repaired.modelRunId }]));
    if (path === 'model_runs') {
      assert.equal(parsed.searchParams.get('notes'), `like.*"videoId":"${V}"*`);
      return new Response(JSON.stringify([failed]));
    }
    return new Response('[]');
  };
  const response = await GET(new Request(`http://localhost/api/videos/${V}/runs`), { params: Promise.resolve({ videoId: V }) });
  assert.equal(response.status, 200);
  const history = await response.json();
  assert.equal(history.video.uploadedAt, repaired.video.uploaded_datetime);
  assert.deepEqual(history.runs.map((run) => [run.modelRunId, run.outcome, Boolean(run.report)]), [['m-cf', 'contract_failed', false], [repaired.modelRunId, 'valid_after_structural_repair', true]]);
  assert.equal(history.counts.withReport, 1);
  assert.equal(history.officialRunId, null);
});

test('the videos list names the incident -> video relationship (videos also reference their official incident)', async () => {
  const { GET: listVideos } = await import('../app/api/videos/route.ts');
  const selects = [];
  globalThis.fetch = async (url) => {
    const params = new URL(String(url)).searchParams;
    selects.push([params.get('select'), params.get('incidents'), params.get('selected_model_run_id')]);
    return new Response('[]', { headers: { 'content-range': '*/0' } });
  };
  for (const filter of ['all', 'without-report', 'awaiting-selection']) {
    assert.equal((await listVideos(new Request(`http://localhost/api/videos?filter=${filter}`))).status, 200);
  }
  for (const [select] of selects) assert.match(select, /incidents!incidents_incident_id_fkey/);
  assert.equal(selects[1][1], 'is.null', 'without-report is an anti-join');
  assert.equal(selects[2][2], 'is.null', 'awaiting-selection = has a report but no official one');
  assert.match(selects[2][0], /!inner\(model_run_id,reports!inner/);
});

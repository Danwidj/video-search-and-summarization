// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

let headContentLength = 1024;

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        return Promise.resolve(command.constructor.name === 'HeadObjectCommand' ? { ContentLength: headContentLength } : {});
      }
    },
    GetObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    PutObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    HeadObjectCommand: class HeadObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    DeleteObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
  },
});

mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: {
    getSignedUrl: async () => 'https://signed.r2.test/uploads/sensor-1/video.mp4',
  },
});

const { POST } = await import('../app/api/analysis/route.ts');
const { getServiceConfiguration } = await import('../lib/env.ts');

const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;

function setBaseEnv() {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000';
  process.env.VLM_GATEWAY_URL = 'http://gateway.test:8600';
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  process.env.R2_ACCOUNT_ID = 'test-account';
  process.env.R2_ACCESS_KEY = 'test-access-key';
  process.env.R2_SECRET_KEY = 'test-secret-key';
  process.env.R2_BUCKET = 'test-bucket';
}

function jsonRequest(body) {
  return new Request('http://localhost/api/analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function successfulPostgrestResponse(url, expectedR2Key) {
  const parsed = new URL(String(url));
  const table = parsed.pathname.replace('/rest/v1/', '');
  const filterValue = (name) => parsed.searchParams.get(name)?.replace(/^eq\./, '');
  const rows = {
    videos: [{ id: filterValue('id'), filepath: expectedR2Key }],
    model_runs: [{ id: filterValue('id') }],
    incidents: [{ incident_id: filterValue('incident_id'), model_run_id: filterValue('model_run_id') }],
    reports: [{ id: filterValue('id'), incident_id: 'verified', model_run_id: 'verified' }],
  }[table];
  return new Response(JSON.stringify(rows ?? [{ id: 'ok' }]), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  setBaseEnv();
  headContentLength = 1024;
});

afterEach(() => {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) {
      delete process.env[key];
    } else {
      process.env[key] = originalEnv[key];
    }
  }
  globalThis.fetch = originalFetch;
});

test('getServiceConfiguration parses ANALYSIS_MODE correctly', () => {
  delete process.env.ANALYSIS_MODE;
  assert.equal(getServiceConfiguration().analysisMode, 'gateway');

  process.env.ANALYSIS_MODE = 'agent';
  assert.equal(getServiceConfiguration().analysisMode, 'agent');

  process.env.ANALYSIS_MODE = 'AGENT';
  assert.equal(getServiceConfiguration().analysisMode, 'agent');

  process.env.ANALYSIS_MODE = 'gateway';
  assert.equal(getServiceConfiguration().analysisMode, 'gateway');

  process.env.ANALYSIS_MODE = 'anything-else';
  assert.equal(getServiceConfiguration().analysisMode, 'gateway');
});

test('analysis route: rejects requests missing required fields', async () => {
  const res1 = await POST(jsonRequest({ filepath: 'uploads/s/v.mp4', filename: 'v.mp4' }));
  assert.equal(res1.status, 400);

  const res2 = await POST(jsonRequest({ sensorId: 's-1', filename: 'v.mp4' }));
  assert.equal(res2.status, 400);

  const res3 = await POST(jsonRequest({ sensorId: 's-1', filepath: 'uploads/s/v.mp4' }));
  assert.equal(res3.status, 400);
});

test('analysis route: rejects an R2 key whose object is empty before calling inference', async () => {
  headContentLength = 0;
  let inferenceCalled = false;
  globalThis.fetch = async () => {
    inferenceCalled = true;
    return new Response('{}', { status: 200 });
  };

  const response = await POST(
    jsonRequest({ sensorId: 'sensor-empty', filepath: 'uploads/sensor-empty/clip.mp4', filename: 'clip.mp4' }),
  );

  assert.equal(response.status, 500);
  assert.equal(inferenceCalled, false);
  assert.match((await response.json()).error, /verifying the R2 video object/);
});

test('gateway mode: configuration validation requires gatewayUrl and Supabase', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  delete process.env.VLM_GATEWAY_URL;

  const res1 = await POST(jsonRequest({ sensorId: 's-1', filepath: 'uploads/s/v.mp4', filename: 'v.mp4' }));
  assert.equal(res1.status, 500);
  const data1 = await res1.json();
  assert.match(data1.error, /VLM_GATEWAY_URL is not configured/);

  process.env.VLM_GATEWAY_URL = 'http://gateway.test:8600';
  delete process.env.INCIDENT_SUPABASE_URL;

  const res2 = await POST(jsonRequest({ sensorId: 's-1', filepath: 'uploads/s/v.mp4', filename: 'v.mp4' }));
  assert.equal(res2.status, 500);
  const data2 = await res2.json();
  assert.match(data2.error, /Supabase PostgREST is not configured/);
});

test('agent mode: configuration validation requires agentUrl and Supabase, but not gatewayUrl', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.VLM_GATEWAY_URL;
  delete process.env.INCIDENT_AGENT_BASE_URL;

  const res1 = await POST(jsonRequest({ sensorId: 's-1', filepath: 'uploads/s/v.mp4', filename: 'v.mp4' }));
  assert.equal(res1.status, 500);
  const data1 = await res1.json();
  assert.match(data1.error, /INCIDENT_AGENT_BASE_URL is not configured/);

  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000';
  delete process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY;

  const res2 = await POST(jsonRequest({ sensorId: 's-1', filepath: 'uploads/s/v.mp4', filename: 'v.mp4' }));
  assert.equal(res2.status, 500);
  const data2 = await res2.json();
  assert.match(data2.error, /Supabase PostgREST is not configured/);
});

test('agent mode: calls agent analyze endpoint, keeps native snake_case report, writes only report bookkeeping', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.VLM_GATEWAY_URL;

  const recordedCalls = [];
  globalThis.fetch = async (url, options = {}) => {
    recordedCalls.push({ url: String(url), options });
    if (String(url).includes('/api/v1/incidents/')) {
      const mockAgentResponse = {
        title: 'Vehicle Collision at Intersection',
        incident_type: 'road accident',
        severity: 4,
        confidence: 0.95,
        incident_start: '00:01:15',
        incident_end: '00:01:45',
        incident_start_confirmed: true,
        description: 'Two vehicles collided at the intersection.',
        persons: [
          { description: 'Driver of sedan', actions: 'exited vehicle' }
        ],
        severity_reason: 'High impact collision with lane obstruction.',
        timeline: [
          { start_seconds: 75.5, end_seconds: 105.0, description: 'Sedan enters intersection and collides' }
        ],
        instruments: [
          { name: 'Sedan', description: 'Blue four-door passenger car', threat_level: 3 }
        ],
        assets: [
          { name: 'Traffic signal', description: 'Damaged post on southwest corner' }
        ],
        uncertainties: ['Exact speed prior to braking'],
        location: 'Intersection Cam 4',
        duration_seconds: 30,
      };
      return new Response(JSON.stringify(mockAgentResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return successfulPostgrestResponse(url, 'uploads/sensor-camera-01/clip.mp4');
  };

  const response = await POST(
    jsonRequest({
      sensorId: 'sensor-camera-01',
      filepath: 'uploads/sensor-camera-01/clip.mp4',
      filename: 'clip.mp4',
      reasoning: true,
      promptOverride: 'focus on vehicle movement',
    }),
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.ok(payload.report);
  const { report } = payload;

  // Agent call verification
  const agentCalls = recordedCalls.filter((c) => c.url.includes('/api/v1/incidents/'));
  assert.equal(agentCalls.length, 1);
  const agentCall = agentCalls[0];
  assert.match(agentCall.url, new RegExp(`http://agent\\.test:8000/api/v1/incidents/${report.videoId}/analyze$`));
  assert.equal(agentCall.options.method, 'POST');
  const agentBody = JSON.parse(agentCall.options.body);
  assert.equal(agentBody.model_run_id, report.modelRunId);
  assert.equal(agentBody.reasoning, true);
  assert.equal(agentBody.prompt_override, 'focus on vehicle movement');

  const agentIndex = recordedCalls.findIndex((c) => c.url.includes('/api/v1/incidents/'));
  const supabaseWrites = recordedCalls
    .map((c, index) => ({ ...c, index }))
    .filter((c) => c.url.includes('supabase.test') && c.options.method === 'POST')
    .map((c) => ({
      index: c.index,
      table: new URL(c.url).pathname.replace('/rest/v1/', ''),
      body: JSON.parse(c.options.body),
    }));
  const writtenTables = new Set(supabaseWrites.map((w) => w.table));
  assert.deepEqual([...writtenTables].sort(), ['model_runs', 'reports', 'videos']);
  for (const table of ['incidents', 'review_status', 'entities', 'instruments', 'assets', 'rpc/insert_incident']) {
    assert.ok(!writtenTables.has(table), `agent mode must not write ${table}`);
  }

  const videoWrites = supabaseWrites.filter((w) => w.table === 'videos');
  assert.ok(videoWrites.some((w) => w.index < agentIndex), 'videos row must be upserted before the agent call');
  for (const write of videoWrites) {
    assert.equal(write.body.id, report.videoId);
    assert.equal(write.body.source, 'sensor-camera-01');
    assert.equal(write.body.filepath, 'uploads/sensor-camera-01/clip.mp4');
  }
  const lastVideoWrite = videoWrites.at(-1);
  assert.ok(lastVideoWrite.index > agentIndex, 'videos.filepath must be restored after the agent call');
  assert.equal(lastVideoWrite.body.filepath, 'uploads/sensor-camera-01/clip.mp4');

  const modelRunWrite = supabaseWrites.find((w) => w.table === 'model_runs');
  assert.ok(modelRunWrite.index > agentIndex);
  assert.equal(modelRunWrite.body.id, report.modelRunId);
  const notes = JSON.parse(modelRunWrite.body.notes);
  assert.deepEqual(notes.incidentConsoleV2.report, report);
  assert.equal(notes.incidentConsoleV2.rawModelOutput, report.rawModelOutput);

  const reportWrite = supabaseWrites.find((w) => w.table === 'reports');
  assert.ok(reportWrite.index > modelRunWrite.index);
  assert.equal(reportWrite.body.id, report.reportId);
  assert.equal(reportWrite.body.incident_id, report.videoId);
  assert.equal(reportWrite.body.model_run_id, report.modelRunId);

  // Schema & mapping verification (unified snake_case matching agent Pydantic model)
  assert.equal(report.title, 'Vehicle Collision at Intersection');
  assert.equal(report.incident_type, 'road accident');
  assert.equal(report.description, 'Two vehicles collided at the intersection.');
  assert.equal(report.incident_start, '00:01:15');
  assert.equal(report.incident_end, '00:01:45');
  assert.equal(report.incident_start_confirmed, true);
  assert.equal(report.duration_seconds, 30);
  assert.equal(report.severity, 4);
  assert.equal(report.severity_reason, 'High impact collision with lane obstruction.');
  assert.equal(report.confidence, 0.95);
  assert.deepEqual(report.timeline, [
    { start_seconds: 75.5, end_seconds: 105.0, description: 'Sedan enters intersection and collides' },
  ]);
  assert.deepEqual(report.persons, [
    { description: 'Driver of sedan', actions: 'exited vehicle' },
  ]);
  assert.deepEqual(report.instruments, [
    { name: 'Sedan', description: 'Blue four-door passenger car', threat_level: 3 },
  ]);
  assert.deepEqual(report.assets, [
    { name: 'Traffic signal', description: 'Damaged post on southwest corner' },
  ]);
  assert.deepEqual(report.uncertainties, ['Exact speed prior to braking']);
  assert.equal(report.location, 'Intersection Cam 4');
  assert.equal(report.playbackUrl, 'https://signed.r2.test/uploads/sensor-1/video.mp4');
  assert.equal(report.model, 'vss-agent');
  assert.match(report.videoId, /^v[0-9a-f]{19}$/);
  assert.match(report.modelRunId, /^m[0-9a-f]{19}$/);
  assert.match(report.reportId, /^r[0-9a-f]{19}$/);
});

const { compactId } = await import('../lib/ids.ts');
const compactVideoId = (sensorId) => compactId('v', sensorId);

const contractFixture = (name) => readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', name), 'utf8');
const validContractReport = () => JSON.parse(contractFixture('valid/full-report.json'));

function completion(content, extra = {}) {
  return new Response(JSON.stringify({
    choices: [{ message: { role: 'assistant', content, reasoning_content: 'model reasoning' }, finish_reason: 'stop' }],
    model: 'nvidia/cosmos-3-super-reasoner',
    usage: { prompt_tokens: 100, completion_tokens: 50 },
    ...extra,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

function gatewayFetch(recordedCalls, content, r2Key) {
  return async (url, options = {}) => {
    const urlStr = String(url);
    recordedCalls.push({ url: urlStr, options });
    if (urlStr.includes('/v1/chat/completions')) return completion(content);
    return successfulPostgrestResponse(url, r2Key);
  };
}

function supabaseWrites(recordedCalls) {
  return recordedCalls
    .filter((c) => c.url.includes('supabase.test') && c.options.method === 'POST')
    .map((c) => ({ table: new URL(c.url).pathname.replace('/rest/v1/', ''), body: JSON.parse(c.options.body) }));
}

test('gateway mode: sends the shared contract P1 request for the selected model and persists a contract run', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const recordedCalls = [];
  globalThis.fetch = gatewayFetch(recordedCalls, JSON.stringify(validContractReport()), 'uploads/sensor-cam-02/night.mp4');

  const response = await POST(jsonRequest({
    sensorId: 'sensor-cam-02',
    filepath: 'uploads/sensor-cam-02/night.mp4',
    filename: 'night.mp4',
    model: 'nvidia/cosmos-3-super-reasoner',
  }));

  assert.equal(response.status, 200);
  const { report } = await response.json();

  const gatewayCalls = recordedCalls.filter((c) => c.url.includes('/v1/chat/completions'));
  assert.equal(gatewayCalls.length, 1, 'exactly one model call: no repair retry');
  const body = JSON.parse(gatewayCalls[0].options.body);
  assert.equal(body.model, 'nvidia/cosmos-3-super-reasoner');
  assert.deepEqual(Object.keys(body).sort(), ['max_tokens', 'media_io_kwargs', 'messages', 'model', 'response_format', 'temperature']);
  assert.equal(body.temperature, 0);
  assert.equal(body.max_tokens, 16384);
  assert.deepEqual(body.media_io_kwargs, { video: { num_frames: 64 } });
  assert.deepEqual(body.response_format, JSON.parse(contractFixture('response_format.json')));
  assert.equal(body.messages.length, 1);
  const [videoPart, promptPart, ...rest] = body.messages[0].content;
  assert.deepEqual(videoPart, { type: 'video_url', video_url: { url: 'https://signed.r2.test/uploads/sensor-1/video.mp4' } });
  assert.equal(promptPart.text, readFileSync(join(process.cwd(), '..', 'contracts', 'incident_extraction_prompt.md'), 'utf8'));
  assert.deepEqual(rest, [], 'no additional instruction part unless one is given');

  const writes = supabaseWrites(recordedCalls);
  const modelRun = writes.find((w) => w.table === 'model_runs').body;
  assert.equal(modelRun.id, report.modelRunId);
  assert.equal(modelRun.model_name, 'nvidia/cosmos-3-super-reasoner');
  assert.equal(modelRun.prompt_version, 'incident-contract-v2');
  const notes = JSON.parse(modelRun.notes).incidentConsoleV2;
  assert.equal(notes.recordType, 'analysis_attempt');
  assert.equal(notes.status, 'valid_first_pass');
  assert.deepEqual(notes.validation, { firstPass: [] });
  assert.equal(notes.repair, null);
  assert.equal(notes.contractVersion, 'incident-contract-v2');
  assert.deepEqual(notes.report, { ...validContractReport(), incident: { ...validContractReport().incident, duration: 8 } });
  assert.equal(notes.request.model, 'nvidia/cosmos-3-super-reasoner');
  assert.equal(notes.request.additionalInstruction, null);
  assert.deepEqual(notes.request.inferenceConfig, { temperature: 0, max_tokens: 16384, media_io_kwargs: { video: { num_frames: 64 } } });
  assert.match(notes.request.promptSha256, /^[0-9a-f]{64}$/);
  assert.match(notes.request.schemaSha256, /^[0-9a-f]{64}$/);
  assert.equal(notes.response.content, JSON.stringify(validContractReport()));
  assert.equal(notes.response.reasoningContent, 'model reasoning');
  assert.equal(notes.response.finishReason, 'stop');
  assert.deepEqual(notes.response.usage, { prompt_tokens: 100, completion_tokens: 50 });

  const incident = writes.find((w) => w.table === 'rpc/insert_incident').body;
  assert.deepEqual(incident, {
    p_incident_id: report.videoId,
    p_model_run_id: report.modelRunId,
    p_type: 'assault',
    p_start_timestamp: '3',
    p_end_timestamp: '11',
    p_duration: 8,
    p_description: 'E1 approaches E2 and strikes E2 with a bottle.',
    p_severity_level: 3,
    p_confidence_score: null,
  });
  assert.deepEqual(writes.find((w) => w.table === 'entities').body.map((row) => [row.entity_id, row.type]), [['E1', 'human'], ['E2', 'human']]);
  assert.deepEqual(writes.find((w) => w.table === 'instruments').body.map((row) => [row.instrument_id, row.entity_id, row.threat_level]), [['I1', 'E1', 3]]);
  assert.deepEqual(writes.find((w) => w.table === 'assets').body.map((row) => row.asset_id), ['A1']);
  const videoCall = recordedCalls.find((c) => c.url.includes('/rest/v1/videos') && c.options.method === 'POST');
  assert.match(videoCall.options.headers.Prefer, /resolution=ignore-duplicates/, 'an existing video row is never updated (upload time preserved)');
  const video = writes.find((w) => w.table === 'videos').body;
  assert.equal(video.filepath, 'uploads/sensor-cam-02/night.mp4');
  assert.equal(video.source, 'sensor-cam-02');
  assert.ok(!('duration' in video), 'the incident duration is not the video duration');
  assert.ok(writes.find((w) => w.table === 'reports'));

  // The upload flow only needs the run's identity to open its report page.
  assert.deepEqual(Object.keys(report).sort(), ['model', 'modelRunId', 'outcome', 'promptVersion', 'reportId', 'videoId']);
  assert.equal(report.outcome, 'valid_first_pass');
  assert.equal(report.model, 'nvidia/cosmos-3-super-reasoner');
  assert.equal(report.promptVersion, 'incident-contract-v2');
});

test('gateway mode: defaults to the configured VLM_MODEL when no model is sent', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  process.env.VLM_MODEL = 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning';
  const recordedCalls = [];
  globalThis.fetch = gatewayFetch(recordedCalls, JSON.stringify(validContractReport()), 'uploads/s-d/clip.mp4');

  const response = await POST(jsonRequest({ sensorId: 's-d', filepath: 'uploads/s-d/clip.mp4', filename: 'clip.mp4' }));

  assert.equal(response.status, 200);
  const body = JSON.parse(recordedCalls.find((c) => c.url.includes('/v1/chat/completions')).options.body);
  assert.equal(body.model, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning');
});

test('gateway mode: rejects a model outside the allowlist before calling anything', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const recordedCalls = [];
  globalThis.fetch = gatewayFetch(recordedCalls, '{}', 'uploads/s-x/clip.mp4');

  const response = await POST(jsonRequest({ sensorId: 's-x', filepath: 'uploads/s-x/clip.mp4', filename: 'clip.mp4', model: 'some/other-model' }));

  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /Unsupported model/);
  assert.equal(recordedCalls.length, 0);
});

const REPORT_TABLES = ['rpc/insert_incident', 'incidents', 'entities', 'instruments', 'assets', 'reports', 'review_status'];

function attemptNotesFrom(recordedCalls) {
  const runs = supabaseWrites(recordedCalls).filter((w) => w.table === 'model_runs');
  assert.equal(runs.length, 1, 'exactly one model_runs attempt record');
  return { row: runs[0].body, notes: JSON.parse(runs[0].body.notes).incidentConsoleV2 };
}

test('gateway mode: a contract failure is a 422 with no model repair call; only the video and the attempt record are written', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const cases = [
    ['```json\n' + JSON.stringify(validContractReport()) + '\n```', ['INVALID_JSON']],
    [contractFixture('invalid/cross-unknown-instrument-holder.json'), ['INSTRUMENT_HOLDER_UNKNOWN']],
    [contractFixture('invalid/schema-legacy-incident-type.json'), ['SCHEMA_VIOLATION']],
    [contractFixture('invalid/cross-timeline-outside-incident.json'), ['TIMELINE_END_OUTSIDE_WINDOW']],
  ];
  for (const [content, codes] of cases) {
    const recordedCalls = [];
    globalThis.fetch = gatewayFetch(recordedCalls, content, 'uploads/s-bad/clip.mp4');

    const response = await POST(jsonRequest({ sensorId: 's-bad', filepath: 'uploads/s-bad/clip.mp4', filename: 'clip.mp4', model: 'nvidia/cosmos-3-nano-reasoner' }));

    assert.equal(response.status, 422);
    const payload = await response.json();
    assert.match(payload.error, /did not satisfy the incident contract/);
    assert.equal(payload.outcome, 'contract_failed');
    assert.deepEqual(payload.codes, codes);
    assert.equal(payload.rawContent, content);
    assert.equal(payload.attemptRecorded, true);
    assert.equal(recordedCalls.filter((c) => c.url.includes('/v1/chat/completions')).length, 1, 'no second model call');

    const tables = supabaseWrites(recordedCalls).map((w) => w.table);
    for (const table of REPORT_TABLES) assert.ok(!tables.includes(table), `contract_failed must not write ${table}`);
    assert.ok(tables.includes('videos'), 'the uploaded video is recorded even though analysis failed');
    const { row, notes } = attemptNotesFrom(recordedCalls);
    assert.equal(row.id, payload.attemptId);
    assert.equal(row.model_name, 'nvidia/cosmos-3-nano-reasoner');
    assert.equal(row.prompt_version, 'incident-contract-v2');
    assert.equal(notes.status, 'contract_failed');
    assert.equal(notes.stage, 'contract_validation');
    assert.equal(notes.videoId, compactVideoId('s-bad'));
    assert.equal(notes.response.content, content, 'the original response is stored unaltered');
    assert.deepEqual(notes.validation.firstPass.map((v) => v.code), codes);
    assert.equal(notes.repair.eligible, false);
    assert.ok(!('report' in notes));
  }
});

test('gateway mode: an ID-only violation is repaired by id-normalization-v1 and saved as valid_after_structural_repair', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const { rawContent } = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-failures', 'nemotron-3-omni-malformed-ids.json'), 'utf8'));
  const recordedCalls = [];
  globalThis.fetch = gatewayFetch(recordedCalls, rawContent, 'uploads/s-rep/clip.mp4');

  const response = await POST(jsonRequest({ sensorId: 's-rep', filepath: 'uploads/s-rep/clip.mp4', filename: 'clip.mp4', model: 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning' }));

  assert.equal(response.status, 200);
  const { report } = await response.json();
  assert.equal(report.outcome, 'valid_after_structural_repair');
  assert.equal(recordedCalls.filter((c) => c.url.includes('/v1/chat/completions')).length, 1, 'no second model call');
  const { notes } = attemptNotesFrom(recordedCalls);
  assert.equal(notes.status, 'valid_after_structural_repair');
  assert.equal(notes.response.content, rawContent, 'the original response is stored unaltered');
  assert.deepEqual(notes.validation.firstPass.map((v) => v.code).sort(), ['ID_NOT_SEQUENTIAL_ENTITY', 'ID_NOT_SEQUENTIAL_INSTRUMENT']);
  assert.equal(notes.repair.ruleSet, 'id-normalization-v1');
  assert.deepEqual(notes.repair.revalidation, []);
  assert.equal(notes.repair.operations.length, 2);
  assert.deepEqual(notes.report.entities.map((e) => e.entity_id), ['E1', 'E2']);
  const writes = supabaseWrites(recordedCalls);
  assert.deepEqual(writes.find((w) => w.table === 'entities').body.map((row) => row.entity_id), ['E1', 'E2']);
  assert.deepEqual(writes.find((w) => w.table === 'instruments').body.map((row) => [row.instrument_id, row.entity_id, row.name]), [['I1', 'E1', 'bag'], ['I2', null, 'white van']]);
  assert.ok(writes.find((w) => w.table === 'rpc/insert_incident'));
});

test('gateway mode: request failures are recorded as request_failed with only the provenance that exists', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const scenarios = [
    {
      name: 'gateway HTTP error', status: 502, code: 'GATEWAY_HTTP_ERROR', stage: 'gateway',
      reply: () => new Response('upstream exploded', { status: 500 }),
      response: { httpStatus: 500, errorBody: 'upstream exploded' },
    },
    {
      name: 'timeout', status: 504, code: 'GATEWAY_TIMEOUT', stage: 'gateway',
      reply: () => { throw new DOMException('The operation was aborted due to timeout', 'TimeoutError'); },
      response: null,
    },
    {
      name: 'no completion', status: 502, code: 'UPSTREAM_NO_COMPLETION', stage: 'gateway',
      reply: () => new Response('null', { status: 200 }),
      response: { httpStatus: 200, errorBody: 'null' },
    },
    {
      name: 'token budget exhausted', status: 502, code: 'FINISH_LENGTH', stage: 'upstream_response',
      reply: () => new Response(JSON.stringify({ choices: [{ message: { role: 'assistant', content: '{"incident": {' }, finish_reason: 'length' }], usage: { completion_tokens: 16384 } }), { status: 200 }),
      response: { content: '{"incident": {', finishReason: 'length', usage: { completion_tokens: 16384 } },
    },
    {
      name: 'empty content', status: 502, code: 'UPSTREAM_EMPTY_CONTENT', stage: 'upstream_response',
      reply: () => new Response(JSON.stringify({ choices: [{ message: { role: 'assistant', content: '' }, finish_reason: 'stop' }] }), { status: 200 }),
      response: { content: '', finishReason: 'stop' },
    },
  ];
  for (const scenario of scenarios) {
    const recordedCalls = [];
    globalThis.fetch = async (url, options = {}) => {
      recordedCalls.push({ url: String(url), options });
      if (String(url).includes('/v1/chat/completions')) return scenario.reply();
      return successfulPostgrestResponse(url, 'uploads/s-req/clip.mp4');
    };

    const response = await POST(jsonRequest({ sensorId: 's-req', filepath: 'uploads/s-req/clip.mp4', filename: 'clip.mp4', model: 'nvidia/cosmos-3-nano-reasoner' }));

    assert.equal(response.status, scenario.status, scenario.name);
    const payload = await response.json();
    assert.equal(payload.outcome, 'request_failed', scenario.name);
    assert.equal(payload.code, scenario.code, scenario.name);
    const tables = supabaseWrites(recordedCalls).map((w) => w.table);
    for (const table of REPORT_TABLES) assert.ok(!tables.includes(table), `${scenario.name}: request_failed must not write ${table}`);
    const { notes } = attemptNotesFrom(recordedCalls);
    assert.equal(notes.status, 'request_failed', scenario.name);
    assert.equal(notes.stage, scenario.stage, scenario.name);
    assert.equal(notes.failure.code, scenario.code, scenario.name);
    assert.deepEqual(notes.response, scenario.response, `${scenario.name}: no invented response fields`);
    assert.equal(notes.request.model, 'nvidia/cosmos-3-nano-reasoner');
    assert.match(notes.request.promptSha256, /^[0-9a-f]{64}$/);
  }
});

test('gateway mode: every analysis of the same video creates a new model run', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const runIds = new Set();
  for (let index = 0; index < 2; index += 1) {
    const recordedCalls = [];
    globalThis.fetch = gatewayFetch(recordedCalls, JSON.stringify(validContractReport()), 'uploads/s-same/clip.mp4');
    const response = await POST(jsonRequest({ sensorId: 's-same', filepath: 'uploads/s-same/clip.mp4', filename: 'clip.mp4', model: 'nvidia/cosmos-3-nano-reasoner' }));
    assert.equal(response.status, 200);
    runIds.add((await response.json()).report.modelRunId);
  }
  assert.equal(runIds.size, 2);
});

test('agent mode: rejects a model other than the configured one (agent keeps its own contract)', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  process.env.VLM_MODEL = 'nvidia/cosmos-3-nano-reasoner';
  let called = false;
  globalThis.fetch = async () => { called = true; return new Response('{}'); };

  const response = await POST(jsonRequest({ sensorId: 's-1', filepath: 'uploads/s-1/v.mp4', filename: 'v.mp4', model: 'nvidia/cosmos-3-super-reasoner' }));

  assert.equal(response.status, 409);
  assert.equal(called, false);
});

test('agent mode: keeps the agent-reported duration_seconds of 0 even with a positive timeline span', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.VLM_GATEWAY_URL;

  globalThis.fetch = async (url) => {
    if (String(url).includes('/api/v1/incidents/')) {
      return new Response(JSON.stringify({
          title: 'Short clip',
          incident_type: 'other',
          duration_seconds: 0,
          timeline: [{ start_seconds: 0, end_seconds: 5, description: 'Event' }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return successfulPostgrestResponse(url, 'uploads/sensor-cam-03/clip.mp4');
  };

  const response = await POST(
    jsonRequest({ sensorId: 'sensor-cam-03', filepath: 'uploads/sensor-cam-03/clip.mp4', filename: 'clip.mp4' }),
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.report.duration_seconds, 0);
});

test('gateway mode: does not report success when persistence read-back is incomplete', async () => {
  process.env.ANALYSIS_MODE = 'gateway';

  globalThis.fetch = async (url) => {
    if (String(url).includes('/v1/chat/completions')) return completion(JSON.stringify(validContractReport()));
    if (String(url).includes('select=')) {
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return new Response(JSON.stringify([{ id: 'ok' }]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const response = await POST(
    jsonRequest({ sensorId: 'sensor-missing', filepath: 'uploads/sensor-missing/clip.mp4', filename: 'clip.mp4' }),
  );

  assert.equal(response.status, 500);
  const payload = await response.json();
  assert.match(payload.error, /verifying the persisted report/);
  assert.match(payload.error, /videos, model_runs, incidents, reports/);
});

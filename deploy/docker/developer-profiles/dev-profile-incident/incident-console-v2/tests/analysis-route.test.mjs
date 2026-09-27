// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
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

const MODEL_OUTPUT = {
  incident: {
    type: 'assault',
    title: 'Person strikes another person with a bottle',
    start_timestamp: 3,
    end_timestamp: 11,
    description: 'E1 approaches E2 and strikes E2 with a bottle.',
    severity_level: 3,
    severity_reason: 'Repeated strikes with an improvised weapon.',
    confidence_score: null,
    location: 'shop interior',
  },
  entities: [
    { entity_id: 'E1', type: 'human', description: 'Person in a dark jacket attacking.' },
    { entity_id: 'E2', type: 'human', description: 'Person at the counter being struck.' },
  ],
  instruments: [{ instrument_id: 'I1', entity_id: 'E1', name: 'bottle', description: 'Glass bottle.', threat_level: 3 }],
  assets: [{ asset_id: 'A1', name: 'counter', description: 'Shop counter.' }],
  timeline: [
    { start_seconds: 3, end_seconds: 5, description: 'E1 approaches E2.' },
    { start_seconds: 5, end_seconds: 11, description: 'E1 strikes E2 with I1.' },
  ],
  uncertainties: ['It is unclear whether E2 was injured.'],
};

function completion(content, model = 'nvidia/cosmos-3-nano-reasoner') {
  return new Response(JSON.stringify({ model, choices: [{ message: { role: 'assistant', content }, finish_reason: 'stop' }] }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

const REQUEST = { sensorId: 'sensor-1', filepath: 'uploads/sensor-1/video.mp4', filename: 'video.mp4' };

function gatewayFetch({ p1Content = JSON.stringify(MODEL_OUTPUT), rp1 = () => completion('INCIDENT REPORT\nA person was struck.', 'nvidia/nemotron-3-nano-30b-a3b') } = {}) {
  const calls = { gateway: [], postgrest: [] };
  const fetchImpl = async (url, options = {}) => {
    const target = String(url);
    if (target.startsWith('http://gateway.test:8600/v1/chat/completions')) {
      const body = JSON.parse(options.body);
      calls.gateway.push(body);
      return body.response_format ? completion(p1Content) : rp1(body);
    }
    if (target.startsWith('https://supabase.test/')) {
      calls.postgrest.push({ url: target, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : undefined });
      return successfulPostgrestResponse(url, REQUEST.filepath);
    }
    throw new Error(`unexpected fetch ${target}`);
  };
  return { calls, fetchImpl };
}

test('gateway mode: P1 sends the signed URL first with the strict contract schema, then RP1; persists contract rows', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const { calls, fetchImpl } = gatewayFetch();
  globalThis.fetch = fetchImpl;

  const response = await POST(jsonRequest(REQUEST));
  const payload = await response.json();
  assert.equal(response.status, 200, JSON.stringify(payload));

  assert.equal(calls.gateway.length, 2);
  const [p1, rp1] = calls.gateway;
  assert.equal(p1.model, 'nvidia/cosmos-3-nano-reasoner');
  assert.deepEqual(p1.messages[0].content[0], { type: 'video_url', video_url: { url: 'https://signed.r2.test/uploads/sensor-1/video.mp4' } });
  assert.equal(p1.messages[0].content[1].type, 'text');
  assert.match(p1.messages[0].content[1].text, /UNIFIED VLM INCIDENT EXTRACTION PROMPT/);
  assert.equal(p1.response_format.type, 'json_schema');
  assert.equal(p1.response_format.json_schema.strict, true);
  assert.equal(p1.response_format.json_schema.schema.$schema, undefined);
  assert.equal(p1.max_tokens, 16384);
  assert.equal(p1.temperature, 0);
  assert.deepEqual(p1.media_io_kwargs, { video: { num_frames: 64 } });

  assert.equal(rp1.model, 'nvidia/nemotron-3-nano-30b-a3b');
  assert.deepEqual(rp1.chat_template_kwargs, { enable_thinking: false });
  assert.equal(rp1.response_format, undefined);
  assert.match(rp1.messages[0].content, /"type": "assault"/);
  assert.match(rp1.messages[0].content, /"duration": 8/);

  const { report } = payload;
  assert.equal(report.incident.duration, 8);
  assert.equal(report.incident.confidence_score, null);
  assert.equal(report.entities[0].entity_id, 'E1');
  assert.equal(report.reportText, 'INCIDENT REPORT\nA person was struck.');
  assert.equal(report.promptVersion, 'incident-contract-v2');

  const rpc = calls.postgrest.find((call) => call.url.includes('/rpc/insert_incident'));
  assert.deepEqual(
    { type: rpc.body.p_type, start: rpc.body.p_start_timestamp, end: rpc.body.p_end_timestamp, duration: rpc.body.p_duration, confidence: rpc.body.p_confidence_score },
    { type: 'assault', start: '3', end: '11', duration: 8, confidence: null },
  );
  const entities = calls.postgrest.find((call) => call.url.includes('/rest/v1/entities') && call.method === 'POST');
  assert.deepEqual(entities.body.map((row) => [row.entity_id, row.type]), [['E1', 'human'], ['E2', 'human']]);
  const instruments = calls.postgrest.find((call) => call.url.includes('/rest/v1/instruments') && call.method === 'POST');
  assert.equal(instruments.body[0].entity_id, 'E1');
  const modelRun = calls.postgrest.find((call) => call.url.includes('/rest/v1/model_runs') && call.method === 'POST');
  const notes = JSON.parse(modelRun.body.notes);
  assert.equal(notes.incidentConsoleV2.report.incident.title, MODEL_OUTPUT.incident.title);
  assert.equal(notes.incidentConsoleV2.reportText, 'INCIDENT REPORT\nA person was struck.');
});

for (const [name, content] of [
  ['a label outside the taxonomy', JSON.stringify({ ...MODEL_OUTPUT, incident: { ...MODEL_OUTPUT.incident, type: 'fighting' } })],
  ['a model-supplied duration', JSON.stringify({ ...MODEL_OUTPUT, incident: { ...MODEL_OUTPUT.incident, duration: 8 } })],
  ['fenced JSON', '```json\n' + JSON.stringify(MODEL_OUTPUT) + '\n```'],
  ['a timeline event outside the incident window', JSON.stringify({ ...MODEL_OUTPUT, timeline: [{ start_seconds: 0, end_seconds: 2, description: 'lead-up' }] })],
]) {
  test(`gateway mode: ${name} is a 422 contract violation, with no repair call and nothing persisted`, async () => {
    process.env.ANALYSIS_MODE = 'gateway';
    const { calls, fetchImpl } = gatewayFetch({ p1Content: content });
    globalThis.fetch = fetchImpl;

    const response = await POST(jsonRequest(REQUEST));
    assert.equal(response.status, 422);
    assert.match((await response.json()).error, /did not match the incident contract/);
    assert.equal(calls.gateway.length, 1);
    assert.equal(calls.postgrest.length, 0);
  });
}

test('gateway mode: an RP1 failure keeps the valid P1 report and records why', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const { fetchImpl } = gatewayFetch({ rp1: () => completion('') });
  globalThis.fetch = fetchImpl;

  const response = await POST(jsonRequest(REQUEST));
  const { report } = await response.json();
  assert.equal(response.status, 200);
  assert.equal(report.reportText, undefined);
  assert.equal(report.reportTextError, 'RP1 returned no final content');
  assert.equal(report.incident.type, 'assault');
});

test('gateway mode: does not report success when persistence read-back is incomplete', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  const { fetchImpl } = gatewayFetch();
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).includes('/rest/v1/reports') && (options.method || 'GET') === 'GET') {
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return fetchImpl(url, options);
  };

  const response = await POST(jsonRequest(REQUEST));
  assert.equal(response.status, 500);
  assert.match((await response.json()).error, /missing rows: reports/);
});

function agentFetch(agentResponse) {
  const calls = { agent: [], postgrest: [] };
  const fetchImpl = async (url, options = {}) => {
    const target = String(url);
    if (target.startsWith('http://agent.test:8000/api/v1/incidents/')) {
      calls.agent.push({ url: target, body: JSON.parse(options.body) });
      return agentResponse();
    }
    if (target.startsWith('https://supabase.test/')) {
      calls.postgrest.push({ url: target, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : undefined });
      return successfulPostgrestResponse(url, REQUEST.filepath);
    }
    throw new Error(`unexpected fetch ${target}`);
  };
  return { calls, fetchImpl };
}

const AGENT_REPORT = { ...MODEL_OUTPUT, incident: { ...MODEL_OUTPUT.incident, duration: 8 } };

test('agent mode: sends the signed URL to /analyze, validates the contract report, writes only bookkeeping', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.VLM_GATEWAY_URL;
  const { calls, fetchImpl } = agentFetch(() => new Response(JSON.stringify({
    report: AGENT_REPORT,
    report_text: 'INCIDENT REPORT\nFrom the agent.',
    report_text_error: null,
    model: 'nvidia/cosmos-3-nano-reasoner',
    contract_version: 'incident-contract-v2',
    raw_output: JSON.stringify(MODEL_OUTPUT),
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  globalThis.fetch = fetchImpl;

  const response = await POST(jsonRequest(REQUEST));
  const payload = await response.json();
  assert.equal(response.status, 200, JSON.stringify(payload));

  assert.equal(calls.agent.length, 1);
  assert.match(calls.agent[0].url, /\/api\/v1\/incidents\/v[^/]+\/analyze$/);
  assert.equal(calls.agent[0].body.video_url, 'https://signed.r2.test/uploads/sensor-1/video.mp4');
  assert.ok(calls.agent[0].body.model_run_id);
  assert.equal(calls.agent[0].body.prompt_override, undefined);

  assert.equal(payload.report.incident.duration, 8);
  assert.equal(payload.report.reportText, 'INCIDENT REPORT\nFrom the agent.');
  assert.equal(payload.report.model, 'nvidia/cosmos-3-nano-reasoner');
  const writes = calls.postgrest.filter((call) => call.method === 'POST').map((call) => new URL(call.url).pathname);
  assert.ok(!writes.some((path) => /rpc\/insert_incident|\/entities|\/instruments|\/assets/.test(path)), writes.join(', '));
});

test('agent mode: an agent 422 is surfaced as a 422 contract violation', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  const { fetchImpl } = agentFetch(() => new Response(JSON.stringify({ detail: 'schema violation: /incident/type' }), { status: 422 }));
  globalThis.fetch = fetchImpl;

  const response = await POST(jsonRequest(REQUEST));
  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /schema violation/);
});

test('agent mode: a non-contract agent report is rejected, not translated', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  const { fetchImpl } = agentFetch(() => new Response(JSON.stringify({
    report: { incident_type: 'road accident', severity: 4, persons: [] },
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  globalThis.fetch = fetchImpl;

  const response = await POST(jsonRequest(REQUEST));
  assert.equal(response.status, 422);
});

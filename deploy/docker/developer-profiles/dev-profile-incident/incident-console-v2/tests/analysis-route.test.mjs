// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send() {
        return Promise.resolve({});
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

beforeEach(() => {
  setBaseEnv();
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
    return new Response(JSON.stringify([{ id: 'ok' }]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
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
    .filter((c) => c.url.includes('supabase.test'))
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

test('gateway mode: calls VLM gateway with snake_case prompt and persists to Supabase', async () => {
  process.env.ANALYSIS_MODE = 'gateway';

  const recordedCalls = [];
  globalThis.fetch = async (url, options = {}) => {
    const urlStr = String(url);
    recordedCalls.push({ url: urlStr, options });
    if (urlStr.includes('/v1/chat/completions')) {
      const vlmResponse = {
        choices: [
          {
            message: {
              role: 'assistant',
              content: JSON.stringify({
                title: 'Warehouse Trespassing',
                incident_type: 'burglary',
                description: 'Unauthorized entry detected after hours.',
                incident_start: '00:00:10',
                incident_end: '00:00:50',
                incident_start_confirmed: true,
                duration_seconds: 40,
                severity: 3,
                severity_reason: 'Unauthorized presence in restricted area.',
                confidence: 0.9,
                timeline: [{ start_seconds: 10, end_seconds: 50, description: 'Subject climbed fence' }],
                persons: [{ description: 'Intruder in dark jacket', actions: 'climbed fence' }],
                instruments: [{ name: 'Flashlight', description: 'Handheld beam', threat_level: null }],
                assets: [{ name: 'Perimeter fence', description: 'Cut section' }],
                uncertainties: ['Entry point details'],
                location: 'Warehouse Perimeter',
              }),
            },
          },
        ],
        model: 'nvidia/cosmos-3-nano-reasoner',
      };
      return new Response(JSON.stringify(vlmResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    // PostgREST responses
    return new Response(JSON.stringify([{ id: 'ok' }]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const response = await POST(
    jsonRequest({
      sensorId: 'sensor-cam-02',
      filepath: 'uploads/sensor-cam-02/night.mp4',
      filename: 'night.mp4',
    }),
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.ok(payload.report);
  assert.equal(payload.report.title, 'Warehouse Trespassing');
  assert.equal(payload.report.incident_type, 'burglary');
  assert.equal(payload.report.description, 'Unauthorized entry detected after hours.');
  assert.equal(payload.report.severity, 3);
  assert.equal(payload.report.confidence, 0.9);
  assert.deepEqual(payload.report.persons, [{ description: 'Intruder in dark jacket', actions: 'climbed fence' }]);
  assert.deepEqual(payload.report.instruments, [{ name: 'Flashlight', description: 'Handheld beam', threat_level: null }]);

  const gatewayCalls = recordedCalls.filter((c) => c.url.includes('/v1/chat/completions'));
  assert.equal(gatewayCalls.length, 1);
  const gatewayBody = JSON.parse(gatewayCalls[0].options.body);
  const promptText = gatewayBody.messages[0].content[0].text;
  assert.ok(promptText.includes('incident_type'));
  assert.ok(promptText.includes('threat_level'));
  assert.ok(promptText.includes('duration_seconds'));

  const supabaseCalls = recordedCalls.filter((c) => c.url.includes('supabase.test'));
  assert.ok(supabaseCalls.length > 0, 'gateway mode must persist to Supabase');

  // Verify RPC insert call has snake_case mappings
  const rpcCall = supabaseCalls.find((c) => c.url.includes('/rpc/insert_incident'));
  assert.ok(rpcCall, 'insert_incident RPC must be called');
  const rpcBody = JSON.parse(rpcCall.options.body);
  assert.equal(rpcBody.p_type, 'burglary');
  assert.equal(rpcBody.p_description, 'Unauthorized entry detected after hours.');
  assert.equal(rpcBody.p_severity_level, 3);
  assert.equal(rpcBody.p_confidence_score, 0.9);
  assert.equal(rpcBody.p_start_timestamp, '00:00:10');
  assert.equal(rpcBody.p_end_timestamp, '00:00:50');
  assert.equal(rpcBody.p_duration, 40);

  // Verify entities written from persons
  const entityCall = supabaseCalls.find((c) => c.url.includes('/entities') && c.options.method === 'POST');
  assert.ok(entityCall, 'entities table must be written');
  const entityBody = JSON.parse(entityCall.options.body);
  assert.equal(entityBody[0].type, 'person');
  assert.equal(entityBody[0].description, 'Intruder in dark jacket climbed fence');
});

test('agent mode: keeps the agent-reported duration_seconds of 0 even with a positive timeline span', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.VLM_GATEWAY_URL;

  globalThis.fetch = async (url) => {
    const body = String(url).includes('/api/v1/incidents/')
      ? {
          title: 'Short clip',
          incident_type: 'other',
          duration_seconds: 0,
          timeline: [{ start_seconds: 0, end_seconds: 5, description: 'Event' }],
        }
      : [{ id: 'ok' }];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  const response = await POST(
    jsonRequest({ sensorId: 'sensor-cam-03', filepath: 'uploads/sensor-cam-03/clip.mp4', filename: 'clip.mp4' }),
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.report.duration_seconds, 0);
});

test('gateway mode: derives duration_seconds from the timeline span when the VLM reports 0', async () => {
  process.env.ANALYSIS_MODE = 'gateway';

  const recordedCalls = [];
  globalThis.fetch = async (url, options = {}) => {
    const urlStr = String(url);
    recordedCalls.push({ url: urlStr, options });
    const body = urlStr.includes('/v1/chat/completions')
      ? {
          choices: [
            {
              message: {
                role: 'assistant',
                content: JSON.stringify({
                  title: 'Short clip',
                  incident_type: 'other',
                  duration_seconds: 0,
                  timeline: [
                    { start_seconds: 2.6, end_seconds: 5.0, description: 'Later event' },
                    { start_seconds: 0.0, end_seconds: 0.3, description: 'Earlier event' },
                  ],
                }),
              },
            },
          ],
          model: 'nvidia/cosmos-3-nano-reasoner',
        }
      : [{ id: 'ok' }];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  const response = await POST(
    jsonRequest({ sensorId: 'sensor-cam-04', filepath: 'uploads/sensor-cam-04/clip.mp4', filename: 'clip.mp4' }),
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.report.duration_seconds, 5);
  const rpcCall = recordedCalls.find((c) => c.url.includes('/rpc/insert_incident'));
  assert.equal(JSON.parse(rpcCall.options.body).p_duration, 5);
});

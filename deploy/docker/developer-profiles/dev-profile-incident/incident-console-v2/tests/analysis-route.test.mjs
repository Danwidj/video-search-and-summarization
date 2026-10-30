// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

let headContentLength = 1024;
// The stored video's bytes for ranged reads (the MP4 length reader); null = unreadable.
let videoBytes = null;

/** A minimal MP4 (ftyp, mdat, then moov/mvhd) whose header says `seconds` long. */
function mp4Bytes(seconds, mdatBytes = 1000, createdUnixSeconds = 0) {
  const box = (type, body) => {
    const out = Buffer.alloc(8 + body.length);
    out.writeUInt32BE(8 + body.length, 0);
    out.write(type, 4, 'latin1');
    body.copy(out, 8);
    return out;
  };
  const mvhdBody = Buffer.alloc(4 + 8 + 8 + 80);
  if (createdUnixSeconds) mvhdBody.writeUInt32BE(createdUnixSeconds + 2082844800, 4);
  mvhdBody.writeUInt32BE(1000, 12);
  mvhdBody.writeUInt32BE(Math.round(seconds * 1000), 16);
  return Buffer.concat([box('ftyp', Buffer.alloc(8)), box('mdat', Buffer.alloc(mdatBytes)), box('moov', box('mvhd', mvhdBody))]);
}

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        if (command.constructor.name === 'HeadObjectCommand')
          return Promise.resolve({ ContentLength: videoBytes ? videoBytes.length : headContentLength });
        if (command.constructor.name === 'GetObjectCommand' && command.input?.Range && videoBytes) {
          const [, from, to] = /bytes=(\d+)-(\d+)/.exec(command.input.Range);
          const slice = new Uint8Array(videoBytes.subarray(Number(from), Number(to) + 1));
          return Promise.resolve({ Body: { transformToByteArray: async () => slice } });
        }
        return Promise.resolve({});
      }
    },
    GetObjectCommand: class GetObjectCommand {
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

const { POST } = await import('../src/app/api/analysis/route.ts');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');
const { getServiceConfiguration } = await import('../src/lib/env.ts');

/** remove_video (delete mode) over the fake's tables, as the migration defines it. */
function removeVideo({ p_video_id: videoId }, store) {
  const video = store.videos.find((row) => row.id === videoId);
  if (!video) throw new Error(`video ${videoId} does not exist`);
  store.videos = store.videos.filter((row) => row.id !== videoId);
  const emptied = !store.videos.some((row) => row.incident_id === video.incident_id);
  if (emptied) store.incidents = store.incidents.filter((row) => row.id !== video.incident_id);
  return { incident_id: video.incident_id, incident_deleted: emptied, deleted_video_key: video.filepath, deleted_crop_images: [] };
}

// The in-memory PostgREST every test's Supabase calls land on; replaced before each test.
let testDb;
const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;

function setBaseEnv() {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8001';
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
  testDb = fakePostgrest({ incidents: [], videos: [] }, { identity: { incidents: 'id' }, rpc: { remove_video: removeVideo } });
  headContentLength = 1024;
  videoBytes = null;
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

const UPLOAD = { sensorId: 'sensor-1', filepath: 'uploads/front-door.mp4', filename: 'front-door.mp4' };

/** Database calls go to the fake PostgREST; the agent's answer is `agent(body, url)`. */
function stubFetch(agent) {
  const agentCalls = [];
  globalThis.fetch = async (url, init) => {
    if (String(url).startsWith('https://supabase.test')) return testDb.fetch(url, init);
    agentCalls.push({ url: String(url), body: JSON.parse(init.body) });
    return agent(JSON.parse(init.body), String(url));
  };
  return agentCalls;
}

const analysed = (body) =>
  new Response(
    JSON.stringify({ analysis_id: 41, model_run_id: body.model_run_id, outcome: 'stored', report: { incident: { type: 'assault' } } }),
    {
      status: 200,
    },
  );

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
  for (const body of [{ filepath: UPLOAD.filepath, filename: UPLOAD.filename }, { sensorId: 's-1', filepath: UPLOAD.filepath }, {}]) {
    assert.equal((await POST(jsonRequest(body))).status, 400);
  }
});

test('analysis route: a new upload creates its incident and video, stores the analysis and answers with the ids', async () => {
  const agentCalls = stubFetch(analysed);

  const response = await POST(jsonRequest({ ...UPLOAD, model: 'nvidia/cosmos-3-nano-reasoner' }));

  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.videoName, 'front-door.mp4');
  assert.equal(result.analysisId, 41);
  assert.equal(typeof result.incidentId, 'number');
  assert.match(result.modelRunId, /^front-door\.mp4@\d{4}-\d\d-\d\dT/);
  assert.deepEqual(
    testDb.store.videos.map((row) => [row.id, row.incident_id, row.filepath, row.source]),
    [['front-door.mp4', result.incidentId, 'uploads/front-door.mp4', 'sensor-1']],
  );
  assert.equal(agentCalls.length, 1);
  assert.equal(agentCalls[0].url, 'http://agent.test:8001/api/v1/incidents/front-door.mp4/analyze');
  assert.equal(agentCalls[0].body.video_key, 'uploads/front-door.mp4');
  assert.equal(agentCalls[0].body.model_run_id, result.modelRunId);
  // The console writes no revision and no analysis: the agent stores the analysis.
  assert.equal(testDb.store.report_revisions, undefined);
  assert.equal(testDb.store.video_analyses, undefined);
});

test('analysis route: a video already stored is analysed again in its own incident', async () => {
  stubFetch(analysed);
  const first = await (await POST(jsonRequest(UPLOAD))).json();

  const response = await POST(jsonRequest({ videoName: 'front-door.mp4', additionalInstruction: 'watch the door' }));

  assert.equal(response.status, 200);
  const again = await response.json();
  assert.equal(again.incidentId, first.incidentId);
  assert.equal(again.videoName, 'front-door.mp4');
  assert.equal(testDb.store.videos.length, 1);
  assert.equal((await (await POST(jsonRequest({ videoName: 'nope.mp4' }))).json()).error, 'Video not found: nope.mp4');
});

test('analysis route: an upload under a taken name is refused with 409', async () => {
  stubFetch(analysed);
  await POST(jsonRequest(UPLOAD));
  assert.equal((await POST(jsonRequest(UPLOAD))).status, 409);
});

test('analysis route: a contract failure keeps the raw output and leaves no video behind', async () => {
  stubFetch(
    () =>
      new Response(JSON.stringify({ detail: { message: 'bad json', raw_output: 'not json', finish_reason: 'length', model: 'm' } }), {
        status: 422,
      }),
  );

  const response = await POST(jsonRequest(UPLOAD));

  assert.equal(response.status, 422);
  const body = await response.json();
  assert.equal(body.outcome, 'contract_failed');
  assert.equal(body.rawContent, 'not json');
  assert.equal(testDb.store.videos.length, 0);
  assert.equal(testDb.store.incidents.length, 0);
});

test('analysis route: a slow VLM ends as 504 inside the route limit and leaves no video behind', async () => {
  globalThis.fetch = async (url, init) => {
    if (String(url).startsWith('https://supabase.test')) return testDb.fetch(url, init);
    throw new DOMException('The operation was aborted due to timeout', 'TimeoutError');
  };

  const response = await POST(jsonRequest(UPLOAD));

  assert.equal(response.status, 504);
  assert.match((await response.json()).error, /did not finish the analysis in time/);
  assert.equal(testDb.store.videos.length, 0);
});

test('analysis route: an object that is not in storage is refused before the agent is called', async () => {
  headContentLength = 0;
  const agentCalls = stubFetch(analysed);

  const response = await POST(jsonRequest(UPLOAD));

  assert.equal(response.status, 404);
  assert.match((await response.json()).error, /is not in storage/);
  assert.equal(agentCalls.length, 0);
  assert.equal(testDb.store.videos.length, 0);
});

test('analysis route: recorded_at comes from the file header when it carries one', async () => {
  videoBytes = mp4Bytes(8, 100, Date.UTC(2026, 9, 29, 8, 0, 0) / 1000);
  stubFetch(analysed);

  assert.equal((await POST(jsonRequest(UPLOAD))).status, 200);

  const [video] = testDb.store.videos;
  assert.equal(new Date(video.recorded_at).toISOString(), '2026-10-29T08:00:00.000Z');
  assert.equal(video.duration, 8);
});

test('analysis route: the agent URL and Supabase must be configured; there is no gateway mode', async () => {
  delete process.env.INCIDENT_AGENT_BASE_URL;
  const res1 = await POST(jsonRequest(UPLOAD));
  assert.equal(res1.status, 500);
  assert.match((await res1.json()).error, /INCIDENT_AGENT_BASE_URL is not configured/);

  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8001';
  delete process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY;
  const res2 = await POST(jsonRequest(UPLOAD));
  assert.equal(res2.status, 500);
  assert.match((await res2.json()).error, /Supabase PostgREST is not configured/);
});

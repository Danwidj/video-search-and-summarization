// SPDX-License-Identifier: Apache-2.0

// Build report (Regenerate): the use case over the in-memory fakes, and the route over the
// Supabase adapters on a fake PostgREST.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';
import { incidentRpcs } from './support/incident-database.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { buildIncidentReport, BuildReportError } = await import('../src/modules/reports/application/build-incident-report/index.ts');
const { InMemoryIncidentReportRepository } = await import('../src/modules/reports/infrastructure/memory/incident-reports.ts');
const { InMemoryIncidentVideoRepository } = await import('../src/modules/videos/infrastructure/memory/incident-videos.ts');
const { InMemoryModelRunRepository } = await import('../src/modules/analysis/infrastructure/memory/model-runs.ts');
const { InMemoryVideoAnalysisRepository } = await import('../src/modules/analysis/infrastructure/memory/video-analyses.ts');
const { FakeIncidentSynthesizer } = await import('../src/modules/analysis/infrastructure/agent/fake-incident-synthesizer.ts');
const { FakeEvidenceLinker } = await import('../src/modules/analysis/infrastructure/agent/fake-evidence-linker.ts');
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');
const { POST } = await import('../src/app/api/reports/[incidentId]/build/route.ts');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' });
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test';
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const FRONT = 'p5-2-front-door.mp4';
const LOBBY = 'p5-2-lobby.mp4';
const OLD_RUN = 'p5-2-front-door.mp4@2026-10-01T00:00:00.000Z';
const LOBBY_RUN = 'p5-2-lobby.mp4@2026-10-02T00:00:00.000Z';
const NOW = new Date('2026-10-30T02:03:04.000Z');

const report = (type, severity, start, end, description) => ({
  incident: { type, severity_level: severity, start_timestamp: start, end_timestamp: end, description, location: 'Front door' },
  entities: [],
  instruments: [],
  assets: [],
  timeline: [],
});
const evidenceOf = (video) => [
  { item_type: 'entity', item_id: 'E1', image: `evidence/${video}/E1.jpg`, bounding_box: null, timestamp_seconds: 1 },
];

const videoRow = (id, incidentId, uploadedAt) => ({
  videoId: id,
  incidentId,
  storageKey: id,
  recordedAt: null,
  uploadedAt,
  durationSeconds: 10,
  source: 'upload',
});

/** Incident 1 holds FRONT and LOBBY (both analysed; FRONT twice); incident 2 holds an unanalysed video. */
async function memoryPorts({ analyseLobby = true, synthesizer = new FakeIncidentSynthesizer() } = {}) {
  const reports = new InMemoryIncidentReportRepository({
    incidents: [
      { incidentId: 1, officialRevisionId: null, officialSince: null, createdAt: '2026-10-01T00:00:00' },
      { incidentId: 2, officialRevisionId: null, officialSince: null, createdAt: '2026-10-01T00:00:00' },
    ],
    videos: [
      { ...videoRow(FRONT, 1, '2026-10-01T01:00:00'), incidentId: 1 },
      { ...videoRow(LOBBY, 1, '2026-10-02T01:00:00'), incidentId: 1 },
      { ...videoRow('p5-2-bare.mp4', 2, '2026-10-02T01:00:00'), incidentId: 2 },
    ],
  });
  const runs = new InMemoryModelRunRepository();
  const record = runs.recordRun.bind(runs);
  runs.recordRun = async (run) => {
    await record(run);
    reports.modelRuns.set(run.id, run.modelName);
  };
  const analyses = new InMemoryVideoAnalysisRepository([FRONT, LOBBY, 'p5-2-bare.mp4'], runs);
  const run = (id, at) => ({ id, modelName: 'model-x', modelVersion: null, promptVersion: 'incident-contract-v4', runAt: at, notes: null });
  await runs.recordRun(run(OLD_RUN, '2026-10-01T00:00:00.000Z'));
  await runs.recordRun(run('p5-2-front-door.mp4@2026-10-03T00:00:00.000Z', '2026-10-03T00:00:00.000Z'));
  await runs.recordRun(run(LOBBY_RUN, '2026-10-02T00:00:00.000Z'));
  await analyses.saveAnalysis({
    videoId: FRONT,
    modelRunId: OLD_RUN,
    payload: report('Theft', 2, 1, 4, 'old front'),
    evidence: evidenceOf(FRONT),
    createdAt: '2026-10-01T00:00:00.000Z',
  });
  await analyses.saveAnalysis({
    videoId: FRONT,
    modelRunId: 'p5-2-front-door.mp4@2026-10-03T00:00:00.000Z',
    payload: report('Theft', 3, 2, 6, 'new front'),
    evidence: evidenceOf(FRONT),
    createdAt: '2026-10-03T00:00:00.000Z',
  });
  if (analyseLobby) {
    await analyses.saveAnalysis({
      videoId: LOBBY,
      modelRunId: LOBBY_RUN,
      payload: report('Theft', 4, 5, 9, 'lobby'),
      evidence: evidenceOf(LOBBY),
      createdAt: '2026-10-02T00:00:00.000Z',
    });
  }
  const videos = new InMemoryIncidentVideoRepository([...reports.videos.map((video) => ({ ...video }))]);
  return { ports: { incidents: reports, videos, analyses, modelRuns: runs, synthesizer, now: () => NOW }, reports, runs, synthesizer };
}

describe('buildIncidentReport', () => {
  test('builds a version covering exactly the incident videos from the latest analysis of each, without re-analysing', async () => {
    const { ports, reports, runs, synthesizer } = await memoryPorts();
    const built = await buildIncidentReport(ports, { incidentId: 1, note: ' Regenerated ' });

    assert.deepEqual(built.videoNames, [FRONT, LOBBY]);
    assert.equal(built.revisionNo, 1);
    assert.equal(built.modelRunId, 'incident-1@2026-10-30T02:03:04.000Z');
    // The agent saw the newest analysis of each video, in order, and nothing else.
    assert.deepEqual(
      synthesizer.calls[0].map((video) => [video.videoName, video.payload.incident.description]),
      [
        [FRONT, 'new front'],
        [LOBBY, 'lobby'],
      ],
    );
    const stored = reports.revisions.at(-1);
    assert.equal(stored.revision.kind, 'ai');
    assert.equal(stored.revision.note, 'Regenerated');
    assert.deepEqual(stored.revision.videoNames, [FRONT, LOBBY]);
    assert.deepEqual(
      stored.payload.cameras.map((camera) => [camera.video, camera.report.incident.description]),
      [
        [FRONT, 'new front'],
        [LOBBY, 'lobby'],
      ],
    );
    assert.equal(stored.payload.overview.severity_level, 4);
    assert.deepEqual(
      stored.evidence.map((entry) => [entry.video, entry.image]),
      [
        [FRONT, `evidence/${FRONT}/E1.jpg`],
        [LOBBY, `evidence/${LOBBY}/E1.jpg`],
      ],
    );
    const run = await runs.getRun(built.modelRunId);
    assert.equal(run.modelName, 'model-x');
    assert.equal(run.promptVersion, 'incident-contract-v4');
    assert.equal(JSON.parse(run.notes).recordType, 'incident_synthesis');
  });

  test('a second build appends the next version and follows a changed video set', async () => {
    const { ports, reports } = await memoryPorts();
    await buildIncidentReport(ports, { incidentId: 1 });
    ports.videos.videos.delete(LOBBY);
    ports.now = () => new Date('2026-10-30T03:00:00.000Z');
    reports.videos.splice(
      reports.videos.findIndex((video) => video.videoId === LOBBY),
      1,
    );
    const second = await buildIncidentReport(ports, { incidentId: 1 });
    assert.equal(second.revisionNo, 2);
    assert.deepEqual(second.videoNames, [FRONT]);
    assert.deepEqual(reports.revisions[0].revision.videoNames, [FRONT, LOBBY]);
  });

  test('refuses, writing nothing, when a current video has no analysis', async () => {
    const { ports, reports, runs } = await memoryPorts({ analyseLobby: false });
    await assert.rejects(
      buildIncidentReport(ports, { incidentId: 1 }),
      (error) => error instanceof BuildReportError && error.status === 409 && error.details.videos[0] === LOBBY,
    );
    assert.equal(reports.revisions.length, 0);
    assert.equal(ports.synthesizer.calls.length, 0);
    assert.equal(await runs.getRun('incident-1@2026-10-30T02:03:04.000Z'), null);
  });

  test('refuses an unknown incident, a missing agent and agent failures without writing', async () => {
    const { ports, reports } = await memoryPorts();
    await assert.rejects(
      buildIncidentReport(ports, { incidentId: 99 }),
      (error) => error instanceof StoreRejection && error.reason === 'not-found',
    );
    await assert.rejects(buildIncidentReport({ ...ports, synthesizer: null }, { incidentId: 1 }), (error) => error.status === 503);
    const failing = { ...ports, synthesizer: new FakeIncidentSynthesizer([{ kind: 'failed', status: 422, message: 'nope' }]) };
    await assert.rejects(buildIncidentReport(failing, { incidentId: 1 }), (error) => error.status === 502 && /nope/.test(error.message));
    const timeout = { ...ports, synthesizer: new FakeIncidentSynthesizer([new AgentRequestError('AGENT_TIMEOUT', 'slow')]) };
    await assert.rejects(buildIncidentReport(timeout, { incidentId: 1 }), (error) => error.status === 504);
    assert.equal(reports.revisions.length, 0);
  });
});

describe('buildIncidentReport evidence groups', () => {
  const GROUP = {
    id: 'G1',
    kind: 'entity',
    label: 'Man at the door',
    members: [
      { video: FRONT, itemId: 'E1' },
      { video: LOBBY, itemId: 'E1' },
    ],
    source: 'ai',
  };

  test('stores the linker groups on a version built from two videos', async () => {
    const { ports, reports } = await memoryPorts();
    const linker = new FakeEvidenceLinker([{ kind: 'linked', groups: [GROUP] }]);
    await buildIncidentReport({ ...ports, linker }, { incidentId: 1 });
    assert.deepEqual(
      linker.calls[0].map((video) => video.videoName),
      [FRONT, LOBBY],
    );
    assert.deepEqual(reports.revisions.at(-1).payload.evidence_groups, [GROUP]);
  });

  test('a failed, thrown or empty link stores no field and never fails the build', async () => {
    for (const script of [
      [{ kind: 'failed', status: 502, message: 'x' }],
      [new AgentRequestError('AGENT_TIMEOUT', 'slow')],
      [{ kind: 'linked', groups: [] }],
    ]) {
      const { ports, reports } = await memoryPorts();
      const built = await buildIncidentReport({ ...ports, linker: new FakeEvidenceLinker(script) }, { incidentId: 1 });
      assert.equal(built.revisionNo, 1);
      assert.equal('evidence_groups' in reports.revisions.at(-1).payload, false);
    }
  });

  test('a one-video version skips the linker', async () => {
    const { ports, reports } = await memoryPorts();
    ports.videos.videos.delete(LOBBY);
    reports.videos.splice(
      reports.videos.findIndex((video) => video.videoId === LOBBY),
      1,
    );
    const linker = new FakeEvidenceLinker([{ kind: 'linked', groups: [GROUP] }]);
    await buildIncidentReport({ ...ports, linker }, { incidentId: 1 });
    assert.equal(linker.calls.length, 0);
    assert.equal('evidence_groups' in reports.revisions.at(-1).payload, false);
  });
});

describe('POST /api/reports/[incidentId]/build', () => {
  const store = () => ({
    incidents: [{ id: 1, official_revision_id: null, official_since: null, created_at: '2026-10-01T00:00:00' }],
    videos: [
      {
        id: FRONT,
        incident_id: 1,
        filepath: FRONT,
        uploaded_datetime: '2026-10-01T01:00:00',
        recorded_at: null,
        duration: 10,
        source: 'upload',
      },
      {
        id: LOBBY,
        incident_id: 1,
        filepath: LOBBY,
        uploaded_datetime: '2026-10-02T01:00:00',
        recorded_at: null,
        duration: 10,
        source: 'upload',
      },
    ],
    model_runs: [
      {
        id: OLD_RUN,
        model_name: 'model-x',
        model_version: null,
        prompt_version: 'incident-contract-v4',
        run_datetime: '2026-10-01T00:00:00',
        notes: null,
      },
      {
        id: LOBBY_RUN,
        model_name: 'model-x',
        model_version: null,
        prompt_version: 'incident-contract-v4',
        run_datetime: '2026-10-02T00:00:00',
        notes: null,
      },
    ],
    video_analyses: [
      {
        id: 1,
        video_id: FRONT,
        model_run_id: OLD_RUN,
        payload: report('Theft', 2, 1, 4, 'front'),
        evidence: evidenceOf(FRONT),
        created_at: '2026-10-01T00:00:00Z',
      },
      {
        id: 2,
        video_id: LOBBY,
        model_run_id: LOBBY_RUN,
        payload: report('Theft', 4, 5, 9, 'lobby'),
        evidence: evidenceOf(LOBBY),
        created_at: '2026-10-02T00:00:00Z',
      },
    ],
    report_revisions: [],
    evidence_crops: [],
  });

  const call = (incidentId, body) =>
    POST(new Request(`http://localhost/api/reports/${incidentId}/build`, { method: 'POST', body }), {
      params: Promise.resolve({ incidentId }),
    });

  function serve(fake, agent) {
    globalThis.fetch = async (url, init) => {
      if (String(url).startsWith('http://agent.test/')) return agent(JSON.parse(init.body));
      return fake.fetch(url, init);
    };
  }
  const synthesis = (body) =>
    new Response(
      JSON.stringify({ overview: { ...body.videos[0].payload.incident, title: 'Two cameras' }, embedding: Array(1024).fill(0.5) }),
    );

  test('stores the version through the database and answers with its coverage', async () => {
    const fake = fakePostgrest(store(), { rpc: incidentRpcs, identity: { report_revisions: 'id', video_analyses: 'id' } });
    serve(fake, synthesis);
    const response = await call('1', JSON.stringify({ note: 'Regenerate' }));
    assert.equal(response.status, 200);
    const { built } = await response.json();
    assert.deepEqual(built.videoNames, [FRONT, LOBBY]);
    assert.equal(built.revisionNo, 1);
    const [row] = fake.store.report_revisions;
    assert.deepEqual(row.video_names, [FRONT, LOBBY]);
    assert.equal(row.payload.overview.title, 'Two cameras');
    assert.equal(row.payload.cameras.length, 2);
    assert.equal(row.note, 'Regenerate');
    assert.equal(
      fake.store.model_runs.some((run) => run.id === built.modelRunId),
      true,
    );
  });

  test('stores evidence_groups from the agent link-evidence answer and survives a failing link', async () => {
    const group = {
      id: 'G1',
      kind: 'entity',
      label: 'Man at the door',
      members: [
        { video: FRONT, itemId: 'E1' },
        { video: LOBBY, itemId: 'E1' },
      ],
      source: 'ai',
    };
    const links = [
      { respond: () => new Response(JSON.stringify({ evidence_groups: [group] })), stored: [group] },
      { respond: () => new Response('down', { status: 503 }), stored: undefined },
    ];
    for (const link of links) {
      const fake = fakePostgrest(store(), { rpc: incidentRpcs, identity: { report_revisions: 'id', video_analyses: 'id' } });
      globalThis.fetch = async (url, init) => {
        if (String(url) === 'http://agent.test/api/v1/incidents/link-evidence') return link.respond();
        if (String(url).startsWith('http://agent.test/')) return synthesis(JSON.parse(init.body));
        return fake.fetch(url, init);
      };
      assert.equal((await call('1', '')).status, 200);
      const [row] = fake.store.report_revisions;
      assert.deepEqual(row.payload.evidence_groups, link.stored);
    }
  });

  test('answers 400, 404, 409 and 502 for a bad id, an unknown incident, an unanalysed video and an agent failure', async () => {
    const fake = fakePostgrest(store(), { rpc: incidentRpcs, identity: { report_revisions: 'id', video_analyses: 'id' } });
    serve(fake, () => new Response(JSON.stringify({ detail: 'overloaded' }), { status: 503 }));
    assert.equal((await call('abc', '')).status, 400);
    assert.equal((await call('1', '{"other":1}')).status, 400);
    assert.equal((await call('7', '')).status, 404);
    assert.equal((await call('1', '')).status, 502);
    fake.store.video_analyses.pop();
    const unanalysed = await call('1', '');
    assert.equal(unanalysed.status, 409);
    assert.deepEqual((await unanalysed.json()).videos, [LOBBY]);
    assert.equal(fake.store.report_revisions.length, 0);
  });
});

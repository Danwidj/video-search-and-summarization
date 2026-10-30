// SPDX-License-Identifier: Apache-2.0

// The analyse use case (analyseVideo) over the in-memory video repository, the fake analyzer and a
// stub object store: a new upload creates its incident and video, an existing video is analysed
// again, and every failure ends as a plain AnalysisRequestError.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { analyseVideo, ANALYSIS_DEADLINE_MS } = await import('../src/modules/analysis/application/analyse-video.ts');
const { AnalysisRequestError } = await import('../src/modules/analysis/application/run-contract-analysis.ts');
const { FakeVideoAnalyzer } = await import('../src/modules/analysis/infrastructure/agent/fake-video-analyzer.ts');
const { InMemoryIncidentVideoRepository } = await import('../src/modules/videos/infrastructure/memory/incident-videos.ts');
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');
const { defaultContractCatalog } = await import('../src/modules/contract/infrastructure/loader.ts');

const MODEL = defaultContractCatalog.allowedModels()[0];
const NOW = new Date('2026-10-30T01:02:03.000Z');

function objects(overrides = {}) {
  const calls = [];
  return {
    calls,
    verify: async (key) => {
      calls.push(['verify', key]);
      if (overrides.missing) throw new Error('object not found');
      return { contentLength: 4096 };
    },
    playbackUrl: async () => 'https://signed.test/video.mp4',
    durationSeconds: async () => ('duration' in overrides ? overrides.duration : 12.5),
    recordedAt: async () => ('recordedAt' in overrides ? overrides.recordedAt : '2026-10-29T08:00:00.000Z'),
  };
}

function setup({ script, store = {}, videos = [] } = {}) {
  const repository = new InMemoryIncidentVideoRepository(videos, () => NOW);
  const analyzer = new FakeVideoAnalyzer(script);
  const stored = objects(store);
  return {
    repository,
    analyzer,
    stored,
    ports: { videos: repository, objects: stored, analyzer, catalog: defaultContractCatalog, now: () => NOW },
  };
}

const upload = (extra = {}) => ({
  kind: 'upload',
  videoName: 'front-door.mp4',
  storageKey: 'uploads/front-door.mp4',
  sensorId: 'sensor-1',
  model: MODEL.id,
  ...extra,
});

const rejects = (promise, status) =>
  assert.rejects(promise, (error) => {
    assert.ok(error instanceof AnalysisRequestError, String(error));
    assert.equal(error.status, status);
    return true;
  });

describe('analyseVideo: a new upload', () => {
  test('creates the incident and video, analyses once and returns the ids', async () => {
    const { ports, repository, analyzer } = setup();
    const result = await analyseVideo(upload({ additionalInstruction: '  look at the door  ' }), ports);

    const video = await repository.getVideo('front-door.mp4');
    assert.deepEqual(
      { id: video.videoId, key: video.storageKey, recordedAt: video.recordedAt, duration: video.durationSeconds, source: video.source },
      { id: 'front-door.mp4', key: 'uploads/front-door.mp4', recordedAt: '2026-10-29T08:00:00.000Z', duration: 13, source: 'sensor-1' }, // the row keeps whole seconds
    );
    assert.equal(result.incidentId, video.incidentId);
    assert.equal(result.videoName, 'front-door.mp4');
    assert.equal(result.analysisId, 1);
    assert.equal(result.model, MODEL.id);
    assert.equal(result.promptVersion, defaultContractCatalog.contractVersion());

    assert.equal(analyzer.requests.length, 1);
    assert.deepEqual(analyzer.requests[0], {
      videoName: 'front-door.mp4',
      videoKey: 'uploads/front-door.mp4',
      videoUrl: 'https://signed.test/video.mp4',
      model: MODEL.id,
      reviewerPrompt: 'look at the door',
      modelRunId: 'front-door.mp4@2026-10-30T01:02:03.000Z',
      videoDurationSeconds: 12.5,
    });
    assert.equal(result.modelRunId, analyzer.requests[0].modelRunId);
  });

  test('stores no recorded_at when the file carries none', async () => {
    const { ports, repository } = setup({ store: { recordedAt: null } });
    await analyseVideo(upload(), ports);
    assert.equal((await repository.getVideo('front-door.mp4')).recordedAt, null);
  });

  test('every upload starts its own incident', async () => {
    const { ports } = setup();
    const first = await analyseVideo(upload(), ports);
    const second = await analyseVideo(upload({ videoName: 'back-door.mp4', storageKey: 'uploads/back-door.mp4' }), ports);
    assert.notEqual(first.incidentId, second.incidentId);
  });

  test('refuses a name that is already taken without touching the existing video', async () => {
    const { ports, repository, analyzer } = setup();
    await analyseVideo(upload(), ports);
    analyzer.requests.length = 0;
    await rejects(analyseVideo(upload(), ports), 409);
    assert.equal(analyzer.requests.length, 0);
    assert.ok(await repository.getVideo('front-door.mp4'));
  });

  test('rejects a model outside the allowlist, a bad key and a missing object before creating anything', async () => {
    const { ports, repository } = setup();
    await rejects(analyseVideo(upload({ model: 'not-a-model' }), ports), 400);
    await rejects(analyseVideo(upload({ storageKey: '../outside.mp4' }), ports), 400);
    await rejects(analyseVideo(upload({ additionalInstruction: 'x'.repeat(1001) }), ports), 400);
    const missing = setup({ store: { missing: true } });
    await rejects(analyseVideo(upload(), missing.ports), 404);
    assert.equal(repository.videos.size, 0);
    assert.equal(missing.repository.videos.size, 0);
  });

  const failures = [
    [
      'a contract refusal',
      422,
      [{ kind: 'contract_refused', message: 'bad', rawOutput: 'raw', finishReason: 'stop', model: 'm', contractVersion: 'v' }],
    ],
    ['an agent error', 502, [{ kind: 'failed', status: 500, message: 'boom' }]],
    ['an unreachable agent', 502, [new AgentRequestError('AGENT_FETCH_FAILED', 'refused')]],
    ['a slow VLM', 504, [new AgentRequestError('AGENT_TIMEOUT', 'timed out')]],
  ];
  for (const [label, status, script] of failures) {
    test(`removes the new video and its incident after ${label}`, async () => {
      const { ports, repository } = setup({ script });
      await rejects(analyseVideo(upload(), ports), status);
      assert.equal(repository.videos.size, 0);
      // The same name can be uploaded again.
      const retry = new FakeVideoAnalyzer();
      await analyseVideo(upload(), { ...ports, analyzer: retry });
      assert.ok(await repository.getVideo('front-door.mp4'));
    });
  }

  test('a contract refusal carries the raw model output for the reviewer', async () => {
    const { ports } = setup({
      script: [
        { kind: 'contract_refused', message: 'bad', rawOutput: 'raw text', finishReason: 'length', model: 'm', contractVersion: 'v' },
      ],
    });
    await assert.rejects(analyseVideo(upload(), ports), (error) => {
      assert.equal(error.details.outcome, 'contract_failed');
      assert.equal(error.details.rawContent, 'raw text');
      assert.equal(error.details.finishReason, 'length');
      return true;
    });
  });
});

describe('analyseVideo: an existing video', () => {
  const stored = {
    videoId: 'lobby.mp4',
    incidentId: 7,
    storageKey: 'uploads/lobby.mp4',
    recordedAt: null,
    uploadedAt: '2026-10-01T00:00:00.000Z',
    durationSeconds: 30,
    source: 'sensor-9',
  };

  test('adds an analysis to the same incident and leaves the video row alone', async () => {
    const { ports, repository, analyzer } = setup({ videos: [stored] });
    const result = await analyseVideo({ kind: 'reanalysis', videoName: 'lobby.mp4', model: MODEL.id }, ports);
    assert.equal(result.incidentId, 7);
    assert.equal(result.videoName, 'lobby.mp4');
    assert.equal(analyzer.requests[0].videoKey, 'uploads/lobby.mp4');
    assert.equal(analyzer.requests[0].videoDurationSeconds, 30);
    assert.deepEqual(await repository.getVideo('lobby.mp4'), stored);
  });

  test('reads the length from the file when the row has none', async () => {
    const { ports, analyzer } = setup({ videos: [{ ...stored, durationSeconds: null }] });
    await analyseVideo({ kind: 'reanalysis', videoName: 'lobby.mp4', model: MODEL.id }, ports);
    assert.equal(analyzer.requests[0].videoDurationSeconds, 12.5);
  });

  test('never removes the video when the analysis fails', async () => {
    const { ports, repository } = setup({ videos: [stored], script: [{ kind: 'failed', status: 500, message: 'boom' }] });
    await rejects(analyseVideo({ kind: 'reanalysis', videoName: 'lobby.mp4', model: MODEL.id }, ports), 502);
    assert.deepEqual(await repository.getVideo('lobby.mp4'), stored);
  });

  test('answers 404 for an unknown video and 409 for one with no stored object', async () => {
    const { ports } = setup({ videos: [{ ...stored, videoId: 'ghost.mp4', storageKey: null }] });
    await rejects(analyseVideo({ kind: 'reanalysis', videoName: 'nope.mp4', model: MODEL.id }, ports), 404);
    await rejects(analyseVideo({ kind: 'reanalysis', videoName: 'ghost.mp4', model: MODEL.id }, ports), 409);
  });
});

describe('analyseVideo: the time limit', () => {
  test('the agent call is bounded by the model timeout and never outlives the route', async () => {
    assert.ok(ANALYSIS_DEADLINE_MS < 360_000);
    const seen = [];
    const { ports } = setup();
    const analyzer = {
      analyze: async (request, signal) => {
        seen.push(signal);
        return new FakeVideoAnalyzer().analyze(request, signal);
      },
    };
    await analyseVideo(upload(), { ...ports, analyzer });
    assert.equal(seen.length, 1);
    assert.ok(seen[0] instanceof AbortSignal);
    assert.equal(seen[0].aborted, false);
  });

  test('a signal that fires ends as a 504 and cleans up the new video', async () => {
    const { ports, repository } = setup();
    const analyzer = {
      analyze: (_request, signal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new AgentRequestError('AGENT_TIMEOUT', 'aborted')));
          setTimeout(() => reject(new AgentRequestError('AGENT_TIMEOUT', 'aborted')), 5);
        }),
    };
    await rejects(analyseVideo(upload(), { ...ports, analyzer }), 504);
    assert.equal(repository.videos.size, 0);
  });
});

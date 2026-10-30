// SPDX-License-Identifier: Apache-2.0

// The agent's analyse contract requires a signed video_url next to video_key: the analyse use case
// signs the stored object's key and the HTTP client sends both.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { analyseVideo } = await import('../src/modules/analysis/application/analyse-video.ts');
const { HttpVideoAnalyzer } = await import('../src/modules/analysis/infrastructure/agent/video-analyzer.ts');
const { FakeVideoAnalyzer } = await import('../src/modules/analysis/infrastructure/agent/fake-video-analyzer.ts');
const { InMemoryIncidentVideoRepository } = await import('../src/modules/videos/infrastructure/memory/incident-videos.ts');
const { defaultContractCatalog } = await import('../src/modules/contract/infrastructure/loader.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const NOW = new Date('2026-10-30T01:02:03.000Z');
const MODEL = defaultContractCatalog.allowedModels()[0];

function objects() {
  const signed = [];
  return {
    signed,
    verify: async () => ({ contentLength: 4096 }),
    playbackUrl: async (key) => {
      signed.push(key);
      return `https://signed.test/${key}?sig=abc`;
    },
    durationSeconds: async () => 12.5,
    recordedAt: async () => null,
  };
}

describe('analyse sends the signed video URL', () => {
  test('the HTTP client posts video_url and video_key together', async () => {
    const calls = [];
    globalThis.fetch = async (_url, init) => {
      calls.push(JSON.parse(init.body));
      return new Response(JSON.stringify({ analysis_id: 1, model_run_id: 'r', outcome: 'stored', report: {} }), { status: 200 });
    };
    await new HttpVideoAnalyzer('http://agent').analyze(
      {
        videoName: 'a.mp4',
        videoKey: 'uploads/a.mp4',
        videoUrl: 'https://signed.test/uploads/a.mp4?sig=abc',
        model: 'qwen',
        reviewerPrompt: null,
        modelRunId: 'r',
        videoDurationSeconds: null,
      },
      new AbortController().signal,
    );
    assert.equal(calls[0].video_url, 'https://signed.test/uploads/a.mp4?sig=abc');
    assert.equal(calls[0].video_key, 'uploads/a.mp4');
  });

  for (const kind of ['upload', 'reanalysis']) {
    test(`a ${kind} signs the stored key and hands the URL to the analyzer`, async () => {
      const repository = new InMemoryIncidentVideoRepository([], () => NOW);
      const store = objects();
      const analyzer = new FakeVideoAnalyzer();
      const ports = { videos: repository, objects: store, analyzer, catalog: defaultContractCatalog, now: () => NOW };
      const input = { model: MODEL.id, kind: 'upload', videoName: 'a.mp4', storageKey: 'uploads/a.mp4', sensorId: 's' };
      await analyseVideo(input, ports);
      if (kind === 'reanalysis') await analyseVideo({ model: MODEL.id, kind, videoName: 'a.mp4' }, ports);

      const last = analyzer.requests.at(-1);
      assert.equal(last.videoKey, 'uploads/a.mp4');
      assert.equal(last.videoUrl, 'https://signed.test/uploads/a.mp4?sig=abc');
      assert.deepEqual(store.signed.at(-1), 'uploads/a.mp4');
    });
  }
});

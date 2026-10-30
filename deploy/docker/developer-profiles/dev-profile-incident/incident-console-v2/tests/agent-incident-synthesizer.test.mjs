// SPDX-License-Identifier: Apache-2.0

// The synthesise client (HttpIncidentSynthesizer) against a stubbed fetch, and its in-memory fake.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { HttpIncidentSynthesizer, EMBEDDING_DIMENSIONS } = await import(
  '../src/modules/analysis/infrastructure/agent/incident-synthesizer.ts'
);
const { FakeIncidentSynthesizer } = await import('../src/modules/analysis/infrastructure/agent/fake-incident-synthesizer.ts');
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const signal = new AbortController().signal;
const embedding = () => Array.from({ length: EMBEDDING_DIMENSIONS }, () => 0.5);
const VIDEOS = [
  {
    videoName: 'a.mp4',
    payload: { incident: { type: 'assault', title: 'A', start_timestamp: 5, end_timestamp: 9, severity_level: 2, description: 'one' } },
  },
  {
    videoName: 'b.mp4',
    payload: { incident: { type: 'assault', title: 'B', start_timestamp: 2, end_timestamp: 20, severity_level: 4, description: 'two' } },
  },
];

function stubFetch(status, body) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  };
  return calls;
}

describe('HttpIncidentSynthesizer', () => {
  test('posts the videos as snake_case and returns the overview and embedding', async () => {
    const calls = stubFetch(200, { overview: { title: 'Both' }, embedding: embedding() });
    const result = await new HttpIncidentSynthesizer('http://agent:8001/').synthesize(VIDEOS, signal);
    assert.equal(calls[0].url, 'http://agent:8001/api/v1/incidents/synthesize');
    assert.deepEqual(calls[0].body, { videos: VIDEOS.map((video) => ({ video_name: video.videoName, payload: video.payload })) });
    assert.deepEqual(result, { kind: 'synthesised', overview: { title: 'Both' }, embedding: embedding() });
  });

  test('HTTP errors are failures carrying the agent detail', async () => {
    stubFetch(503, { detail: 'No embedding API key configured' });
    assert.deepEqual(await new HttpIncidentSynthesizer('http://agent').synthesize(VIDEOS, signal), {
      kind: 'failed',
      status: 503,
      message: 'No embedding API key configured',
    });
    stubFetch(422, { detail: [{ msg: 'videos too short' }] });
    const result = await new HttpIncidentSynthesizer('http://agent').synthesize([], signal);
    assert.equal(result.status, 422);
    assert.match(result.message, /videos too short/);
    stubFetch(502, 'bad gateway');
    assert.equal((await new HttpIncidentSynthesizer('http://agent').synthesize(VIDEOS, signal)).message, 'bad gateway');
  });

  test('a success body without an overview or a 1024-number embedding is a 502 failure', async () => {
    const broken = [
      '<html>',
      '[]',
      { embedding: embedding() },
      { overview: {}, embedding: [0.1] },
      { overview: {}, embedding: [...embedding().slice(1), 'x'] },
      { overview: {} },
    ];
    for (const body of broken) {
      stubFetch(200, body);
      const result = await new HttpIncidentSynthesizer('http://agent').synthesize(VIDEOS, signal);
      assert.equal(result.kind, 'failed', JSON.stringify(body).slice(0, 60));
      assert.equal(result.status, 502);
    }
  });

  test('a network failure or timeout is thrown as AgentRequestError', async () => {
    globalThis.fetch = async () => {
      throw new TypeError('connect ECONNREFUSED');
    };
    await assert.rejects(
      new HttpIncidentSynthesizer('http://agent').synthesize(VIDEOS, signal),
      (error) => error instanceof AgentRequestError && error.code === 'AGENT_FETCH_FAILED',
    );
    globalThis.fetch = async () => {
      throw new DOMException('timed out', 'TimeoutError');
    };
    await assert.rejects(
      new HttpIncidentSynthesizer('http://agent').synthesize(VIDEOS, signal),
      (error) => error instanceof AgentRequestError && error.code === 'AGENT_TIMEOUT',
    );
  });
});

describe('FakeIncidentSynthesizer', () => {
  test('one video keeps its own overview fields and nothing else', async () => {
    const fake = new FakeIncidentSynthesizer();
    const result = await fake.synthesize(
      [{ videoName: 'a.mp4', payload: { incident: { ...VIDEOS[0].payload.incident, duration: 4 } } }],
      signal,
    );
    assert.deepEqual(result.overview, VIDEOS[0].payload.incident);
    assert.equal(result.embedding.length, EMBEDDING_DIMENSIONS);
  });

  test('several videos take the earliest start, latest end and highest severity', async () => {
    const result = await new FakeIncidentSynthesizer().synthesize(VIDEOS, signal);
    assert.equal(result.overview.start_timestamp, 2);
    assert.equal(result.overview.end_timestamp, 20);
    assert.equal(result.overview.severity_level, 4);
  });

  test('no videos fail, calls are recorded, and the script can force results', async () => {
    const fake = new FakeIncidentSynthesizer();
    assert.equal((await fake.synthesize([], signal)).kind, 'failed');
    assert.equal(fake.calls.length, 1);
    const scripted = new FakeIncidentSynthesizer([
      { kind: 'failed', status: 502, message: 'x' },
      new AgentRequestError('AGENT_TIMEOUT', 'slow'),
    ]);
    assert.equal((await scripted.synthesize(VIDEOS, signal)).status, 502);
    await assert.rejects(scripted.synthesize(VIDEOS, signal), AgentRequestError);
  });
});

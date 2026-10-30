// SPDX-License-Identifier: Apache-2.0

// The analyse client (HttpVideoAnalyzer) against a stubbed fetch, and its in-memory fake.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { HttpVideoAnalyzer } = await import('../src/modules/analysis/infrastructure/agent/video-analyzer.ts');
const { FakeVideoAnalyzer } = await import('../src/modules/analysis/infrastructure/agent/fake-video-analyzer.ts');
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const REQUEST = {
  videoName: 'front door 2.mp4',
  videoKey: 'uploads/front door 2.mp4',
  model: 'qwen',
  reviewerPrompt: null,
  modelRunId: 'front door 2.mp4@2026-10-30T01:02:03Z',
  videoDurationSeconds: 12.5,
};
const PAYLOAD = { incident: { type: 'assault' } };
const signal = new AbortController().signal;

function stubFetch(status, body) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  };
  return calls;
}

describe('HttpVideoAnalyzer', () => {
  test('posts the contract inputs addressed by the encoded video name', async () => {
    const calls = stubFetch(200, { analysis_id: 7, model_run_id: REQUEST.modelRunId, outcome: 'stored', payload: PAYLOAD });
    const result = await new HttpVideoAnalyzer('http://agent:8001/').analyze({ ...REQUEST, reviewerPrompt: 'focus on the door' }, signal);
    assert.equal(calls[0].url, 'http://agent:8001/api/v1/incidents/front%20door%202.mp4/analyze');
    assert.deepEqual(calls[0].body, {
      video_key: REQUEST.videoKey,
      model_run_id: REQUEST.modelRunId,
      model: 'qwen',
      skip_rp1: true,
      reviewer_prompt: 'focus on the door',
      video_duration_seconds: 12.5,
    });
    assert.deepEqual(result, { kind: 'analysed', analysisId: 7, modelRunId: REQUEST.modelRunId, outcome: 'stored', payload: PAYLOAD });
  });

  test('omits the reviewer prompt and an unusable duration', async () => {
    for (const duration of [null, 0, Number.NaN]) {
      const calls = stubFetch(200, { analysis_id: 1, model_run_id: 'r', outcome: 'stored', payload: PAYLOAD });
      await new HttpVideoAnalyzer('http://agent').analyze({ ...REQUEST, videoDurationSeconds: duration }, signal);
      assert.equal('reviewer_prompt' in calls[0].body, false);
      assert.equal('video_duration_seconds' in calls[0].body, false);
    }
  });

  test('a 422 with the model output is a contract refusal', async () => {
    stubFetch(422, {
      detail: {
        message: 'Incident contract violation: bad',
        raw_output: '{"x":1}',
        finish_reason: 'stop',
        model: 'qwen',
        contract_version: 'incident-contract-v4',
      },
    });
    const result = await new HttpVideoAnalyzer('http://agent').analyze(REQUEST, signal);
    assert.deepEqual(result, {
      kind: 'contract_refused',
      message: 'Incident contract violation: bad',
      rawOutput: '{"x":1}',
      finishReason: 'stop',
      model: 'qwen',
      contractVersion: 'incident-contract-v4',
    });
  });

  test('other HTTP errors are failures that keep the status and body', async () => {
    stubFetch(504, '{"detail":"Incident analysis timed out"}');
    assert.deepEqual(await new HttpVideoAnalyzer('http://agent').analyze(REQUEST, signal), {
      kind: 'failed',
      status: 504,
      message: '{"detail":"Incident analysis timed out"}',
    });
    stubFetch(422, { detail: 'body validation failed' });
    assert.equal((await new HttpVideoAnalyzer('http://agent').analyze(REQUEST, signal)).kind, 'failed');
  });

  test('a success body that breaks the contract table is a 502 failure', async () => {
    const good = { analysis_id: 1, model_run_id: 'r', outcome: 'stored', payload: PAYLOAD };
    const broken = [
      '<html>',
      '[]',
      { ...good, analysis_id: '1' },
      { ...good, analysis_id: 1.5 },
      { ...good, model_run_id: '' },
      { ...good, outcome: undefined },
      { ...good, payload: [] },
    ];
    for (const body of broken) {
      stubFetch(200, body);
      const result = await new HttpVideoAnalyzer('http://agent').analyze(REQUEST, signal);
      assert.equal(result.kind, 'failed', JSON.stringify(body));
      assert.equal(result.status, 502);
    }
  });

  test('a network failure or timeout is thrown as AgentRequestError', async () => {
    globalThis.fetch = async () => {
      throw new TypeError('connect ECONNREFUSED');
    };
    await assert.rejects(
      new HttpVideoAnalyzer('http://agent').analyze(REQUEST, signal),
      (error) => error instanceof AgentRequestError && error.code === 'AGENT_FETCH_FAILED',
    );
    globalThis.fetch = async () => {
      throw new DOMException('timed out', 'TimeoutError');
    };
    await assert.rejects(
      new HttpVideoAnalyzer('http://agent').analyze(REQUEST, signal),
      (error) => error instanceof AgentRequestError && error.code === 'AGENT_TIMEOUT',
    );
  });
});

describe('FakeVideoAnalyzer', () => {
  test('records requests and returns numbered successes by default', async () => {
    const fake = new FakeVideoAnalyzer();
    const first = await fake.analyze(REQUEST, signal);
    const second = await fake.analyze(REQUEST, signal);
    assert.deepEqual([first.analysisId, second.analysisId], [1, 2]);
    assert.equal(first.modelRunId, REQUEST.modelRunId);
    assert.equal(fake.requests.length, 2);
  });

  test('plays its script in order, the last entry repeating, and throws Error entries', async () => {
    const refusal = { kind: 'failed', status: 500, message: 'boom' };
    const fake = new FakeVideoAnalyzer([refusal, new AgentRequestError('AGENT_TIMEOUT', 'slow')]);
    assert.equal(await fake.analyze(REQUEST, signal), refusal);
    await assert.rejects(fake.analyze(REQUEST, signal), AgentRequestError);
    await assert.rejects(fake.analyze(REQUEST, signal), AgentRequestError);
  });
});

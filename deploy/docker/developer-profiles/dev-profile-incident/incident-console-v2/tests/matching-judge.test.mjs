// SPDX-License-Identifier: Apache-2.0

// The match-judge client (HttpMatchJudge) against a stubbed fetch, and its in-memory fake.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { HttpMatchJudge } = await import('../src/modules/matching/infrastructure/agent/match-judge.ts');
const { FakeMatchJudge } = await import('../src/modules/matching/infrastructure/agent/fake-match-judge.ts');
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const signal = new AbortController().signal;
const REQUEST = {
  analysis: { incident: { type: 'assault', location: 'Main street' } },
  recordedAtStart: 100,
  recordedAtEnd: 160,
  candidates: [
    {
      incidentId: 7,
      overview: { type: 'assault', location: 'main street' },
      videoNames: ['front.mp4'],
      recordedAtStart: 120,
      recordedAtEnd: 180,
    },
    { incidentId: 8, overview: { type: 'fire', location: 'Dock' }, videoNames: ['dock.mp4'], recordedAtStart: null, recordedAtEnd: null },
  ],
};

function stubFetch(status, body) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  };
  return calls;
}

describe('HttpMatchJudge', () => {
  test("accepts the agent's structured_reasons field and ignores it", async () => {
    stubFetch(200, {
      judgements: [
        {
          incident_id: 7,
          score: 0.85,
          reasons: ['event types match'],
          structured_reasons: [{ kind: 'same_event_type', label: 'Same event type', detail: 'assault' }],
        },
      ],
    });
    const result = await new HttpMatchJudge('http://agent:8000').judge(REQUEST, signal);
    assert.deepEqual(result, { kind: 'judged', judgements: [{ incidentId: 7, score: 0.85, reasons: ['event types match'] }] });
  });

  test('posts the analysis and candidates as snake_case and returns the judgements', async () => {
    const calls = stubFetch(200, {
      judgements: [
        { incident_id: 7, score: 1, reasons: ['event types match'] },
        { incident_id: 8, score: 0, reasons: ['event type mismatch'] },
      ],
    });
    const result = await new HttpMatchJudge('http://agent:8001/').judge(REQUEST, signal);
    assert.equal(calls[0].url, 'http://agent:8001/api/v1/incidents/match-judge');
    assert.deepEqual(calls[0].body, {
      analysis: REQUEST.analysis,
      recorded_at_start: 100,
      recorded_at_end: 160,
      candidates: [
        {
          incident_id: 7,
          overview: REQUEST.candidates[0].overview,
          video_names: ['front.mp4'],
          recorded_at_start: 120,
          recorded_at_end: 180,
        },
        {
          incident_id: 8,
          overview: REQUEST.candidates[1].overview,
          video_names: ['dock.mp4'],
          recorded_at_start: null,
          recorded_at_end: null,
        },
      ],
    });
    assert.deepEqual(result, {
      kind: 'judged',
      judgements: [
        { incidentId: 7, score: 1, reasons: ['event types match'] },
        { incidentId: 8, score: 0, reasons: ['event type mismatch'] },
      ],
    });
  });

  test('no candidates means no call', async () => {
    const calls = stubFetch(200, { judgements: [] });
    assert.deepEqual(await new HttpMatchJudge('http://agent').judge({ ...REQUEST, candidates: [] }, signal), {
      kind: 'judged',
      judgements: [],
    });
    assert.equal(calls.length, 0);
  });

  test('HTTP errors are failures carrying the agent detail', async () => {
    stubFetch(422, { detail: [{ msg: 'candidates too short' }] });
    const result = await new HttpMatchJudge('http://agent').judge(REQUEST, signal);
    assert.equal(result.kind, 'failed');
    assert.equal(result.status, 422);
    assert.match(result.message, /candidates too short/);
    stubFetch(503, 'bad gateway');
    assert.equal((await new HttpMatchJudge('http://agent').judge(REQUEST, signal)).message, 'bad gateway');
  });

  test('a success body that is not a list of judgements with a 0 to 1 score is a 502 failure', async () => {
    const broken = [
      '<html>',
      '[]',
      {},
      { judgements: [{ incident_id: 7, score: 1.2, reasons: [] }] },
      { judgements: [{ incident_id: 7, score: 0.5, reasons: [1] }] },
      { judgements: [{ incident_id: '7', score: 0.5, reasons: [] }] },
      { judgements: [null] },
    ];
    for (const body of broken) {
      stubFetch(200, body);
      const result = await new HttpMatchJudge('http://agent').judge(REQUEST, signal);
      assert.equal(result.kind, 'failed', JSON.stringify(body).slice(0, 60));
      assert.equal(result.status, 502);
    }
  });

  test('a network failure or timeout is thrown as AgentRequestError', async () => {
    globalThis.fetch = async () => {
      throw new TypeError('connect ECONNREFUSED');
    };
    await assert.rejects(
      new HttpMatchJudge('http://agent').judge(REQUEST, signal),
      (error) => error instanceof AgentRequestError && error.code === 'AGENT_FETCH_FAILED',
    );
    globalThis.fetch = async () => {
      throw new DOMException('timed out', 'TimeoutError');
    };
    await assert.rejects(
      new HttpMatchJudge('http://agent').judge(REQUEST, signal),
      (error) => error instanceof AgentRequestError && error.code === 'AGENT_TIMEOUT',
    );
  });
});

describe('FakeMatchJudge', () => {
  test('scores by event type, location and recorded times like the agent', async () => {
    const judge = new FakeMatchJudge();
    const result = await judge.judge(REQUEST, signal);
    assert.equal(result.kind, 'judged');
    const [same, other] = result.judgements;
    assert.equal(same.incidentId, 7);
    assert.equal(same.score, 1);
    assert.deepEqual(same.reasons.length, 3);
    assert.deepEqual(other, {
      incidentId: 8,
      score: 0,
      reasons: ['event type mismatch: new video is "assault", candidate is "fire"'],
    });
    assert.deepEqual(judge.calls, [REQUEST]);
  });

  test('a missing location is neutral and a time gap earns no bonus', async () => {
    const analysis = { incident: { type: 'assault' } };
    const request = { ...REQUEST, analysis, candidates: [{ ...REQUEST.candidates[0], recordedAtStart: 500, recordedAtEnd: 600 }] };
    const result = await new FakeMatchJudge().judge(request, signal);
    assert.equal(result.judgements[0].score, 0.65);
    assert.ok(result.judgements[0].reasons.includes('recorded times do not overlap'));
  });

  test('a script returns its results in order, repeating the last, and throws an Error entry', async () => {
    const failure = { kind: 'failed', status: 503, message: 'down' };
    const judge = new FakeMatchJudge([failure, new Error('boom')]);
    assert.deepEqual(await judge.judge(REQUEST, signal), failure);
    await assert.rejects(judge.judge(REQUEST, signal), /boom/);
    await assert.rejects(judge.judge(REQUEST, signal), /boom/);
  });
});

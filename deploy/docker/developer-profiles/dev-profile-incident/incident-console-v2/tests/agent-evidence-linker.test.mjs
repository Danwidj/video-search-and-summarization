// SPDX-License-Identifier: Apache-2.0

// The link-evidence client (HttpEvidenceLinker) against a stubbed fetch, and its in-memory fake.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { HttpEvidenceLinker, parseLinkResponse } = await import('../src/modules/analysis/infrastructure/agent/evidence-linker.ts');
const { FakeEvidenceLinker } = await import('../src/modules/analysis/infrastructure/agent/fake-evidence-linker.ts');
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const signal = new AbortController().signal;
const VIDEOS = [
  { videoName: 'a.mp4', payload: { entities: [] } },
  { videoName: 'b.mp4', payload: { entities: [] } },
];
const group = (id, a, b) => ({
  id,
  kind: 'entity',
  label: 'Man in blue shirt',
  members: [
    { video: 'a.mp4', itemId: a },
    { video: 'b.mp4', itemId: b },
  ],
  source: 'ai',
  reason: 'Same shirt.',
});

describe('HttpEvidenceLinker', () => {
  test('posts the videos to link-evidence and returns the groups', async () => {
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push({ url, body: JSON.parse(init.body) });
      return new Response(JSON.stringify({ evidence_groups: [group('G1', 'E1', 'E2')] }), { status: 200 });
    };
    const result = await new HttpEvidenceLinker('http://agent.test/').link(VIDEOS, signal);
    assert.equal(calls[0].url, 'http://agent.test/api/v1/incidents/link-evidence');
    assert.deepEqual(
      calls[0].body.videos.map((video) => video.video_name),
      ['a.mp4', 'b.mp4'],
    );
    assert.deepEqual(result, { kind: 'linked', groups: [group('G1', 'E1', 'E2')] });
  });

  test('drops malformed groups from the answer', () => {
    const one = { ...group('G2', 'E1', 'E1'), members: [{ video: 'a.mp4', itemId: 'E1' }] };
    const result = parseLinkResponse(200, true, 'OK', JSON.stringify({ evidence_groups: [group('G1', 'E1', 'E2'), one, 'junk'] }));
    assert.deepEqual(result, { kind: 'linked', groups: [group('G1', 'E1', 'E2')] });
  });

  test('an HTTP error or a body without the list is a failed result', () => {
    assert.deepEqual(parseLinkResponse(503, false, 'Unavailable', 'no key'), { kind: 'failed', status: 503, message: 'no key' });
    assert.equal(parseLinkResponse(200, true, 'OK', 'not json').kind, 'failed');
    assert.equal(parseLinkResponse(200, true, 'OK', '{"groups":[]}').kind, 'failed');
    assert.equal(parseLinkResponse(200, true, 'OK', 'null').kind, 'failed');
  });

  test('a network failure is thrown as AgentRequestError', async () => {
    globalThis.fetch = async () => {
      throw new TypeError('connect refused');
    };
    await assert.rejects(new HttpEvidenceLinker('http://agent.test').link(VIDEOS, signal), (error) => error instanceof AgentRequestError);
  });
});

test('the fake returns no groups unscripted, then its script in order', async () => {
  const fake = new FakeEvidenceLinker();
  assert.deepEqual(await fake.link(VIDEOS, signal), { kind: 'linked', groups: [] });
  const scripted = new FakeEvidenceLinker([{ kind: 'failed', status: 500, message: 'x' }, new Error('boom')]);
  assert.equal((await scripted.link(VIDEOS, signal)).kind, 'failed');
  await assert.rejects(scripted.link(VIDEOS, signal), /boom/);
  assert.equal(scripted.calls.length, 2);
});

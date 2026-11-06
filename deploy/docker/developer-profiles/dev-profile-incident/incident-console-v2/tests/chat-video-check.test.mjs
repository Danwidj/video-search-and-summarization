// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { POST } = await import('../src/app/api/chat/video-check/route.ts');
const { fromAgentChatResponse } = await import('../src/modules/chat/infrastructure/agent/agent-chat.ts');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
let upstream;
beforeEach(() => {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000/';
  upstream = { calls: [], status: 200, body: { content: 'Stored report: a.\n\nVideo reanalysis: b.', source: 'video' } };
  globalThis.fetch = async (url, init) => {
    upstream.calls.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response(JSON.stringify(upstream.body), { status: upstream.status });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const post = (body) => POST(new Request('http://console.test/api/chat/video-check', { method: 'POST', body: JSON.stringify(body) }));
const check = { videoId: 'V 1', question: 'Was it a dog?', storedAnswer: 'The report says a dog.' };

test('a check goes to the agent route for that video and returns its labelled result', async () => {
  const response = await post(check);
  assert.equal(response.status, 200);
  assert.deepEqual(upstream.calls, [
    {
      url: 'http://agent.test:8000/api/v1/incidents/V%201/video-check',
      body: { question: 'Was it a dog?', stored_answer: 'The report says a dog.' },
    },
  ]);
  assert.equal((await response.json()).source, 'video');
});

test('a check with anything missing never reaches the agent', async () => {
  for (const missing of ['videoId', 'question', 'storedAnswer']) {
    assert.equal((await post({ ...check, [missing]: '' })).status, 400);
  }
  assert.equal(upstream.calls.length, 0);
});

test('checks switched off on the agent, or a failed look, reach the panel as an error with a reason', async () => {
  upstream.status = 404;
  upstream.body = { detail: 'Video checks are not enabled on this agent' };
  const off = await post(check);
  assert.equal(off.status, 404);
  assert.match((await off.json()).error, /not enabled/);
  upstream.status = 502;
  upstream.body = { detail: 'The video check timed out, so nothing was learned from the video.' };
  assert.equal((await post(check)).status, 502);
});

test('a reply that is not a video check is refused rather than shown', async () => {
  upstream.body = { content: 'x', source: 'report' };
  assert.notEqual((await post(check)).status, 200);
});

test('a routed answer maps its source, offer and unknown times, and every v3 fixture reads', () => {
  const dir = join(process.cwd(), '..', 'contracts', 'chat-contract-v3', 'fixtures', 'valid');
  const offer = fromAgentChatResponse(JSON.parse(readFileSync(join(dir, 'response_routed_video_offer.json'), 'utf8')));
  assert.equal(offer.message.source, 'report_llm');
  assert.deepEqual(offer.message.videoOffer, { reason: 'The report does not record the colour of his shirt.' });
  assert.equal(offer.grounding.route, 'report_llm');
  assert.deepEqual(offer.grounding.unknownTimes, ['0:99']);
  const code = fromAgentChatResponse(JSON.parse(readFileSync(join(dir, 'response_routed_deterministic.json'), 'utf8')));
  assert.equal(code.message.source, 'report');
  assert.equal(code.message.videoOffer, undefined);
  assert.equal(code.grounding.mode, 'routed');
});

test('a template answer keeps none of these', () => {
  const answer = fromAgentChatResponse({ session_id: 's', message: { role: 'assistant', content: 'x', citations: [] } });
  assert.equal(answer.message.source, undefined);
  assert.equal(answer.message.videoOffer, undefined);
  assert.equal(answer.grounding, undefined);
});

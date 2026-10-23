// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';
import Ajv2020 from 'ajv/dist/2020.js';

register('./support/alias-loader.mjs', import.meta.url);

const { POST } = await import('../app/api/chat/route.ts');

const contractDir = join(process.cwd(), '..', 'contracts', 'chat-contract-v1');
const read = (...parts) => JSON.parse(readFileSync(join(contractDir, ...parts), 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateRequest = ajv.compile(read('chat_request.schema.json'));
const agentResponse = read('fixtures', 'valid', 'full-response.json');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
let upstream;
beforeEach(() => {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000/';
  upstream = { calls: [], status: 200, body: agentResponse };
  globalThis.fetch = async (url, init) => {
    upstream.calls.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response(JSON.stringify(upstream.body), { status: upstream.status });
  };
});
afterEach(() => { globalThis.fetch = originalFetch; process.env = { ...originalEnv }; });

const post = (body) => POST(new Request('http://console.test/api/chat', { method: 'POST', body: JSON.stringify(body) }));

test('the route calls POST /api/v1/incidents/chat with a chat-contract-v1 request scoped to the incident', async () => {
  const response = await post({ messages: [{ role: 'user', content: 'What weapon?' }], sessionId: 'session_abc', incidentId: 'Assault007' });
  assert.equal(response.status, 200);
  assert.equal(upstream.calls.length, 1);
  assert.equal(upstream.calls[0].url, 'http://agent.test:8000/api/v1/incidents/chat');
  assert.deepEqual(upstream.calls[0].body, {
    session_id: 'session_abc',
    messages: [{ role: 'user', content: 'What weapon?' }],
    context: { scope: 'incident', incident_id: 'Assault007' },
  });
  assert.equal(validateRequest(upstream.calls[0].body), true, JSON.stringify(validateRequest.errors));
});

test('the session and context are left out when not given', async () => {
  await post({ messages: [{ role: 'user', content: 'Hi' }] });
  assert.deepEqual(upstream.calls[0].body, { messages: [{ role: 'user', content: 'Hi' }] });
});

test('the response carries the session and the cited evidence in camelCase', async () => {
  const body = await (await post({ messages: [{ role: 'user', content: 'Hi' }] })).json();
  assert.equal(body.sessionId, agentResponse.session_id);
  assert.equal(body.message.role, 'assistant');
  assert.equal(body.message.content, agentResponse.message.content);
  const [first] = agentResponse.message.citations;
  assert.deepEqual(body.message.citations[0], {
    incidentId: first.incident_id, itemId: first.item_id, itemType: first.item_type,
    timestampSeconds: first.timestamp_seconds, cropImageUrl: first.crop_image_url,
  });
  assert.equal(body.message.citations.length, agentResponse.message.citations.length);
});

test('an answer with no citations passes through with an empty list', async () => {
  upstream.body = read('fixtures', 'valid', 'empty-response.json');
  const body = await (await post({ messages: [{ role: 'user', content: 'Hi' }] })).json();
  assert.deepEqual(body.message.citations, []);
});

test('no messages is a 400 and never reaches the agent', async () => {
  assert.equal((await post({ messages: [] })).status, 400);
  assert.equal(upstream.calls.length, 0);
});

test('an agent error is a 500 carrying the agent status', async () => {
  upstream.status = 422;
  upstream.body = { detail: 'bad' };
  const response = await post({ messages: [{ role: 'user', content: 'Hi' }] });
  assert.equal(response.status, 500);
  assert.match((await response.json()).error, /HTTP 422/);
});

test('a malformed agent response is a 500', async () => {
  upstream.body = { session_id: 's', message: { role: 'assistant', content: 'x' } };
  const response = await post({ messages: [{ role: 'user', content: 'Hi' }] });
  assert.equal(response.status, 500);
  assert.match((await response.json()).error, /invalid chat response/);
});

test('a version and an unsaved draft are forwarded as version_id and draft_report', async () => {
  const draftReport = { entities: [{ entity_id: 'E1', type: 'human', description: 'Guard' }] };
  const response = await post({ messages: [{ role: 'user', content: 'Who?' }], incidentId: 'Assault007', versionId: 7, draftReport });
  assert.equal(response.status, 200);
  assert.deepEqual(upstream.calls[0].body, {
    messages: [{ role: 'user', content: 'Who?' }],
    context: { scope: 'incident', incident_id: 'Assault007' },
    version_id: 7,
    draft_report: draftReport,
  });
  assert.equal(validateRequest(upstream.calls[0].body), true, JSON.stringify(validateRequest.errors));
});

test('a version alone sends no draft_report', async () => {
  await post({ messages: [{ role: 'user', content: 'Who?' }], incidentId: 'Assault007', versionId: 3 });
  assert.equal(upstream.calls[0].body.version_id, 3);
  assert.equal('draft_report' in upstream.calls[0].body, false);
});

test('a draft without its version, or a bad version, is a 400 and never reaches the agent', async () => {
  assert.equal((await post({ messages: [{ role: 'user', content: 'Hi' }], draftReport: {} })).status, 400);
  assert.equal((await post({ messages: [{ role: 'user', content: 'Hi' }], versionId: 0 })).status, 400);
  assert.equal((await post({ messages: [{ role: 'user', content: 'Hi' }], versionId: 'x' })).status, 400);
  assert.equal(upstream.calls.length, 0);
});

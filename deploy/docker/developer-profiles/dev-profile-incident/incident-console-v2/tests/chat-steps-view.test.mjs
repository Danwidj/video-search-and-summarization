// SPDX-License-Identifier: Apache-2.0

// Unit tests for expandable "What I did" chat steps view (Plan B Item 2C).
// Verifies UI source structure, pure helpers, client adapter, and API route behavior.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { summaryLabel, hasStepsOrActions } = await import('../src/lib/chat/chat-steps.ts');
const { sendAgentInvestigate, fromAgentInvestigateResponse } = await import('../src/modules/chat/infrastructure/agent/agent-chat.ts');
const { POST } = await import('../src/app/api/chat/route.ts');
const { isChatStepsEnabled } = await import('../src/lib/env.ts');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

let upstreamCalls = [];
beforeEach(() => {
  upstreamCalls = [];
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000/';
  delete process.env.INCIDENT_CHAT_STEPS_ENABLED;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const postChat = (body, headers = {}) =>
  POST(
    new Request('http://console.test/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(body),
    }),
  );

// --- 1. Pure helper tests ---

test('hasStepsOrActions detects steps or applied/skipped changes', () => {
  assert.equal(hasStepsOrActions({}), false);
  assert.equal(hasStepsOrActions({ steps: [], applied: [], skipped: [] }), false);
  assert.equal(hasStepsOrActions({ steps: [{ tool: 't', ok: true, ms: 1 }] }), true);
  assert.equal(hasStepsOrActions({ applied: [{ tool: 't' }] }), true);
  assert.equal(hasStepsOrActions({ skipped: [{ tool: 't', reason: 'r' }] }), true);
});

test('summaryLabel composes tool count and change counts cleanly', () => {
  assert.equal(summaryLabel(0, 0, 0), '');
  assert.equal(summaryLabel(1, 0, 0), '1 tool');
  assert.equal(summaryLabel(3, 0, 0), '3 tools');
  assert.equal(summaryLabel(2, 1, 0), '2 tools · 1 applied');
  assert.equal(summaryLabel(1, 2, 1), '1 tool · 2 applied · 1 skipped');
  assert.equal(summaryLabel(0, 1, 2), '1 applied · 2 skipped');
});

// --- 2. Source-reading UI checks ---

test('ChatStepsView renders expandable trigger and sections matching the spec', async () => {
  const file = await readFile(new URL('../src/sections/reports/components/ReportChat/ChatStepsView.tsx', import.meta.url), 'utf8');
  assert.match(file, /data-testid="chat-steps-view"/);
  assert.match(file, /data-testid="chat-steps-trigger"/);
  assert.match(file, /What I did/);
  assert.match(file, /data-testid="chat-steps-summary"/);
  assert.match(file, /data-testid="chat-steps-content"/);
  assert.match(file, /Tools used \(\{stepCount\}\)/);
  assert.match(file, /data-testid="chat-step-item"/);
  assert.match(file, /data-testid="chat-step-tool"/);
  assert.match(file, /Changes applied \(\{appliedCount\}\)/);
  assert.match(file, /data-testid="chat-applied-action"/);
  assert.match(file, /Changes skipped \(\{skippedCount\}\)/);
  assert.match(file, /data-testid="chat-skipped-action"/);
  assert.match(file, /Total duration: \{wallMs\} ms/);
});

test('ChatStepsView shows an applied action note, which names a removed item', async () => {
  const file = await readFile(new URL('../src/sections/reports/components/ReportChat/ChatStepsView.tsx', import.meta.url), 'utf8');
  assert.match(file, /\{action\.note && <p[^>]*>\{action\.note\}<\/p>\}/);
});

test('ReportChat integrates ChatStepsView under assistant bubbles', async () => {
  const file = await readFile(new URL('../src/sections/reports/components/ReportChat/ReportChat.tsx', import.meta.url), 'utf8');
  assert.match(file, /import \{ ChatStepsView \} from '\.\/ChatStepsView';/);
  assert.match(file, /<ChatStepsView/);
  assert.match(file, /steps=\{message\.steps\}/);
  assert.match(file, /applied=\{message\.applied\}/);
  assert.match(file, /skipped=\{message\.skipped\}/);
  assert.match(file, /wallMs=\{message\.wallMs\}/);
});

test('LibraryChat integrates ChatStepsView under assistant bubbles', async () => {
  const file = await readFile(new URL('../src/sections/library/components/LibraryChat/LibraryChat.tsx', import.meta.url), 'utf8');
  assert.match(file, /import \{ ChatStepsView \} from '@\/sections\/reports\/components\/ReportChat';/);
  assert.match(file, /<ChatStepsView/);
});

// --- 3. API client adapter tests ---

test('fromAgentInvestigateResponse answers a blank reply with a sentence for its status', () => {
  const blank = fromAgentInvestigateResponse({
    status: 'aborted:step_budget',
    answer: '',
    steps: [],
    actions: [
      { tool: 'propose_rename', args: { key: 'k1' } },
      { tool: 'propose_rename', args: { key: 'k2' } },
    ],
    wall_ms: 10,
  });
  assert.equal(blank.message.content, 'The agent reached its tool step limit before it could answer; 2 changes were proposed.');
  const timedOut = fromAgentInvestigateResponse({ status: 'timeout', answer: '  ', steps: [], wall_ms: 90000 });
  assert.equal(timedOut.message.content, 'The agent ran out of time before it could answer; no changes were proposed.');
});

test('fromAgentInvestigateResponse parses steps, actions and wallMs into ChatResponse', () => {
  const payload = {
    status: 'ok',
    answer: 'The burglar carried a flashlight at 00:22.',
    steps: [
      { tool: 'incident_read_report', args: { video_id: 'v1' }, ok: true, ms: 15, error: null },
      { tool: 'incident_list_versions', args: {}, ok: true, ms: 8, error: null },
    ],
    actions: [{ tool: 'propose_set_incident_fields', args: { title: 'Break-in' } }],
    wall_ms: 125,
  };
  const response = fromAgentInvestigateResponse(payload, 'test-session');
  assert.equal(response.sessionId, 'test-session');
  assert.equal(response.message.content, 'The burglar carried a flashlight at 00:22.');
  assert.equal(response.message.source, 'investigator');
  assert.equal(response.message.status, 'ok');
  assert.equal(response.message.wallMs, 125);
  assert.equal(response.message.steps.length, 2);
  assert.equal(response.message.steps[0].tool, 'incident_read_report');
  assert.equal(response.message.steps[0].ok, true);
  assert.equal(response.message.steps[0].ms, 15);
  assert.equal(response.message.actions.length, 1);
  assert.equal(response.message.actions[0].tool, 'propose_set_incident_fields');
});

test('sendAgentInvestigate calls POST /api/v1/incidents/{videoId}/investigate', async () => {
  globalThis.fetch = async (url, init) => {
    upstreamCalls.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response(
      JSON.stringify({
        status: 'ok',
        answer: 'Report details',
        steps: [{ tool: 'incident_read_report', args: {}, ok: true, ms: 10 }],
        actions: [],
        wall_ms: 50,
      }),
      { status: 200 },
    );
  };
  const result = await sendAgentInvestigate('http://agent.test:8000', 'Assault 001', 'Who did it?');
  assert.equal(upstreamCalls.length, 1);
  assert.equal(upstreamCalls[0].url, 'http://agent.test:8000/api/v1/incidents/Assault%20001/investigate');
  assert.deepEqual(upstreamCalls[0].body, { question: 'Who did it?' });
  assert.equal(result.message.steps.length, 1);
});

// --- 4. Flag gating and route tests ---

test('isChatStepsEnabled returns false by default and true when flag is set', () => {
  assert.equal(isChatStepsEnabled(), false);
  process.env.INCIDENT_CHAT_STEPS_ENABLED = '1';
  assert.equal(isChatStepsEnabled(), true);
  delete process.env.INCIDENT_CHAT_STEPS_ENABLED;
  const reqWithHeader = new Request('http://test', { headers: { 'x-chat-steps': 'true' } });
  assert.equal(isChatStepsEnabled(reqWithHeader), true);
});

test('POST /api/chat calls stock chat when INCIDENT_CHAT_STEPS_ENABLED is off', async () => {
  globalThis.fetch = async (url, init) => {
    upstreamCalls.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response(
      JSON.stringify({
        session_id: 'sess-1',
        message: { role: 'assistant', content: 'Stock answer', citations: [] },
      }),
      { status: 200 },
    );
  };
  const response = await postChat({
    messages: [{ role: 'user', content: 'What happened?' }],
    incidentId: 'Incident01',
  });
  assert.equal(response.status, 200);
  assert.equal(upstreamCalls.length, 1);
  assert.equal(upstreamCalls[0].url, 'http://agent.test:8000/api/v1/incidents/chat');
  const json = await response.json();
  assert.equal(json.message.content, 'Stock answer');
  assert.equal(json.message.steps, undefined);
});

test('POST /api/chat calls investigator route when INCIDENT_CHAT_STEPS_ENABLED is on and returns steps', async () => {
  process.env.INCIDENT_CHAT_STEPS_ENABLED = '1';
  globalThis.fetch = async (url, init) => {
    upstreamCalls.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response(
      JSON.stringify({
        status: 'ok',
        answer: 'Investigated answer',
        steps: [{ tool: 'incident_read_report', args: {}, ok: true, ms: 22 }],
        actions: [],
        wall_ms: 70,
      }),
      { status: 200 },
    );
  };
  const response = await postChat({
    messages: [{ role: 'user', content: 'What happened?' }],
    incidentId: 'Incident01',
  });
  assert.equal(response.status, 200);
  assert.equal(upstreamCalls.length, 1);
  assert.equal(upstreamCalls[0].url, 'http://agent.test:8000/api/v1/incidents/Incident01/investigate');
  assert.deepEqual(upstreamCalls[0].body, { question: 'What happened?' });
  const json = await response.json();
  assert.equal(json.message.content, 'Investigated answer');
  assert.equal(json.message.source, 'investigator');
  assert.equal(json.message.steps.length, 1);
  assert.equal(json.message.steps[0].tool, 'incident_read_report');
  assert.equal(json.message.wallMs, 70);
});

test('POST /api/chat falls back to stock chat when investigator returns 404', async () => {
  process.env.INCIDENT_CHAT_STEPS_ENABLED = '1';
  let callCount = 0;
  globalThis.fetch = async (url, init) => {
    callCount += 1;
    upstreamCalls.push({ url: String(url), body: JSON.parse(init.body) });
    if (callCount === 1) {
      return new Response(JSON.stringify({ detail: 'The investigator is not enabled on this agent' }), { status: 404 });
    }
    return new Response(
      JSON.stringify({
        session_id: 'sess-fallback',
        message: { role: 'assistant', content: 'Fallback answer', citations: [] },
      }),
      { status: 200 },
    );
  };
  const response = await postChat({
    messages: [{ role: 'user', content: 'What happened?' }],
    incidentId: 'Incident01',
  });
  assert.equal(response.status, 200);
  assert.equal(upstreamCalls.length, 2);
  assert.match(upstreamCalls[0].url, /investigate$/);
  assert.match(upstreamCalls[1].url, /chat$/);
  const json = await response.json();
  assert.equal(json.message.content, 'Fallback answer');
});

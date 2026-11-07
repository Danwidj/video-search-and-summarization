// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { evidenceRows, pendingEvidenceExchange, splitEvidenceActions } = await import('../src/lib/chat/evidence-ask.ts');
const { chatRequestBody, chatTarget } = await import('../src/lib/chat/report-chat.ts');

const user = (content) => ({ role: 'user', content });
const asked = (content) => ({ role: 'assistant', content, askedReviewer: true });
const answered = (content) => ({ role: 'assistant', content });
const opened = (seconds, name) => ({ role: 'assistant', content: 'Opening the box tool.', openedBox: { seconds, name } });

test('no exchange is pending until the editor has asked the reviewer something', () => {
  assert.equal(pendingEvidenceExchange([user('a bag on the floor')]), null);
  assert.equal(pendingEvidenceExchange([user('who is in the red hood?'), answered('The man in the red hood.'), user('thanks')]), null);
});

test('the pending exchange holds the reviewer request and the questions, and counts the questions asked', () => {
  const turns = [
    user('I want to add a new evidence item, a bag on the floor'),
    asked('Which shop is it in?'),
    user('the till shop'),
    asked('Which corner?'),
    user('near the door'),
  ];
  assert.deepEqual(pendingEvidenceExchange(turns), {
    questionsAsked: 2,
    transcript: [
      { role: 'reviewer', text: 'I want to add a new evidence item, a bag on the floor' },
      { role: 'assistant', text: 'Which shop is it in?' },
      { role: 'reviewer', text: 'the till shop' },
      { role: 'assistant', text: 'Which corner?' },
    ],
  });
});

test('an editor reply that is not a question is left out of the transcript', () => {
  const turns = [user('add a bag on the floor'), asked('Which shop?'), answered('Noted, one moment.'), user('the till shop')];
  assert.deepEqual(pendingEvidenceExchange(turns).transcript, [
    { role: 'reviewer', text: 'add a bag on the floor' },
    { role: 'assistant', text: 'Which shop?' },
  ]);
});

test('once the box tool has opened the exchange is over, and a new request starts a new one', () => {
  const turns = [
    user('add a bag'),
    asked('Which shop?'),
    user('till'),
    opened(12, 'Bag'),
    user('add a cup'),
    asked('Which table?'),
    user('by the door'),
  ];
  assert.deepEqual(pendingEvidenceExchange(turns), {
    questionsAsked: 1,
    transcript: [
      { role: 'reviewer', text: 'add a cup' },
      { role: 'assistant', text: 'Which table?' },
    ],
  });
  assert.equal(pendingEvidenceExchange([user('add a bag'), opened(12, 'Bag'), user('thanks')]), null);
});

test('the question becomes the reply, the box opening is taken out, and the other edits stay', () => {
  const split = splitEvidenceActions([
    { tool: 'propose_set_incident_fields', args: { severity_level: 4 } },
    { tool: 'propose_ask_reviewer', args: { question: 'Which shop?' } },
    { tool: 'propose_open_box_tool', args: { seconds: 12, name: 'Bag on floor' } },
  ]);
  assert.equal(split.question, 'Which shop?');
  assert.deepEqual(split.opening, { seconds: 12, name: 'Bag on floor' });
  assert.deepEqual(split.rest, [{ tool: 'propose_set_incident_fields', args: { severity_level: 4 } }]);
});

test('a new-evidence action without its fields is not shown or applied', () => {
  const split = splitEvidenceActions([
    { tool: 'propose_ask_reviewer', args: { question: '  ' } },
    { tool: 'propose_open_box_tool', args: { seconds: 12, name: '' } },
  ]);
  assert.deepEqual(split, { rest: [] });
});

test('each new-evidence step has its own row for What I did', () => {
  assert.deepEqual(evidenceRows({ content: 'Which shop?', askedReviewer: true, openedBox: { seconds: 75, name: 'Bag' } }), [
    { kind: 'asked', text: 'Which shop?' },
    { kind: 'opened', text: 'Opened the box tool at 1:15 as "Bag"' },
  ]);
  assert.deepEqual(evidenceRows({ content: 'Noted.' }), []);
});

test('the request sends the pending exchange, and sends nothing when none is pending', () => {
  const target = chatTarget({
    revision: { revisionId: 7, revisionNo: 2, kind: 'human' },
    isOfficial: false,
    draft: null,
  });
  const evidence = { questionsAsked: 1, transcript: [{ role: 'reviewer', text: 'a bag' }] };
  const messages = [{ role: 'user', content: 'near the till' }];
  assert.equal(chatRequestBody({ messages, videoId: 'V1', target, evidence }).evidence, evidence);
  assert.equal('evidence' in chatRequestBody({ messages, videoId: 'V1', target }), false);
});

test('the report page and its panes wire the box opening from the chat to the edit pane once', () => {
  const page = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportPage/ReportPage.tsx'), 'utf8');
  const pane = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportEditPane/ReportEditPane.tsx'), 'utf8');
  const steps = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportChat/ChatStepsView.tsx'), 'utf8');
  assert.match(page, /const editFromChat = \(sent: EditDraft, proposals: ProposedAction\[\], opening\?: EvidenceOpening\)/);
  assert.match(page, /if \(opening\) setEvidenceOpening\(opening\);/);
  assert.match(page, /evidenceOpening=\{evidenceOpening\}/);
  assert.match(page, /onEvidenceOpened=\{clearEvidenceOpening\}/);
  assert.match(pane, /onEvidenceOpened\?\.\(\);/);
  assert.match(steps, /New evidence/);
});

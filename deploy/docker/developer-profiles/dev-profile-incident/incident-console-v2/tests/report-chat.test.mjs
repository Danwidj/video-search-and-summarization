// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';
import Ajv2020 from 'ajv/dist/2020.js';

register('./support/alias-loader.mjs', import.meta.url);

const { chatTarget, draftReport, chatRequestBody } = await import('../src/lib/chat/report-chat.ts');
const { toAgentChatBody } = await import('../src/modules/chat/infrastructure/agent/agent-chat.ts');

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateRequest = ajv.compile(
  JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'chat-contract-v1', 'chat_request.schema.json'), 'utf8')),
);

const details = (key, sourceId, extra = {}) => ({
  key,
  sourceId,
  timestampSeconds: 12,
  label: 'label',
  image: null,
  imageUrl: null,
  ...extra,
});
const draft = () => ({
  incident: { type: 'burglary', start_timestamp: 5, end_timestamp: 40, description: 'A break-in', severity_level: 3 },
  entities: [
    { ...details('entity-0', 'E1'), type: 'human', description: 'Guard' },
    { ...details('entity-new', null), type: 'unknown', description: 'Added' },
  ],
  instruments: [
    { ...details('instrument-0', 'I1'), holderKey: 'entity-new', name: 'Torch', description: '', threat_level: null },
    { ...details('instrument-1', null, { timestampSeconds: null }), holderKey: null, name: 'Bar', description: '', threat_level: 4 },
  ],
  assets: [{ ...details('asset-0', 'A1'), name: 'Van', description: '' }],
});
const revision = { revisionId: 42, revisionNo: 2, kind: 'human' };

test('View asks about the version on screen and says whether it is official', () => {
  assert.deepEqual(chatTarget({ revision, isOfficial: false, draft: null }), {
    versionId: 42,
    draftReport: null,
    label: 'v2 · Human · not official',
  });
  assert.equal(chatTarget({ revision: { ...revision, kind: 'ai' }, isOfficial: true, draft: null }).label, 'v2 · AI · official');
});

test('Edit asks about the draft, edited from the version being edited', () => {
  const target = chatTarget({ revision, isOfficial: true, draft: draft() });
  assert.equal(target.versionId, 42);
  assert.equal(target.label, 'Draft from v2 · unsaved');
  assert.ok(target.draftReport);
});

test('the draft report keeps source ids, resolves holders and leaves half-filled values out', () => {
  const report = draftReport(draft());
  assert.deepEqual(
    report.entities.map((entity) => entity.entity_id),
    ['E1', 'new-E2'],
  );
  assert.deepEqual(
    report.instruments.map((instrument) => [instrument.instrument_id, instrument.entity_id]),
    [
      ['I1', 'new-E2'],
      ['new-I2', null],
    ],
  );
  assert.equal('threat_level' in report.instruments[0], false, 'an unrated threat is left out');
  assert.equal('timestamp_seconds' in report.instruments[1], false, 'an unset time is left out');
  assert.deepEqual(
    report.assets.map((asset) => asset.asset_id),
    ['A1'],
  );
  assert.equal(report.incident.severity_level, 3);
  assert.deepEqual(
    draftReport({ ...draft(), incident: { type: null, start_timestamp: null, end_timestamp: null, description: '', severity_level: null } })
      .incident,
    { description: '' },
  );
});

test('the request carries the incident, the version and (in Edit) the draft, as a valid chat-contract-v1 body', () => {
  const messages = [{ role: 'user', content: 'Who is there?' }];
  const view = chatRequestBody({ messages, videoId: 'Burglary01', target: chatTarget({ revision, isOfficial: false, draft: null }) });
  assert.deepEqual(view, { messages, incidentId: 'Burglary01', versionId: 42 });

  const edit = chatRequestBody({
    messages,
    sessionId: 's1',
    videoId: 'Burglary01',
    target: chatTarget({ revision, isOfficial: false, draft: draft() }),
  });
  assert.equal(edit.versionId, 42);
  const agentBody = toAgentChatBody({
    messages: edit.messages,
    sessionId: edit.sessionId,
    context: { scope: 'incident', incidentId: edit.incidentId },
    versionId: edit.versionId,
    draftReport: edit.draftReport,
  });
  assert.equal(validateRequest(agentBody), true, JSON.stringify(validateRequest.errors));
  assert.equal(agentBody.version_id, 42);
  assert.equal(agentBody.draft_report.entities.length, 2);
});

test('a citation under an answer is named like its evidence card, never by its id', async () => {
  const { citationTitles, citationTitle } = await import('../src/lib/chat/report-chat.ts');
  const titles = citationTitles({
    entities: [
      { entityId: 'E1', type: 'human', label: 'person in light shirt' },
      { entityId: 'E2', type: 'human', label: '' },
    ],
    instruments: [{ instrumentId: 'I1', name: 'cash register', label: 'black bag' }],
    assets: [{ assetId: 'A1', name: '', label: 'stack of papers' }],
  });
  assert.deepEqual(titles, { E1: 'Person in light shirt', E2: 'Human', I1: 'Cash register', A1: 'Stack of papers' });
  assert.deepEqual(citationTitles(null), {});
  assert.equal(citationTitle(titles, { itemId: 'I1', itemType: 'instrument' }), 'Cash register');
  assert.equal(citationTitle(titles, { itemId: 'new-E3', itemType: 'entity' }), 'Entity', 'an item added in a draft');
  const chat = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportChat', 'ReportChat.tsx'), 'utf8');
  assert.doesNotMatch(chat, />\s*\{citation\.itemId\}/, 'the chip never renders the id');
  assert.match(chat, /citationTitle\(titles, citation\)/);
});

test('every video time in an answer is a button, and the answer text goes through the time finder', () => {
  const chat = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportChat', 'ReportChat.tsx'), 'utf8');
  assert.match(chat, /segmentChatText\(content, \{ durationSeconds \}\)/);
  assert.match(chat, /<AnswerText content=\{message\.content\}/);
  assert.doesNotMatch(chat, /<p className="whitespace-pre-wrap">\{message\.content\}<\/p>/, 'an answer is never rendered as bare text');
  assert.match(chat, /onClick=\{\(\) => onSeek\(segment\.seconds\)\}/);
  assert.match(chat, /\{segment\.text\}/, 'the button shows the time as written');
});

test('a citation with no crop draws no empty image', () => {
  const chat = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportChat', 'ReportChat.tsx'), 'utf8');
  assert.match(chat, /citation\.cropImageUrl \? \(/);
});

test('the page bounds every seek and gives the chat the video length', () => {
  const page = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportPage', 'ReportPage.tsx'), 'utf8');
  assert.match(page, /seekTarget\(seconds, video\.duration\)/);
  assert.match(page, /durationSeconds=\{playerDuration\}/);
});

test('the conversation lives on the page, so closing the panel keeps it, and each version has its own', () => {
  const read = (name) => readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', name, `${name}.tsx`), 'utf8');
  const chat = read('ReportChat');
  const page = read('ReportPage');
  assert.doesNotMatch(chat, /useState<ChatMessage\[\]>/, 'the panel holds no conversation of its own');
  assert.match(page, /useState<Record<string, ChatThread>>/);
  assert.match(page, /thread=\{chatThreads\[threadKey\] \?\? EMPTY_CHAT_THREAD\}/);
  assert.match(page, /chatThreadKey\(target\.versionId, /, 'a thread is keyed by the version asked about');
  assert.match(page, /_earlierDraft/, 'a new draft does not inherit answers about an earlier draft');
});

test('the player stays usable beside the chat, and a jump reaches the player on screen', () => {
  const page = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportPage', 'ReportPage.tsx'), 'utf8');
  assert.match(page, /<Sheet modal=\{false\}/);
  assert.match(page, /onInteractOutside=\{\(event\) => event\.preventDefault\(\)\}/, 'using the player does not close the chat');
  assert.match(page, /ref=\{compactVideoRef\}/);
  assert.match(page, /\[videoRef\.current, compactVideoRef\.current\]\.find/);
});

test('an answer sits on the muted bubble, so its times, citation titles and version line can be read', () => {
  const chat = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportChat', 'ReportChat.tsx'), 'utf8');
  assert.match(chat, /<Message align="start"[^>]*>\s*<Bubble variant="muted">/);
});

test('the panel leads with the timeline question and says answers come from the stored report', () => {
  const chat = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportChat', 'ReportChat.tsx'), 'utf8');
  assert.match(chat, /SUGGESTIONS = \['Show the timeline of events'/);
  assert.match(chat, /stored report for the version you have\s+open, not from a new look at the video/);
  assert.match(chat, /Answered from the stored report: \{message\.answeredFrom\}/);
  assert.doesNotMatch(chat, /Searching evidence/, 'nothing is searched, so the panel does not say so');
});

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { evidenceRows, splitEvidenceActions } = await import('../src/lib/chat/evidence-ask.ts');
const { chatRequestBody, chatTarget } = await import('../src/lib/chat/report-chat.ts');
const { applyChatEdit } = await import('../src/lib/edits/chat-edit.ts');
const { draftFromView } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' });

test('the box opening is taken out of the editor actions and the other edits stay', () => {
  const split = splitEvidenceActions([
    { tool: 'propose_set_incident_fields', args: { severity_level: 4 } },
    { tool: 'propose_open_box_tool', args: { seconds: 12, name: 'Bag on floor' } },
  ]);
  assert.deepEqual(split.opening, { seconds: 12, name: 'Bag on floor' });
  assert.deepEqual(split.rest, [{ tool: 'propose_set_incident_fields', args: { severity_level: 4 } }]);
});

test('no question step exists: a question tool action is not an opening and is not dropped into the draft as one', () => {
  const ask = { tool: 'propose_ask_reviewer', args: { question: 'Who left the bag?' } };
  const split = splitEvidenceActions([ask], null);
  assert.equal(split.opening, undefined);
  assert.deepEqual(split.rest, [ask]);
  const draft = draftFromView(view);
  const before = structuredClone(draft);
  const result = applyChatEdit(draft, draft, split.rest);
  assert.deepEqual(result.applied, []);
  assert.deepEqual(
    result.skipped.map(({ tool, reason }) => ({ tool, reason })),
    [{ tool: 'ask_reviewer', reason: 'unknown tool "ask_reviewer"' }],
  );
  assert.deepEqual(result.draft, before);
  assert.deepEqual(result.changedKeys, []);
});

test('a new-evidence action without its fields is not shown or applied', () => {
  assert.deepEqual(splitEvidenceActions([{ tool: 'propose_open_box_tool', args: { seconds: 12, name: '' } }], null), {
    rest: [],
  });
  assert.deepEqual(splitEvidenceActions([{ tool: 'propose_open_box_tool', args: { name: 'Bag' } }], null), { rest: [] });
});

// The draft the chat was sent with: the agent checks an item's key against it.
const sentDraft = {
  incident: {},
  entities: [{ key: 'p1', type: 'human', label: 'Person in purple', timestampSeconds: 5 }],
  instruments: [{ key: 'k1', name: 'knife', threat_level: 3, timestampSeconds: 9 }],
  assets: [],
};

test('an opening on an existing item is found by its key in the sent draft, and is not a new-evidence opening', () => {
  const split = splitEvidenceActions(
    [
      { tool: 'propose_set_incident_fields', args: { severity_level: 4 } },
      { tool: 'propose_open_box_tool', args: { item_key: 'k1' } },
    ],
    sentDraft,
  );
  assert.deepEqual(split.opening, { itemKey: 'k1', name: 'knife' });
  assert.deepEqual(split.rest, [{ tool: 'propose_set_incident_fields', args: { severity_level: 4 } }]);
  assert.equal(
    splitEvidenceActions([{ tool: 'propose_open_box_tool', args: { item_key: 'p1' } }], sentDraft).opening.name,
    'Person in purple',
  );
});

test('an opening on an item the sent draft does not have, or with no draft, is not shown', () => {
  assert.deepEqual(splitEvidenceActions([{ tool: 'propose_open_box_tool', args: { item_key: 'E9' } }], sentDraft), {
    rest: [],
  });
  assert.deepEqual(splitEvidenceActions([{ tool: 'propose_open_box_tool', args: { item_key: 'p1' } }], null), {
    rest: [],
  });
});

test('the new-evidence opening has its own row for What I did, and a reply with no opening has none', () => {
  assert.deepEqual(evidenceRows({ openedBox: { seconds: 75, name: 'Bag' } }), [
    { kind: 'opened', text: 'Opened the box tool at 1:15 as "Bag"' },
  ]);
  assert.deepEqual(evidenceRows({ content: 'Noted.' }), []);
});

test('a redraw of an existing item has its own row, not an opening of new evidence', () => {
  assert.deepEqual(evidenceRows({ content: 'Noted.', openedBox: { itemKey: 'p1', name: 'Person in purple' } }), [
    { kind: 'redraw', text: 'Opened the box tool on "Person in purple" to redraw its box' },
  ]);
});

test('the request carries the draft and no question-count exchange', () => {
  const target = chatTarget({
    revision: { revisionId: 7, revisionNo: 2, kind: 'human' },
    isOfficial: false,
    draft: null,
  });
  const messages = [{ role: 'user', content: 'near the till' }];
  assert.equal('evidence' in chatRequestBody({ messages, videoId: 'V1', target }), false);
});

test('the report page and its panes wire the box opening from the chat to the edit pane once', () => {
  const page = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportPage/ReportPage.tsx'), 'utf8');
  const pane = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportEditPane/ReportEditPane.tsx'), 'utf8');
  const steps = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportChat/ChatStepsView.tsx'), 'utf8');
  assert.match(page, /const editFromChat = \(sent: EditDraft, proposals: ProposedAction\[\], opening\?: BoxOpening\)/);
  assert.match(page, /if \(opening\) setEvidenceOpening\(opening\);/);
  assert.match(page, /evidenceOpening=\{evidenceOpening\}/);
  assert.match(page, /onEvidenceOpened=\{clearEvidenceOpening\}/);
  assert.match(pane, /onEvidenceOpened\?\.\(\);/);
  assert.match(steps, /Evidence \(\{evidence\.length\}\)/);
  assert.match(steps, /'Redraw'/);
});

test('a redraw of an existing item opens the box tool on that item and is proposed, not applied', () => {
  const pane = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportEditPane/ReportEditPane.tsx'), 'utf8');
  assert.match(pane, /if \(!isItemOpening\(evidenceOpening\)\) setBoxTool\(\{ row: null, opening: evidenceOpening \}\);/);
  assert.match(pane, /setBoxTool\(\{ row: found\.item, redraw: true \}\);/);
  assert.match(pane, /if \(target && boxTool\?\.redraw\) \{/);
  assert.match(pane, /onChange\(proposeEvidence\(draft, target\.key, proposal\)\);/);
});

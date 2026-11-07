// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { applyChatEdit, toApplierActions } = await import('../src/lib/edits/chat-edit.ts');
const { gapRetryProposals, gapRetryResultText, gapRetryStartedText, splitGapRetryActions } = await import('../src/lib/chat/gap-retry.ts');
const { readGapRetry, startGapRetry } = await import('../src/modules/chat/infrastructure/agent/agent-chat.ts');
const { draftFromView } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const view = buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' });
const base = () => draftFromView(view);

const found = (itemKey, name) => ({ itemKey, name, status: 'found', reason: null, seconds: 12, box: [100, 200, 300, 400] });
const missed = (itemKey, name) => ({
  itemKey,
  name,
  status: 'not_found',
  reason: 'no box was found near the second it is seen',
  seconds: null,
  box: null,
});

test('a gap retry request is taken out of the editor actions, with its item or none for every gap', () => {
  const split = splitGapRetryActions([
    { tool: 'propose_retry_gaps', args: { item_key: 'E2' } },
    { tool: 'propose_retry_gaps', args: {} },
    { tool: 'propose_set_incident_fields', args: { severity_level: 4 } },
  ]);
  assert.deepEqual(split.retries, [{ itemKey: 'E2' }, { itemKey: null }]);
  assert.deepEqual(
    split.rest.map((action) => action.tool),
    ['propose_set_incident_fields'],
  );
});

test('only the boxes found become set-image proposals, and the applier holds each one beside its item', () => {
  const draft = base();
  const key = draft.entities[0].key;
  const job = { jobId: 'j1', videoId: 'v', revisionId: 1, status: 'done', items: [found(key, 'man'), missed('other', 'bag')] };
  const proposals = gapRetryProposals(job);
  assert.deepEqual(
    proposals.map((proposal) => proposal.tool),
    ['change_evidence'],
  );
  const result = applyChatEdit(draft, draft, proposals);
  assert.equal(result.skipped.length, 0);
  const item = result.draft.entities.find((entity) => entity.key === key);
  assert.equal(item.proposal.kind, 'set_image');
  assert.equal(item.proposal.pick.seconds, 12);
  assert.deepEqual(item.proposal.pick.box, [100, 200, 300, 400]);
});

test('a change_evidence action is renamed to the applier arguments, and an item the reviewer removed is skipped', () => {
  const draft = base();
  const [action] = toApplierActions(draft, [
    { tool: 'change_evidence', args: { item_key: draft.entities[0].key, op: 'set_image', seconds: 3, box: [1, 2, 3, 4] } },
  ]);
  assert.deepEqual(action.args, { op: 'set_image', itemKey: draft.entities[0].key, seconds: 3, box: [1, 2, 3, 4] });
  const gone = applyChatEdit(draft, draft, [
    { tool: 'change_evidence', args: { item_key: 'no-such-item', op: 'set_image', seconds: 3, box: [1, 2, 3, 4] } },
  ]);
  assert.equal(gone.applied.length, 0);
  assert.equal(gone.skipped.length, 1);
});

test('the chat says what it started, and the result names each item by its label with the reason for a miss', () => {
  const labels = { E2: 'Man in the blue jacket', E3: 'Crowbar' };
  const label = (key) => labels[key] ?? key;
  assert.equal(
    gapRetryStartedText({ itemKey: 'E2' }, label),
    "I'll look for Man in the blue jacket in the clip. This takes about a minute an item. Any box I find comes back here as a proposal for you to confirm or adjust.",
  );
  assert.match(gapRetryStartedText({ itemKey: null }, label), /the items with no box/);
  const text = gapRetryResultText(
    { jobId: 'j', videoId: 'v', revisionId: 1, status: 'done', items: [found('E2', 'man'), missed('E3', 'crowbar')] },
    label,
  );
  assert.match(text, /^I found a box for 1 of 2 items\./);
  assert.match(text, /Man in the blue jacket: box found at 0:12\. Confirm or adjust it on the item\./);
  assert.match(text, /Crowbar: no box found \(no box was found near the second it is seen\)\./);
  assert.match(text, /draw the box for/);
});

test('a job with nothing to look at says so, without offering the box tool', () => {
  const text = gapRetryResultText({ jobId: 'j', videoId: 'v', revisionId: 1, status: 'done', items: [] }, (key) => key);
  assert.equal(text, 'There is no item with no box to look for.');
});

test('the agent job is read as the console shape: its items camel-cased, a missing reason as null', async () => {
  const realFetch = globalThis.fetch;
  const body = {
    job_id: 'abc',
    video_id: 'v',
    revision_id: 7,
    status: 'running',
    items: [{ item_key: 'E2', name: 'man', status: 'pending', reason: null, seconds: null, box: null }],
  };
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  try {
    const job = await readGapRetry('http://agent.example', 'v', 'abc');
    assert.deepEqual(job, {
      jobId: 'abc',
      videoId: 'v',
      revisionId: 7,
      status: 'running',
      items: [{ itemKey: 'E2', name: 'man', status: 'pending', reason: null, seconds: null, box: null }],
    });
    const started = await startGapRetry('http://agent.example', 'v', 'E2');
    assert.equal(started.jobId, 'abc');
  } finally {
    globalThis.fetch = realFetch;
  }
});

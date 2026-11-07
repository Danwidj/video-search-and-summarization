// SPDX-License-Identifier: Apache-2.0

// Proposed re-track and set-image changes: held beside the item, blocking Save until confirmed, adjusted or dismissed.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { applyAgentActions } = await import('../src/lib/edits/apply-agent-actions.ts');
const proposals = await import('../src/lib/evidence/evidence-proposals.ts');
const { resolveEvidenceActions } = await import('../src/lib/evidence/resolve-evidence-actions.ts');
const { draftFromView, draftProblems, editFromDraft } = await import('../src/modules/reports/domain/edit-draft.ts');
const { buildReportView } = await import('./support/report-view.mjs');

const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));
const base = () => draftFromView(buildReportView({ ...structuredClone(fixture), playbackUrl: 'https://signed.example/v.mp4' }));
const sample = (t) => ({ t, box: [100, 100, 400, 400] });
const track = (partial = false) => ({
  source: 'reviewer',
  samples: [sample(4), sample(5), sample(6)],
  span: [4, 6],
  partial,
  lostAt: partial ? 6 : null,
});
const act = (args, id = 'e1') => ({ id, tool: 'change_evidence', args });
const PENDING = /Confirm, adjust or dismiss/;

test('a set-image proposal sits beside the item, changes nothing about it and blocks Save', () => {
  const draft = base();
  const key = draft.entities[0].key;
  const result = applyAgentActions(draft, [
    act({ op: 'set_image', itemKey: key, seconds: 3.25, box: [10, 20, 300, 400], reason: 'clearer' }),
  ]);
  assert.equal(result.applied.length, 1);
  const [entity] = result.draft.entities;
  assert.deepEqual(entity.proposal, { kind: 'set_image', pick: { seconds: 3.25, box: [10, 20, 300, 400] }, reason: 'clearer' });
  assert.equal(entity.imagePick, null, 'not a pick until confirmed');
  assert.equal(entity.reviewer, null);
  assert.ok(result.problems.some((problem) => PENDING.test(problem)));
  assert.throws(() => editFromDraft(result.draft), PENDING, 'the edit Save sends cannot be built');
});

test('a re-track proposal needs a usable track and keeps partial and lostAt for the card', () => {
  const draft = base();
  const key = draft.entities[0].key;
  const noTrack = applyAgentActions(draft, [act({ op: 'retrack', itemKey: key, seconds: 4, box: [1, 2, 30, 40] })]);
  assert.match(noTrack.skipped[0].reason, /no usable track/);
  const ok = applyAgentActions(draft, [act({ op: 'retrack', itemKey: key, track: track(true) })]);
  const { proposal } = ok.draft.entities[0];
  assert.equal(proposal.track.partial, true);
  assert.equal(proposal.track.lostAt, 6);
  assert.match(proposals.describeProposal(proposal), /lost the item at 6\.0 s/);
  assert.equal(ok.draft.entities[0].reviewer, null);
});

test('an invented key or a box outside the frame is skipped', () => {
  const draft = base();
  assert.match(
    applyAgentActions(draft, [act({ op: 'set_image', itemKey: 'nope', seconds: 1, box: [0, 0, 5, 5] })]).skipped[0].reason,
    /no item/,
  );
  assert.equal(
    applyAgentActions(draft, [act({ op: 'set_image', itemKey: draft.entities[0].key, seconds: 1, box: [0, 0, 5, 1200] })]).skipped.length,
    1,
  );
});

test('Confirm turns a set-image proposal into the pick and clears the block', () => {
  const draft = base();
  const key = draft.entities[0].key;
  const proposed = proposals.proposeEvidence(draft, key, { kind: 'set_image', pick: { seconds: 2, box: [1, 2, 30, 40] }, reason: null });
  const confirmed = proposals.confirmProposal(proposed, key);
  assert.deepEqual(confirmed.entities[0].imagePick, { seconds: 2, box: [1, 2, 30, 40] });
  assert.equal(confirmed.entities[0].proposal, null);
  assert.ok(!draftProblems(confirmed).some((problem) => PENDING.test(problem)));
  assert.deepEqual(editFromDraft(confirmed).entities[0].image_pick, { seconds: 2, box: [1, 2, 30, 40] });
});

test('Confirm of a re-track keeps the text and moves the evidence second, box and span', () => {
  const draft = base();
  const key = draft.entities[0].key;
  const before = draft.entities[0];
  const confirmed = proposals.confirmProposal(
    proposals.proposeEvidence(draft, key, { kind: 'retrack', track: track(), reason: null }),
    key,
  );
  const [entity] = confirmed.entities;
  assert.deepEqual([entity.label, entity.description], [before.label, before.description]);
  assert.deepEqual([entity.timestampSeconds, entity.firstSeenSeconds, entity.lastSeenSeconds], [4, 4, 6]);
  assert.equal(entity.reviewer.track.span[1], 6);
  assert.equal(entity.proposal, null);
  assert.equal(
    draftProblems(confirmed).some((problem) => PENDING.test(problem)),
    false,
  );
});

test('Adjust then Done confirms the adjusted values, and Dismiss leaves the item as it was', () => {
  const draft = base();
  const key = draft.entities[0].key;
  const proposed = proposals.proposeEvidence(draft, key, { kind: 'set_image', pick: { seconds: 2, box: [1, 2, 30, 40] }, reason: null });
  const adjusted = proposals.confirmAdjusted(proposed, key, { seconds: 2.5, box: [5, 5, 50, 50] });
  assert.deepEqual(adjusted.entities[0].imagePick, { seconds: 2.5, box: [5, 5, 50, 50] });
  assert.equal(adjusted.entities[0].proposal, null);
  const dismissed = proposals.dismissProposal(proposed, key);
  assert.deepEqual(dismissed.entities[0], { ...draft.entities[0], proposal: null });
  assert.equal(proposals.pendingProposalCount(proposed), 1);
  assert.equal(proposals.pendingProposalCount(dismissed), 0);
});

test('a re-track action gets the tracker answer before applying; a failed call leaves it to be skipped', async () => {
  const draft = base();
  const key = draft.entities[0].key;
  const calls = [];
  const client = {
    async track(videoId, request) {
      calls.push([videoId, request]);
      return track();
    },
  };
  const action = act({ op: 'retrack', itemKey: key, seconds: 5, box: [1, 2, 30, 40] });
  const [resolved] = await resolveEvidenceActions('vid', draft, [action], client);
  assert.equal(calls[0][1].itemType, 'entity');
  assert.equal(calls[0][1].seconds, 5);
  assert.equal(resolved.args.track.span[0], 4);
  const result = applyAgentActions(draft, [resolved]);
  assert.equal(result.applied.length, 1);
  const [failed] = await resolveEvidenceActions('vid', draft, [action], {
    track: async () => {
      throw new Error('agent down');
    },
  });
  assert.equal(failed.args.track, undefined);
  assert.equal(applyAgentActions(draft, [failed]).skipped.length, 1);
});

test('the pane always shows Confirm, Adjust and Dismiss on an item with a proposed evidence change', () => {
  const pane = readFileSync(join(process.cwd(), 'src/sections/reports/components/ReportEditPane/ReportEditPane.tsx'), 'utf8');
  for (const id of ['evidence-proposal', 'proposal-confirm', 'proposal-adjust', 'proposal-dismiss'])
    assert.ok(pane.includes(`"${id}"`), id);
  assert.doesNotMatch(pane, /evidenceProposals/);
});

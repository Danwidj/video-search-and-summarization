// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import { MergeRequestError, mergeFailureMessage } from '../src/lib/reports/merge-client.ts';
import { mergedNotice, mergeThenRebuild, officialMergeWarning } from '../src/lib/reports/merge-flow.ts';
import { needsRegenerate } from '../src/lib/reports/regenerate.ts';
import { removedNotice, staleReportNote } from '../src/lib/reports/remove-video.ts';

const flow = ({ failMerge = false, buildResult = true } = {}) => {
  const calls = [];
  return {
    calls,
    deps: {
      merge: async () => {
        calls.push('merge');
        if (failMerge) throw new MergeRequestError(404, 'incident 3 or 4 does not exist');
      },
      build: async (id) => {
        calls.push(`build:${id}`);
        return buildResult;
      },
    },
  };
};

test('a merge builds the kept incident once, after the merge is saved', async () => {
  const { calls, deps } = flow();
  assert.equal(await mergeThenRebuild(deps, 7), true);
  assert.deepEqual(calls, ['merge', 'build:7']);
});

test('a failed build is reported, not thrown, and the merge stays saved', async () => {
  const { calls, deps } = flow({ buildResult: false });
  assert.equal(await mergeThenRebuild(deps, 7), false);
  assert.deepEqual(calls, ['merge', 'build:7']);
});

test('a refused merge builds nothing and throws the friendly error', async () => {
  const { calls, deps } = flow({ failMerge: true });
  await assert.rejects(mergeThenRebuild(deps, 7), /no longer exists/);
  assert.deepEqual(calls, ['merge']);
});

test('refusals are worded for the reviewer', () => {
  assert.match(mergeFailureMessage(404, 'incident 114 or 115 does not exist'), /no longer exists.*nothing was merged/);
  assert.doesNotMatch(mergeFailureMessage(404, 'incident 114 or 115 does not exist'), /114/);
  assert.match(mergeFailureMessage(422, 'cannot merge incident 1 into itself'), /cannot be merged/);
  assert.equal(mergeFailureMessage(500, 'Boom'), 'Boom');
  assert.match(mergeFailureMessage(null, ''), /Nothing was changed/);
  assert.equal(new MergeRequestError(422, 'x').status, 422);
});

test('the success notice names the incident, the video count and the rebuild', () => {
  const notice = mergedNotice({ keptIncidentId: 12, videoCount: 3, rebuilt: true });
  assert.equal(notice.title, 'Merged into Incident 12');
  assert.match(notice.detail, /Incident 12 now holds 3 videos/);
  assert.match(notice.detail, /report was rebuilt/);
  assert.equal(notice.keptIncidentId, 12);
});

test('a failed rebuild tells the reviewer to press Regenerate', () => {
  const notice = mergedNotice({ keptIncidentId: 12, videoCount: 1, rebuilt: false });
  assert.match(notice.detail, /1 video, but its report could not be rebuilt/);
  assert.match(notice.detail, /Regenerate/);
});

test('the official warning appears only for a target with an official version', () => {
  assert.equal(officialMergeWarning({ incidentId: 5, hasOfficial: false }, ['a.mp4']), null);
  const warning = officialMergeWarning({ incidentId: 5, hasOfficial: true }, ['a.mp4', 'b.mp4']);
  assert.match(warning, /Incident 5's official version stays as it is/);
  assert.match(warning, /not include a\.mp4, b\.mp4/);
});

test('Regenerate is the main action only when the open version is out of date', () => {
  assert.equal(needsRegenerate({ note: null }), false);
  assert.equal(needsRegenerate({ note: 'Does not include: c.mp4' }), true);
});

test('a delete or move leaves the stale report note on the incident, with a move naming the new one', () => {
  assert.match(staleReportNote(4), /Incident #4's report still includes this video\. Press Regenerate/);
  assert.deepEqual(removedNotice('a.mp4', 'delete', 4), { title: 'a.mp4 deleted', detail: staleReportNote(4) });
  assert.equal(removedNotice('a.mp4', 'move', 4, 9).title, 'a.mp4 moved to Incident #9');
});

test('the server-side join paths never build: only the confirmed manual merge and Accept do, so an automatic join builds once', async () => {
  const { readFileSync } = await import('node:fs');
  for (const file of ['src/modules/matching/application/decide-suggestion.ts', 'src/modules/matching/application/evaluate-incident.ts']) {
    assert.doesNotMatch(readFileSync(file, 'utf8'), /\/build|requestReportBuild|synthesi[sz]e/i, file);
  }
  const hook = readFileSync('src/sections/suggestions/use-suggestion-cards.ts', 'utf8');
  assert.equal(hook.match(/mergeThenRebuild\(/g)?.length, 1);
});

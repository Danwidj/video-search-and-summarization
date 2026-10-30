// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { overviewChangeCount, overviewDraftFrom, overviewFromDraft, overviewProblems } = await import(
  '../src/modules/reports/domain/overview-draft.ts'
);

const base = { title: 'Fight at the door', type: 'assault', severity_level: 3, description: 'Two people fight.', location: 'Front door' };

test('a draft starts equal to the opened overview and counts no change', () => {
  const draft = overviewDraftFrom(base);
  assert.deepEqual(draft, base);
  assert.notEqual(draft, base);
  assert.equal(overviewChangeCount(base, draft), 0);
});

test('stray spaces are not a change, blank text saves as absent', () => {
  const draft = { ...overviewDraftFrom(base), title: '  Fight at the door  ', location: '   ' };
  assert.equal(overviewChangeCount(base, draft), 1);
  assert.deepEqual(overviewFromDraft(draft), { ...base, location: null });
});

test('each changed field counts once', () => {
  const draft = { ...base, title: 'Brawl', type: 'burglary', severity_level: 4, description: 'x', location: null };
  assert.equal(overviewChangeCount(base, draft), 5);
});

test('problems: over-long text and an out-of-range severity are refused, a clean draft has none', () => {
  assert.deepEqual(overviewProblems(overviewDraftFrom(base)), []);
  assert.deepEqual(overviewProblems({ ...base, title: 'x'.repeat(501) }), ['The title is longer than 500 characters.']);
  assert.deepEqual(overviewProblems({ ...base, severity_level: 7 }), ['The severity must be a whole number from 1 to 5.']);
  assert.deepEqual(overviewProblems({ ...base, severity_level: null, type: null }), []);
});

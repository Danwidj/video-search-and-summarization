// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import { EMPTY_FILTERS, libraryUrl, parseFilters, parseTab } from '../src/lib/library/filters.ts';
import { cardTitle, matchesSortNote } from '../src/lib/library/view.ts';

const read = (...parts) => readFileSync(join(process.cwd(), 'src', ...parts), 'utf8');

test('the tab is part of the library URL, beside the filters in force', () => {
  assert.equal(libraryUrl('incidents', EMPTY_FILTERS), '/library');
  assert.equal(libraryUrl('matches', EMPTY_FILTERS), '/library?tab=matches');
  assert.equal(libraryUrl('evidence', { ...EMPTY_FILTERS, type: 'Fall', page: 2 }), '/library?tab=evidence&type=Fall&page=2');
  assert.equal(libraryUrl('incidents', { ...EMPTY_FILTERS, severity: 'high' }), '/library?severity=high');
});

test('a reload of the URL a tab click wrote lands on the same tab and filters', () => {
  const filters = { ...EMPTY_FILTERS, type: 'Fall', sort: 'oldest' };
  for (const tab of ['incidents', 'evidence', 'matches']) {
    const query = new URL(libraryUrl(tab, filters), 'http://x').searchParams;
    assert.equal(parseTab(query.get('tab')), tab);
    assert.deepEqual(parseFilters(query), filters);
  }
  assert.equal(parseTab('nonsense'), 'incidents');
  assert.equal(parseTab(null), 'incidents');
});

test('choosing a tab writes the URL, not only the incidents list loading', () => {
  const screen = read('sections', 'library', 'components', 'LibraryScreen', 'LibraryScreen.tsx');
  assert.match(screen, /if \(ready && tab !== 'incidents'\) router\.replace\(libraryUrl\(tab, filters\)/);
});

test('a card led by the official version says which version it shows', () => {
  assert.equal(cardTitle({ title: 'Forklift near miss', isOfficial: true, revisionNo: 3 }, 'x'), 'Official v3 · Forklift near miss');
  assert.equal(cardTitle({ title: 'Forklift near miss', isOfficial: false, revisionNo: 4 }, 'x'), 'Forklift near miss');
  assert.equal(cardTitle({ title: '', isOfficial: true, revisionNo: 2 }, 'Fall · today'), 'Official v2 · Fall · today');
  assert.equal(cardTitle({ title: '', isOfficial: false, revisionNo: null }, 'Fall · today'), 'Fall · today');
});

test('the Matches tab sorts only when something is pending', () => {
  assert.equal(matchesSortNote(0), null);
  assert.equal(matchesSortNote(1), '1 pending · highest score first');
  assert.equal(matchesSortNote(4), '4 pending · highest score first');
});

test('the library button names videos, as the batch page does', () => {
  const screen = read('sections', 'library', 'components', 'LibraryScreen', 'LibraryScreen.tsx');
  assert.equal(screen.match(/Analyze videos/g)?.length, 2);
  assert.doesNotMatch(screen, /Analyze video\b(?!s)/);
});

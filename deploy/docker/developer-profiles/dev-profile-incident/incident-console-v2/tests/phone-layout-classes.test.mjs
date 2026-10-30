// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// The console has no DOM test layer, so the 390px layouts are proved in a browser
// (innerWidth equals scrollWidth) and these assertions keep the classes that do it.
const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

test('library tabs scroll inside their own list at phone width instead of widening the page', () => {
  const library = source('sections/library/components/LibraryScreen/LibraryScreen.tsx');
  const list = library.match(/<TabsList className="([^"]*)"/)?.[1] ?? '';
  assert.match(list, /\boverflow-x-auto\b/);
  const triggers = [...library.matchAll(/<TabsTrigger className="([^"]*)"/g)].map((match) => match[1]);
  assert.equal(triggers.length, 3);
  for (const classes of triggers) assert.match(classes, /\bpx-3\b.*\bsm:px-4\b/);
});

test('dashboard heatmap fits the card below sm and keeps its width floor from sm up', () => {
  const dashboard = source('sections/dashboard/components/Dashboard/Dashboard.tsx');
  assert.doesNotMatch(dashboard, /["' ]min-w-\[520px\]/);
  assert.match(dashboard, /\bw-full min-w-0 sm:min-w-\[520px\]/);
  assert.match(dashboard, /\baspect-square min-w-0 [^']*\bp-0\b/);
});

test('edit-mode start and end inputs cap at the video length', () => {
  const pane = source('sections/reports/components/ReportEditPane/ReportEditPane.tsx');
  assert.equal(pane.match(/max=\{videoLength === null \? undefined : Math\.floor\(videoLength\)\}/g)?.length, 2);
  const page = source('sections/reports/components/ReportPage/ReportPage.tsx');
  assert.match(page, /videoLength=\{playerDuration\}/);
});

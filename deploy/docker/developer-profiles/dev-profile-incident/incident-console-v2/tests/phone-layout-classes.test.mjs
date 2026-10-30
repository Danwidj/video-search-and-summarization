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

test('report title takes its own full-width row below sm, with the controls wrapping under it', () => {
  const page = source('sections/reports/components/ReportPage/ReportPage.tsx');
  const title = page.match(/<h1\s+className="([^"]*)"\s+title=\{filename\}/)?.[1] ?? '';
  assert.doesNotMatch(title, /\border-/);
  assert.match(title, /\bbasis-full\b/);
  assert.match(title, /\bsm:flex-1\b/);
  assert.match(title, /\bsm:basis-0\b/);
});

test('version rows wrap their pills and only the star, badge and buttons keep their width', () => {
  const versions = source('sections/reports/components/ReportVersions/ReportVersions.tsx');
  assert.match(versions, /<span className="flex flex-wrap items-center gap-x-1\.5 gap-y-1 text-muted-foreground">/);
  assert.doesNotMatch(versions, /<span className="truncate">/);
  assert.match(versions, /<span className="min-w-0 \[overflow-wrap:anywhere\]">/);
  for (const marker of [
    'h-7 w-7 shrink-0',
    'h-6 shrink-0 self-center px-2 text-\\[10\\.5px\\] font-bold',
    'shrink-0 self-center px-2 py-0\\.5',
  ]) {
    assert.match(versions, new RegExp(marker));
  }
});

// SPDX-License-Identifier: Apache-2.0

// Known issue 4: the /library card image is MVP1's report-card thumbnail again
// (the upload-time screenshot only, MVP1's skeleton when it is missing or fails,
// MVP1's severity chip and AI/Human badge). The components are TSX, which the
// test runner cannot strip, so their sources are checked like the other UI tests.

import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import test from 'node:test';

import { reportThumbnailView } from '../src/lib/ui/thumbnail.ts';

const src = new URL('../src/', import.meta.url);
const read = (path) => readFile(new URL(path, src), 'utf8');

test('the card image is the screenshot, else the skeleton, never anything else', () => {
  assert.deepEqual(reportThumbnailView('https://signed.r2.test/thumbnails/v.mp4.webp'), {
    kind: 'image',
    loading: 'lazy',
    src: 'https://signed.r2.test/thumbnails/v.mp4.webp',
  });
  assert.deepEqual(reportThumbnailView(undefined), { kind: 'skeleton' }, 'a video with no screenshot shows the skeleton');
  assert.deepEqual(
    reportThumbnailView('https://signed.r2.test/thumbnails/v.mp4.webp', true),
    { kind: 'skeleton' },
    'a failed load shows it too',
  );
});

test('the incident card passes only the screenshot URL to the MVP1 thumbnail', async () => {
  const card = await read('sections/library/components/IncidentCard/IncidentCard.tsx');
  assert.match(card, /<ReportThumbnail kind=\{item\.kind\} severity=\{item\.severity\} thumbnailUrl=\{item\.thumbnailUrl\} \/>/);
  assert.doesNotMatch(card, /evidenceThumbnailUrl|item\.thumbnail\b|IncidentThumbnail/);
});

test('the MVP1 thumbnail keeps its skeleton, severity chip and AI/Human badge', async () => {
  const thumbnail = await read('sections/library/components/ReportThumbnail/ReportThumbnail.tsx');
  assert.match(thumbnail, /reportThumbnailView\(thumbnailUrl, failed\)/);
  // A failed request flips to the skeleton once and is never retried with another image.
  assert.match(thumbnail, /onError=\{\(\) => setFailed\(true\)\}/);
  assert.match(thumbnail, /data-testid="library-thumbnail-skeleton"/);
  assert.match(thumbnail, /border-y-\[10px\] border-l-\[16px\] border-y-transparent border-l-ink\/25/, 'the skeleton play mark');
  assert.match(thumbnail, /absolute left-3 top-3 rounded-full px-3 py-1\.5 text-xs font-bold \$\{severityClass\(severity\)\}/);
  assert.match(thumbnail, /Severity \{severity\}/);
  assert.match(thumbnail, /absolute right-3 top-3 rounded-full bg-white\/90 px-3 py-1\.5 text-xs font-semibold text-ink/);
  assert.match(thumbnail, /\{kind === 'human' \? 'Human' : 'AI'\}/);
});

test('no console code signs or shows an evidence crop as a card thumbnail', async () => {
  const pending = [src];
  while (pending.length) {
    const dir = pending.pop();
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const url = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir);
      if (entry.isDirectory()) pending.push(url);
      else if (/\.(ts|tsx)$/.test(entry.name)) assert.doesNotMatch(await readFile(url, 'utf8'), /evidenceThumbnailUrl/, url.pathname);
    }
  }
});

// SPDX-License-Identifier: Apache-2.0

// Known issue 4: the /library card image is MVP1's report-card thumbnail again:
// the upload-time screenshot only, MVP1's skeleton when it is missing or fails
// to load, and MVP1's severity and AI/Human badges. ReportThumbnail renders
// exactly what libraryCardThumbnail returns.

import assert from 'node:assert/strict';
import test from 'node:test';

import { libraryCardThumbnail } from '../src/lib/ui/thumbnail.ts';

const SCREENSHOT = 'https://signed.r2.test/thumbnails/uploads/s/v.mp4.webp';

test('a card with a screenshot lazy-loads it', () => {
  assert.deepEqual(libraryCardThumbnail({ thumbnailUrl: SCREENSHOT, severity: 4, kind: 'ai' }).image, {
    kind: 'image',
    loading: 'lazy',
    src: SCREENSHOT,
  });
});

test('a card with no screenshot shows the skeleton, even when the incident has evidence images', () => {
  const item = {
    severity: 3,
    kind: 'human',
    // What #185 used as a fallback: the shown revision's first evidence image, signed or as an R2 key.
    thumbnail: 'evidence/v1/u1/E1.jpg',
    evidenceThumbnailUrl: 'https://signed.r2.test/evidence/v1/u1/E1.jpg',
  };
  assert.deepEqual(libraryCardThumbnail(item).image, { kind: 'skeleton' });
});

test('a screenshot that failed to load shows the skeleton instead of another image', () => {
  assert.deepEqual(libraryCardThumbnail({ thumbnailUrl: SCREENSHOT, severity: 2, kind: 'ai' }, true).image, { kind: 'skeleton' });
});

test('the badges read as on MVP1: the severity level and the revision kind', () => {
  assert.deepEqual(
    [libraryCardThumbnail({ severity: 5, kind: 'human' }), libraryCardThumbnail({ severity: 1, kind: 'ai' })].map(
      ({ severityLabel, kindLabel }) => [severityLabel, kindLabel],
    ),
    [
      ['Severity 5', 'Human'],
      ['Severity 1', 'AI'],
    ],
  );
});

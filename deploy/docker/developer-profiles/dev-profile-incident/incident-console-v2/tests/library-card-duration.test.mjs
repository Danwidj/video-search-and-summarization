// SPDX-License-Identifier: Apache-2.0

// The /library card shows its video's length as a badge: m:ss, or h:mm:ss from an hour, and nothing when the
// length is unknown. IncidentCard passes durationSeconds to ReportThumbnail, which renders libraryCardThumbnail's
// durationLabel, so these tests cover the formatter and the card's view model with and without a duration.

import assert from 'node:assert/strict';
import test from 'node:test';

const { formatVideoDuration, libraryCardThumbnail } = await import('../src/lib/ui/thumbnail.ts');

test('a length under an hour reads as m:ss', () => {
  assert.equal(formatVideoDuration(12), '0:12');
  assert.equal(formatVideoDuration(75), '1:15');
  assert.equal(formatVideoDuration(3599), '59:59');
});

test('a length of an hour or more reads as h:mm:ss', () => {
  assert.equal(formatVideoDuration(3600), '1:00:00');
  assert.equal(formatVideoDuration(3725), '1:02:05');
});

test('fractions round down to whole seconds', () => {
  assert.equal(formatVideoDuration(12.9), '0:12');
});

test('an unknown or sub-second length has no badge', () => {
  for (const value of [null, undefined, 0, 0.4, -3, Number.NaN, Number.POSITIVE_INFINITY, '12']) {
    assert.equal(formatVideoDuration(value), null, String(value));
  }
});

test('a card with a duration shows its badge text', () => {
  const card = libraryCardThumbnail({ severity: 3, kind: 'ai', durationSeconds: 12.4 });
  assert.equal(card.durationLabel, '0:12');
});

test('a card without a duration shows no badge', () => {
  assert.equal(libraryCardThumbnail({ severity: 3, kind: 'ai', durationSeconds: null }).durationLabel, null);
  assert.equal(libraryCardThumbnail({ severity: 3, kind: 'ai' }).durationLabel, null);
});

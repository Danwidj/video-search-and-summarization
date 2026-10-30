// SPDX-License-Identifier: Apache-2.0

// recorded_at from an MP4's mvhd creation time: used only when the file carries a plausible one.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { mp4DurationSeconds, mp4RecordedAt } = await import('../src/lib/video/mp4-duration.ts');

const MP4_EPOCH_OFFSET = 2_082_844_800;
const NOW = new Date('2026-10-30T00:00:00.000Z');

function box(type, body) {
  const out = Buffer.alloc(8 + body.length);
  out.writeUInt32BE(8 + body.length, 0);
  out.write(type, 4, 'latin1');
  body.copy(out, 8);
  return out;
}

/** ftyp, mdat, then moov/mvhd (version 0 or 1) with the given MP4-epoch creation time. */
function mp4({ created, version = 0, seconds = 10 }) {
  const body = Buffer.alloc(version === 1 ? 4 + 8 + 8 + 4 + 8 + 80 : 4 + 4 + 4 + 4 + 4 + 80);
  body[0] = version;
  if (version === 1) {
    body.writeBigUInt64BE(BigInt(created), 4);
    body.writeUInt32BE(1000, 4 + 16);
    body.writeBigUInt64BE(BigInt(seconds * 1000), 4 + 16 + 4);
  } else {
    body.writeUInt32BE(created, 4);
    body.writeUInt32BE(1000, 4 + 8);
    body.writeUInt32BE(seconds * 1000, 4 + 8 + 4);
  }
  return Buffer.concat([box('ftyp', Buffer.alloc(8)), box('mdat', Buffer.alloc(64)), box('moov', box('mvhd', body))]);
}

const reader = (bytes) => async (offset, length) => new Uint8Array(bytes.subarray(offset, offset + length));
const recordedAt = (bytes) => mp4RecordedAt(reader(bytes), bytes.length, NOW);

test('reads the creation time of a version 0 and a version 1 header', async () => {
  const unix = Date.UTC(2026, 9, 29, 8, 0, 0) / 1000;
  assert.equal(await recordedAt(mp4({ created: unix + MP4_EPOCH_OFFSET })), '2026-10-29T08:00:00.000Z');
  assert.equal(await recordedAt(mp4({ created: unix + MP4_EPOCH_OFFSET, version: 1 })), '2026-10-29T08:00:00.000Z');
});

test('the duration reader still works on the same files', async () => {
  const bytes = mp4({ created: 1, seconds: 12 });
  assert.equal(await mp4DurationSeconds(reader(bytes), bytes.length), 12);
});

test('no time when the header leaves it unset, before 1970, in the future or unreadable', async () => {
  assert.equal(await recordedAt(mp4({ created: 0 })), null);
  assert.equal(await recordedAt(mp4({ created: 1_000 })), null);
  assert.equal(await recordedAt(mp4({ created: Math.floor(NOW.getTime() / 1000) + MP4_EPOCH_OFFSET + 86_400 })), null);
  const garbage = Buffer.from('not an mp4 at all');
  assert.equal(await recordedAt(garbage), null);
});

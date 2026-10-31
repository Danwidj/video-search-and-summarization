// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MAX_UPLOAD_NAME_LENGTH, firstFreeName, inspectUploadName, nameWithCounter, uploadKeyForName } from '../src/lib/r2/names.ts';

test('a clean name is kept as it is', () => {
  assert.deepEqual(inspectUploadName('Assault018_x264.mp4'), { name: 'Assault018_x264.mp4', unsafeChars: [], truncated: false });
  assert.equal(inspectUploadName('Café_(2).mp4').name, 'Café_(2).mp4');
});

test('the stored name always ends in .mp4, because every stored video is an H.264 MP4', () => {
  assert.deepEqual(inspectUploadName('IMG_9170.MOV'), { name: 'IMG_9170.mp4', unsafeChars: [], truncated: false });
  assert.equal(inspectUploadName('Café_(2).mov').name, 'Café_(2).mp4');
  assert.equal(inspectUploadName('clip.webm').name, 'clip.mp4');
  assert.equal(inspectUploadName('clip.MP4').name, 'clip.mp4');
  assert.equal(inspectUploadName('noext').name, 'noext.mp4');
  assert.equal(inspectUploadName('   ').name, 'video.mp4');
});

test('unsafe characters become _ and are listed once each', () => {
  const result = inspectUploadName('front door #1 #2.mp4');
  assert.deepEqual([result.name, result.unsafeChars], ['front_door__1__2.mp4', ['space', '#']]);
});

test('a path is reduced to its last segment and flagged', () => {
  const result = inspectUploadName('../../etc/passwd.mp4');
  assert.equal(result.name, 'passwd.mp4');
  assert.ok(result.unsafeChars.includes('/'));
  assert.equal(inspectUploadName('C:\\clips\\a.mp4').name, 'C_.mp4'.length ? inspectUploadName('C:\\clips\\a.mp4').name : '');
});

test('dots cannot make a hidden or traversing name, and an empty name gets a default', () => {
  assert.equal(inspectUploadName('..a..b.mp4').name.startsWith('.'), false);
  assert.equal(inspectUploadName('a..b.mp4').name.includes('..'), false);
  assert.equal(inspectUploadName('   ').name, 'video.mp4');
});

test('only a name over the limit is truncated, and the extension survives', () => {
  const exact = `${'a'.repeat(MAX_UPLOAD_NAME_LENGTH - 4)}.mp4`;
  assert.deepEqual(inspectUploadName(exact), { name: exact, unsafeChars: [], truncated: false });
  const long = inspectUploadName(`${'a'.repeat(400)}.mp4`);
  assert.equal(long.truncated, true);
  assert.equal(long.name.length, MAX_UPLOAD_NAME_LENGTH);
  assert.ok(long.name.endsWith('.mp4'));
  const longStem = inspectUploadName('a'.repeat(MAX_UPLOAD_NAME_LENGTH));
  assert.deepEqual([longStem.truncated, longStem.name.length, longStem.name.endsWith('.mp4')], [true, MAX_UPLOAD_NAME_LENGTH, true]);
});

test('a counter goes before the extension and keeps the name within the limit', () => {
  assert.equal(nameWithCounter('clip.mp4', 1), 'clip.mp4');
  assert.equal(nameWithCounter('clip.mp4', 2), 'clip-2.mp4');
  assert.equal(nameWithCounter('noext', 3), 'noext-3');
  assert.equal(nameWithCounter(`${'a'.repeat(146)}.mp4`, 12).length, MAX_UPLOAD_NAME_LENGTH);
});

test('firstFreeName takes the first unused counter, deterministically', async () => {
  const taken = new Set(['clip.mp4', 'clip-2.mp4']);
  assert.equal(await firstFreeName('clip.mp4', async (name) => taken.has(name)), 'clip-3.mp4');
  assert.equal(await firstFreeName('other.mp4', async (name) => taken.has(name)), 'other.mp4');
  await assert.rejects(
    firstFreeName('x.mp4', async () => true),
    /Too many files/,
  );
  assert.equal(uploadKeyForName('clip.mp4'), 'uploads/clip.mp4');
});

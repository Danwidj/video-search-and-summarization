// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { test } from 'node:test';

const { segmentChatText, seekTarget } = await import('../src/lib/chat/timestamps.ts');

const times = (text, options) =>
  segmentChatText(text, options)
    .filter((segment) => segment.kind === 'time')
    .map((segment) => [segment.text, segment.seconds]);
const joined = (text, options) =>
  segmentChatText(text, options)
    .map((segment) => segment.text)
    .join('');

test('every supported way of writing a video time is found, with its second', () => {
  const cases = [
    ['00:15', [['00:15', 15]]],
    ['01:23', [['01:23', 83]]],
    ['1:23', [['1:23', 83]]],
    ['00:01:23', [['00:01:23', 83]]],
    ['1:02:05', [['1:02:05', 3725]]],
    ['[00:15]', [['00:15', 15]]],
    ['(1:23)', [['1:23', 83]]],
    ['**0:15**', [['0:15', 15]]],
    ['• 0:15 He enters.', [['0:15', 15]]],
    ['- 0:15: he enters', [['0:15', 15]]],
    ['At 0:15, he enters.', [['0:15', 15]]],
    ['He leaves at 0:15.', [['0:15', 15]]],
    ['seen at 12:05, then gone', [['12:05', 725]]],
    ['0:12.5 is the frame', [['0:12.5', 12.5]]],
  ];
  for (const [text, expected] of cases) assert.deepEqual(times(text), expected, text);
});

test('each end of a range is its own time', () => {
  const both = [
    ['00:15', 15],
    ['00:30', 30],
  ];
  assert.deepEqual(times('00:15–00:30'), both);
  assert.deepEqual(times('00:15—00:30'), both);
  assert.deepEqual(times('00:15-00:30'), both);
  assert.deepEqual(times('00:15 - 00:30'), both);
  assert.deepEqual(times('from 00:15 to 00:30'), both);
});

test('numbers that are not video times stay text', () => {
  const plain = [
    '16:9 aspect ratio',
    'at 12:30 pm',
    '12:30pm',
    '9:15 a.m.',
    '12:30 hrs',
    '10:15 UTC',
    '2026-11-06T10:15:30',
    '2026-11-06 10:15',
    '6/11/2026, 10:15',
    'http://host:8000/a',
    'https://example.com/clip/1:23',
    'v2:15',
    'E1:15',
    'abc-1:23',
    '1:2',
    '1:60',
    '1:23:75',
    '10:15:30:45',
    '3/4:15',
    '25 seconds',
    'threat level 3 of 5',
  ];
  for (const text of plain) assert.deepEqual(times(text), [], text);
});

test('the text is kept exactly, whatever is found in it', () => {
  const answers = [
    'From 0:21 to 0:46 (25 seconds).\n\n• 0:02–0:05 He enters.\n• [00:15] **He** leaves at 1:02:05.',
    'No times here.',
    '',
    '0:15',
    '  0:15  ',
  ];
  for (const text of answers) {
    assert.equal(joined(text), text);
    assert.equal(joined(text, { durationSeconds: 10 }), text, 'a time past the end stays in the text as written');
  }
});

test('several times in one answer each keep their place', () => {
  assert.deepEqual(segmentChatText('Before 0:02, then 0:05.'), [
    { kind: 'text', text: 'Before ' },
    { kind: 'time', text: '0:02', seconds: 2 },
    { kind: 'text', text: ', then ' },
    { kind: 'time', text: '0:05', seconds: 5 },
    { kind: 'text', text: '.' },
  ]);
});

test('a time past the end of the video is not offered as a jump', () => {
  assert.deepEqual(times('0:30 and 0:31 and 0:32', { durationSeconds: 30.46 }), [
    ['0:30', 30],
    ['0:31', 31],
  ]);
  assert.deepEqual(times('5:00', { durationSeconds: 60 }), []);
});

test('with no known length every valid time is kept', () => {
  for (const durationSeconds of [undefined, null, Number.NaN, Number.POSITIVE_INFINITY, 0]) {
    assert.deepEqual(times('5:00', { durationSeconds }), [['5:00', 300]]);
  }
});

test('a seek never gets a value that is no position, and stays inside a known length', () => {
  for (const bad of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, -1]) assert.equal(seekTarget(bad, 30), null);
  assert.equal(seekTarget(0, 30), 0);
  assert.equal(seekTarget(12.5, 30), 12.5);
  assert.equal(seekTarget(31, 30.46), 30.46);
  assert.equal(seekTarget(31, Number.NaN), 31);
  assert.equal(seekTarget(31), 31);
});

test('a time the agent found the report does not hold is left as text, whatever it looks like', () => {
  assert.deepEqual(times('At 0:22, then 0:58.', { unsupported: ['0:58'] }), [['0:22', 22]]);
  assert.equal(joined('At 0:22, then 0:58.', { unsupported: ['0:58'] }), 'At 0:22, then 0:58.');
});

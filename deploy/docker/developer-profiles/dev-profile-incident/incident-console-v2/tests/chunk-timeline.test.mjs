// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { buildReportView } = await import('./support/report-view.mjs');
const { activeChunkIndex, chunkTimelineFrom } = await import('../src/modules/reports/domain/chunk-timeline.ts');
const { seekToWindow } = await import('../src/lib/reports/chunk-seek.ts');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));

/** The smoke run with its notes' response carrying `chunkTimeline` (left out when undefined). */
function rowsWithTimeline(chunkTimeline) {
  const rows = clone(smoke);
  const wrapper = JSON.parse(rows.modelRun.notes);
  if (chunkTimeline !== undefined) wrapper.incidentConsoleV2.response.chunkTimeline = chunkTimeline;
  rows.modelRun.notes = JSON.stringify(wrapper);
  return { ...rows, playbackUrl: 'https://signed.example/video.mp4' };
}

// The agent's default plan for a 45 s clip: 20 s windows overlapping by 2 s.
const agentTimeline = [
  {
    start: 18,
    end: 38,
    caption: '[18.0s-30.0s] Two people walk.\n[30.0s-38.0s] One stops.',
    events: [
      { start: 18, end: 30, text: 'Two people walk.' },
      { start: 30, end: 38, text: 'One stops.' },
    ],
  },
  { start: 0, end: 20, caption: '[0.0s-20.0s] An empty pavement.', events: [{ start: 0, end: 20, text: 'An empty pavement.' }] },
  { start: 36, end: 45, caption: '[40.5s-41.5s] A person falls.', events: [] },
];
const windows = chunkTimelineFrom(agentTimeline);

test('chunk timeline view: present in the run notes, ordered by start, with its events', () => {
  const view = buildReportView(rowsWithTimeline(agentTimeline));
  assert.deepEqual(
    view.chunkTimeline.map((window) => [window.startSeconds, window.endSeconds]),
    [
      [0, 20],
      [18, 38],
      [36, 45],
    ],
  );
  assert.equal(view.chunkTimeline[1].caption, '[18.0s-30.0s] Two people walk.\n[30.0s-38.0s] One stops.');
  assert.deepEqual(view.chunkTimeline[1].events[1], { startSeconds: 30, endSeconds: 38, text: 'One stops.' });
  assert.deepEqual(view.chunkTimeline[2].events, []);
});

test('chunk timeline view: absent (no caption pass, or a skipped one) gives an empty list', () => {
  assert.deepEqual(buildReportView(rowsWithTimeline(undefined)).chunkTimeline, []);
  assert.deepEqual(buildReportView(rowsWithTimeline({ skipped: 'ffmpeg missing' })).chunkTimeline, []);
  assert.deepEqual(chunkTimelineFrom(null), []);
});

test('chunk timeline view: malformed entries and events are skipped without throwing', () => {
  const view = buildReportView(
    rowsWithTimeline([
      null,
      'caption',
      [1, 2],
      { start: '0', end: 20, caption: 'text start' },
      { start: 5, end: 5, caption: 'empty window' },
      { start: 10, end: 4, caption: 'reversed' },
      { start: -1, end: 4, caption: 'negative' },
      { start: 0, end: Number.NaN, caption: 'not finite' },
      { start: 0, end: 20, caption: '   ' },
      { start: 0, end: 20 },
      {
        start: 20,
        end: 40,
        caption: 'kept',
        events: [null, { start: 21, end: 22 }, { start: 'x', end: 2, text: 'bad' }, { start: 25, end: 26, text: ' ok ' }],
      },
      { start: 40, end: 60, caption: 'kept, events not a list', events: 'none' },
    ]),
  );
  assert.deepEqual(
    view.chunkTimeline.map((window) => [window.startSeconds, window.caption, window.events]),
    [
      [20, 'kept', [{ startSeconds: 25, endSeconds: 26, text: 'ok' }]],
      [40, 'kept, events not a list', []],
    ],
  );
});

test('active window: the latest-starting window containing the time, so the overlap hands over', () => {
  assert.equal(activeChunkIndex(windows, 0), 0);
  assert.equal(activeChunkIndex(windows, 17.9), 0);
  assert.equal(activeChunkIndex(windows, 18), 1, 'the overlap 18-20 s belongs to the later window');
  assert.equal(activeChunkIndex(windows, 20), 1);
  assert.equal(activeChunkIndex(windows, 37), 2);
  assert.equal(activeChunkIndex(windows, 45), 2, 'the last window stays active at the very end');
});

test('active window: none before the first window, after the last or in a gap', () => {
  const gappy = chunkTimelineFrom([
    { start: 5, end: 10, caption: 'a' },
    { start: 20, end: 30, caption: 'b' },
  ]);
  assert.equal(activeChunkIndex(gappy, 4.9), -1);
  assert.equal(activeChunkIndex(gappy, 15), -1);
  assert.equal(activeChunkIndex(gappy, 30.1), -1);
  assert.equal(activeChunkIndex(gappy, 10), 0);
  assert.equal(activeChunkIndex([], 3), -1);
});

test('seek: a window click moves the playhead to its start and never starts or stops playback', () => {
  const calls = [];
  const video = {
    currentTime: 3,
    play: () => calls.push('play'),
    pause: () => calls.push('pause'),
  };
  seekToWindow(video, windows[1]);
  assert.equal(video.currentTime, 18);
  assert.deepEqual(calls, []);
  assert.doesNotThrow(() => seekToWindow(null, windows[0]), 'no player yet: nothing to seek');
});

// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cameraOptions, currentCameraCount, repeatsOverviewSummary, versionCoverageLabel } from '../src/lib/reports/cameras.ts';

const cameras = [
  { video: 'front-door.mp4', current: true, inVersion: true, valid: true },
  { video: 'rear-fence.mp4', current: false, inVersion: true, valid: true },
  { video: 'side-gate.mp4', current: true, inVersion: true, valid: false },
  { video: 'new-lot.mp4', current: true, inVersion: false, valid: false },
];

test('only current cameras with a valid report are selectable, the others say why', () => {
  const options = cameraOptions(cameras);
  assert.deepEqual(
    options.map((option) => [option.video, option.selectable, option.badge]),
    [
      ['front-door.mp4', true, null],
      ['rear-fence.mp4', false, 'removed'],
      ['side-gate.mp4', false, 'unavailable'],
      ['new-lot.mp4', false, 'not in this version'],
    ],
  );
  assert.match(options[1].reason, /removed/);
  assert.match(options[2].reason, /no valid report/);
  assert.match(options[3].reason, /not in this version.*Regenerate/);
  assert.equal(options[0].reason, null);
});

test('a video the version does not cover is listed disabled, not hidden', () => {
  const options = cameraOptions(cameras.slice(0, 1).concat(cameras.slice(3)));
  assert.equal(options.length, 2);
  assert.equal(options[1].selectable, false);
});

test('the covered count only counts current videos the version holds', () => {
  assert.equal(currentCameraCount(cameras), 2);
});

test('the overview badge reads "N of M videos in vK"', () => {
  assert.equal(versionCoverageLabel(2, 3, 3), '2 of 3 videos in v3');
  assert.equal(versionCoverageLabel(1, 1, 1), '1 of 1 video in v1');
});

test('a single-camera incident does not repeat the overview summary in the camera report', () => {
  assert.equal(repeatsOverviewSummary(cameras.slice(0, 1), 'A man enters.', 'A man enters. '), true);
  assert.equal(repeatsOverviewSummary(cameras, 'A man enters.', 'A man enters.'), false);
  assert.equal(repeatsOverviewSummary(cameras.slice(0, 1), 'A man enters.', 'A man leaves.'), false);
  assert.equal(repeatsOverviewSummary(cameras.slice(0, 1), null, 'A man enters.'), false);
  assert.equal(repeatsOverviewSummary(cameras.slice(0, 1), 'A man enters.', null), false);
});

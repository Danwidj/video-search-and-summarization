// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cameraOptions, currentCameraCount, showCameraSwitcher } from '../src/lib/reports/cameras.ts';

const cameras = [
  { video: 'front-door.mp4', current: true, valid: true },
  { video: 'rear-fence.mp4', current: false, valid: true },
  { video: 'side-gate.mp4', current: true, valid: false },
];

test('only current cameras with a valid report are selectable, the others say why', () => {
  const options = cameraOptions(cameras);
  assert.deepEqual(
    options.map((option) => [option.video, option.selectable]),
    [
      ['front-door.mp4', true],
      ['rear-fence.mp4', false],
      ['side-gate.mp4', false],
    ],
  );
  assert.match(options[1].reason, /removed/);
  assert.match(options[2].reason, /no valid report/);
  assert.equal(options[0].reason, null);
});

test('the switcher shows for more than one camera and counts current cameras', () => {
  assert.equal(showCameraSwitcher(cameras.slice(0, 1)), false);
  assert.equal(showCameraSwitcher(cameras), true);
  assert.equal(currentCameraCount(cameras), 2);
});

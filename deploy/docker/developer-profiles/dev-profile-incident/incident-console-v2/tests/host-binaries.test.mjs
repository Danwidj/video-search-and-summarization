// SPDX-License-Identifier: Apache-2.0

// The ffmpeg and ffprobe resolver: the order is override, then the npm-bundled file when it exists, then the bare name
// for PATH. Fakes stand in for the environment and the filesystem; no real binary runs here.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { resolveHostBinary } = await import('../src/lib/video/host-binaries.ts');

const sources = ({ env = {}, bundled = {}, present = [] } = {}) => ({
  env,
  bundled: { ffmpeg: null, ffprobe: null, ...bundled },
  exists: (path) => present.includes(path),
});

test('an explicit override wins, even when the bundled copy exists', () => {
  const resolved = resolveHostBinary(
    'ffmpeg',
    sources({ env: { FFMPEG_PATH: '/opt/ff/ffmpeg' }, bundled: { ffmpeg: '/bundle/ffmpeg' }, present: ['/bundle/ffmpeg'] }),
  );
  assert.equal(resolved, '/opt/ff/ffmpeg');
});

test('FFPROBE_PATH overrides ffprobe only', () => {
  const env = { FFPROBE_PATH: '/opt/ff/ffprobe', FFMPEG_PATH: '/opt/ff/ffmpeg' };
  assert.equal(resolveHostBinary('ffprobe', sources({ env })), '/opt/ff/ffprobe');
  assert.equal(resolveHostBinary('ffmpeg', sources({ env })), '/opt/ff/ffmpeg');
});

test('the bundled copy is used when its file exists and no override is set', () => {
  const resolved = resolveHostBinary('ffprobe', sources({ bundled: { ffprobe: '/bundle/ffprobe' }, present: ['/bundle/ffprobe'] }));
  assert.equal(resolved, '/bundle/ffprobe');
});

test('a bundled path that does not exist falls back to the bare name for PATH', () => {
  assert.equal(resolveHostBinary('ffmpeg', sources({ bundled: { ffmpeg: '/bundle/ffmpeg' } })), 'ffmpeg');
});

test('no bundled copy for the platform (null) falls back to the bare name', () => {
  assert.equal(resolveHostBinary('ffmpeg', sources({ bundled: { ffmpeg: null } })), 'ffmpeg');
});

test('an empty override is ignored', () => {
  assert.equal(resolveHostBinary('ffmpeg', sources({ env: { FFMPEG_PATH: '' } })), 'ffmpeg');
});

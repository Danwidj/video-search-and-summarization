// SPDX-License-Identifier: Apache-2.0

// The upload conversion with a fake ffprobe and ffmpeg runner: the pass-through
// rule, the conversion arguments (video only, no audio), temp file cleanup on
// failure and the error messages. No real binary runs here.

import assert from 'node:assert/strict';
import { mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { register } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { CommandMissingError } = await import('../src/lib/video/command.ts');
const { TranscodeError, ffmpegTranscodeArguments, ffprobeArguments, isStoredFormat, parseProbe, prepareUpload } = await import(
  '../src/lib/video/transcode.ts'
);

const probeJson = ({ brand = 'isom', codec = 'h264', pixFmt = 'yuv420p', audio = 1 } = {}) =>
  JSON.stringify({
    streams: [
      { codec_type: 'video', codec_name: codec, pix_fmt: pixFmt, width: 3840, height: 2160, r_frame_rate: '30000/1001' },
      ...Array.from({ length: audio }, () => ({ codec_type: 'audio', codec_name: 'aac' })),
      { codec_type: 'data' },
    ],
    format: { duration: '23.851667', tags: { major_brand: brand } },
  });

test('parseProbe reads the first video stream, the brand, the length and counts audio streams', () => {
  const probe = parseProbe(probeJson({ brand: 'qt  ', codec: 'hevc', pixFmt: 'yuv420p10le', audio: 2 }));
  assert.deepEqual(probe, {
    majorBrand: 'qt  ',
    codec: 'hevc',
    pixelFormat: 'yuv420p10le',
    width: 3840,
    height: 2160,
    frameRate: '30000/1001',
    durationSeconds: 23.851667,
    audioStreams: 2,
  });
  assert.throws(() => parseProbe('{"streams":[{"codec_type":"audio"}]}'), /no video stream/);
  assert.throws(() => parseProbe('not json'), /did not describe the file as a video/);
  assert.ok(ffprobeArguments('/tmp/in').includes('json'));
});

test('only an ISO MP4 holding 8-bit yuv420p H.264 is stored untouched', () => {
  assert.equal(isStoredFormat(parseProbe(probeJson())), true, 'isom + h264 + yuv420p passes through');
  assert.equal(isStoredFormat(parseProbe(probeJson({ brand: 'mp42', audio: 0 }))), true);
  assert.equal(isStoredFormat(parseProbe(probeJson({ brand: 'qt  ' }))), false, 'a QuickTime .mov is converted even when H.264');
  assert.equal(isStoredFormat(parseProbe(probeJson({ codec: 'hevc' }))), false, 'HEVC is converted');
  assert.equal(isStoredFormat(parseProbe(probeJson({ pixFmt: 'yuv420p10le' }))), false, '10-bit H.264 is converted');
  assert.equal(isStoredFormat(parseProbe(probeJson({ pixFmt: 'yuv422p' }))), false, '4:2:2 is converted');
  assert.equal(isStoredFormat(parseProbe(probeJson({ brand: '' }))), false, 'no brand (webm, mkv) is converted');
});

test('the conversion keeps only the first video stream, drops audio and keeps size and rate', () => {
  const args = ffmpegTranscodeArguments('/tmp/in', '/tmp/out.mp4');
  const after = (flag) => args[args.indexOf(flag) + 1];
  assert.equal(after('-i'), '/tmp/in');
  assert.equal(after('-map'), '0:v:0');
  assert.ok(args.includes('-an'), 'no audio track, ever');
  assert.equal(after('-c:v'), 'libx264');
  assert.equal(after('-preset'), 'veryfast');
  assert.equal(after('-crf'), '20');
  assert.equal(after('-pix_fmt'), 'yuv420p');
  assert.equal(after('-movflags'), '+faststart');
  assert.equal(args.at(-1), '/tmp/out.mp4');
  for (const flag of ['-vf', '-s', '-r', '-c:a', '-filter:v']) assert.equal(args.includes(flag), false, `${flag} would change the picture`);
});

let tmpRoot;
let calls;
beforeEach(async () => {
  tmpRoot = await mkdtemp(path.join(tmpdir(), 'transcode-test-'));
  calls = [];
});
afterEach(() => rm(tmpRoot, { recursive: true, force: true }));

/** A fake ffprobe/ffmpeg: the probe answer comes from the input file's own text, ffmpeg writes `ffmpeg.ffmpeg` into the output. */
function fakeRunner({ ffmpegExit = 0, ffmpegStderr = '' } = {}) {
  return async (command, args) => {
    calls.push({ command, args });
    if (command === 'ffprobe') {
      const kind = (await readFile(args.at(-1), 'utf8')).trim();
      if (kind === 'broken')
        return { code: 1, stdout: '', stderr: 'moov atom not found\nInvalid data found when processing input', timedOut: false };
      return {
        code: 0,
        stdout: kind === 'hevc' ? probeJson({ brand: 'qt  ', codec: 'hevc', pixFmt: 'yuv420p10le' }) : probeJson(),
        stderr: '',
        timedOut: false,
      };
    }
    if (ffmpegExit === 0) await writeFile(args.at(-1), 'converted-bytes');
    return { code: ffmpegExit, stdout: '', stderr: ffmpegStderr, timedOut: false };
  };
}

const blob = (text) => new Blob([text], { type: 'video/quicktime' });

test('an H.264 MP4 is stored as uploaded: ffmpeg never runs and the file is the original', async () => {
  const prepared = await prepareUpload(blob('h264'), { run: fakeRunner(), tmpRoot });
  assert.equal(prepared.converted, false);
  assert.equal(prepared.size, 4);
  assert.equal(await readFile(prepared.path, 'utf8'), 'h264');
  assert.deepEqual(
    calls.map((call) => call.command),
    ['ffprobe'],
  );
  await prepared.cleanup();
  assert.deepEqual(await readdir(tmpRoot), [], 'cleanup removes the temporary directory');
});

test('anything else is converted into a temporary MP4 that cleanup removes', async () => {
  const prepared = await prepareUpload(blob('hevc'), { run: fakeRunner(), tmpRoot });
  assert.equal(prepared.converted, true);
  assert.ok(prepared.path.endsWith('output.mp4'));
  assert.equal(prepared.size, 'converted-bytes'.length);
  assert.equal(prepared.probe.codec, 'hevc');
  assert.deepEqual(
    calls.map((call) => call.command),
    ['ffprobe', 'ffmpeg'],
  );
  assert.deepEqual(calls[1].args.slice(calls[1].args.indexOf('-map')), ffmpegTranscodeArguments('x', prepared.path).slice(6));
  await prepared.cleanup();
  await prepared.cleanup();
  assert.deepEqual(await readdir(tmpRoot), []);
});

test('when ffmpeg rejects the file the temporary files are removed and the message carries its last lines', async () => {
  await assert.rejects(
    prepareUpload(blob('hevc'), {
      run: fakeRunner({ ffmpegExit: 1, ffmpegStderr: 'frame=1\nError while decoding stream #0:0: Invalid data found' }),
      tmpRoot,
    }),
    (error) => {
      assert.ok(error instanceof TranscodeError);
      assert.equal(error.status, 422);
      assert.equal(error.message, 'ffmpeg could not convert the video: frame=1 Error while decoding stream #0:0: Invalid data found');
      return true;
    },
  );
  assert.deepEqual(await readdir(tmpRoot), [], 'nothing is left behind after a failed conversion');
});

test('a file ffprobe cannot read is refused with 422 and cleaned up', async () => {
  await assert.rejects(prepareUpload(blob('broken'), { run: fakeRunner(), tmpRoot }), {
    status: 422,
    message: 'ffprobe could not read the video: moov atom not found Invalid data found when processing input',
  });
  assert.deepEqual(await readdir(tmpRoot), []);
});

test('a missing binary is 503 with a clear message', async () => {
  const missing = async (command) => {
    throw new CommandMissingError(command);
  };
  await assert.rejects(prepareUpload(blob('h264'), { run: missing, tmpRoot }), {
    status: 503,
    message: 'ffprobe is not installed on the console host, so uploads cannot be converted',
  });
  assert.deepEqual(await readdir(tmpRoot), []);
});

test('a conversion that ran out of time is reported as such', async () => {
  const slow = async (command) => {
    if (command === 'ffprobe') return { code: 0, stdout: probeJson({ codec: 'hevc' }), stderr: '', timedOut: false };
    return { code: null, stdout: '', stderr: '', timedOut: true };
  };
  await assert.rejects(prepareUpload(blob('x'), { run: slow, tmpRoot }), { status: 422, message: /took longer than 25 minutes/ });
  assert.deepEqual(await readdir(tmpRoot), []);
});

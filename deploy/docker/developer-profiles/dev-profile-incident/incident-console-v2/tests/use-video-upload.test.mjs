// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { uploadVideo } = await import('../src/sections/analysis/hooks/use-video-upload.ts');

// Every request the upload makes, by method and path, whether through fetch or XMLHttpRequest.
let requests;
// The answer the fake gives to the R2 upload: [status, JSON body].
let r2Answer;
const originalFetch = globalThis.fetch;
const originalXhr = globalThis.XMLHttpRequest;

/** Just enough of XMLHttpRequest for the upload: progress, load, abort. */
class FakeXhr {
  upload = {};
  open(method, url) {
    this.method = method;
    this.url = url;
  }
  send(body) {
    requests.push({ method: this.method, url: this.url, body });
    this.pending = setTimeout(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
      this.upload.onload?.();
      [this.status, this.responseText] = [r2Answer[0], JSON.stringify(r2Answer[1])];
      this.onload?.();
    }, 0);
  }
  abort() {
    clearTimeout(this.pending);
    this.onabort?.();
  }
}

beforeEach(() => {
  requests = [];
  r2Answer = [200, { filePath: 'uploads/clip.mp4', name: 'clip.mp4' }];
  globalThis.XMLHttpRequest = FakeXhr;
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ method: init.method ?? 'GET', url: String(url), body: init.body });
    return new Response('{}', { status: 200 });
  };
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.XMLHttpRequest = originalXhr;
});

const clip = () => new File([new Uint8Array(10)], 'clip.mp4', { type: 'video/mp4' });

test('the video is uploaded once, straight to R2 through the console, and nothing goes to VST', async () => {
  const progress = [];
  const uploaded = await uploadVideo(clip(), new AbortController().signal, (value) => progress.push(value));

  assert.deepEqual(uploaded, { filePath: 'uploads/clip.mp4', filename: 'clip.mp4', converted: false });
  // Node has no <video> to capture a thumbnail from, so the R2 upload is the only request.
  assert.deepEqual(
    requests.map(({ method, url }) => `${method} ${url}`),
    ['POST /api/uploads/r2'],
  );
  const form = requests[0].body;
  assert.equal(form.get('filename'), 'clip.mp4');
  assert.equal(form.get('file').size, 10);
  assert.deepEqual(progress, [50, 100]);
});

test('a .MOV is sent under its .mp4 name, the converting callback fires once the bytes are up, and the answer says it was converted', async () => {
  r2Answer = [200, { filePath: 'uploads/IMG_9170.mp4', name: 'IMG_9170.mp4', converted: true }];
  const events = [];
  const mov = new File([new Uint8Array(10)], 'IMG_9170.MOV', { type: 'video/quicktime' });
  const uploaded = await uploadVideo(
    mov,
    new AbortController().signal,
    (value) => events.push(`progress ${value}`),
    () => events.push('uploaded'),
  );
  assert.deepEqual(uploaded, { filePath: 'uploads/IMG_9170.mp4', filename: 'IMG_9170.mp4', converted: true });
  assert.equal(requests[0].body.get('filename'), 'IMG_9170.mp4');
  assert.deepEqual(events, ['progress 50', 'uploaded', 'progress 100']);
});

test("a conversion the console refuses surfaces ffmpeg's message", async () => {
  r2Answer = [422, { error: 'ffmpeg could not convert the video: Invalid data found when processing input' }];
  await assert.rejects(
    uploadVideo(clip(), new AbortController().signal, () => {}),
    /ffmpeg could not convert the video: Invalid data found/,
  );
});

test('an R2 upload the console refuses surfaces its error', async () => {
  r2Answer = [413, { error: 'Video exceeds the R2 single-upload size limit' }];
  await assert.rejects(
    uploadVideo(clip(), new AbortController().signal, () => {}),
    /exceeds the R2 single-upload size limit/,
  );
});

test('an answer without a valid R2 key is refused', async () => {
  r2Answer = [200, { filePath: '/srv/vst/clip.mp4' }];
  await assert.rejects(
    uploadVideo(clip(), new AbortController().signal, () => {}),
    /Could not upload the video to R2/,
  );
});

test('cancelling stops the upload', async () => {
  const controller = new AbortController();
  const pending = uploadVideo(clip(), controller.signal, () => {});
  controller.abort();
  await assert.rejects(pending, /Upload was cancelled/);

  const cancelled = new AbortController();
  cancelled.abort();
  requests = [];
  await assert.rejects(
    uploadVideo(clip(), cancelled.signal, () => {}),
    /Upload was cancelled/,
  );
  assert.deepEqual(requests, [], 'nothing is sent once cancelled');
});

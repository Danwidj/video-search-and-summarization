// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { mock, test } from 'node:test';

import { isValidR2Key, thumbnailKeyForVideo } from '../lib/r2/key.ts';

register('./support/alias-loader.mjs', import.meta.url);

process.env.R2_ACCOUNT_ID = 'test-account';
process.env.R2_ACCESS_KEY = 'test-access-key';
process.env.R2_SECRET_KEY = 'test-secret-key';
process.env.R2_BUCKET = 'test-bucket';

const puts = [];
const heads = [];
let headContentLengthOverride;

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        if (command.constructor.name === 'HeadObjectCommand') {
          heads.push(command.input);
          return Promise.resolve({ ContentLength: headContentLengthOverride ?? puts.at(-1)?.ContentLength ?? 1 });
        }
        puts.push(command.input);
        return Promise.resolve({ ETag: '"fake-etag"' });
      }
    },
    PutObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    GetObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    HeadObjectCommand: class HeadObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    DeleteObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
  },
});

const { POST } = await import('../app/api/uploads/r2/route.ts');
const { POST: POST_THUMBNAIL } = await import('../app/api/uploads/thumbnail/route.ts');
const { putR2Video, MAX_R2_PUT_BYTES } = await import('../lib/r2/config.ts');
const { getServiceConfiguration } = await import('../lib/env.ts');

function multipartRequest(fields) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) form.append(key, value);
  }
  return new Request('http://localhost/api/uploads/r2', { method: 'POST', body: form });
}

test('rejects a request missing required fields', async () => {
  const response = await POST(multipartRequest({ sensorId: 'sensor-1' }));
  assert.equal(response.status, 400);
});

test('putR2Video refuses a body over the R2 single-upload cap before ever calling S3', async () => {
  puts.length = 0;
  await assert.rejects(
    () =>
      putR2Video(getServiceConfiguration(), 'uploads/sensor-1/clip.mp4', new ReadableStream(), 'video/mp4', MAX_R2_PUT_BYTES + 1),
    /exceeds the R2 single-upload size limit/,
  );
  assert.equal(puts.length, 0, 'an oversized upload must never reach S3Client.send');
});

test('uploads an attacker-controlled filename under a generated key, not the raw name', async () => {
  puts.length = 0;
  const bytes = new Uint8Array([1, 2, 3, 4]);
  const file = new Blob([bytes], { type: 'video/mp4' });
  const maliciousFilename = '../../../etc/passwd.mp4';

  const response = await POST(multipartRequest({ file, sensorId: 'sensor-42', filename: maliciousFilename }));
  assert.equal(response.status, 200);

  const payload = await response.json();
  assert.equal(isValidR2Key(payload.filePath), true, 'returned filePath must be a valid durable R2 key');
  assert.match(payload.filePath, /^uploads\/sensor-42\/[0-9a-f-]{36}\.mp4$/);
  assert.equal(payload.filePath.includes('etc'), false);
  assert.equal(payload.filePath.includes('passwd'), false);
  assert.equal(payload.filePath.includes('..'), false);

  assert.equal(puts.length, 1, 'the route must PUT the video to R2 exactly once');
  assert.equal(puts[0].Bucket, 'test-bucket');
  assert.equal(puts[0].Key, payload.filePath);
  assert.equal(puts[0].ContentType, 'video/mp4');
  assert.equal(puts[0].ContentLength, bytes.length);
  assert.equal(heads.length, 1, 'the route must verify the uploaded object exactly once');
  assert.equal(heads[0].Key, payload.filePath);
});

test('two uploads with the identical filename never collide on the same R2 key', async () => {
  puts.length = 0;
  heads.length = 0;
  const first = await POST(
    multipartRequest({ file: new Blob([new Uint8Array([1])], { type: 'video/mp4' }), sensorId: 'sensor-7', filename: 'video.mp4' }),
  );
  const second = await POST(
    multipartRequest({ file: new Blob([new Uint8Array([2])], { type: 'video/mp4' }), sensorId: 'sensor-7', filename: 'video.mp4' }),
  );
  const firstKey = (await first.json()).filePath;
  const secondKey = (await second.json()).filePath;
  assert.notEqual(firstKey, secondKey, 'identical filenames must not overwrite each other in R2');
  assert.equal(puts.length, 2);
});

test('reports a clear error when R2 is not configured', async () => {
  delete process.env.R2_ACCOUNT_ID;
  try {
    const file = new Blob([new Uint8Array([1])], { type: 'video/mp4' });
    const response = await POST(multipartRequest({ file, sensorId: 'sensor-1', filename: 'clip.mp4' }));
    assert.equal(response.status, 500);
    const payload = await response.json();
    assert.equal(payload.error, 'R2 is not configured');
  } finally {
    process.env.R2_ACCOUNT_ID = 'test-account';
  }
});

test('does not return an R2 key when object verification reports an empty upload', async () => {
  headContentLengthOverride = 0;
  try {
    const file = new Blob([new Uint8Array([1])], { type: 'video/mp4' });
    const response = await POST(multipartRequest({ file, sensorId: 'sensor-empty', filename: 'clip.mp4' }));
    assert.equal(response.status, 500);
    assert.match((await response.json()).error, /empty or has no content length/);
  } finally {
    headContentLengthOverride = undefined;
  }
});

test('uploads a small image to the deterministic thumbnail key', async () => {
  puts.length = 0;
  heads.length = 0;
  const videoKey = 'uploads/sensor-1/video.mp4';
  const file = new Blob([new Uint8Array([1, 2, 3])], { type: 'image/webp' });
  const response = await POST_THUMBNAIL(multipartRequest({ file, videoKey }));
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.thumbnailKey, thumbnailKeyForVideo(videoKey));
  assert.equal(puts[0].Key, 'thumbnails/uploads/sensor-1/video.mp4.webp');
  assert.equal(puts[0].ContentType, 'image/webp');
  assert.equal(heads[0].Key, puts[0].Key);
});

test('thumbnail upload rejects non-image content', async () => {
  const response = await POST_THUMBNAIL(multipartRequest({
    file: new Blob([new Uint8Array([1])], { type: 'video/mp4' }),
    videoKey: 'uploads/sensor-1/video.mp4',
  }));
  assert.equal(response.status, 415);
});

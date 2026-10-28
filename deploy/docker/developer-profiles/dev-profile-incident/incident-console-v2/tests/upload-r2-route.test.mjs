// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { mock, test } from 'node:test';

import { isValidR2Key, thumbnailKeyForVideo } from '../src/lib/r2/key.ts';

register('./support/alias-loader.mjs', import.meta.url);

process.env.R2_ACCOUNT_ID = 'test-account';
process.env.R2_ACCESS_KEY = 'test-access-key';
process.env.R2_SECRET_KEY = 'test-secret-key';
process.env.R2_BUCKET = 'test-bucket';

const puts = [];
const heads = [];
const stored = new Map();
let headContentLengthOverride;
const awsError = (name, httpStatusCode) => Object.assign(new Error(name), { name, $metadata: { httpStatusCode } });

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        if (command.constructor.name === 'HeadObjectCommand') {
          heads.push(command.input);
          if (!stored.has(command.input.Key)) return Promise.reject(awsError('NotFound', 404));
          return Promise.resolve({ ContentLength: headContentLengthOverride ?? stored.get(command.input.Key) });
        }
        puts.push(command.input);
        if (command.input.IfNoneMatch === '*' && stored.has(command.input.Key)) return Promise.reject(awsError('PreconditionFailed', 412));
        stored.set(command.input.Key, command.input.ContentLength);
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

const { POST } = await import('../src/app/api/uploads/r2/route.ts');
const { POST: CHECK } = await import('../src/app/api/uploads/check/route.ts');
const { POST: POST_THUMBNAIL } = await import('../src/app/api/uploads/thumbnail/route.ts');
const { putR2Video, MAX_R2_PUT_BYTES } = await import('../src/lib/r2/config.ts');
const { getServiceConfiguration } = await import('../src/lib/env.ts');

function multipartRequest(fields) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) form.append(key, value);
  }
  return new Request('http://localhost/api/uploads/r2', { method: 'POST', body: form });
}

test('rejects a request missing required fields', async () => {
  const response = await POST(multipartRequest({ filename: 'clip.mp4' }));
  assert.equal(response.status, 400);
});

test('putR2Video refuses a body over the R2 single-upload cap before ever calling S3', async () => {
  puts.length = 0;
  await assert.rejects(
    () => putR2Video(getServiceConfiguration(), 'uploads/clip.mp4', new ReadableStream(), 'video/mp4', MAX_R2_PUT_BYTES + 1),
    /exceeds the R2 single-upload size limit/,
  );
  assert.equal(puts.length, 0, 'an oversized upload must never reach S3Client.send');
});

const mp4 = (...bytes) => new Blob([new Uint8Array(bytes)], { type: 'video/mp4' });
const check = (filename) =>
  CHECK(new Request('http://localhost/api/uploads/check', { method: 'POST', body: JSON.stringify({ filename }) }));

test('keeps a clean file name as the key and never adds an id', async () => {
  puts.length = 0;
  stored.clear();
  const response = await POST(multipartRequest({ file: mp4(1, 2, 3, 4), filename: 'Lobby_camera 2.mp4' }));
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.filePath, 'uploads/Lobby_camera_2.mp4', 'a space is the one change, and it is reported by the check route');
  assert.equal(isValidR2Key(payload.filePath), true);
  assert.equal(puts.length, 1, 'the route must PUT the video to R2 exactly once');
  assert.equal(puts[0].Key, payload.filePath);
  assert.equal(puts[0].IfNoneMatch, '*', 'R2 itself refuses to replace an existing object');
  assert.equal(puts[0].ContentLength, 4);
  assert.equal(heads.at(-1).Key, payload.filePath, 'the stored object is verified');
});

test('an attacker-controlled filename cannot leave the uploads folder', async () => {
  puts.length = 0;
  stored.clear();
  const response = await POST(multipartRequest({ file: mp4(1), filename: '../../../etc/passwd.mp4' }));
  const { filePath } = await response.json();
  assert.equal(filePath, 'uploads/passwd.mp4');
  assert.equal(filePath.includes('..'), false);
});

test('a second upload of the same name is stored as name-2, name-3 and the first is never overwritten', async () => {
  puts.length = 0;
  stored.clear();
  const keys = [];
  for (const byte of [1, 2, 3]) {
    const response = await POST(multipartRequest({ file: mp4(byte), filename: 'video.mp4' }));
    assert.equal(response.status, 200);
    keys.push((await response.json()).filePath);
  }
  assert.deepEqual(keys, ['uploads/video.mp4', 'uploads/video-2.mp4', 'uploads/video-3.mp4']);
  assert.deepEqual(
    puts.map((put) => put.Key),
    keys,
  );
});

test('a name taken between the check and the write is refused with 409, not overwritten', async () => {
  puts.length = 0;
  stored.clear();
  const realHead = stored.has.bind(stored);
  let probes = 0;
  stored.has = (key) => (key === 'uploads/race.mp4' && probes++ === 0 ? false : realHead(key));
  stored.set('uploads/race.mp4', 9);
  try {
    const response = await POST(multipartRequest({ file: mp4(1), filename: 'race.mp4' }));
    assert.equal(response.status, 409);
    assert.equal(stored.get('uploads/race.mp4'), 9);
  } finally {
    stored.has = realHead;
  }
});

test('the check route reports a duplicate, unsafe characters and truncation without writing', async () => {
  puts.length = 0;
  stored.clear();
  stored.set('uploads/clip.mp4', 1);
  const duplicate = await (await check('clip.mp4')).json();
  assert.deepEqual(
    [duplicate.exists, duplicate.name, duplicate.key, duplicate.existingName, duplicate.unsafeChars, duplicate.truncated],
    [true, 'clip-2.mp4', 'uploads/clip-2.mp4', 'clip.mp4', [], false],
  );
  const unsafe = await (await check('my clip #1.mp4')).json();
  assert.deepEqual([unsafe.exists, unsafe.name, unsafe.unsafeChars], [false, 'my_clip__1.mp4', ['space', '#']]);
  const long = await (await check(`${'a'.repeat(300)}.mp4`)).json();
  assert.deepEqual([long.truncated, long.name.length, long.name.endsWith('.mp4')], [true, 150, true]);
  assert.equal(puts.length, 0, 'a check writes nothing');
  assert.equal((await check('   ')).status, 400);
});

test('reports a clear error when R2 is not configured', async () => {
  delete process.env.R2_ACCOUNT_ID;
  try {
    const file = new Blob([new Uint8Array([1])], { type: 'video/mp4' });
    const response = await POST(multipartRequest({ file, filename: 'clip.mp4' }));
    assert.equal(response.status, 500);
    const payload = await response.json();
    assert.equal(payload.error, 'R2 is not configured');
  } finally {
    process.env.R2_ACCOUNT_ID = 'test-account';
  }
});

test('does not return an R2 key when object verification reports an empty upload', async () => {
  stored.clear();
  headContentLengthOverride = 0;
  try {
    const file = new Blob([new Uint8Array([1])], { type: 'video/mp4' });
    const response = await POST(multipartRequest({ file, filename: 'empty.mp4' }));
    assert.equal(response.status, 500);
    assert.match((await response.json()).error, /empty or has no content length/);
  } finally {
    headContentLengthOverride = undefined;
  }
});

test('uploads a small image to the deterministic thumbnail key', async () => {
  puts.length = 0;
  heads.length = 0;
  const videoKey = 'uploads/video.mp4';
  const file = new Blob([new Uint8Array([1, 2, 3])], { type: 'image/webp' });
  const response = await POST_THUMBNAIL(multipartRequest({ file, videoKey }));
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.thumbnailKey, thumbnailKeyForVideo(videoKey));
  assert.equal(puts[0].Key, 'thumbnails/uploads/video.mp4.webp');
  assert.equal(puts[0].ContentType, 'image/webp');
  assert.equal(heads[0].Key, puts[0].Key);
  assert.equal(puts[0].IfNoneMatch, undefined, 'a thumbnail may be regenerated');
});

test('thumbnail upload rejects non-image content', async () => {
  const response = await POST_THUMBNAIL(
    multipartRequest({
      file: new Blob([new Uint8Array([1])], { type: 'video/mp4' }),
      videoKey: 'uploads/video.mp4',
    }),
  );
  assert.equal(response.status, 415);
});

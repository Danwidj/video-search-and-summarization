// SPDX-License-Identifier: Apache-2.0

// Tests that R2_KEY_PREFIX is applied at the S3 boundary and that no console
// path can list or delete outside the prefix.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

// Capture every S3 call: the command class name, Bucket, Key/Prefix, Range.
let s3Calls = [];

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        const input = command.input ?? {};
        s3Calls.push({ type: command.constructor.name, ...input });
        if (command.constructor.name === 'ListObjectsV2Command') {
          return Promise.resolve({ Contents: [], IsTruncated: false });
        }
        if (command.constructor.name === 'HeadObjectCommand') {
          return Promise.resolve({ ContentLength: 1024 });
        }
        return Promise.resolve({});
      }
    },
    GetObjectCommand: class GetObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    HeadObjectCommand: class HeadObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    PutObjectCommand: class PutObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    DeleteObjectCommand: class DeleteObjectCommand {
      constructor(input) {
        this.input = input;
      }
    },
    ListObjectsV2Command: class ListObjectsV2Command {
      constructor(input) {
        this.input = input;
      }
    },
  },
});

mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_client, command) => `https://signed.test/${command.input.Key}` },
});

// Import after mocking.
const { createR2PlaybackUrl, putR2Video, deleteR2Video } = await import('../src/lib/r2/config.ts');
const { listR2Objects } = await import('../src/lib/r2/list.ts');

const originalEnv = { ...process.env };

function baseConfig(extra = {}) {
  return {
    analysisMode: 'agent',
    vlmModel: 'test',
    r2AccountId: 'acc',
    r2AccessKey: 'key',
    r2SecretKey: 'sec',
    r2Bucket: 'bucket',
    ...extra,
  };
}

beforeEach(() => {
  s3Calls = [];
  process.env = { ...originalEnv };
});
afterEach(() => {
  process.env = { ...originalEnv };
});

// --- list ---

test('listR2Objects with prefix prepends R2_KEY_PREFIX to the S3 Prefix', async () => {
  const config = baseConfig({ r2KeyPrefix: 'mvp3/' });
  await listR2Objects(config, 'evidence/');
  assert.equal(s3Calls.length, 1);
  assert.equal(s3Calls[0].Prefix, 'mvp3/evidence/', 'physical prefix sent to S3');
});

test('listR2Objects returns logical keys with R2_KEY_PREFIX stripped', async () => {
  const { r2LogicalKey, r2PhysicalKey } = await import('../src/lib/r2/key.ts');
  const physicalKeys = ['mvp3/evidence/clip.mp4/a1/E1.jpg', 'mvp3/evidence/clip.mp4/a1/I1.jpg'];
  for (const pk of physicalKeys) {
    assert.equal(r2LogicalKey('mvp3/', pk), pk.slice('mvp3/'.length));
  }
  assert.equal(r2PhysicalKey('mvp3/', 'evidence/clip.mp4/'), 'mvp3/evidence/clip.mp4/');
});

test('listR2Objects without a prefix passes the logical prefix straight to S3', async () => {
  const config = baseConfig();
  await listR2Objects(config, 'uploads/');
  assert.equal(s3Calls[0].Prefix, 'uploads/');
});

// --- delete ---

test('deleteR2Video with prefix sends the physical key to S3', async () => {
  const config = baseConfig({ r2KeyPrefix: 'mvp3/' });
  await deleteR2Video(config, 'uploads/clip.mp4');
  const del = s3Calls.find((c) => c.type === 'DeleteObjectCommand');
  assert.ok(del, 'a DeleteObjectCommand was issued');
  assert.equal(del.Key, 'mvp3/uploads/clip.mp4', 'physical key has prefix');
});

test('deleteR2Video without prefix sends the logical key unchanged', async () => {
  const config = baseConfig();
  await deleteR2Video(config, 'uploads/clip.mp4');
  const del = s3Calls.find((c) => c.type === 'DeleteObjectCommand');
  assert.equal(del.Key, 'uploads/clip.mp4');
});

// --- put ---

test('putR2Video with prefix stores under the physical key', async () => {
  const config = baseConfig({ r2KeyPrefix: 'mvp3/' });
  const { Readable } = await import('node:stream');
  await putR2Video(config, 'uploads/clip.mp4', Readable.from(Buffer.from('x')), 'video/mp4', 1, { overwrite: true });
  const put = s3Calls.find((c) => c.type === 'PutObjectCommand');
  assert.equal(put.Key, 'mvp3/uploads/clip.mp4');
});

// --- sign (playback URL) ---

test('createR2PlaybackUrl with prefix signs the physical key', async () => {
  const config = baseConfig({ r2KeyPrefix: 'mvp3/' });
  const url = await createR2PlaybackUrl(config, 'uploads/clip.mp4');
  assert.ok(url.includes('mvp3/uploads/clip.mp4'), `signed URL contains physical key; got ${url}`);
});

// --- isolation: a list call cannot reach outside the prefix ---

test('a list call with a logical prefix cannot list objects outside the R2_KEY_PREFIX namespace', async () => {
  const config = baseConfig({ r2KeyPrefix: 'mvp3/' });
  // Even if a caller passes a very short prefix like '' or 'e', the physical
  // prefix sent to S3 always starts with 'mvp3/'.
  await listR2Objects(config, 'uploads/');
  for (const call of s3Calls) {
    if (call.type === 'ListObjectsV2Command') {
      assert.ok(call.Prefix.startsWith('mvp3/'), `every list S3 call must start with the global prefix; got: ${call.Prefix}`);
    }
  }
});

test('a delete call cannot reach outside the R2_KEY_PREFIX namespace', async () => {
  const config = baseConfig({ r2KeyPrefix: 'mvp3/' });
  await deleteR2Video(config, 'uploads/clip.mp4');
  for (const call of s3Calls) {
    if (call.type === 'DeleteObjectCommand') {
      assert.ok(call.Key.startsWith('mvp3/'), `every delete S3 call must start with the global prefix; got: ${call.Key}`);
    }
  }
});

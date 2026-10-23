// SPDX-License-Identifier: Apache-2.0

// A cropped image held in the browser until Save: which draft items need an upload, how their R2 keys replace the pending JPEGs, and the upload call.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { editFromDraft, pendingImages, withUploadedImages } = await import('../src/modules/reports/domain/edit-draft.ts');
const { uploadEvidenceImage } = await import('../src/lib/evidence/evidence-image-upload.ts');

const crop = new Blob(['jpeg'], { type: 'image/jpeg' });
const draft = () => ({
  incident: { type: 'burglary', start_timestamp: 0, end_timestamp: 10, description: 'A break-in.', severity_level: 3 },
  entities: [{ key: 'entity-0', sourceId: 'E1', timestampSeconds: 2, label: 'person', image: 'evidence/v1/old/E1.jpg', imageUrl: 'https://signed/old', pendingImage: null, imageTimestampSeconds: null, imageBox: null, type: 'human', description: 'Man in a hat.', firstSeenSeconds: 1, lastSeenSeconds: 5 }],
  instruments: [],
  assets: [{ key: 'asset-0', sourceId: 'A1', timestampSeconds: 3, label: 'bag', image: null, imageUrl: 'blob:preview', pendingImage: crop, imageTimestampSeconds: 3, imageBox: [1, 2, 3, 4], name: 'bag', description: 'Black bag.' }],
});

test('only the crops still held in the browser need an upload, under their item keys', () => {
  const pending = pendingImages(draft());
  assert.deepEqual(pending.map((p) => p.itemId), ['asset-0']);
  assert.equal(pending[0].blob, crop);
});

test('the uploaded R2 key replaces the pending JPEG and the other items are left as they were', () => {
  const before = draft();
  const saved = withUploadedImages(before, new Map([['asset-0', 'evidence/v1/uuid/asset-0.jpg']]));
  assert.equal(saved.assets[0].image, 'evidence/v1/uuid/asset-0.jpg');
  assert.equal(saved.assets[0].pendingImage, null);
  assert.equal(saved.entities[0], before.entities[0], 'an item without a pending crop is the same object');
  assert.deepEqual(pendingImages(saved), []);
  assert.equal(editFromDraft(saved).assets[0].image, 'evidence/v1/uuid/asset-0.jpg', 'the edit Save sends carries the key');
});

test('before the upload the edit would send no image, so Save must upload first', () => {
  assert.equal(editFromDraft(draft()).assets[0].image, null);
});

test('the crop is posted as a file under its item key and the key the server wrote is returned', async () => {
  const originalFetch = globalThis.fetch;
  const sent = [];
  globalThis.fetch = async (url, init) => {
    sent.push({ url, init });
    return new Response(JSON.stringify({ image: 'evidence/v1/uuid/asset-0.jpg' }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    assert.equal(await uploadEvidenceImage('v 1', 'asset-0', crop), 'evidence/v1/uuid/asset-0.jpg');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(sent[0].url, '/api/reports/v%201/evidence-image');
  assert.equal(sent[0].init.method, 'POST');
  assert.equal(sent[0].init.body.get('itemId'), 'asset-0');
  assert.equal(sent[0].init.body.get('file').name, 'asset-0.jpg');
});

test('a refused upload throws the server reason so Save stops before the revision is written', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ error: 'The image must be between 1 byte and 5 MB' }), { status: 413, headers: { 'content-type': 'application/json' } });
  try {
    await assert.rejects(uploadEvidenceImage('v1', 'asset-0', crop), /between 1 byte and 5 MB/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

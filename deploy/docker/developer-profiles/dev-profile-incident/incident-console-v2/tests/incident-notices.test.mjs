// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import { createNoticeStore, incidentScope } from '../src/lib/reports/incident-notices.ts';

const memoryStorage = () => {
  const map = new Map();
  return {
    map,
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => void map.set(key, value),
    removeItem: (key) => void map.delete(key),
  };
};

const notice = { title: 'Merged into Incident 2', detail: 'Incident 2 now holds 2 videos.', keptIncidentId: 2 };

test('a notice is kept per scope and read back as the same object until it changes', () => {
  const store = createNoticeStore(memoryStorage());
  assert.equal(store.get(incidentScope(2)), null);
  store.set(incidentScope(2), notice);
  assert.equal(store.get(incidentScope(2)), store.get(incidentScope(2)));
  assert.deepEqual(store.get(incidentScope(2)), notice);
  assert.equal(store.get(incidentScope(3)), null);
});

test('a notice survives a page change: a new store on the same storage still has it', () => {
  const storage = memoryStorage();
  createNoticeStore(storage).set(incidentScope(2), notice);
  assert.deepEqual(createNoticeStore(storage).get(incidentScope(2)), notice);
});

test('clearing removes it from the store and the storage, and tells the listeners', () => {
  const storage = memoryStorage();
  const store = createNoticeStore(storage);
  let heard = 0;
  store.subscribe(() => heard++);
  store.set(incidentScope(2), notice);
  store.clear(incidentScope(2));
  assert.equal(store.get(incidentScope(2)), null);
  assert.equal(storage.map.size, 0);
  assert.equal(heard, 2);
  store.clear(incidentScope(2));
  assert.equal(heard, 2, 'clearing nothing is not a change');
});

test('a newer decision replaces the older notice', () => {
  const store = createNoticeStore(memoryStorage());
  store.set('library', notice);
  store.set('library', { title: 'Match rejected', detail: 'x' });
  assert.equal(store.get('library').title, 'Match rejected');
});

test('without storage, or with storage that throws or holds junk, the notice still works in memory', () => {
  const memoryOnly = createNoticeStore(null);
  memoryOnly.set('library', notice);
  assert.deepEqual(memoryOnly.get('library'), notice);

  const broken = createNoticeStore({
    getItem: () => {
      throw new Error('blocked');
    },
    setItem: () => {
      throw new Error('blocked');
    },
    removeItem: () => {
      throw new Error('blocked');
    },
  });
  assert.equal(broken.get('library'), null);
  broken.set('library', notice);
  assert.deepEqual(broken.get('library'), notice);
  broken.clear('library');
  assert.equal(broken.get('library'), null);

  const junk = memoryStorage();
  junk.map.set('incident-notice:library', '{"title":1}');
  assert.equal(createNoticeStore(junk).get('library'), null);
});

// SPDX-License-Identifier: Apache-2.0

// The orphan sweep with fakes only: no R2, no database. The rule under test is
// that a key any revision or evidence_crops row names is never removed.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { sweepOrphanEvidence, DEFAULT_SWEEP_AGE_HOURS, MIN_SWEEP_AGE_HOURS } = await import('../src/modules/reports/application/sweep-orphan-evidence/index.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');

const NOW = new Date('2026-10-24T12:00:00Z');
const hoursAgo = (hours) => new Date(NOW.getTime() - hours * 3_600_000);
const OLD = hoursAgo(DEFAULT_SWEEP_AGE_HOURS + 1);
const VIDEO = 'v-1';

/** An object store over a map of key -> lastModified; records every call in order. */
function fakeStore(objects, { failRemoveOf = [] } = {}) {
  const calls = [];
  return {
    calls,
    objects: new Map(Object.entries(objects)),
    async list(prefix) {
      calls.push(`list ${prefix}`);
      return [...this.objects].filter(([key]) => key.startsWith(prefix)).map(([key, lastModified]) => ({ key, lastModified }));
    },
    async remove(key) {
      calls.push(`remove ${key}`);
      if (failRemoveOf.includes(key)) throw new Error(`cannot remove ${key}`);
      this.objects.delete(key);
    },
  };
}

/** An incident port answering with fixed references (null: unknown video); records when it is read. */
const fakeIncidents = (references, calls = []) => ({
  async listReferencedEvidenceImages(videoId) {
    calls.push(`references ${videoId}`);
    if (references instanceof Error) throw references;
    return references;
  },
});

const sweep = (references, store, options = {}) => sweepOrphanEvidence(fakeIncidents(references, store.calls), store, VIDEO, { now: NOW, ...options });
const removals = (store) => store.calls.filter((call) => call.startsWith('remove '));

describe('sweepOrphanEvidence', () => {
  test('a dry run, the default, reports the orphans and removes nothing', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': OLD, 'evidence/v-1/b/E1.jpg': OLD });
    const report = await sweep(['evidence/v-1/a/E1.jpg'], store);
    assert.equal(report.dryRun, true);
    assert.deepEqual(report.orphans, ['evidence/v-1/b/E1.jpg']);
    assert.deepEqual([report.scanned, report.referenced, report.removed], [2, 1, []]);
    assert.deepEqual(removals(store), []);
    assert.equal(store.objects.size, 2);
  });

  test('with dryRun false it removes the old unreferenced objects and nothing else', async () => {
    const store = fakeStore({
      'evidence/v-1/kept/E1.jpg': OLD,
      'evidence/v-1/orphan-1/E1.jpg': OLD,
      'evidence/v-1/orphan-2/A1.jpg': OLD,
    });
    const report = await sweep(['evidence/v-1/kept/E1.jpg'], store, { dryRun: false });
    assert.deepEqual(report.removed, ['evidence/v-1/orphan-1/E1.jpg', 'evidence/v-1/orphan-2/A1.jpg']);
    assert.deepEqual([...store.objects.keys()], ['evidence/v-1/kept/E1.jpg']);
  });

  test('never removes a referenced key, however old: every kind of reference, older revisions included', async () => {
    const objects = {
      'evidence/v-1/run-1/entities/E1.jpg': OLD, // the AI revision's crop, replaced since by a later revision
      'evidence/v-1/run-1/entities/E2.jpg': OLD, // named only by an evidence_crops row
      'evidence/v-1/u-1/E1.jpg': OLD, // the latest human revision's upload
      'evidence/v-1/u-2/A1.jpg': OLD, // an orphan
    };
    const store = fakeStore(objects);
    const references = ['evidence/v-1/run-1/entities/E1.jpg', 'evidence/v-1/run-1/entities/E2.jpg', 'evidence/v-1/u-1/E1.jpg'];
    const report = await sweep(references, store, { dryRun: false, minAgeHours: MIN_SWEEP_AGE_HOURS });
    assert.deepEqual(report.orphans, ['evidence/v-1/u-2/A1.jpg']);
    assert.deepEqual(removals(store), ['remove evidence/v-1/u-2/A1.jpg']);
    for (const key of references) assert.ok(store.objects.has(key), `${key} must survive`);
  });

  test('a key is kept whatever its age, and nothing is removed when everything is referenced', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': hoursAgo(24 * 400), 'evidence/v-1/b/E1.jpg': hoursAgo(24 * 400) });
    const report = await sweep(['evidence/v-1/a/E1.jpg', 'evidence/v-1/b/E1.jpg'], store, { dryRun: false, minAgeHours: 1 });
    assert.deepEqual([report.orphans, report.removed, report.referenced], [[], [], 2]);
    assert.deepEqual(removals(store), []);
  });

  test('an unreferenced object younger than the safety age, or of unknown age, is kept', async () => {
    const store = fakeStore({
      'evidence/v-1/old/E1.jpg': OLD,
      'evidence/v-1/fresh/E1.jpg': hoursAgo(DEFAULT_SWEEP_AGE_HOURS - 1),
      'evidence/v-1/unknown/E1.jpg': null,
    });
    const report = await sweep([], store, { dryRun: false });
    assert.deepEqual([report.orphans, report.tooRecent], [['evidence/v-1/old/E1.jpg'], 2]);
    assert.deepEqual([...store.objects.keys()].sort(), ['evidence/v-1/fresh/E1.jpg', 'evidence/v-1/unknown/E1.jpg']);
  });

  test('the safety age cannot be set below the minimum', async () => {
    const store = fakeStore({ 'evidence/v-1/recent/E1.jpg': hoursAgo(MIN_SWEEP_AGE_HOURS / 2) });
    const report = await sweep([], store, { dryRun: false, minAgeHours: 0.001 });
    assert.deepEqual([report.minAgeHours, report.orphans, report.tooRecent], [MIN_SWEEP_AGE_HOURS, [], 1]);
    assert.deepEqual(removals(store), []);
  });

  test('the objects are listed before the references are read, so a save in between is seen', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': OLD });
    await sweep([], store, { dryRun: false });
    assert.deepEqual(store.calls.slice(0, 2), ['list evidence/v-1/', 'references v-1']);
  });

  test('only the video\'s own prefix is listed, so a video whose id extends this one is not touched', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': OLD, 'evidence/v-10/a/E1.jpg': OLD, 'evidence/v-1x/a/E1.jpg': OLD });
    const report = await sweep([], store, { dryRun: false });
    assert.deepEqual(report.removed, ['evidence/v-1/a/E1.jpg']);
    assert.ok(store.objects.has('evidence/v-10/a/E1.jpg') && store.objects.has('evidence/v-1x/a/E1.jpg'));
  });

  test('a listed key outside the video\'s evidence area is never removed, even if a store returns it', async () => {
    const store = { calls: [], async list() { return [{ key: 'uploads/other.mp4', lastModified: OLD }, { key: 'evidence/v-1/../v-2/E1.jpg', lastModified: OLD }]; }, async remove(key) { this.calls.push(`remove ${key}`); } };
    const report = await sweepOrphanEvidence(fakeIncidents([]), store, VIDEO, { now: NOW, dryRun: false });
    assert.deepEqual([report.orphans, store.calls], [[], []]);
  });

  test('an unknown video is refused and nothing is removed', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': OLD });
    await assert.rejects(sweep(null, store, { dryRun: false }), (error) => error instanceof StoreRejection && error.reason === 'not-found');
    assert.deepEqual(removals(store), []);
  });

  test('when the references cannot be read, nothing is removed', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': OLD });
    await assert.rejects(sweep(new Error('PostgREST returned HTTP 503'), store, { dryRun: false }), /503/);
    assert.deepEqual(removals(store), []);
  });

  test('when the listing fails, no reference is read and nothing is removed', async () => {
    const calls = [];
    const store = { async list() { throw new Error('R2 listing was cut short'); }, async remove(key) { calls.push(key); } };
    await assert.rejects(sweepOrphanEvidence(fakeIncidents([], calls), store, VIDEO, { dryRun: false }), /cut short/);
    assert.deepEqual(calls, []);
  });

  test('a failed removal is reported and the rest are still tried', async () => {
    const store = fakeStore({ 'evidence/v-1/a/E1.jpg': OLD, 'evidence/v-1/b/E1.jpg': OLD }, { failRemoveOf: ['evidence/v-1/a/E1.jpg'] });
    const report = await sweep([], store, { dryRun: false });
    assert.deepEqual(report.removed, ['evidence/v-1/b/E1.jpg']);
    assert.deepEqual(report.failed, [{ key: 'evidence/v-1/a/E1.jpg', error: 'cannot remove evidence/v-1/a/E1.jpg' }]);
  });
});

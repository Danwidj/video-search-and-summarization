// SPDX-License-Identifier: Apache-2.0

// storeIncidentSearchableCrops: stores a new revision's crops only when it is the incident's searchable revision,
// and reports a failure instead of throwing.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { storeIncidentSearchableCrops } = await import('../src/modules/reports/application/store-searchable-crops/incident.ts');
const { SupabaseIncidentReportAdapter } = await import('../src/modules/reports/infrastructure/supabase/incident-reports.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');
const { A, B, incidentDatabase, vector } = await import('./support/incident-write-fixture.mjs');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const setup = (options) => {
  const db = incidentDatabase(options);
  globalThis.fetch = db.fetch;
  return { db, repo: new SupabaseIncidentReportAdapter(new PostgrestClient('https://supabase.test', 'k')) };
};
const calls = [];
const embed = async (evidence) => {
  calls.push(evidence.length);
  return evidence.map((item) => ({ itemType: item.item_type, itemId: item.item_id, embedding: vector(1) }));
};

test('the newest revision of an incident with no official revision gets its crops, one embedding call per camera', async () => {
  calls.length = 0;
  const { db, repo } = setup();
  const result = await storeIncidentSearchableCrops(repo, 1, 1, embed);
  assert.deepEqual(result, { crops: 2 });
  assert.deepEqual(calls, [1, 1]);
  assert.deepEqual(db.store.evidence_crops.map((crop) => crop.video_id).sort(), [A, B]);
});

test('nothing is stored when the incident has an official revision or the revision is not the newest', async () => {
  calls.length = 0;
  const official = setup({ official: 1 });
  assert.deepEqual(await storeIncidentSearchableCrops(official.repo, 1, 1, embed), { crops: null });
  const stale = setup();
  assert.deepEqual(await storeIncidentSearchableCrops(stale.repo, 1, 5, embed), { crops: null });
  assert.deepEqual(await storeIncidentSearchableCrops(stale.repo, 9, 1, embed), { crops: null });
  assert.deepEqual(calls, []);
  assert.deepEqual(stale.db.store.evidence_crops, []);
});

test('an embedding failure is returned, not thrown, and stores nothing', async () => {
  const { db, repo } = setup();
  const result = await storeIncidentSearchableCrops(repo, 1, 1, async () => {
    throw new Error('agent down');
  });
  assert.deepEqual(result, { crops: null, error: 'agent down' });
  assert.deepEqual(db.store.evidence_crops, []);
});

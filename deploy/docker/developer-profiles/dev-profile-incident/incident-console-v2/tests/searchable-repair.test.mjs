// SPDX-License-Identifier: Apache-2.0

// The automatic repair of searchable versions (src/lib/jobs/repair.ts): crops and summary vectors that are missing are stored
// by the job loop, with no one calling the route.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { createSearchableRepair, FAILURE_COOLDOWN_MS, REPAIR_BATCH, REPAIR_INTERVAL_MS } = await import('@/lib/jobs/repair');
const { InMemoryIncidentRepository } = await import('../src/modules/reports/infrastructure/memory/incidents.ts');
const { InMemoryVideoRepository } = await import('../src/modules/videos/infrastructure/memory/videos.ts');
const { aiRunReport } = await import('./support/report-view.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const V = smoke.videoId;

function world() {
  const record = aiRunReport(smoke);
  record.evidence = [
    { item_type: 'entity', item_id: 'E1', image: 'evidence/v/u/E1.jpg', bounding_box: [1, 2, 3, 4], timestamp_seconds: 2 },
  ];
  const incidents = new InMemoryIncidentRepository([record]);
  const videos = new InMemoryVideoRepository();
  videos.videos.set(V, { id: V, revisionIds: [1], officialRevisionId: null });
  const logs = [];
  const embedded = [];
  let clock = 0;
  const setup = {
    db: { incidents, videos },
    embedCrops: async (id) => {
      embedded.push(['crops', id]);
      return [{ itemType: 'entity', itemId: 'E1', embedding: [0.5] }];
    },
    embedSummary: async (summary) => {
      embedded.push(['summary', summary.title]);
      return [0.1];
    },
  };
  const run = createSearchableRepair({ deps: () => setup, log: (m) => logs.push(m), now: () => clock });
  return { videos, setup, logs, embedded, run, advance: (ms) => (clock += ms) };
}

test('a pass with nothing missing is silent and calls no model or embedding endpoint', async () => {
  const { run, logs, embedded } = world();
  await run();
  assert.deepEqual(logs, []);
  assert.deepEqual(embedded, []);
});

test('a revision saved after the job was marked failed is repaired on the next pass, with one log line naming video and revision', async () => {
  const { run, videos, logs, embedded } = world();
  await run(); // the pass after the job failed: the agent had saved nothing yet
  assert.deepEqual(embedded, []);
  // 77 s later the agent's save lands: the searchable version has evidence images, no crops and no summary vector.
  videos.missingCrops = [{ videoId: V, revisionId: 1 }];
  videos.missingEmbeddings = [{ videoId: V, revisionId: 1, title: 'Late report', description: 'Saved after the console gave up.' }];
  await run();
  assert.deepEqual(
    videos.cropCalls.map((c) => [c.videoId, c.revisionId, c.crops.length]),
    [[V, 1, 1]],
  );
  assert.deepEqual(
    videos.embeddingCalls.map((c) => [c.videoId, c.revisionId]),
    [[V, 1]],
  );
  assert.deepEqual(logs, [`repaired the crops of video ${V} revision 1: 1 stored`, `repaired the summary vector of video ${V} revision 1`]);
  await run();
  assert.equal(logs.length, 2, 'idempotent: the next pass finds nothing');
  assert.equal(embedded.length, 2);
});

test('a failing version is logged, retried after the cooldown, and does not stop the rest or throw', async () => {
  const { run, videos, setup, logs, advance } = world();
  videos.missingEmbeddings = [{ videoId: V, revisionId: 1, title: 'A', description: null }];
  let up = false;
  setup.embedSummary = async () => {
    if (!up) throw new Error('embedding service down');
    return [0.1];
  };
  await run();
  assert.match(logs[0], new RegExp(`repair of summary for video ${V} revision 1 failed, will retry later: embedding service down`));
  await run();
  assert.equal(logs.length, 1, 'not retried inside the cooldown');
  up = true;
  advance(FAILURE_COOLDOWN_MS + 1);
  await run();
  assert.deepEqual(
    videos.embeddingCalls.map((c) => c.revisionId),
    [1],
  );
});

test('a database failure in a pass is logged and the pass resolves', async () => {
  const { run, videos, logs } = world();
  videos.listRevisionsMissingCrops = async () => {
    throw new Error('PostgREST down');
  };
  await run();
  assert.match(logs[0], /repair pass failed, will retry: PostgREST down/);
});

test('a version whose evidence yields no crop rows is not retried forever', async () => {
  const { run, videos, setup, logs, embedded } = world();
  setup.embedCrops = async (id) => {
    embedded.push(['crops', id]);
    return []; // the agent returned no vector for the item: officialCrops stores nothing
  };
  videos.repairRevisionCrops = async (videoId, revisionId) => {
    videos.cropCalls.push({ videoId, revisionId, crops: [] });
    return 0;
  };
  videos.missingCrops = [{ videoId: V, revisionId: 1 }];
  await run();
  await run();
  await run();
  assert.equal(embedded.filter(([kind]) => kind === 'crops').length, 1, 'one attempt only');
  assert.equal(logs.filter((m) => /no crops to store/.test(m)).length, 1);
});

test('a pass takes at most REPAIR_BATCH versions of each kind', async () => {
  const { run, videos } = world();
  videos.missingEmbeddings = Array.from({ length: REPAIR_BATCH + 3 }, (_, i) => ({
    videoId: V,
    revisionId: i + 1,
    title: 't',
    description: null,
  }));
  videos.setRevisionEmbedding = async (_v, revisionId) => {
    videos.embeddingCalls.push({ revisionId });
    return true;
  };
  await run();
  assert.equal(videos.embeddingCalls.length, REPAIR_BATCH);
});

test('two passes started together run once (no overlap in one console)', async () => {
  const { run, videos, embedded } = world();
  videos.missingEmbeddings = [{ videoId: V, revisionId: 1, title: 'A', description: null }];
  await Promise.all([run(), run()]);
  assert.equal(embedded.filter(([kind]) => kind === 'summary').length, 1);
});

test('when the console has no database or agent configured the pass is skipped', async () => {
  const logs = [];
  await createSearchableRepair({ deps: () => null, log: (m) => logs.push(m) })();
  assert.deepEqual(logs, []);
});

test('the job loop starts the repair at start, every two minutes and after a job, and stays off with ANALYSIS_JOB_LOOP=off', () => {
  const source = readFileSync(join(process.cwd(), 'src', 'lib', 'jobs', 'loop.ts'), 'utf8');
  assert.equal(REPAIR_INTERVAL_MS, 120_000);
  const start = source.slice(source.indexOf('export function startAnalysisJobLoop'));
  const guard = start.indexOf("ANALYSIS_JOB_LOOP?.trim().toLowerCase() === 'off') return;");
  assert.ok(guard > 0 && guard < start.indexOf('void repairSearchable()'), 'the off switch returns before any repair is scheduled');
  assert.match(start, /setInterval\(\(\) => void repairSearchable\(\), REPAIR_INTERVAL_MS\)/);
  assert.match(start, /if \(busy\) void repairSearchable\(\);/, 'after each job, not awaited');
});

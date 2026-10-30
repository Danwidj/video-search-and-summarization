// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildBatchIncident,
  checkBatchItem,
  isAlreadyStored,
  itemProgress,
  newBatchItem,
  planBatch,
  retryChange,
  runBatchItem,
  runPool,
  summariseBatch,
} from '../src/sections/analysis/batch-upload.ts';

const file = (name) => ({ name, size: 2 * 1024 * 1024 });

function harness(overrides = {}) {
  const calls = [];
  const deps = {
    upload: async (f, onProgress) => {
      calls.push(`upload ${f.name}`);
      onProgress(50);
      return { sensorId: `s-${f.name}`, filePath: `k/${f.name}`, filename: f.name };
    },
    complete: async () => calls.push('complete'),
    analyse: async () => {
      calls.push('analyse');
      return { incidentId: 7 };
    },
    build: async () => calls.push('build'),
    evaluate: async () => {
      calls.push('evaluate');
      return { suggestions: 2 };
    },
    ...overrides,
  };
  return { calls, deps };
}

async function run(f, deps, start = newBatchItem(f, 'k')) {
  let item = start;
  await runBatchItem(f, start, 'model', deps, (change) => {
    item = { ...item, ...change };
  });
  return item;
}

const check = async (start, deps) => {
  let item = start;
  await checkBatchItem(start, deps, (change) => {
    item = { ...item, ...change };
  });
  return item;
};

const analysed = (key, incidentId, extra = {}) => ({
  ...newBatchItem(file(`${key}.mp4`), key),
  status: 'waiting',
  stage: 'matches',
  uploaded: { sensorId: key, filePath: `k/${key}`, filename: `${key}.mp4` },
  analysed: { incidentId },
  ...extra,
});

test('a file uploads and analyses, then waits for the batch without building or matching', async () => {
  const { calls, deps } = harness();
  const item = await run(file('a.mp4'), deps);
  assert.deepEqual(calls, ['upload a.mp4', 'complete', 'analyse']);
  assert.equal(item.status, 'waiting');
  assert.equal(item.stage, 'matches');
  assert.deepEqual(item.analysed, { incidentId: 7 });
  assert.equal(item.built, false);
});

test('a match check leaves the file deciding, with no report built', async () => {
  const { calls, deps } = harness();
  const item = await check(analysed('a', 7), deps);
  assert.deepEqual(calls, ['evaluate']);
  assert.equal(item.status, 'deciding');
  assert.equal(item.stage, 'report');
  assert.equal(item.checked, true);
  assert.equal(item.matches, 2);
});

test('the stage order is upload, analyse, check matches, build report', async () => {
  const { calls, deps } = harness();
  let item = await run(file('a.mp4'), deps);
  item = await check(item, deps);
  await buildBatchIncident(7, ['k'], deps, (_key, change) => {
    item = { ...item, ...change };
  });
  assert.deepEqual(calls, ['upload a.mp4', 'complete', 'analyse', 'evaluate', 'build']);
  assert.equal(item.status, 'done');
  assert.equal(item.built, true);
  assert.equal(itemProgress(item), 100);
});

test('a failure is recorded at its stage and does not throw', async () => {
  const { deps } = harness({ analyse: async () => Promise.reject(new Error('Analysis request timed out')) });
  const item = await run(file('a.mp4'), deps);
  assert.equal(item.status, 'failed');
  assert.equal(item.stage, 'analyse');
  assert.equal(item.error, 'Analysis request timed out');
  assert.ok(item.uploaded, 'the upload is kept for the retry');
});

test('a retry resumes at the stage that failed and does not upload again', async () => {
  const failing = harness({ analyse: async () => Promise.reject(new Error('timeout')) });
  const failed = await run(file('a.mp4'), failing.deps);
  assert.deepEqual(retryChange(failed), { status: 'queued', error: null, stage: 'analyse' });
  const retry = harness();
  const item = await run(file('a.mp4'), retry.deps, { ...failed, ...retryChange(failed) });
  assert.deepEqual(retry.calls, ['analyse']);
  assert.equal(item.status, 'waiting');
});

test('a failed match check retries only the check; a failed build retries only the build', async () => {
  const failing = harness({ evaluate: async () => Promise.reject(new Error('judge unavailable')) });
  const failed = await check(analysed('a', 7), failing.deps);
  assert.equal(failed.status, 'failed');
  assert.equal(failed.stage, 'matches');
  assert.deepEqual(retryChange(failed), { status: 'waiting', error: null, stage: 'matches' });

  const broken = harness({ build: async () => Promise.reject(new Error('synthesis failed')) });
  const changes = [];
  await buildBatchIncident(7, ['a'], broken.deps, (key, change) => changes.push([key, change]));
  assert.deepEqual(changes.at(-1), ['a', { status: 'failed', stage: 'report', error: 'synthesis failed' }]);
  const checked = analysed('a', 7, { status: 'failed', stage: 'report', checked: true });
  assert.deepEqual(retryChange(checked), { status: 'deciding', error: null, stage: 'report' });
});

test('matches are not checked while any file is still uploading or analysing', () => {
  const items = [
    analysed('a', 1),
    { ...newBatchItem(file('b.mp4'), 'b'), status: 'running', stage: 'analyse' },
    newBatchItem(file('c.mp4'), 'c'),
  ];
  assert.deepEqual(planBatch(items, null).check, []);
});

test('once every file is analysed or failed, all analysed files are checked, so batch members meet each other', () => {
  const failed = { ...newBatchItem(file('c.mp4'), 'c'), status: 'failed', stage: 'upload', error: 'x' };
  const items = [analysed('a', 1), analysed('b', 2), failed];
  assert.deepEqual(planBatch(items, null).check, ['a', 'b']);
});

test('no report is built before the matches are checked and the pending suggestions are known', () => {
  const items = [analysed('a', 1), analysed('b', 2, { status: 'deciding', stage: 'report', checked: true })];
  assert.deepEqual(planBatch(items, new Set()).build, [], 'a is still waiting for its check');
  const checked = [analysed('a', 1, { status: 'deciding', stage: 'report', checked: true })];
  assert.deepEqual(planBatch(checked, null).build, [], 'pending suggestions not read yet');
});

test('a file with no pending suggestion builds at once; one with a pending suggestion waits for the decision', () => {
  const items = [
    analysed('a', 1, { status: 'deciding', stage: 'report', checked: true }),
    analysed('b', 2, { status: 'deciding', stage: 'report', checked: true }),
    analysed('c', 3, { status: 'deciding', stage: 'report', checked: true }),
  ];
  assert.deepEqual(planBatch(items, new Set([1, 2])).build, [{ incidentId: 3, keys: ['c'] }]);
  assert.deepEqual(
    planBatch(items, new Set()).build.map((entry) => entry.incidentId),
    [1, 2, 3],
  );
});

test('files that share an incident build it once', () => {
  const items = ['a', 'b'].map((key) => analysed(key, 1, { status: 'deciding', stage: 'report', checked: true }));
  assert.deepEqual(planBatch(items, new Set()).build, [{ incidentId: 1, keys: ['a', 'b'] }]);
  assert.deepEqual(planBatch(items, new Set([1])).build, [], 'an undecided suggestion holds the build');
});

test('a build is shared by the files of an incident and marks each done', async () => {
  const { calls, deps } = harness();
  const changes = [];
  await buildBatchIncident(1, ['a', 'b'], deps, (key, change) => changes.push([key, change.status]));
  assert.deepEqual(calls, ['build']);
  assert.deepEqual(changes, [
    ['a', 'running'],
    ['b', 'running'],
    ['a', 'done'],
    ['b', 'done'],
  ]);
});

test('one failing file does not stop the others in the pool', async () => {
  const names = ['a.mp4', 'b.mp4', 'c.mp4'];
  const results = new Map();
  const { deps } = harness({
    analyse: async ({ uploaded }) => {
      if (uploaded.filename === 'b.mp4') throw new Error('boom');
      return { incidentId: 1 };
    },
  });
  await runPool(names, 2, async (name) => {
    results.set(name, await run(file(name), deps, newBatchItem(file(name), name)));
  });
  assert.deepEqual(
    names.map((name) => results.get(name).status),
    ['waiting', 'failed', 'waiting'],
  );
});

test('the pool never runs more than its limit at once', async () => {
  let running = 0;
  let peak = 0;
  await runPool([1, 2, 3, 4, 5], 2, async () => {
    running += 1;
    peak = Math.max(peak, running);
    await new Promise((resolve) => setTimeout(resolve, 5));
    running -= 1;
  });
  assert.equal(peak, 2);
});

test('summary counts files and settles only when none is queued or running', () => {
  const base = newBatchItem(file('a.mp4'), 'a');
  const items = [
    { ...base, status: 'done' },
    { ...base, key: 'b', status: 'failed' },
    { ...base, key: 'c', status: 'running' },
  ];
  assert.deepEqual(summariseBatch(items), { total: 3, done: 1, failed: 1, deciding: 0, running: 1, percent: 33, settled: false });
  assert.equal(
    summariseBatch([...items.slice(0, 2), { ...base, key: 'd', status: 'deciding' }]).settled,
    true,
    'a file awaiting a decision is handed to the reviewer, so the batch settles',
  );
  assert.equal(summariseBatch(items.slice(0, 2)).settled, true);
  assert.equal(summariseBatch([]).settled, false);
});

test('already-stored refusals are recognised so a retry re-analyses the stored video', () => {
  assert.equal(isAlreadyStored(new Error('A video named a.mp4 already exists')), true);
  assert.equal(isAlreadyStored(new Error('timed out')), false);
});

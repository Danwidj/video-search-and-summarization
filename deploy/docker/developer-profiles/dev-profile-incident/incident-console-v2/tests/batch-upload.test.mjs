// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isAlreadyStored,
  itemProgress,
  newBatchItem,
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

test('a file passes upload, analyse, build report and check matches in order', async () => {
  const { calls, deps } = harness();
  const item = await run(file('a.mp4'), deps);
  assert.deepEqual(calls, ['upload a.mp4', 'complete', 'analyse', 'build', 'evaluate']);
  assert.equal(item.status, 'done');
  assert.equal(item.matches, 2);
  assert.deepEqual(item.analysed, { incidentId: 7 });
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
  const failing = harness({ build: async () => Promise.reject(new Error('synthesis failed')) });
  const failed = await run(file('a.mp4'), failing.deps);
  assert.equal(failed.stage, 'report');
  const retry = harness();
  const item = await run(file('a.mp4'), retry.deps, failed);
  assert.deepEqual(retry.calls, ['build', 'evaluate']);
  assert.equal(item.status, 'done');
  assert.equal(item.error, null);
});

test('a failed match check keeps the report and retries only the check', async () => {
  const failing = harness({ evaluate: async () => Promise.reject(new Error('judge unavailable')) });
  const failed = await run(file('a.mp4'), failing.deps);
  assert.equal(failed.stage, 'matches');
  assert.equal(failed.built, true);
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
    ['done', 'failed', 'done'],
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
  assert.deepEqual(summariseBatch(items), { total: 3, done: 1, failed: 1, running: 1, percent: 33, settled: false });
  assert.equal(summariseBatch(items.slice(0, 2)).settled, true);
  assert.equal(summariseBatch([]).settled, false);
});

test('already-stored refusals are recognised so a retry re-analyses the stored video', () => {
  assert.equal(isAlreadyStored(new Error('A video named a.mp4 already exists')), true);
  assert.equal(isAlreadyStored(new Error('timed out')), false);
});

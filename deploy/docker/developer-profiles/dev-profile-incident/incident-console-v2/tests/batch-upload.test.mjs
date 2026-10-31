// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  cancelQueued,
  drainQueue,
  itemProgress,
  NOT_A_VIDEO_MESSAGE,
  newBatchItem,
  nextToRun,
  removeQueued,
  runBatchItem,
  shouldAbortRunning,
  summariseBatch,
  UPLOAD_CANCELLED_MESSAGE,
  UPLOAD_REFUSED_MESSAGE,
} from '../src/sections/analysis/batch-upload.ts';

const file = (name, type = 'video/mp4') => ({ name, size: 2 * 1024 * 1024, type });
const queued = (key) => newBatchItem(file(`${key}.mp4`), key);
const keys = (items) => items.map((item) => item.key);

function harness(overrides = {}) {
  const calls = [];
  const deps = {
    upload: async (f, onProgress, onUploaded) => {
      calls.push(`upload ${f.name}`);
      onProgress(50);
      onUploaded();
      return { filePath: `uploads/${f.name}`, filename: f.name, converted: true };
    },
    analyse: async ({ filename, model }) => {
      calls.push(`analyse ${filename} ${model}`);
      return { videoId: `v-${filename}`, revisionId: 1 };
    },
    ...overrides,
  };
  return { calls, deps };
}

/** Runs one file and returns its final item plus every status it passed through. */
async function run(f, deps) {
  let item = newBatchItem(f, 'k');
  const statuses = [];
  await runBatchItem(f, 'model-a', deps, (change) => {
    item = { ...item, ...change };
    if (statuses.at(-1) !== item.status) statuses.push(item.status);
  });
  return { item, statuses };
}

/** A queue driven the way the hook drives it: the items live in one array the runs patch. */
function queue(names, deps) {
  let items = names.map((name) => newBatchItem(file(name), name));
  const order = [];
  return {
    get items() {
      return items;
    },
    set items(next) {
      items = next;
    },
    order,
    drain: () =>
      drainQueue(
        () => items,
        async (key) => {
          order.push(key);
          await runBatchItem(file(key), 'model-a', deps, (change) => {
            items = items.map((item) => (item.key === key ? { ...item, ...change } : item));
          });
        },
      ),
  };
}

test('a file passes Uploading, Converting and Analysing in order and ends done with its report', async () => {
  const { calls, deps } = harness();
  const { item, statuses } = await run(file('a.mov'), deps);
  assert.deepEqual(statuses, ['uploading', 'converting', 'analysing', 'done']);
  assert.deepEqual(calls, ['upload a.mov', 'analyse a.mov model-a']);
  assert.deepEqual(item.report, { videoId: 'v-a.mov', revisionId: 1 });
  assert.equal(item.converted, true);
  assert.equal(itemProgress(item), 100);
});

test('the row takes the stored name once the upload answers', async () => {
  const { deps } = harness({
    upload: async () => ({ filePath: 'uploads/clip-2.mp4', filename: 'clip-2.mp4', converted: false }),
  });
  const { item } = await run(file('clip.MOV'), deps);
  assert.equal(item.name, 'clip-2.mp4');
  assert.equal(item.converted, false);
});

test('a failure is recorded at its step and does not throw', async () => {
  const { deps } = harness({ analyse: async () => Promise.reject(new Error('The agent request failed (AGENT_TIMEOUT)')) });
  const { item } = await run(file('a.mp4'), deps);
  assert.equal(item.status, 'failed');
  assert.equal(item.failedAt, 'analysing');
  assert.equal(item.error, 'The agent request failed (AGENT_TIMEOUT)');
  assert.equal(item.report, null);

  const refused = harness({
    upload: async (_f, _p, onUploaded) => {
      onUploaded();
      throw new Error('ffprobe could not read the file: Invalid data found when processing input');
    },
  });
  const converting = (await run(file('b.mp4'), refused.deps)).item;
  assert.equal(converting.failedAt, 'converting', 'a file the server refuses after the bytes are up fails at Converting');
  assert.match(converting.error, /Invalid data/);
});

test('a refused upload with no message says the file was not accepted as a video', async () => {
  for (const message of ['', '  ']) {
    const { deps } = harness({ upload: async () => Promise.reject(new Error(message)) });
    const { item } = await run(file('notvideo.mp4'), deps);
    assert.equal(item.status, 'failed');
    assert.equal(item.failedAt, 'uploading');
    assert.equal(item.error, UPLOAD_REFUSED_MESSAGE);
    assert.equal(item.error, 'The file was not accepted as a video');
  }
  const later = harness({ analyse: async () => Promise.reject(new Error('')) });
  assert.equal((await run(file('a.mp4'), later.deps)).item.error, 'The analysis failed', 'only the upload steps have the video fallback');
});

test('a file that is not a video by name or type fails at once and is never sent', async () => {
  const item = newBatchItem(file('notes.txt', 'text/plain'), 'n');
  assert.equal(item.status, 'failed');
  assert.equal(item.error, NOT_A_VIDEO_MESSAGE);
  assert.equal(nextToRun([item]), null);
  assert.equal(newBatchItem(file('clip.MOV', ''), 'm').status, 'queued', 'a known extension is enough');
});

test('files run strictly one at a time, in the order they were added', async () => {
  let running = 0;
  let peak = 0;
  const { deps } = harness({
    analyse: async ({ filename }) => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((resolve) => setTimeout(resolve, 5));
      running -= 1;
      return { videoId: filename, revisionId: 1 };
    },
  });
  const q = queue(['a', 'b', 'c'], deps);
  await q.drain();
  assert.deepEqual(q.order, ['a', 'b', 'c']);
  assert.equal(peak, 1);
  assert.deepEqual(
    q.items.map((item) => item.status),
    ['done', 'done', 'done'],
  );
});

test('nothing starts while a file runs; the first queued file starts next', () => {
  const items = [{ ...queued('a'), status: 'done' }, { ...queued('b'), status: 'converting' }, queued('c'), queued('d')];
  assert.equal(nextToRun(items), null);
  assert.equal(nextToRun(items.map((item) => (item.key === 'b' ? { ...item, status: 'failed' } : item))), 'c');
  assert.equal(nextToRun([{ ...queued('a'), status: 'done' }]), null);
});

test('one failing file never stops the ones after it', async () => {
  const { deps } = harness({
    upload: async (f, _p, onUploaded) => {
      if (f.name === 'b') throw new Error('ffprobe could not read the file');
      onUploaded();
      return { filePath: `uploads/${f.name}`, filename: f.name, converted: false };
    },
  });
  const q = queue(['a', 'b', 'c'], deps);
  await q.drain();
  assert.deepEqual(
    q.items.map((item) => [item.key, item.status]),
    [
      ['a', 'done'],
      ['b', 'failed'],
      ['c', 'done'],
    ],
  );
  assert.equal(q.items[1].report, null, 'the failed file has no report');
});

test('a run that throws is still followed by the next file', async () => {
  let items = [queued('a'), queued('b')];
  const order = [];
  await drainQueue(
    () => items,
    async (key) => {
      order.push(key);
      items = items.map((item) => (item.key === key ? { ...item, status: key === 'a' ? 'failed' : 'done' } : item));
      if (key === 'a') throw new Error('unexpected');
    },
  );
  assert.deepEqual(order, ['a', 'b']);
});

test('a queued file can be removed; a running or finished one cannot', () => {
  const items = [{ ...queued('a'), status: 'analysing' }, queued('b'), { ...queued('c'), status: 'done' }];
  assert.deepEqual(keys(removeQueued(items, 'b')), ['a', 'c']);
  assert.deepEqual(keys(removeQueued(items, 'a')), ['a', 'b', 'c']);
  assert.deepEqual(keys(removeQueued(items, 'c')), ['a', 'b', 'c']);
});

test('a file removed while another runs is never started', async () => {
  const { deps } = harness();
  const q = queue(['a', 'b', 'c'], {
    ...deps,
    analyse: async (input) => {
      if (input.filename === 'a') q.items = removeQueued(q.items, 'b');
      return deps.analyse(input);
    },
  });
  await q.drain();
  assert.deepEqual(q.order, ['a', 'c']);
  assert.deepEqual(keys(q.items), ['a', 'c']);
});

test('cancelling the batch cancels every queued file and leaves the running one to finish its step', async () => {
  const items = [{ ...queued('a'), status: 'done' }, { ...queued('b'), status: 'analysing' }, queued('c'), queued('d')];
  const cancelled = cancelQueued(items);
  assert.deepEqual(
    cancelled.map((item) => item.status),
    ['done', 'analysing', 'cancelled', 'cancelled'],
  );
  assert.equal(shouldAbortRunning(items), false, 'a file past its upload is not aborted');
  assert.equal(shouldAbortRunning([{ ...queued('a'), status: 'uploading' }]), true, 'a file still uploading is aborted');
  assert.equal(nextToRun(cancelled.map((item) => (item.key === 'b' ? { ...item, status: 'done' } : item))), null);
});

test('cancelling during a run stops the queue after the running file', async () => {
  const { deps } = harness();
  const q = queue(['a', 'b', 'c'], {
    ...deps,
    analyse: async (input) => {
      if (input.filename === 'a') q.items = cancelQueued(q.items);
      return deps.analyse(input);
    },
  });
  await q.drain();
  assert.deepEqual(q.order, ['a']);
  assert.deepEqual(
    q.items.map((item) => item.status),
    ['done', 'cancelled', 'cancelled'],
  );
});

test('an upload aborted by cancel is cancelled, not failed', async () => {
  const { deps } = harness({ upload: async () => Promise.reject(new Error(UPLOAD_CANCELLED_MESSAGE)) });
  const { item } = await run(file('a.mp4'), deps);
  assert.equal(item.status, 'cancelled');
  assert.equal(item.error, null);
});

test('the summary counts files and settles only when none is queued or running', () => {
  const items = [
    { ...queued('a'), status: 'done' },
    { ...queued('b'), status: 'failed', failedAt: 'converting' },
    { ...queued('c'), status: 'uploading', uploadProgress: 50 },
    queued('d'),
  ];
  assert.deepEqual(summariseBatch(items), {
    total: 4,
    done: 1,
    failed: 1,
    cancelled: 0,
    pending: 2,
    percent: 54,
    settled: false,
  });
  assert.equal(summariseBatch(cancelQueued(items.slice(0, 2).concat(items[3]))).settled, true);
  assert.equal(summariseBatch([]).settled, false);
});

test("each file's bar follows its own step", () => {
  const base = queued('a');
  assert.equal(itemProgress(base), 0);
  assert.equal(itemProgress({ ...base, status: 'uploading', uploadProgress: 0 }), 2);
  assert.equal(itemProgress({ ...base, status: 'uploading', uploadProgress: 100 }), 33);
  assert.equal(itemProgress({ ...base, status: 'converting' }), 50);
  assert.equal(itemProgress({ ...base, status: 'analysing' }), 83);
  assert.equal(itemProgress({ ...base, status: 'failed', failedAt: 'analysing' }), 83);
  assert.equal(itemProgress({ ...base, status: 'cancelled' }), 0);
});

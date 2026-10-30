// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildAfterApart, buildAfterJoin } from '../src/sections/suggestions/build-after-decision.ts';

const deps = (pending = []) => {
  const built = [];
  return {
    built,
    deps: {
      hasPending: async (id) => pending.includes(id),
      build: async (id) => {
        built.push(id);
        return true;
      },
    },
  };
};

test('a join builds the kept incident once nothing on it is undecided', async () => {
  const { built, deps: d } = deps();
  assert.equal(await buildAfterJoin(d, 1), true);
  assert.deepEqual(built, [1]);
});

test('a join with other matches still pending builds nothing yet', async () => {
  const { built, deps: d } = deps([1]);
  assert.equal(await buildAfterJoin(d, 1), null);
  assert.deepEqual(built, []);
});

test('a pair kept apart builds only incidents without a report and without pending matches', async () => {
  const { built, deps: d } = deps([3]);
  const results = await buildAfterApart(d, [
    { incidentId: 1, hasReport: true },
    { incidentId: 2, hasReport: false },
    { incidentId: 3, hasReport: false },
  ]);
  assert.deepEqual(built, [2]);
  assert.deepEqual(results, [true]);
});

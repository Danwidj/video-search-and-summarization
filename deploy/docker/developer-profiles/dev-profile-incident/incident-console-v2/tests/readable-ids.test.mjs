// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

const src = join(import.meta.dirname, '..', 'src');
const read = (path) => readFileSync(join(src, path), 'utf8');

test('compactId and its hashing module are gone', () => {
  assert.equal(existsSync(join(src, 'lib', 'ids.ts')), false);
  for (const path of [
    'app/api/analysis/route.ts',
    'modules/analysis/application/analyse-video.ts',
    'modules/analysis/application/run-contract-analysis.ts',
  ]) {
    assert.doesNotMatch(read(path), /compactId|lib\/ids/, path);
  }
});

test('the analysis route keys the video by its real upload file name', () => {
  assert.match(read('app/api/analysis/route.ts'), /videoName: body\.filename as string,/);
});

test('model-run ids read <video name>@<UTC timestamp>', () => {
  assert.match(
    read('modules/analysis/application/run-contract-analysis.ts'),
    /const modelRunId = `\$\{input\.videoId\}@\$\{attemptedAt\}`;/,
  );
});

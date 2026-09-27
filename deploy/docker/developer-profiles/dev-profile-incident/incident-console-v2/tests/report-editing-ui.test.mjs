// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const components = new URL('../components/', import.meta.url);
const apiRoute = new URL('../app/api/reports/[videoId]/route.ts', import.meta.url);

test('report editing is embedded beside the original AI summary', async () => {
  const report = await readFile(new URL('incident-report.tsx', components), 'utf8');
  const tools = await readFile(new URL('advanced-report-tools.tsx', components), 'utf8');
  const route = await readFile(apiRoute, 'utf8');

  assert.match(report, /'Edit report'/);
  assert.match(report, /Original AI report/);
  assert.match(report, /Your editable report/);
  assert.match(report, /Timeline/);
  assert.match(report, /People and entities/);
  assert.match(report, /Written report/);
  assert.doesNotMatch(report, /Start review/);
  assert.doesNotMatch(report, /persons/);
  assert.doesNotMatch(tools, /Edit structured report/);
  assert.match(route, /editedReport/);
});

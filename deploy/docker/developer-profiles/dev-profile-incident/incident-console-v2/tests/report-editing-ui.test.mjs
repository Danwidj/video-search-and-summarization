// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

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
  assert.doesNotMatch(report, /Start review/);
  assert.doesNotMatch(tools, /Edit structured report/);
  assert.match(route, /editedReport/);
});

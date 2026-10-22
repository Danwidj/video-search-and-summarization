// SPDX-License-Identifier: Apache-2.0

// The report page renders on the server through the getReport use case; the
// client screen only shows the loaded ReportView and asks the server to render
// again after a change. Source checks, as for the other page-structure tests.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const route = new URL('../app/reports/[videoId]/(report)/', import.meta.url);
const read = (name) => readFile(new URL(name, route), 'utf8');

test('the report page loads the report on the server through the use case, uncached', async () => {
  const page = await read('page.tsx');
  assert.doesNotMatch(page, /^'use client'/m);
  assert.match(page, /export const dynamic = 'force-dynamic'/);
  assert.match(page, /from '@\/lib\/application\/reports'/);
  assert.match(page, /await getReport\(incidents, \{ videoId, modelRunId \}, \(storageKey\) => createR2PlaybackUrl\(config, storageKey\)\)/, 'the playback URL is signed on the server');
  assert.match(page, /if \(!report\) notFound\(\)/);
  assert.doesNotMatch(page, /lib\/postgrest|lib\/adapters\/supabase\/(?!index)/, 'pages reach the database only through the adapter factory');
});

test('the report route group has its own loading, error and not-found states', async () => {
  assert.match(await read('loading.tsx'), /ReportLoading/);
  const error = await read('error.tsx');
  assert.match(error, /^'use client'/m, 'Next.js error boundaries are client components');
  assert.match(error, /reset=\{reset\}/);
  assert.match(await read('not-found.tsx'), /Report not found/);
});

test('the client report screen never fetches the report and refreshes the server render after a change', async () => {
  const screen = await readFile(new URL('../components/report-screen.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(screen, /fetch\(|useEffect/);
  assert.match(screen, /onEdited=\{\(\) => router\.refresh\(\)\}/);
  assert.match(screen, /router\.refresh\(\); reset\?\.\(\);/, 'retry renders the page again before resetting the boundary');
});

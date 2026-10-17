// SPDX-License-Identifier: Apache-2.0

// Dependency rules of the hexagonal middle layer (.docs/mvp2/console-hexagonal-architecture.md),
// checked from source text.

import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, sep } from 'node:path';
import { test } from 'node:test';

const root = process.cwd();
const sourceFiles = (dir) => readdirSync(join(root, dir)).flatMap((name) => {
  const path = join(dir, name);
  return statSync(join(root, path)).isDirectory() ? sourceFiles(path) : /\.tsx?$/.test(name) ? [path.split(sep).join('/')] : [];
});
/** Every import/export-from in a file, and whether it is type-only. */
const dependencies = (file) => [...readFileSync(join(root, file), 'utf8').matchAll(/^(?:import|export)\s+(type\s+)?[^'"]*?from\s+'([^']+)'/gm)]
  .map((match) => ({ typeOnly: Boolean(match[1]), from: match[2] }));
const importsPostgrestValue = (file) => dependencies(file).some(({ from, typeOnly }) => from === '@/lib/postgrest/client' && !typeOnly);

/**
 * Database callers not yet behind the ports, each with the reason it waits.
 * Remove an entry when its caller moves; a stale entry fails the test.
 */
const KNOWN_EXCEPTIONS = {
  'app/api/dashboard/route.ts': 'deferred until the lazy-loading change lands',
  'app/api/reports/route.ts': 'deferred until the lazy-loading change lands',
  'app/api/reports/[videoId]/ground-truth/route.ts': 'ground truth stays untouched',
  'app/api/videos/[videoId]/runs/route.ts': 'run history moves with the verified/AI report split',
  'lib/analysis/run-contract-analysis.ts': 'analysis saving moves with the verified/AI report split',
  'lib/analysis/persistence.ts': 'analysis saving moves with the verified/AI report split',
};

const inside = (file, dir) => file.startsWith(`${dir}/`);

test('only Supabase adapters import the PostgREST client, apart from the known exceptions', () => {
  const offenders = [...sourceFiles('app'), ...sourceFiles('lib'), ...sourceFiles('components')]
    .filter((file) => !inside(file, 'lib/adapters/supabase') && !inside(file, 'lib/postgrest'))
    .filter((file) => importsPostgrestValue(file) && !(file in KNOWN_EXCEPTIONS));
  assert.deepEqual(offenders, []);
});

test('every known exception still calls PostgREST directly (remove migrated entries)', () => {
  const stale = Object.keys(KNOWN_EXCEPTIONS).filter((file) => !importsPostgrestValue(file));
  assert.deepEqual(stale, []);
});

test('route handlers reach adapters only through the factory', () => {
  for (const file of sourceFiles('app')) {
    for (const { from } of dependencies(file)) {
      assert.ok(!from.startsWith('@/lib/adapters/') || from === '@/lib/adapters/supabase', `${file} imports ${from}`);
    }
  }
});

test('components never import adapters or the PostgREST client', () => {
  for (const file of sourceFiles('components')) {
    for (const { from } of dependencies(file)) assert.ok(!/^@\/lib\/(adapters|postgrest)/.test(from), `${file} imports ${from}`);
  }
});

test('ports import types only (apart from the shared error class)', () => {
  for (const file of sourceFiles('lib/ports')) {
    for (const { from, typeOnly } of dependencies(file)) assert.ok(typeOnly || from === '@/lib/ports/common', `${file} imports ${from}`);
  }
});

test('use cases never import adapters or infrastructure', () => {
  for (const file of existsSync(join(root, 'lib/application')) ? sourceFiles('lib/application') : []) {
    for (const { from } of dependencies(file)) assert.ok(!/^@\/lib\/(adapters|postgrest|r2|gateway)/.test(from), `${file} imports ${from}`);
  }
});

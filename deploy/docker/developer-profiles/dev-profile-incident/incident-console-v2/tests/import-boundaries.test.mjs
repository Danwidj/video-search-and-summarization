// SPDX-License-Identifier: Apache-2.0

// Hexagonal import boundaries, enforced by `npm test`. Rules and the layout they assume:
// .docs/mvp2/console-hexagonal-architecture.md. Paths are relative to src/ and have no extension.
// - Domain and application code must not import infrastructure, UI (app, sections), next, react or node:*.
// - Sections (client UI) must not import infrastructure or node:*.
// Each exception is named in ALLOWED with its reason. An entry that matches no import fails the test.

import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));

const INNER = [/^modules\/[^/]+\/(domain|application)\//, /^lib\/(application|ports)\//];
const SECTIONS = [/^sections(\/|$)/];
const INFRA = [
  /^modules\/[^/]+\/infrastructure(\/|$)/,
  /^lib\/(adapters|postgrest)(\/|$)/,
  /^lib\/r2\/(config|frame-source)$/,
  /^lib\/container$/,
];
const UI = [/^app(\/|$)/, /^sections(\/|$)/];
const NEXT_REACT = /^(next(\/|$)|react(-dom)?(\/|$))/;
const NODE = /^node:/;

const ALLOWED = [];

const matchesAny = (value, patterns) => patterns.some((pattern) => pattern.test(value));

function isForbidden(from, to) {
  if (matchesAny(from, INNER)) return matchesAny(to, INFRA) || matchesAny(to, UI) || NEXT_REACT.test(to) || NODE.test(to);
  if (matchesAny(from, SECTIONS)) return matchesAny(to, INFRA) || NODE.test(to);
  return false;
}

export function findViolations(edges) {
  return edges.filter(({ from, to }) => isForbidden(from, to));
}

function isAllowed({ from, to }) {
  return ALLOWED.some((entry) => entry.from === from && entry.to === to);
}

function stripExtension(target) {
  return target.replace(/\.(tsx?|mjs|js|css)$/, '').replace(/\/index$/, '');
}

function resolveSpecifier(from, specifier) {
  if (specifier.startsWith('@/')) return stripExtension(specifier.slice(2));
  if (specifier.startsWith('.')) return stripExtension(path.posix.normalize(path.posix.join(path.posix.dirname(from), specifier)));
  return specifier;
}

function importSpecifiers(text) {
  const specifiers = [];
  for (const pattern of [/\bfrom\s*['"]([^'"]+)['"]/g, /\bimport\s*['"]([^'"]+)['"]/g, /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g]) {
    for (const match of text.matchAll(pattern)) specifiers.push(match[1]);
  }
  return specifiers;
}

async function sourceFiles(dir) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await sourceFiles(full)));
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.|\.d\.ts$/.test(entry.name)) files.push(full);
  }
  return files;
}

async function importEdges() {
  const edges = [];
  for (const file of await sourceFiles(SRC)) {
    const from = path.relative(SRC, file).split(path.sep).join('/');
    for (const specifier of importSpecifiers(await readFile(file, 'utf8'))) {
      edges.push({ from, to: resolveSpecifier(from, specifier) });
    }
  }
  return edges;
}

const describe = ({ from, to }) => `${from} -> ${to}`;

test('domain, application and section code keep the hexagonal import boundaries', async () => {
  const violations = findViolations(await importEdges()).filter((edge) => !isAllowed(edge));
  assert.deepEqual(violations.map(describe), []);
});

test('every import-boundary exception still matches an import', async () => {
  const edges = await importEdges();
  const stale = ALLOWED.filter((entry) => !edges.some((edge) => edge.from === entry.from && edge.to === entry.to));
  assert.deepEqual(
    stale.map((entry) => `${entry.from} -> ${entry.to}`),
    [],
  );
});

test('the boundary rules catch forbidden imports and allow the shared pure helpers', () => {
  const edges = [
    { from: 'modules/search/application/search.ts', to: 'modules/search/infrastructure/agent' },
    { from: 'modules/search/domain/search.ts', to: 'react' },
    { from: 'sections/library/components/Card/Card.tsx', to: 'lib/adapters/agent/search' },
    { from: 'sections/library/components/Card/Card.tsx', to: 'node:fs' },
    { from: 'lib/application/evidence-frames.ts', to: 'lib/r2/key' },
    { from: 'sections/library/components/Card/Card.tsx', to: 'lib/r2/key' },
  ];
  assert.deepEqual(findViolations(edges).map(describe), [
    'modules/search/application/search.ts -> modules/search/infrastructure/agent',
    'modules/search/domain/search.ts -> react',
    'sections/library/components/Card/Card.tsx -> lib/adapters/agent/search',
    'sections/library/components/Card/Card.tsx -> node:fs',
  ]);
});

// SPDX-License-Identifier: Apache-2.0

// The colour meanings (version kinds, official and not yet official, severity bands, card hover) live as tokens in
// src/app/styles.css. This fails if their hex appears anywhere else in src/, or a canvas mirror drifts from the tokens.

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join, relative } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { levelBand, severityChartColor } = await import('../src/lib/ui/severity.ts');
const { CHART_COLORS } = await import('../src/lib/ui/chart-colors.ts');

const SRC = join(process.cwd(), 'src');
const css = readFileSync(join(SRC, 'app', 'styles.css'), 'utf8');
const token = (name) => css.match(new RegExp(`${name}: (#[0-9a-f]{6});`))?.[1];

const MEANINGS = {
  'version-model': token('--color-version-model'),
  'version-human': token('--color-version-human'),
  'version-official': token('--color-version-official'),
  'not-official': token('--color-not-official'),
  'sev-high': token('--color-sev-high'),
  'sev-medium': token('--color-sev-medium'),
  'sev-low': token('--color-sev-low'),
  'asset-size': token('--color-asset-size'),
  signal: token('--color-signal'),
};
// styles.css defines the tokens; these two hold the hex mirrors for canvases and the agent (checked equal below).
const ALLOWED = new Set(['app/styles.css', 'lib/ui/severity.ts', 'lib/ui/chart-colors.ts', 'app/icon.svg']);

function* files(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* files(path);
    else yield path;
  }
}

test('every colour meaning has a token in styles.css', () => {
  for (const [name, hex] of Object.entries(MEANINGS)) assert.ok(hex, `--color-${name} is missing from styles.css`);
});

test('no source file outside styles.css spells a colour-meaning hex', () => {
  const hexes = Object.values(MEANINGS).map((hex) => hex.toLowerCase());
  const offenders = [];
  for (const path of files(SRC)) {
    const name = relative(SRC, path);
    if (ALLOWED.has(name)) continue;
    const text = readFileSync(path, 'utf8').toLowerCase();
    for (const hex of hexes) if (text.includes(hex)) offenders.push(`${name}: ${hex}`);
  }
  assert.deepEqual(
    offenders,
    [],
    'use the colour token (bg-version-model, text-sev-high, var(--color-not-official) ...) instead of the hex',
  );
});

test('no source file spells a colour-meaning as rgb() or a Tailwind palette class', () => {
  const rgbs = Object.values(MEANINGS).map((hex) =>
    hex
      .match(/../g)
      .map((x) => Number.parseInt(x, 16))
      .join('[ ,]+'),
  );
  // amber is the repair and no-official notice colour (no token); every other palette family is a meaning or a mistake.
  const palette =
    /\b(?:bg|text|border|ring|fill|stroke|from|to|via|shadow|outline|decoration|accent)-(?:red|orange|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/;
  const offenders = [];
  for (const path of files(SRC)) {
    const name = relative(SRC, path);
    if (ALLOWED.has(name) || !/\.(tsx?|css)$/.test(name)) continue;
    const text = readFileSync(path, 'utf8');
    if (palette.test(text)) offenders.push(`${name}: Tailwind palette class`);
    for (const rgb of rgbs) if (new RegExp(`rgba?\\(\\s*${rgb}`).test(text)) offenders.push(`${name}: rgb(${rgb})`);
  }
  assert.deepEqual(offenders, [], 'use the colour token instead');
});

test('the canvas mirrors equal the tokens', () => {
  assert.deepEqual(severityChartColor, { high: MEANINGS['sev-high'], medium: MEANINGS['sev-medium'], low: MEANINGS['sev-low'] });
  assert.equal(CHART_COLORS.official, MEANINGS['version-official']);
  assert.equal(CHART_COLORS.notOfficial, MEANINGS['not-official']);
});

test('severity and threat level share one band mapping: 5 and 4 high, 3 medium, 2 and 1 low', () => {
  assert.deepEqual([5, 4, 3, 2, 1].map(levelBand), ['high', 'high', 'medium', 'low', 'low']);
  assert.deepEqual([null, undefined, 0].map(levelBand), [null, null, null]);
});

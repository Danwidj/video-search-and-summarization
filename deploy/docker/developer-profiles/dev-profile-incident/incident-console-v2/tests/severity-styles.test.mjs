// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import { severityChartColor, severityClass, severityStyle } from '../src/lib/ui/severity.ts';

// Helper to calculate relative luminance according to WCAG 2.1 specs
function relativeLuminance(hex) {
  const rgb = hex
    .replace('#', '')
    .match(/.{2}/g)
    .map((x) => parseInt(x, 16) / 255);
  const a = rgb.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
}

// Helper to calculate WCAG contrast ratio between two hex colors
function contrastRatio(hex1, hex2) {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

const mixWithWhite = (hex, share) =>
  `#${hex
    .replace('#', '')
    .match(/.{2}/g)
    .map((x) =>
      Math.round(parseInt(x, 16) * share + 255 * (1 - share))
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;

test('severity and threat levels map to the three bands: 5 and 4 high, 3 medium, 2 and 1 low', () => {
  assert.deepEqual([5, 4, 3, 2, 1].map(severityClass), [
    'sev-pill-high',
    'sev-pill-high',
    'sev-pill-medium',
    'sev-pill-low',
    'sev-pill-low',
  ]);
});

test('each band is distinguishable from the others', () => {
  assert.equal(new Set([5, 3, 1].map(severityClass)).size, 3);
});

test('each band pill text (its token on a 12% tint of itself) satisfies WCAG AA', () => {
  for (const hex of Object.values(severityChartColor)) {
    const ratio = contrastRatio(hex, mixWithWhite(hex, 0.12));
    assert.ok(ratio >= 4.5, `${hex} on its tint is ${ratio.toFixed(2)}:1`);
  }
});

test('the pill classes derive tint and border from the band token with color-mix', () => {
  const css = readFileSync(join(process.cwd(), 'src', 'app', 'styles.css'), 'utf8');
  for (const band of ['high', 'medium', 'low'])
    assert.match(css, new RegExp(`\\.sev-pill-${band} \\{\\s*--sev: var\\(--color-sev-${band}\\)`));
  assert.match(css, /background-color: color-mix\(in oklab, var\(--sev\) 12%, white\)/);
});

test('null, undefined and non-positive levels fall back to a neutral style', () => {
  for (const invalid of [null, undefined, 0, -1]) assert.ok(!severityClass(invalid).includes('sev-pill'));
});

test('severityStyle alias matches severityClass', () => {
  assert.equal(severityStyle, severityClass);
});

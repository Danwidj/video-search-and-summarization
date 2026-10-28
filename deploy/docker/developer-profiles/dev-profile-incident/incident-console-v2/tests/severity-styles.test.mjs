// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import test from 'node:test';

import { severityClass, severityStyle } from '../src/lib/ui/severity.ts';

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

function extractHex(className, prefix) {
  const match = className.match(new RegExp(`${prefix}-\\[(#?[0-9a-fA-F]+)\\]`));
  return match ? match[1] : null;
}

test('severityClass returns solid, opaque styles with border for each level 1-5', () => {
  for (let level = 1; level <= 5; level++) {
    const cls = severityClass(level);
    assert.ok(cls.includes('border'), `level ${level} must have border utility`);
    assert.ok(cls.includes('bg-['), `level ${level} must have solid hex background: ${cls}`);
    assert.ok(!cls.includes('/'), `level ${level} must not contain alpha/opacity slash: ${cls}`);

    const bg = extractHex(cls, 'bg');
    const border = extractHex(cls, 'border');
    const text = extractHex(cls, 'text');

    assert.ok(bg && /^#[0-9a-fA-F]{6}$/.test(bg), `level ${level} must have 6-digit hex bg: ${bg}`);
    assert.ok(border && /^#[0-9a-fA-F]{6}$/.test(border), `level ${level} must have 6-digit hex border: ${border}`);
    assert.ok(text && /^#[0-9a-fA-F]{6}$/.test(text), `level ${level} must have 6-digit hex text: ${text}`);

    const ratio = contrastRatio(bg, text);
    assert.ok(ratio >= 4.5, `level ${level} contrast ratio ${ratio.toFixed(2)} must satisfy WCAG AA (>= 4.5:1)`);
  }
});

test('each severity level 1-5 is distinguishable from one another', () => {
  const styles = [1, 2, 3, 4, 5].map((lvl) => severityClass(lvl));
  const uniqueStyles = new Set(styles);
  assert.equal(uniqueStyles.size, 5, 'all 5 severity levels must have distinct styles');
});

test('existing colour family per severity is preserved', () => {
  // Low severity (1 and 2): green family (moss text #174f3b)
  assert.equal(extractHex(severityClass(1), 'text'), '#174f3b');
  assert.equal(extractHex(severityClass(2), 'text'), '#174f3b');

  // Medium severity (3): amber family (#765300 text and #fff1c7 bg)
  assert.equal(extractHex(severityClass(3), 'text'), '#765300');
  assert.equal(extractHex(severityClass(3), 'bg'), '#fff1c7');

  // High severity (4 and 5): red/coral family (#9b3518 text and #ffe8df bg for 4, deep red for 5)
  assert.equal(extractHex(severityClass(4), 'text'), '#9b3518');
  assert.equal(extractHex(severityClass(4), 'bg'), '#ffe8df');
  assert.equal(extractHex(severityClass(5), 'text'), '#991b1b');
});

test('null, undefined, and non-positive levels fall back to a clean solid style', () => {
  for (const invalid of [null, undefined, 0, -1]) {
    const cls = severityClass(invalid);
    assert.ok(!cls.includes('/'), `invalid level ${invalid} must not be semi-transparent`);
    assert.ok(cls.includes('border'), `invalid level ${invalid} must have border`);
    const bg = extractHex(cls, 'bg');
    const text = extractHex(cls, 'text');
    assert.ok(contrastRatio(bg, text) >= 4.5, 'fallback style must satisfy WCAG AA');
  }
});

test('severityStyle alias matches severityClass', () => {
  assert.equal(severityStyle, severityClass);
});

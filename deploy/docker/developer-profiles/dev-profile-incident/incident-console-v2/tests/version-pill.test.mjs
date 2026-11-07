// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { versionLabel } from '../src/lib/ui/version-label.ts';

test('the pill text always names the type, and official adds to it', () => {
  assert.equal(versionLabel('ai', false), 'Model');
  assert.equal(versionLabel('human', false), 'Human');
  assert.equal(versionLabel('ai', true), 'Official · Model');
  assert.equal(versionLabel('human', true), 'Official · Human');
});

test('the three colours are theme tokens, official being teal', async () => {
  const css = await readFile(new URL('../src/app/styles.css', import.meta.url), 'utf8');
  assert.match(css, /--color-version-model: #3f5f8a;/);
  assert.match(css, /--color-version-human: #7a4e8c;/);
  assert.match(css, /--color-version-official: #0b7a8f;/);
});

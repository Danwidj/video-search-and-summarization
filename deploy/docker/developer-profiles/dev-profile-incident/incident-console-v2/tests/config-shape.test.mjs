// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('client-facing source does not reference service credentials', async () => {
  const source = await readFile(new URL('../components/health-strip.tsx', import.meta.url), 'utf8');
  assert.equal(source.includes('SERVICE_ROLE_KEY'), false);
  assert.equal(source.includes('R2_SECRET_KEY'), false);
  assert.equal(source.includes('VLM_GATEWAY_API_KEY'), false);
});

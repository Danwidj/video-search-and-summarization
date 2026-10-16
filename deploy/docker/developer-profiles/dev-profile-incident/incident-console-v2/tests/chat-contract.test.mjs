// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import Ajv2020 from 'ajv/dist/2020.js';

const chatContractDir = join(process.cwd(), '..', 'contracts', 'chat-contract-v1');
const requestSchema = JSON.parse(readFileSync(join(chatContractDir, 'chat_request.schema.json'), 'utf8'));
const responseSchema = JSON.parse(readFileSync(join(chatContractDir, 'chat_response.schema.json'), 'utf8'));

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateRequest = ajv.compile(requestSchema);
const validateResponse = ajv.compile(responseSchema);

const fixturesDir = join(chatContractDir, 'fixtures');
const readFixture = (kind, name) => JSON.parse(readFileSync(join(fixturesDir, kind, name), 'utf8'));

test('chat contract VERSION file equals chat-contract-v1', () => {
  const version = readFileSync(join(chatContractDir, 'VERSION'), 'utf8').trim();
  assert.equal(version, 'chat-contract-v1');
});

test('valid request fixtures pass JSON Schema validation', () => {
  for (const name of ['minimal-request.json', 'full-request.json']) {
    const fixture = readFixture('valid', name);
    const valid = validateRequest(fixture);
    assert.equal(valid, true, `Expected ${name} to pass request schema, errors: ${JSON.stringify(validateRequest.errors)}`);
  }
});

test('invalid request fixtures fail JSON Schema validation', () => {
  for (const name of ['request-missing-messages.json', 'request-empty-messages.json', 'request-invalid-scope.json']) {
    const fixture = readFixture('invalid', name);
    const valid = validateRequest(fixture);
    assert.equal(valid, false, `Expected ${name} to fail request schema`);
  }
});

test('valid response fixtures pass JSON Schema validation', () => {
  for (const name of ['empty-response.json', 'full-response.json']) {
    const fixture = readFixture('valid', name);
    const valid = validateResponse(fixture);
    assert.equal(valid, true, `Expected ${name} to pass response schema, errors: ${JSON.stringify(validateResponse.errors)}`);
  }
});

test('invalid response fixtures fail JSON Schema validation', () => {
  for (const name of ['response-missing-session.json', 'response-invalid-role.json', 'response-invalid-citation.json']) {
    const fixture = readFixture('invalid', name);
    const valid = validateResponse(fixture);
    assert.equal(valid, false, `Expected ${name} to fail response schema`);
  }
});

test('response schema enforces grounded citations with timestamp_seconds and crop_image_url', () => {
  const full = readFixture('valid', 'full-response.json');
  assert.equal(full.message.role, 'assistant');
  assert.ok(Array.isArray(full.message.citations));
  assert.ok(full.message.citations.length > 0);

  const cit = full.message.citations[0];
  assert.equal(typeof cit.incident_id, 'string');
  assert.equal(typeof cit.item_id, 'string');
  assert.ok(['entity', 'instrument', 'asset'].includes(cit.item_type));
  assert.equal(typeof cit.timestamp_seconds, 'number');
  assert.ok(cit.timestamp_seconds >= 0);
  assert.equal(typeof cit.crop_image_url, 'string');
});

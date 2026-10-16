// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import Ajv2020 from 'ajv/dist/2020.js';

const searchContractDir = join(process.cwd(), '..', 'contracts', 'search-contract-v1');
const requestSchema = JSON.parse(readFileSync(join(searchContractDir, 'search_request.schema.json'), 'utf8'));
const responseSchema = JSON.parse(readFileSync(join(searchContractDir, 'search_response.schema.json'), 'utf8'));

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateRequest = ajv.compile(requestSchema);
const validateResponse = ajv.compile(responseSchema);

const fixturesDir = join(searchContractDir, 'fixtures');
const readFixture = (kind, name) => JSON.parse(readFileSync(join(fixturesDir, kind, name), 'utf8'));

test('search contract VERSION file equals search-contract-v1', () => {
  const version = readFileSync(join(searchContractDir, 'VERSION'), 'utf8').trim();
  assert.equal(version, 'search-contract-v1');
});

test('valid request fixtures pass JSON Schema validation', () => {
  for (const name of ['minimal-request.json', 'full-request.json']) {
    const fixture = readFixture('valid', name);
    const valid = validateRequest(fixture);
    assert.equal(valid, true, `Expected ${name} to pass request schema, errors: ${JSON.stringify(validateRequest.errors)}`);
  }
});

test('invalid request fixtures fail JSON Schema validation', () => {
  for (const name of ['request-missing-query.json', 'request-invalid-top-k.json', 'request-invalid-item-type.json']) {
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
  for (const name of ['response-missing-critic.json', 'response-invalid-verdict.json', 'response-negative-timestamp.json']) {
    const fixture = readFixture('invalid', name);
    const valid = validateResponse(fixture);
    assert.equal(valid, false, `Expected ${name} to fail response schema`);
  }
});

test('response schema enforces pilot constraints: optional bounding_box, required timestamp_seconds, label and critic verdict', () => {
  const full = readFixture('valid', 'full-response.json');
  const hit1 = full.hits[0];
  assert.equal(typeof hit1.item.timestamp_seconds, 'number');
  assert.ok(hit1.item.timestamp_seconds >= 0);
  assert.equal(typeof hit1.item.label, 'string');
  assert.ok(Array.isArray(hit1.item.bounding_box) && hit1.item.bounding_box.length === 4);

  const hit2 = full.hits[1];
  assert.equal(hit2.item.bounding_box, null, 'bounding_box can be null when detector crop is unboxed');
  assert.equal(hit2.critic.verdict, 'rejected');
});

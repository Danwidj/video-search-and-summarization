// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv/dist/2020.js';

const contractsDir = path.dirname(fileURLToPath(import.meta.url));

function load(filename) {
  return JSON.parse(fs.readFileSync(path.join(contractsDir, filename), 'utf8'));
}

const ajv = new Ajv({ allErrors: true, strict: false });

const searchRequestSchema = load('search-contract-v1/search_request.schema.json');
const searchResponseSchema = load('search-contract-v1/search_response.schema.json');

const requestFixturesValid = ['minimal-request.json', 'full-request.json'].map(name =>
  load(`search-contract-v1/fixtures/valid/${name}`)
);
const requestFixturesInvalid = ['request-missing-query.json', 'request-invalid-top-k.json', 'request-invalid-item-type.json'].map(name =>
  load(`search-contract-v1/fixtures/invalid/${name}`)
);
const responseFixturesValid = ['empty-response.json', 'full-response.json'].map(name =>
  load(`search-contract-v1/fixtures/valid/${name}`)
);
const responseFixturesInvalid = ['response-missing-critic.json', 'response-invalid-verdict.json', 'response-negative-timestamp.json'].map(name =>
  load(`search-contract-v1/fixtures/invalid/${name}`)
);

function validateRequest(fixture) {
  return ajv.compile(searchRequestSchema)(fixture);
}

function validateResponse(fixture) {
  return ajv.compile(searchResponseSchema)(fixture);
}

// Search contract v1: valid request fixtures
console.log('=== Search request: valid fixtures ===');
for (const fixture of requestFixturesValid) {
  const valid = validateRequest(fixture);
  assert.ok(valid, 'request fixture should be valid');
  console.log('  PASS:', fixture.query || 'minimal');
}

// Search contract v1: invalid request fixtures
console.log('=== Search request: invalid fixtures ===');
for (const fixture of requestFixturesInvalid) {
  const valid = validateRequest(fixture);
  assert.ok(!valid, 'request fixture should be invalid');
  console.log('  PASS (rejected)');
}

// Search contract v1: valid response fixtures
console.log('=== Search response: valid fixtures ===');
for (const fixture of responseFixturesValid) {
  const valid = validateResponse(fixture);
  assert.ok(valid, 'response fixture should be valid');
  console.log('  PASS: total_hits=' + fixture.total_hits);
}

// Search contract v1: invalid response fixtures
console.log('=== Search response: invalid fixtures ===');
for (const fixture of responseFixturesInvalid) {
  const valid = validateResponse(fixture);
  assert.ok(!valid, 'response fixture should be invalid');
  console.log('  PASS (rejected)');
}

// Pilot constraints: timestamp_seconds, label, bounding_box, critic
console.log('=== Pilot constraints ===');
const fullResponse = load('search-contract-v1/fixtures/valid/full-response.json');
for (const hit of fullResponse.hits) {
  const item = hit.item;
  assert.ok(typeof item.timestamp_seconds === 'number', 'timestamp_seconds must be number');
  assert.ok(item.timestamp_seconds >= 0, 'timestamp_seconds must be >= 0');
  assert.ok(typeof item.label === 'string', 'label must be string');
  assert.ok(typeof item.crop_image_url === 'string', 'crop_image_url must be string');
  assert.ok(
    hit.critic.verdict === 'confirmed' || hit.critic.verdict === 'rejected' || hit.critic.verdict === 'unverified',
    'critic verdict must be enum'
  );
  // bounding_box optional: null or 4-int array
  if (item.bounding_box !== null && item.bounding_box !== undefined) {
    assert.ok(Array.isArray(item.bounding_box) && item.bounding_box.length === 4, 'bounding_box must be null or [4]ints');
  }
}
console.log('  PASS: all pilot constraints satisfied');

// Incident contract v3: schema has required fields
console.log('=== Incident contract v3 schema ===');
const incidentSchema = load('incident_report.schema.json');

// Check entities have timestamp_seconds and label
const entityProps = incidentSchema.properties.entities.items.properties;
assert.ok('timestamp_seconds' in entityProps, 'entities must have timestamp_seconds');
assert.ok('label' in entityProps, 'entities must have label');
assert.ok(entityProps.timestamp_seconds.minimum === 0, 'timestamp_seconds min must be 0');
for (const key of ['first_seen_seconds', 'last_seen_seconds']) {
  assert.ok(entityProps[key]?.type === 'integer' && entityProps[key].minimum === 0, `entities must have integer ${key} >= 0`);
  assert.ok(incidentSchema.properties.entities.items.required.includes(key), `${key} must be required`);
}

// Check instruments have timestamp_seconds and label
const instrumentProps = incidentSchema.properties.instruments.items.properties;
assert.ok('timestamp_seconds' in instrumentProps, 'instruments must have timestamp_seconds');
assert.ok('label' in instrumentProps, 'instruments must have label');
assert.ok(instrumentProps.timestamp_seconds.minimum === 0, 'timestamp_seconds min must be 0');

// Check assets have timestamp_seconds and label
const assetProps = incidentSchema.properties.assets.items.properties;
assert.ok('timestamp_seconds' in assetProps, 'assets must have timestamp_seconds');
assert.ok('label' in assetProps, 'assets must have label');
assert.ok(assetProps.timestamp_seconds.minimum === 0, 'timestamp_seconds min must be 0');

// Check NO bounding_box in entities/instruments/assets
for (const key of ['entities', 'instruments', 'assets']) {
  const bbKey = 'bounding_box';
  assert.ok(!(bbKey in incidentSchema.properties[key].items.properties), (
    `${key} must NOT have bounding_box in incident-contract-v4`
  ));
}
console.log('  PASS: incident-contract-v4 schema has required fields, no bounding_box');

// VERSION file
console.log('=== VERSION file ===');
const version = fs.readFileSync(path.join(contractsDir, 'VERSION'), 'utf8').trim();
assert.strictEqual(version, 'incident-contract-v4', 'VERSION must be incident-contract-v4');
console.log('  PASS: VERSION = incident-contract-v4');

console.log('\n=== ALL TESTS PASSED ===');
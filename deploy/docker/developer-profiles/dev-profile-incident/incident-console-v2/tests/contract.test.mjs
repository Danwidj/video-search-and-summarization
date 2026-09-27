// SPDX-License-Identifier: Apache-2.0

// The console validates model output against the same contracts/ files as eval and vss-agent.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const contract = await import('../lib/analysis/contract.ts');
const { CONTRACT_KEYS, INCIDENT_TYPES, ENTITY_TYPES } = await import('../lib/analysis/contract-types.ts');

const OUTPUT = {
  incident: {
    type: 'burglary', title: 'Break-in at a shop', start_timestamp: 1, end_timestamp: 6, description: 'E1 forces the door.',
    severity_level: 2, severity_reason: 'Property damage only.', confidence_score: null, location: null,
  },
  entities: [{ entity_id: 'E1', type: 'human', description: 'Person in a hood.' }],
  instruments: [{ instrument_id: 'I1', entity_id: 'E1', name: 'crowbar', description: 'Used on the door.', threat_level: 3 }],
  assets: [{ asset_id: 'A1', name: 'door', description: 'Forced open.' }],
  timeline: [{ start_seconds: 1, end_seconds: 6, description: 'E1 forces A1 with I1.' }],
  uncertainties: [],
};
const clone = () => JSON.parse(JSON.stringify(OUTPUT));

test('types and constants mirror the schema file', async () => {
  const schema = JSON.parse(await readFile(new URL('../../contracts/incident_report.schema.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(schema.properties), [...CONTRACT_KEYS]);
  assert.deepEqual(schema.properties.incident.properties.type.enum, [...INCIDENT_TYPES]);
  assert.deepEqual(schema.properties.entities.items.properties.type.enum, [...ENTITY_TYPES]);
  assert.equal(schema.properties.incident.properties.duration, undefined);
  assert.equal(contract.contractVersion(), (await readFile(new URL('../../contracts/VERSION', import.meta.url), 'utf8')).trim());
});

test('valid output parses and duration is derived by code', () => {
  const report = contract.parseContractContent(JSON.stringify(OUTPUT));
  assert.equal(report.incident.duration, 5);
});

for (const [name, content] of [
  ['empty content', ''],
  ['fenced JSON', '```json\n' + JSON.stringify(OUTPUT) + '\n```'],
  ['prose around JSON', 'Here you go: ' + JSON.stringify(OUTPUT)],
  ['reasoning before JSON', '<think>hmm</think>' + JSON.stringify(OUTPUT)],
]) {
  test(`no extraction: ${name} is rejected`, () => {
    assert.throws(() => contract.parseContractContent(content), contract.ContractError);
  });
}

for (const [name, mutate, pattern] of [
  ['unknown type', (r) => { r.incident.type = 'fighting'; }, /schema violation/],
  ['model-supplied duration', (r) => { r.incident.duration = 5; }, /schema violation/],
  ['missing title', (r) => { delete r.incident.title; }, /schema violation/],
  ['extra field', (r) => { r.persons = []; }, /schema violation/],
  ['string severity', (r) => { r.incident.severity_level = '2'; }, /schema violation/],
  ['entity type person', (r) => { r.entities[0].type = 'person'; }, /schema violation/],
  ['end before start', (r) => { r.incident.end_timestamp = 0; r.timeline = []; }, /before start_timestamp/],
  ['non-sequential ids', (r) => { r.entities[0].entity_id = 'E2'; r.instruments[0].entity_id = 'E2'; }, /not sequential/],
  ['dangling holder', (r) => { r.instruments[0].entity_id = 'E9'; }, /unknown entity_id/],
  ['timeline outside the window', (r) => { r.timeline[0].start_seconds = 0; }, /outside/],
]) {
  test(`contract violation: ${name}`, () => {
    const value = clone();
    mutate(value);
    assert.throws(() => contract.validateModelOutput(value), (error) => error instanceof contract.ContractError && pattern.test(error.message));
  });
}

test('validateContractReport ignores a stored duration and recomputes it', () => {
  const stored = clone();
  stored.incident.duration = 999;
  assert.equal(contract.validateContractReport(stored).incident.duration, 5);
});

test('response_format is strict and omits schema document keys; request configs come from contracts/', () => {
  const format = contract.responseFormat();
  assert.equal(format.json_schema.strict, true);
  assert.equal(format.json_schema.schema.$schema, undefined);
  assert.equal(format.json_schema.schema.$id, undefined);
  assert.deepEqual(contract.p1Request(), { temperature: 0, max_tokens: 16384, media_io_kwargs: { video: { num_frames: 64 } } });
  assert.equal(contract.rp1Request().model, 'nvidia/nemotron-3-nano-30b-a3b');
});

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { ContractError, parseReport, validateReport, withDerivedFields } = await import('../lib/contract/validate.ts');
const { contractVersion, responseFormat, schema, allowedModels, inferenceSettings, promptSha256, schemaSha256 } = await import('../lib/contract/load.ts');

const fixturesDir = join(process.cwd(), '..', 'contracts', 'fixtures');
const fixtures = (kind) => readdirSync(join(fixturesDir, kind)).filter((name) => name.endsWith('.json')).sort();
const readFixture = (kind, name) => JSON.parse(readFileSync(join(fixturesDir, kind, name), 'utf8'));

test('shared contract fixtures exist (the same set eval/tests/test_contract_fixtures.py validates)', () => {
  assert.ok(fixtures('valid').length > 0);
  assert.ok(fixtures('invalid').length > 0);
});

for (const name of fixtures('valid')) {
  test(`valid fixture passes: ${name}`, () => {
    assert.doesNotThrow(() => validateReport(readFixture('valid', name)));
  });
}

for (const name of fixtures('invalid')) {
  test(`invalid fixture is rejected: ${name}`, () => {
    assert.throws(() => validateReport(readFixture('invalid', name)), ContractError);
  });
}

test('invalid fixtures fail for the category their name states', () => {
  for (const name of fixtures('invalid')) {
    const expected = name.startsWith('schema-') ? /^schema violation/ : /^cross-field violation/;
    assert.throws(() => validateReport(readFixture('invalid', name)), (error) => expected.test(error.message), name);
  }
});

test('parseReport is strict: no fence stripping, brace extraction or empty content', () => {
  const valid = JSON.stringify(readFixture('valid', 'full-report.json'));
  assert.throws(() => parseReport('```json\n' + valid + '\n```'), /not a single JSON document/);
  assert.throws(() => parseReport('Here is the report: ' + valid), /not a single JSON document/);
  assert.throws(() => parseReport(''), /empty response content/);
  assert.throws(() => parseReport(null), /empty response content/);
});

test('parseReport derives incident.duration from the validated timestamps', () => {
  const report = parseReport(JSON.stringify(readFixture('valid', 'full-report.json')));
  assert.equal(report.incident.duration, 8);
  assert.equal(withDerivedFields(readFixture('valid', 'minimal-report.json')).incident.duration, 0);
});

test('responseFormat() equals the Python contract.response_format() output', () => {
  const expected = JSON.parse(readFileSync(join(fixturesDir, 'response_format.json'), 'utf8'));
  assert.deepEqual(responseFormat(), expected);
});

test('contract version, hashes and inference settings load from contracts/', () => {
  assert.equal(contractVersion(), readFileSync(join(process.cwd(), '..', 'contracts', 'VERSION'), 'utf8').trim());
  assert.match(promptSha256(), /^[0-9a-f]{64}$/);
  assert.match(schemaSha256(), /^[0-9a-f]{64}$/);
  assert.deepEqual(allowedModels().map((model) => model.id), [
    'nvidia/cosmos-3-nano-reasoner',
    'nvidia/cosmos-3-super-reasoner',
    'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning',
  ]);
  assert.deepEqual(inferenceSettings().p1, { temperature: 0, max_tokens: 16384, media_io_kwargs: { video: { num_frames: 64 } } });
});

test('lib/contract/types.ts keys match the schema file', () => {
  const source = readFileSync(join(process.cwd(), 'lib', 'contract', 'types.ts'), 'utf8');
  const interfaceKeys = (name) => {
    const body = source.match(new RegExp(`interface ${name} \\{([^}]*)\\}`))[1];
    return [...body.matchAll(/^\s+(\w+)\??:/gm)].map((match) => match[1]).sort();
  };
  const properties = schema().properties;
  assert.deepEqual(interfaceKeys('IncidentContractReport'), Object.keys(properties).sort());
  assert.deepEqual(interfaceKeys('ContractIncident'), Object.keys(properties.incident.properties).sort());
  assert.deepEqual(interfaceKeys('ContractEntity'), Object.keys(properties.entities.items.properties).sort());
  assert.deepEqual(interfaceKeys('ContractInstrument'), Object.keys(properties.instruments.items.properties).sort());
  assert.deepEqual(interfaceKeys('ContractAsset'), Object.keys(properties.assets.items.properties).sort());
  assert.deepEqual(interfaceKeys('ContractTimelineEvent'), Object.keys(properties.timeline.items.properties).sort());
});

test('INCIDENT_TYPES and ENTITY_TYPES match the schema enums', async () => {
  const { INCIDENT_TYPES, ENTITY_TYPES } = await import('../lib/contract/types.ts');
  const properties = schema().properties;
  assert.deepEqual([...INCIDENT_TYPES], properties.incident.properties.type.enum);
  assert.deepEqual([...ENTITY_TYPES], properties.entities.items.properties.type.enum);
});

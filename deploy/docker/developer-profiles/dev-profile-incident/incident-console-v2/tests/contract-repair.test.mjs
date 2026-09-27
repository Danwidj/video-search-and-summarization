// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { attemptIdNormalization, REPAIR_RULE_SET } = await import('../lib/contract/repair.ts');
const { ContractError, validateReport } = await import('../lib/contract/validate.ts');
const { evaluateContent } = await import('../lib/analysis/run-contract-analysis.ts');

const fixture = (name) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-failures', name), 'utf8'));
const validReport = () => JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'full-report.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));

function violationsOf(report) {
  try {
    validateReport(report);
    return [];
  } catch (error) {
    assert.ok(error instanceof ContractError);
    return error.violations;
  }
}

/** Every field except identifiers and list order must be unchanged. */
function assertOnlyIdsChanged(before, after) {
  assert.deepEqual(after.incident, before.incident);
  assert.deepEqual(after.timeline, before.timeline);
  assert.deepEqual(after.uncertainties, before.uncertainties);
  const content = (items, drop) => items.map((item) => JSON.stringify(Object.fromEntries(Object.entries(item).filter(([key]) => !drop.includes(key))))).sort();
  assert.deepEqual(content(after.entities, ['entity_id']), content(before.entities, ['entity_id']));
  assert.deepEqual(content(after.instruments, ['instrument_id', 'entity_id']), content(before.instruments, ['instrument_id', 'entity_id']));
  assert.deepEqual(content(after.assets, ['asset_id']), content(before.assets, ['asset_id']));
}

test('real Nemotron response (E2,E1 and instrument id ",") is repaired by reorder + one rename, then passes strict validation', () => {
  const { rawContent } = fixture('nemotron-3-omni-malformed-ids.json');
  const outcome = evaluateContent(rawContent);
  assert.equal(outcome.kind, 'valid');
  assert.deepEqual(outcome.firstPass.map((v) => v.code).sort(), ['ID_NOT_SEQUENTIAL_ENTITY', 'ID_NOT_SEQUENTIAL_INSTRUMENT']);
  assert.equal(outcome.repair.ruleSet, REPAIR_RULE_SET);
  assert.deepEqual(outcome.repair.operations, [
    { op: 'reorder', collection: 'entities', from: ['E2', 'E1'], to: ['E1', 'E2'] },
    { op: 'rename-id', collection: 'instruments', from: ',', to: 'I2' },
  ]);
  assert.deepEqual(outcome.repair.revalidation, []);
  const original = JSON.parse(rawContent);
  assertOnlyIdsChanged(original, outcome.report);
  assert.deepEqual(outcome.report.entities.map((e) => [e.entity_id, e.description]), [
    ['E1', 'Person attacking victim with object'],
    ['E2', 'Person walking on sidewalk, becomes victim of assault'],
  ]);
  assert.equal(outcome.report.instruments.find((i) => i.name === 'bag').entity_id, 'E1', 'the bag is still held by the attacker');
});

test('real Cosmos Super response (timeline outside the incident window) is not eligible and stays contract_failed', () => {
  const { rawContent } = fixture('cosmos-3-super-timeline-window.json');
  const outcome = evaluateContent(rawContent);
  assert.equal(outcome.kind, 'contract_failed');
  assert.equal(outcome.stage, 'contract_validation');
  assert.equal(outcome.repair.eligible, false);
  assert.equal(outcome.repair.reason, 'INELIGIBLE_VIOLATION');
  assert.deepEqual(outcome.repair.blockingCodes.sort(), ['TIMELINE_END_OUTSIDE_WINDOW', 'TIMELINE_START_OUTSIDE_WINDOW']);
});

test('one ineligible violation blocks repair even when ID violations are also present', () => {
  const report = validReport();
  report.entities.reverse();
  report.timeline[1].end_seconds = 99;
  const result = attemptIdNormalization(report, violationsOf(report));
  assert.equal(result.eligible, false);
  assert.deepEqual(result.blockingCodes, ['TIMELINE_END_OUTSIDE_WINDOW']);
});

test('schema violations, invalid JSON and empty content are never repaired', () => {
  const schemaBroken = validReport();
  schemaBroken.entities[0].entity_id = 7;
  for (const content of [JSON.stringify(schemaBroken), '{"incident":', '']) {
    const outcome = evaluateContent(content);
    assert.equal(outcome.kind, 'contract_failed');
    assert.equal(outcome.repair.eligible, false);
  }
});

test('an out-of-range well-formed ID is renamed only when neither it nor its target appears in free text', () => {
  const report = withoutIdMentions(validReport());
  report.assets.push({ asset_id: 'A5', name: 'shelf', description: 'A metal shelf.' });
  const repaired = attemptIdNormalization(report, violationsOf(report));
  assert.equal(repaired.eligible, true);
  assert.deepEqual(repaired.operations, [{ op: 'rename-id', collection: 'assets', from: 'A5', to: 'A2' }]);
  assert.doesNotThrow(() => validateReport(repaired.repaired));
  assertOnlyIdsChanged(report, repaired.repaired);

  const mentioned = clone(report);
  mentioned.uncertainties.push('Whether A5 was damaged is unclear.');
  assert.equal(attemptIdNormalization(mentioned, violationsOf(mentioned)).reason, 'RENAMED_ID_IN_FREE_TEXT');

  const targetMentioned = clone(report);
  targetMentioned.incident.description += ' A2 is mentioned here.';
  assert.equal(attemptIdNormalization(targetMentioned, violationsOf(targetMentioned)).reason, 'TARGET_ID_IN_FREE_TEXT');
});

/** The valid fixture's free text names E1/E2/I1; strip those mentions for rename cases. */
function withoutIdMentions(report) {
  const scrub = (text) => text.replace(/\b[EIA][0-9]+\b/g, 'someone');
  report.incident.description = scrub(report.incident.description);
  report.assets.forEach((asset) => { asset.description = scrub(asset.description); });
  report.timeline.forEach((event) => { event.description = scrub(event.description); });
  report.uncertainties = report.uncertainties.map(scrub);
  return report;
}

test('renaming onto an ID that free text already mentions is refused (TARGET_ID_IN_FREE_TEXT)', () => {
  const report = validReport();
  report.entities[0].entity_id = 'e1';
  report.instruments[0].entity_id = 'e1';
  assert.equal(attemptIdNormalization(report, violationsOf(report)).reason, 'TARGET_ID_IN_FREE_TEXT');
});

test('a renamed entity carries its holder reference with it; relationships are preserved', () => {
  const report = withoutIdMentions(validReport());
  report.entities[0].entity_id = 'e1';
  report.instruments[0].entity_id = 'e1';
  const result = attemptIdNormalization(report, violationsOf(report));
  assert.equal(result.eligible, true);
  assert.deepEqual(result.operations, [
    { op: 'rename-id', collection: 'entities', from: 'e1', to: 'E1' },
    { op: 'remap-reference', path: 'instruments/0/entity_id', from: 'e1', to: 'E1' },
  ]);
  assert.equal(result.repaired.instruments[0].entity_id, 'E1');
  assert.doesNotThrow(() => validateReport(result.repaired));
});

test('a lowercase malformed ID that free text mentions is not renamed (free text is never edited)', () => {
  const report = withoutIdMentions(validReport());
  report.entities[0].entity_id = 'e1';
  report.instruments[0].entity_id = 'e1';
  report.timeline[0].description = 'e1 approaches E2.';
  assert.equal(attemptIdNormalization(report, violationsOf(report)).reason, 'RENAMED_ID_IN_FREE_TEXT');
});

test('duplicate IDs and unresolvable holders are ineligible', () => {
  const duplicate = validReport();
  duplicate.entities[1].entity_id = 'E1';
  duplicate.entities.push({ entity_id: 'E3', type: 'unknown', description: 'Third.' });
  assert.equal(attemptIdNormalization(duplicate, violationsOf(duplicate)).reason, 'DUPLICATE_ID');

  const holder = validReport();
  holder.instruments[0].entity_id = 'E9';
  const result = attemptIdNormalization(holder, violationsOf(holder));
  assert.equal(result.eligible, false);
  assert.ok(['INELIGIBLE_VIOLATION', 'INSTRUMENT_HOLDER_UNRESOLVABLE'].includes(result.reason));
});

test('a valid report is not touched', () => {
  const outcome = evaluateContent(JSON.stringify(validReport()));
  assert.equal(outcome.kind, 'valid');
  assert.equal(outcome.repair, null);
  assert.deepEqual(outcome.firstPass, []);
});

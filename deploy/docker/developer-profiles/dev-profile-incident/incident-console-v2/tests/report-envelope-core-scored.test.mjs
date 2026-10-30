// SPDX-License-Identifier: Apache-2.0

// Regression: analyses are accepted and stored under validation policy core-scored-v1, which allows timeline
// enrichment violations. A camera holding such a stored analysis is shown on the report page, unchanged; a core
// violation still hides it.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

await import('../src/modules/contract/infrastructure/loader.ts');
const envelope = await import('../src/modules/reports/domain/envelope.ts');
const validate = await import('../src/modules/contract/domain/validate.ts');

const modelReport = JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'minimal-report.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));

/** A stored analysis (derived incident.duration included) whose first timeline event starts after the incident window ends. */
const storedWithEnrichmentViolation = () => {
  const report = clone(modelReport);
  report.incident.duration = report.incident.end_timestamp - report.incident.start_timestamp;
  report.timeline[0].start_seconds = report.incident.end_timestamp + 5;
  return report;
};

const parse = (report) => envelope.parseEnvelope({ overview: {}, cameras: [{ video: 'front.mp4', report }] });

test('the fixture is accepted by core-scored-v1 but rejected by the full contract', () => {
  const model = validate.withoutDerivedFields(storedWithEnrichmentViolation());
  assert.equal(validate.validateCore(model).enrichment.length > 0, true);
  assert.throws(() => validate.validateReport(model), /TIMELINE|timeline\[0\]\.start_seconds/);
});

test('cameraReport shows a camera whose stored analysis has a timeline enrichment violation, unchanged', () => {
  const stored = storedWithEnrichmentViolation();
  const parsed = parse(stored);
  assert.deepEqual(envelope.cameraReport(parsed, 'front.mp4'), storedWithEnrichmentViolation());
  assert.equal(envelope.firstValidCamera(parsed), 'front.mp4');
});

test('cameraReport still hides a camera with a core violation', () => {
  const broken = storedWithEnrichmentViolation();
  broken.incident.start_timestamp = broken.incident.end_timestamp + 1;
  assert.equal(envelope.cameraReport(parse(broken), 'front.mp4'), null);
});

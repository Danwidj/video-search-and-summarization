// SPDX-License-Identifier: Apache-2.0

// Regression: a camera whose stored report is shaped like an analyse payload
// (the contract report plus the derived incident.duration that analyse adds)
// counts as valid on the report page, and its stored report is shown unchanged.

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

/** A stored per-video analysis: the model's report plus the derived incident.duration analyse adds. */
const storedAnalysis = () => {
  const report = clone(modelReport);
  report.incident.duration = report.incident.end_timestamp - report.incident.start_timestamp;
  return report;
};

test('the stored analysis shape is rejected by the strict contract validator', () => {
  assert.throws(() => validate.validateReport(storedAnalysis()), /incident: must NOT have additional properties \(duration\)/);
});

test('withoutDerivedFields removes incident.duration and leaves everything else and the input alone', () => {
  const stored = storedAnalysis();
  const before = clone(stored);
  const model = validate.withoutDerivedFields(stored);
  assert.deepEqual(model, modelReport);
  assert.deepEqual(stored, before);
  for (const junk of [null, 'x', [], {}, { incident: 'broken' }, { incident: [] }]) {
    assert.deepEqual(validate.withoutDerivedFields(junk), junk);
  }
});

test('cameraReport counts a camera with a stored analysis as valid and returns the stored report unchanged', () => {
  const parsed = envelope.parseEnvelope({
    overview: { title: 'Fight', type: 'assault', severity_level: 3, description: 'd', location: null },
    cameras: [
      { video: 'front.mp4', report: storedAnalysis() },
      { video: 'back.mp4', report: storedAnalysis() },
    ],
  });
  assert.deepEqual(envelope.cameraReport(parsed, 'front.mp4'), storedAnalysis());
  assert.deepEqual(envelope.cameraReport(parsed, 'back.mp4'), storedAnalysis());
  assert.equal(envelope.firstValidCamera(parsed), 'front.mp4');
  assert.equal(envelope.firstValidCamera(parsed, ['back.mp4']), 'back.mp4');
});

test('cameraReport still rejects a stored analysis whose model-shaped part is invalid', () => {
  const broken = storedAnalysis();
  delete broken.incident.title;
  const parsed = envelope.parseEnvelope({ overview: {}, cameras: [{ video: 'front.mp4', report: broken }] });
  assert.equal(envelope.cameraReport(parsed, 'front.mp4'), null);
  assert.equal(envelope.firstValidCamera(parsed), null);
});

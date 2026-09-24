import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { parseIncidentAnalysis } = await import('../lib/analysis/parse.ts');

function reportWithThreatLevel(threatLevel) {
  return JSON.stringify({
    title: 'Test incident',
    incidentType: 'other',
    summary: 'A visible event occurred.',
    startTimestamp: null,
    endTimestamp: null,
    durationSeconds: null,
    severityLevel: 1,
    severityReason: 'Limited visible impact.',
    confidenceScore: 0.5,
    timeline: [],
    entities: [],
    instruments: [{ name: 'Object', description: 'Visible object', threatLevel }],
    assets: [],
    uncertainties: ['Details are limited.'],
  });
}

test('parseIncidentAnalysis normalizes numeric threat-level strings', () => {
  const report = parseIncidentAnalysis(reportWithThreatLevel('3'));
  assert.equal(report.instruments[0].threatLevel, 3);
});

test('parseIncidentAnalysis still rejects non-numeric threat levels', () => {
  assert.throws(() => parseIncidentAnalysis(reportWithThreatLevel('high')), /Expected number/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { incidentAnalysisSchema } from '../lib/analysis/schema.ts';
import { INCIDENT_ANALYSIS_PROMPT, INCIDENT_PROMPT_VERSION } from '../lib/analysis/prompt.ts';

const contractPath = join(process.cwd(), 'lib/analysis/incident-report-contract.json');
const contract = JSON.parse(readFileSync(contractPath, 'utf8'));

test('contract-parity: incident-report-contract.json defines expected fields and types', () => {
  assert.ok(contract.fields, 'contract must have fields');

  const expectedFields = [
    'title',
    'incident_type',
    'severity',
    'severity_reason',
    'confidence',
    'incident_start',
    'incident_end',
    'incident_start_confirmed',
    'duration_seconds',
    'description',
    'persons',
    'instruments',
    'assets',
    'timeline',
    'uncertainties',
    'location',
  ];

  for (const field of expectedFields) {
    assert.ok(contract.fields[field], `contract must define ${field}`);
  }
  assert.equal(Object.keys(contract.fields).length, expectedFields.length);
});

test('contract-parity: incidentAnalysisSchema validates contract default instance', () => {
  const defaultInstance = {};
  for (const [key, spec] of Object.entries(contract.fields)) {
    if (spec.default !== undefined) {
      defaultInstance[key] = spec.default;
    }
  }

  const parsed = incidentAnalysisSchema.parse(defaultInstance);
  assert.equal(parsed.title, '');
  assert.equal(parsed.incident_type, 'road accident');
  assert.equal(parsed.severity, 1);
  assert.equal(parsed.confidence, 0.0);
  assert.equal(parsed.incident_start, '0:00');
  assert.equal(parsed.incident_end, '0:00');
  assert.equal(parsed.incident_start_confirmed, false);
  assert.equal(parsed.duration_seconds, null);
  assert.deepEqual(parsed.persons, []);
  assert.deepEqual(parsed.instruments, []);
  assert.deepEqual(parsed.assets, []);
  assert.deepEqual(parsed.timeline, []);
  assert.deepEqual(parsed.uncertainties, []);
  assert.equal(parsed.location, '');
});

function promptRuleFields(prompt) {
  const rules = prompt.split('Rules:\n')[1].split('\n\n')[0];
  return rules.split('\n').filter((line) => line.startsWith('- ')).map((line) => line.slice(2).split(/[\s:]/)[0]);
}

function promptShape(prompt) {
  return JSON.parse(prompt.slice(prompt.indexOf('Use exactly this shape:\n') + 'Use exactly this shape:\n'.length));
}

test('contract-parity: INCIDENT_ANALYSIS_PROMPT has one rule per contract field', () => {
  assert.equal(INCIDENT_PROMPT_VERSION, 'incident-v2-snake');
  const fields = promptRuleFields(INCIDENT_ANALYSIS_PROMPT);
  assert.equal(new Set(fields).size, fields.length);
  assert.deepEqual([...fields].sort(), Object.keys(contract.fields).sort());
});

test('contract-parity: INCIDENT_ANALYSIS_PROMPT response shape matches the contract and schema', () => {
  const shape = promptShape(INCIDENT_ANALYSIS_PROMPT);
  assert.deepEqual(Object.keys(shape).sort(), Object.keys(contract.fields).sort());
  const parsed = incidentAnalysisSchema.parse(shape);
  assert.deepEqual(Object.keys(parsed).sort(), Object.keys(contract.fields).sort());
  assert.deepEqual(Object.keys(parsed.timeline[0]).sort(), Object.keys(contract.fields.timeline.items.properties).sort());
  assert.deepEqual(Object.keys(parsed.persons[0]).sort(), Object.keys(contract.fields.persons.items.properties).sort());
  assert.deepEqual(Object.keys(parsed.instruments[0]).sort(), Object.keys(contract.fields.instruments.items.properties).sort());
  assert.deepEqual(Object.keys(parsed.assets[0]).sort(), Object.keys(contract.fields.assets.items.properties).sort());
});

test('contract-parity: full report payload parses into snake_case schema', () => {
  const sampleReport = {
    title: 'Break-in at Warehouse B',
    incident_type: 'burglary',
    severity: 4,
    severity_reason: 'Forced entry with physical theft',
    confidence: 0.95,
    incident_start: '1:15',
    incident_end: '2:30',
    incident_start_confirmed: true,
    duration_seconds: 75,
    description: 'A masked suspect forced open the rear entrance and took electronic equipment.',
    persons: [
      { description: 'Individual in dark clothing', actions: 'Pried door open with crowbar' }
    ],
    instruments: [
      { name: 'crowbar', description: 'Used to force door latch', threat_level: 3 }
    ],
    assets: [
      { name: 'rear entrance door', description: 'Frame damaged and latch broken' }
    ],
    timeline: [
      { start_seconds: 75.5, end_seconds: 90.0, description: 'Suspect approaches door' },
      { start_seconds: 90.0, end_seconds: 150.0, description: 'Suspect enters and takes items' }
    ],
    uncertainties: ['Make and model of getaway vehicle'],
    location: 'Warehouse B - Rear Alley'
  };

  const parsed = incidentAnalysisSchema.parse(sampleReport);
  assert.equal(parsed.title, sampleReport.title);
  assert.equal(parsed.incident_type, 'burglary');
  assert.equal(parsed.severity, 4);
  assert.equal(parsed.severity_reason, sampleReport.severity_reason);
  assert.equal(parsed.confidence, 0.95);
  assert.equal(parsed.incident_start, '1:15');
  assert.equal(parsed.incident_end, '2:30');
  assert.equal(parsed.incident_start_confirmed, true);
  assert.equal(parsed.duration_seconds, 75);
  assert.equal(parsed.description, sampleReport.description);
  assert.equal(parsed.persons.length, 1);
  assert.equal(parsed.persons[0].description, 'Individual in dark clothing');
  assert.equal(parsed.instruments.length, 1);
  assert.equal(parsed.instruments[0].threat_level, 3);
  assert.equal(parsed.assets.length, 1);
  assert.equal(parsed.timeline.length, 2);
  assert.equal(parsed.timeline[0].start_seconds, 75.5);
  assert.equal(parsed.uncertainties.length, 1);
  assert.equal(parsed.location, 'Warehouse B - Rear Alley');
});

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { parseIncidentAnalysis } = await import('../lib/analysis/parse.ts');

function baseReport(overrides = {}) {
  return JSON.stringify({
    title: 'Test incident',
    incident_type: 'road accident',
    description: 'A visible event occurred.',
    incident_start: '0:00',
    incident_end: '0:00',
    incident_start_confirmed: false,
    duration_seconds: null,
    severity: 1,
    severity_reason: 'Limited visible impact.',
    confidence: 0.5,
    timeline: [],
    persons: [],
    instruments: [{ name: 'Object', description: 'Visible object', threat_level: 1 }],
    assets: [],
    uncertainties: ['Details are limited.'],
    location: '',
    ...overrides,
  });
}

test('parseIncidentAnalysis normalizes numeric threat-level strings', () => {
  const report = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: '3' }] }));
  assert.equal(report.instruments[0].threat_level, 3);

  // Backward compatibility with threatLevel
  const reportLegacy = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: '3' }] }));
  assert.equal(reportLegacy.instruments[0].threat_level, 3);
});

test('parseIncidentAnalysis normalizes word threat levels', () => {
  const report = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 'high' }] }));
  assert.equal(report.instruments[0].threat_level, 4);

  const report2 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 'critical' }] }));
  assert.equal(report2.instruments[0].threat_level, 5);

  const report3 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 'medium' }] }));
  assert.equal(report3.instruments[0].threat_level, 3);

  const report4 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 'low' }] }));
  assert.equal(report4.instruments[0].threat_level, 2);

  const report5 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 'none' }] }));
  assert.equal(report5.instruments[0].threat_level, 1);
});

test('parseIncidentAnalysis falls back to null for unrecognized threat levels', () => {
  const report = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 'extreme' }] }));
  assert.equal(report.instruments[0].threat_level, null);

  const report2 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: 99 }] }));
  assert.equal(report2.instruments[0].threat_level, 5); // clamped > 5 to 5 per Pydantic model validator

  const report3 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: -1 }] }));
  assert.equal(report3.instruments[0].threat_level, null); // < 1 mapped to null per Pydantic model validator

  const report4 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threat_level: true }] }));
  assert.equal(report4.instruments[0].threat_level, null); // booleans mapped to null
});

test('parseIncidentAnalysis handles missing fields with defaults matching Pydantic model', () => {
  const minimal = JSON.stringify({});
  const report = parseIncidentAnalysis(minimal);

  assert.equal(report.title, '');
  assert.equal(report.incident_type, 'road accident');
  assert.equal(report.description, '');
  assert.equal(report.incident_start, '0:00');
  assert.equal(report.incident_end, '0:00');
  assert.equal(report.incident_start_confirmed, false);
  assert.equal(report.duration_seconds, null);
  assert.equal(report.severity, 1);
  assert.equal(report.severity_reason, '');
  assert.equal(report.confidence, 0.0);
  assert.deepEqual(report.timeline, []);
  assert.deepEqual(report.persons, []);
  assert.deepEqual(report.instruments, []);
  assert.deepEqual(report.assets, []);
  assert.deepEqual(report.uncertainties, []);
  assert.equal(report.location, '');
});

test('parseIncidentAnalysis truncates long title to 160 chars', () => {
  const longTitle = 'A'.repeat(200);
  const report = parseIncidentAnalysis(baseReport({ title: longTitle }));
  assert.equal(report.title.length, 160);
  assert.equal(report.title, 'A'.repeat(160));
});

test('parseIncidentAnalysis truncates long incident_type to 32 chars', () => {
  const longType = 'B'.repeat(50);
  const report = parseIncidentAnalysis(baseReport({ incident_type: longType }));
  assert.equal(report.incident_type.length, 32);
  assert.equal(report.incident_type, 'B'.repeat(32));
});

test('parseIncidentAnalysis normalizes severity from words', () => {
  const report = parseIncidentAnalysis(baseReport({ severity: 'high' }));
  assert.equal(report.severity, 4);

  const report2 = parseIncidentAnalysis(baseReport({ severity: 'critical' }));
  assert.equal(report2.severity, 5);

  const report3 = parseIncidentAnalysis(baseReport({ severity: 'medium' }));
  assert.equal(report3.severity, 3);

  const report4 = parseIncidentAnalysis(baseReport({ severity: 'low' }));
  assert.equal(report4.severity, 2);

  const report5 = parseIncidentAnalysis(baseReport({ severity: 'none' }));
  assert.equal(report5.severity, 1);
});

test('parseIncidentAnalysis clamps severity to 1-5', () => {
  const report = parseIncidentAnalysis(baseReport({ severity: 10 }));
  assert.equal(report.severity, 5);

  const report2 = parseIncidentAnalysis(baseReport({ severity: 0 }));
  assert.equal(report2.severity, 1);

  const report3 = parseIncidentAnalysis(baseReport({ severity: -5 }));
  assert.equal(report3.severity, 1);
});

test('parseIncidentAnalysis normalizes confidence from percentage', () => {
  const report = parseIncidentAnalysis(baseReport({ confidence: 85 }));
  assert.equal(report.confidence, 0.85);

  const report2 = parseIncidentAnalysis(baseReport({ confidence: '95' }));
  assert.equal(report2.confidence, 0.95);

  const report3 = parseIncidentAnalysis(baseReport({ confidence: 0.7 }));
  assert.equal(report3.confidence, 0.7);
});

test('parseIncidentAnalysis clamps confidence to 0-1', () => {
  const report = parseIncidentAnalysis(baseReport({ confidence: 150 }));
  assert.equal(report.confidence, 1.0);

  const report2 = parseIncidentAnalysis(baseReport({ confidence: -0.5 }));
  assert.equal(report2.confidence, 0.0);
});

test('parseIncidentAnalysis handles timeline with missing/partial fields and unconstrained floats', () => {
  const report = parseIncidentAnalysis(baseReport({
    timeline: [
      { start_seconds: 10.5, end_seconds: 20.25, description: 'Event A' },
      { start_seconds: '30.1', description: 'Event B' },
      { end_seconds: 50.75, description: 'Event C' },
      {},
    ],
  }));

  assert.equal(report.timeline.length, 4);
  assert.equal(report.timeline[0].start_seconds, 10.5);
  assert.equal(report.timeline[0].end_seconds, 20.25);
  assert.equal(report.timeline[0].description, 'Event A');
  assert.equal(report.timeline[1].start_seconds, 30.1);
  assert.equal(report.timeline[1].end_seconds, null);
  assert.equal(report.timeline[1].description, 'Event B');
  assert.equal(report.timeline[2].start_seconds, 0.0);
  assert.equal(report.timeline[2].end_seconds, 50.75);
  assert.equal(report.timeline[2].description, 'Event C');
  assert.equal(report.timeline[3].start_seconds, 0.0);
  assert.equal(report.timeline[3].end_seconds, null);
  assert.equal(report.timeline[3].description, '');
});

test('parseIncidentAnalysis handles persons with actions and description', () => {
  const report = parseIncidentAnalysis(baseReport({
    persons: [
      { description: 'Person A in dark hoodie', actions: 'prying door' },
      { description: 'Driver', actions: 'fleeing on foot' },
      {},
    ],
  }));

  assert.equal(report.persons.length, 3);
  assert.equal(report.persons[0].description, 'Person A in dark hoodie');
  assert.equal(report.persons[0].actions, 'prying door');
  assert.equal(report.persons[1].description, 'Driver');
  assert.equal(report.persons[1].actions, 'fleeing on foot');
  assert.equal(report.persons[2].description, '');
  assert.equal(report.persons[2].actions, '');
});

test('parseIncidentAnalysis maps legacy entities array to persons if persons is omitted', () => {
  const report = parseIncidentAnalysis(baseReport({
    persons: undefined,
    entities: [
      { type: 'human', description: 'Suspect in hoodie' },
      { type: 'animal', description: 'Guard dog' },
    ],
  }));

  assert.equal(report.persons.length, 2);
  assert.equal(report.persons[0].description, 'Suspect in hoodie');
  assert.equal(report.persons[0].actions, '');
  assert.equal(report.persons[1].description, 'Guard dog');
  assert.equal(report.persons[1].actions, '');
});

test('parseIncidentAnalysis handles empty arrays and null arrays', () => {
  const report = parseIncidentAnalysis(baseReport({
    timeline: null,
    persons: null,
    instruments: null,
    assets: null,
    uncertainties: null,
  }));

  assert.deepEqual(report.timeline, []);
  assert.deepEqual(report.persons, []);
  assert.deepEqual(report.instruments, []);
  assert.deepEqual(report.assets, []);
  assert.deepEqual(report.uncertainties, []);
});

test('parseIncidentAnalysis allows extra unknown fields', () => {
  const report = parseIncidentAnalysis(baseReport({
    extraField: 'should not crash',
    anotherExtra: 123,
    nested: { foo: 'bar' },
  }));

  assert.equal(report.title, 'Test incident');
});

test('parseIncidentAnalysis handles instruments with missing threat_level', () => {
  const report = parseIncidentAnalysis(baseReport({
    instruments: [
      { name: 'Tool', description: 'A tool' },
      { name: 'Weapon', description: 'A weapon', threat_level: 'high' },
    ],
  }));

  assert.equal(report.instruments.length, 2);
  assert.equal(report.instruments[0].threat_level, null);
  assert.equal(report.instruments[1].threat_level, 4);
});

test('parseIncidentAnalysis handles duration_seconds coercion', () => {
  const report = parseIncidentAnalysis(baseReport({ duration_seconds: '45' }));
  assert.equal(report.duration_seconds, 45);

  const report2 = parseIncidentAnalysis(baseReport({ duration_seconds: -10 }));
  assert.equal(report2.duration_seconds, null);

  const report3 = parseIncidentAnalysis(baseReport({ duration_seconds: 'abc' }));
  assert.equal(report3.duration_seconds, null);
});

test('parseIncidentAnalysis filters empty uncertainties', () => {
  const report = parseIncidentAnalysis(baseReport({
    uncertainties: ['Valid uncertainty', '', '   ', null, 'Another valid'],
  }));

  assert.deepEqual(report.uncertainties, ['Valid uncertainty', 'Another valid']);
});

test('parseIncidentAnalysis provides tolerant read-compatibility for legacy camelCase fields', () => {
  const legacyJson = JSON.stringify({
    title: 'Legacy Title',
    incidentType: 'burglary',
    summary: 'Legacy summary text',
    startTimestamp: '01:15',
    endTimestamp: '01:45',
    durationSeconds: 30,
    severityLevel: 'high',
    severityReason: 'High risk detected',
    confidenceScore: 90,
    timeline: [{ startSeconds: 15, endSeconds: 45, description: 'Event' }],
    entities: [{ type: 'human', description: 'Intruder' }],
    instruments: [{ name: 'Crowbar', description: 'Tool', threatLevel: 4 }],
    assets: [{ name: 'Door', description: 'Pried' }],
    uncertainties: ['Unknown suspect identity'],
  });

  const report = parseIncidentAnalysis(legacyJson);
  assert.equal(report.title, 'Legacy Title');
  assert.equal(report.incident_type, 'burglary');
  assert.equal(report.description, 'Legacy summary text');
  assert.equal(report.incident_start, '01:15');
  assert.equal(report.incident_end, '01:45');
  assert.equal(report.duration_seconds, 30);
  assert.equal(report.severity, 4);
  assert.equal(report.severity_reason, 'High risk detected');
  assert.equal(report.confidence, 0.9);
  assert.deepEqual(report.timeline, [{ start_seconds: 15, end_seconds: 45, description: 'Event' }]);
  assert.deepEqual(report.persons, [{ description: 'Intruder', actions: '' }]);
  assert.deepEqual(report.instruments, [{ name: 'Crowbar', description: 'Tool', threat_level: 4 }]);
  assert.deepEqual(report.assets, [{ name: 'Door', description: 'Pried' }]);
  assert.deepEqual(report.uncertainties, ['Unknown suspect identity']);
});
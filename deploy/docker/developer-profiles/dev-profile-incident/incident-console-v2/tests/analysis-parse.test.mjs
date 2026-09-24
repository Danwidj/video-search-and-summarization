import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { parseIncidentAnalysis } = await import('../lib/analysis/parse.ts');

function baseReport(overrides = {}) {
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
    instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 1 }],
    assets: [],
    uncertainties: ['Details are limited.'],
    ...overrides,
  });
}

test('parseIncidentAnalysis normalizes numeric threat-level strings', () => {
  const report = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: '3' }] }));
  assert.equal(report.instruments[0].threatLevel, 3);
});

test('parseIncidentAnalysis normalizes word threat levels', () => {
  const report = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 'high' }] }));
  assert.equal(report.instruments[0].threatLevel, 4);

  const report2 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 'critical' }] }));
  assert.equal(report2.instruments[0].threatLevel, 5);

  const report3 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 'medium' }] }));
  assert.equal(report3.instruments[0].threatLevel, 3);

  const report4 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 'low' }] }));
  assert.equal(report4.instruments[0].threatLevel, 2);

  const report5 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 'none' }] }));
  assert.equal(report5.instruments[0].threatLevel, 1);
});

test('parseIncidentAnalysis falls back to null for unrecognized threat levels', () => {
  const report = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 'extreme' }] }));
  assert.equal(report.instruments[0].threatLevel, null);

  const report2 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: 99 }] }));
  assert.equal(report2.instruments[0].threatLevel, null);

  const report3 = parseIncidentAnalysis(baseReport({ instruments: [{ name: 'Object', description: 'Visible object', threatLevel: -1 }] }));
  assert.equal(report3.instruments[0].threatLevel, null);
});

test('parseIncidentAnalysis handles missing fields with defaults', () => {
  const minimal = JSON.stringify({});
  const report = parseIncidentAnalysis(minimal);

  assert.equal(report.title, 'Untitled Incident');
  assert.equal(report.incidentType, 'other');
  assert.equal(report.summary, '');
  assert.equal(report.startTimestamp, null);
  assert.equal(report.endTimestamp, null);
  assert.equal(report.durationSeconds, null);
  assert.equal(report.severityLevel, 1);
  assert.equal(report.severityReason, 'Severity determined from visible evidence.');
  assert.equal(report.confidenceScore, 0.5);
  assert.deepEqual(report.timeline, []);
  assert.deepEqual(report.entities, []);
  assert.deepEqual(report.instruments, []);
  assert.deepEqual(report.assets, []);
  assert.deepEqual(report.uncertainties, []);
});

test('parseIncidentAnalysis truncates long title to 160 chars', () => {
  const longTitle = 'A'.repeat(200);
  const report = parseIncidentAnalysis(baseReport({ title: longTitle }));
  assert.equal(report.title.length, 160);
  assert.equal(report.title, 'A'.repeat(160));
});

test('parseIncidentAnalysis truncates long incidentType to 32 chars', () => {
  const longType = 'B'.repeat(50);
  const report = parseIncidentAnalysis(baseReport({ incidentType: longType }));
  assert.equal(report.incidentType.length, 32);
  assert.equal(report.incidentType, 'B'.repeat(32));
});

test('parseIncidentAnalysis normalizes severityLevel from words', () => {
  const report = parseIncidentAnalysis(baseReport({ severityLevel: 'high' }));
  assert.equal(report.severityLevel, 4);

  const report2 = parseIncidentAnalysis(baseReport({ severityLevel: 'critical' }));
  assert.equal(report2.severityLevel, 5);

  const report3 = parseIncidentAnalysis(baseReport({ severityLevel: 'medium' }));
  assert.equal(report3.severityLevel, 3);

  const report4 = parseIncidentAnalysis(baseReport({ severityLevel: 'low' }));
  assert.equal(report4.severityLevel, 2);

  const report5 = parseIncidentAnalysis(baseReport({ severityLevel: 'none' }));
  assert.equal(report5.severityLevel, 1);
});

test('parseIncidentAnalysis clamps severityLevel to 1-5', () => {
  const report = parseIncidentAnalysis(baseReport({ severityLevel: 10 }));
  assert.equal(report.severityLevel, 5);

  const report2 = parseIncidentAnalysis(baseReport({ severityLevel: 0 }));
  assert.equal(report2.severityLevel, 1);

  const report3 = parseIncidentAnalysis(baseReport({ severityLevel: -5 }));
  assert.equal(report3.severityLevel, 1);
});

test('parseIncidentAnalysis normalizes confidenceScore from percentage', () => {
  const report = parseIncidentAnalysis(baseReport({ confidenceScore: 85 }));
  assert.equal(report.confidenceScore, 0.85);

  const report2 = parseIncidentAnalysis(baseReport({ confidenceScore: '95' }));
  assert.equal(report2.confidenceScore, 0.95);

  const report3 = parseIncidentAnalysis(baseReport({ confidenceScore: 0.7 }));
  assert.equal(report3.confidenceScore, 0.7);
});

test('parseIncidentAnalysis clamps confidenceScore to 0-1', () => {
  const report = parseIncidentAnalysis(baseReport({ confidenceScore: 150 }));
  assert.equal(report.confidenceScore, 1.0);

  const report2 = parseIncidentAnalysis(baseReport({ confidenceScore: -0.5 }));
  assert.equal(report2.confidenceScore, 0.0);
});

test('parseIncidentAnalysis handles timeline with missing/partial fields', () => {
  const report = parseIncidentAnalysis(baseReport({
    timeline: [
      { startSeconds: 10, endSeconds: 20, description: 'Event A' },
      { startSeconds: '30', description: 'Event B' },
      { endSeconds: 50, description: 'Event C' },
      {},
    ],
  }));

  assert.equal(report.timeline.length, 4);
  assert.equal(report.timeline[0].startSeconds, 10);
  assert.equal(report.timeline[0].endSeconds, 20);
  assert.equal(report.timeline[0].description, 'Event A');
  assert.equal(report.timeline[1].startSeconds, 30);
  assert.equal(report.timeline[1].endSeconds, null);
  assert.equal(report.timeline[1].description, 'Event B');
  assert.equal(report.timeline[2].startSeconds, 0);
  assert.equal(report.timeline[2].endSeconds, 50);
  assert.equal(report.timeline[2].description, 'Event C');
  assert.equal(report.timeline[3].startSeconds, 0);
  assert.equal(report.timeline[3].endSeconds, null);
  assert.equal(report.timeline[3].description, '');
});

test('parseIncidentAnalysis maps entity types case-insensitively with fallback', () => {
  const report = parseIncidentAnalysis(baseReport({
    entities: [
      { type: 'HUMAN', description: 'Person A' },
      { type: 'Animal', description: 'Dog' },
      { type: 'vehicle', description: 'Car' },
      { type: '', description: 'Unknown type' },
      { description: 'Missing type' },
    ],
  }));

  assert.equal(report.entities.length, 5);
  assert.equal(report.entities[0].type, 'human');
  assert.equal(report.entities[1].type, 'animal');
  assert.equal(report.entities[2].type, 'unknown');
  assert.equal(report.entities[3].type, 'unknown');
  assert.equal(report.entities[4].type, 'unknown');
});

test('parseIncidentAnalysis handles empty arrays and null arrays', () => {
  const report = parseIncidentAnalysis(baseReport({
    timeline: null,
    entities: null,
    instruments: null,
    assets: null,
    uncertainties: null,
  }));

  assert.deepEqual(report.timeline, []);
  assert.deepEqual(report.entities, []);
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

test('parseIncidentAnalysis handles instruments with missing threatLevel', () => {
  const report = parseIncidentAnalysis(baseReport({
    instruments: [
      { name: 'Tool', description: 'A tool' },
      { name: 'Weapon', description: 'A weapon', threatLevel: 'high' },
    ],
  }));

  assert.equal(report.instruments.length, 2);
  assert.equal(report.instruments[0].threatLevel, null);
  assert.equal(report.instruments[1].threatLevel, 4);
});

test('parseIncidentAnalysis handles durationSeconds coercion', () => {
  const report = parseIncidentAnalysis(baseReport({ durationSeconds: '45' }));
  assert.equal(report.durationSeconds, 45);

  const report2 = parseIncidentAnalysis(baseReport({ durationSeconds: -10 }));
  assert.equal(report2.durationSeconds, null);

  const report3 = parseIncidentAnalysis(baseReport({ durationSeconds: 'abc' }));
  assert.equal(report3.durationSeconds, null);
});

test('parseIncidentAnalysis filters empty uncertainties', () => {
  const report = parseIncidentAnalysis(baseReport({
    uncertainties: ['Valid uncertainty', '', '   ', null, 'Another valid'],
  }));

  assert.deepEqual(report.uncertainties, ['Valid uncertainty', 'Another valid']);
});
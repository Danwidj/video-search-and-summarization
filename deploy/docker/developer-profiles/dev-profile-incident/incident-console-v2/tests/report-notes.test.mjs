// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { reportsFromNotes, legacyToContract, toSeconds } = await import('../lib/reports/storage.ts');

const CONTRACT = {
  incident: {
    type: 'road accident', title: 'Two cars collide', start_timestamp: 2, end_timestamp: 9, duration: 7,
    description: 'Car E1 hits car E2.', severity_level: 3, severity_reason: 'Visible damage.', confidence_score: null, location: null,
  },
  entities: [{ entity_id: 'E1', type: 'human', description: 'Driver.' }],
  instruments: [],
  assets: [{ asset_id: 'A1', name: 'car', description: 'Damaged car.' }],
  timeline: [{ start_seconds: 2, end_seconds: 4, description: 'Impact.' }],
  uncertainties: [],
};

test('contract notes are validated strictly and keep report text and raw output', () => {
  const notes = JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v1', modelRunId: 'r1', model: 'm', ...CONTRACT }, rawModelOutput: '{...}', reportText: 'Prose.' } });
  const { original, edited } = reportsFromNotes(notes);
  assert.equal(original.legacy, undefined);
  assert.equal(original.incident.duration, 7);
  assert.equal(original.reportText, 'Prose.');
  assert.equal(original.rawModelOutput, '{...}');
  assert.equal(edited, null);
});

test('the reviewer-edited copy is returned alongside the untouched original', () => {
  const editedContract = { ...CONTRACT, incident: { ...CONTRACT.incident, title: 'Edited title', end_timestamp: 10 } };
  const notes = JSON.stringify({ incidentConsoleV2: { report: { videoId: 'v1', ...CONTRACT }, editedReport: editedContract } });
  const { original, edited } = reportsFromNotes(notes);
  assert.equal(original.incident.title, 'Two cars collide');
  assert.equal(edited.incident.title, 'Edited title');
  assert.equal(edited.incident.duration, 8);
});

test('pre-contract camelCase notes are converted read-only and flagged legacy', () => {
  const notes = JSON.stringify({
    incidentConsoleV2: {
      report: {
        videoId: 'video-1', modelRunId: 'run-1', title: 'Legacy Title', incidentType: 'fighting', summary: 'Legacy summary',
        startTimestamp: '01:15', endTimestamp: '01:45', durationSeconds: 30, severityLevel: 4, confidenceScore: 0.8,
        entities: [{ description: 'A person' }], timeline: [{ startSeconds: 75, description: 'Start' }],
      },
    },
  });
  const { original } = reportsFromNotes(notes);
  assert.equal(original.legacy, true);
  assert.equal(original.incident.type, 'assault');
  assert.equal(original.incident.start_timestamp, 75);
  assert.equal(original.incident.end_timestamp, 105);
  assert.equal(original.incident.duration, 30);
  assert.equal(original.incident.confidence_score, 0.8);
  assert.deepEqual(original.entities, [{ entity_id: 'E1', type: 'human', description: 'A person' }]);
  assert.deepEqual(original.timeline, [{ start_seconds: 75, end_seconds: null, description: 'Start' }]);
});

test('pre-contract flat snake_case notes with persons are converted', () => {
  const report = legacyToContract({
    title: 'Old', incident_type: 'animal', severity: 2, confidence: 0.5, incident_start: '0:05', incident_end: '0:09',
    duration_seconds: null, description: 'Dog bites.', persons: [{ description: 'Walker', actions: 'runs away' }],
    instruments: [{ name: 'leash', description: 'held', threat_level: null }], assets: [], timeline: [], uncertainties: ['x'], location: '',
  });
  assert.equal(report.incident.type, 'animal attack');
  assert.equal(report.incident.duration, 4);
  assert.equal(report.incident.location, null);
  assert.equal(report.entities[0].description, 'Walker runs away');
  assert.equal(report.instruments[0].threat_level, 1);
  assert.deepEqual(report.uncertainties, ['x']);
});

test('unreadable notes return null', () => {
  assert.equal(reportsFromNotes(null), null);
  assert.equal(reportsFromNotes('not json'), null);
  assert.equal(reportsFromNotes(JSON.stringify({ other: {} })), null);
});

test('toSeconds accepts bare seconds and clock strings', () => {
  assert.equal(toSeconds('21'), 21);
  assert.equal(toSeconds('15.6'), 15);
  assert.equal(toSeconds('1:05'), 65);
  assert.equal(toSeconds('1:00:05'), 3605);
  assert.equal(toSeconds('garbage'), 0);
  assert.equal(toSeconds(null), 0);
});

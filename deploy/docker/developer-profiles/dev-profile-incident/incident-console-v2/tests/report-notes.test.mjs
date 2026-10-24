import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { reportFromNotes } = await import('../src/modules/reports/domain/storage.ts');

test('reportFromNotes normalizes legacy camelCase notes to snake_case', () => {
  const notes = JSON.stringify({
    incidentConsoleV2: {
      report: {
        videoId: 'video-1',
        modelRunId: 'run-1',
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
        entities: [
          { type: 'human', description: 'Intruder' },
          { type: 'animal', description: 'Guard dog' },
        ],
        instruments: [{ name: 'Crowbar', description: 'Tool', threatLevel: 4 }],
        assets: [{ name: 'Door', description: 'Pried' }],
        uncertainties: ['Unknown suspect identity'],
      },
    },
  });

  const report = reportFromNotes(notes);
  assert.ok(report);
  assert.equal(report.videoId, 'video-1');
  assert.equal(report.title, 'Legacy Title');
  assert.equal(report.incident_type, 'burglary');
  assert.equal(report.description, 'Legacy summary text');
  assert.equal(report.incident_start, '01:15');
  assert.equal(report.incident_end, '01:45');
  assert.equal(report.severity, 4);
  assert.equal(report.severity_reason, 'High risk detected');
  assert.deepEqual(report.timeline, [{ start_seconds: 15, end_seconds: 45, description: 'Event' }]);
  assert.deepEqual(report.uncertainties, ['Unknown suspect identity']);
});

test('reportFromNotes keeps snake_case notes unchanged', () => {
  const notes = JSON.stringify({
    incidentConsoleV2: {
      videoId: 'video-2',
      incident_type: 'fighting',
      description: 'Two people fight.',
      severity: 3,
      location: 'Main street',
      timeline: [{ start_seconds: 2, end_seconds: null, description: 'Fight starts' }],
    },
  });

  const report = reportFromNotes(notes);
  assert.ok(report);
  assert.equal(report.incident_type, 'fighting');
  assert.equal(report.description, 'Two people fight.');
  assert.equal(report.severity, 3);
  assert.equal(report.location, 'Main street');
  assert.deepEqual(report.timeline, [{ start_seconds: 2, end_seconds: null, description: 'Fight starts' }]);
});

test('reportFromNotes coerces legacy timeline seconds like the retired schema.ts: numeric strings only', () => {
  const notes = JSON.stringify({
    incidentConsoleV2: {
      videoId: 'video-3',
      timeline: [
        { start_seconds: ' 7.5 ', end_seconds: '12', description: 'Numeric strings' },
        { start_seconds: '1:15', end_seconds: '1:45', description: 'Clock strings are not numbers' },
        { start_seconds: -3, description: 'Negative start, missing end' },
      ],
    },
  });

  const report = reportFromNotes(notes);
  assert.ok(report);
  assert.deepEqual(report.timeline, [
    { start_seconds: 7.5, end_seconds: 12, description: 'Numeric strings' },
    { start_seconds: 0, end_seconds: null, description: 'Clock strings are not numbers' },
    { start_seconds: 0, end_seconds: null, description: 'Negative start, missing end' },
  ]);
});

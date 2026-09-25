import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { reportFromNotes } = await import('../lib/reports/storage.ts');

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
        entities: [{ type: 'human', description: 'Intruder' }, { type: 'animal', description: 'Guard dog' }],
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
  assert.equal(report.duration_seconds, 30);
  assert.equal(report.severity, 4);
  assert.equal(report.severity_reason, 'High risk detected');
  assert.equal(report.confidence, 0.9);
  assert.deepEqual(report.timeline, [{ start_seconds: 15, end_seconds: 45, description: 'Event' }]);
  assert.deepEqual(report.persons, [{ description: 'Intruder', actions: '' }, { description: 'Guard dog', actions: '' }]);
  assert.deepEqual(report.instruments, [{ name: 'Crowbar', description: 'Tool', threat_level: 4 }]);
  assert.deepEqual(report.assets, [{ name: 'Door', description: 'Pried' }]);
  assert.deepEqual(report.uncertainties, ['Unknown suspect identity']);
});

test('reportFromNotes keeps snake_case notes unchanged', () => {
  const notes = JSON.stringify({
    incidentConsoleV2: {
      videoId: 'video-2',
      incident_type: 'fighting',
      description: 'Two people fight.',
      severity: 3,
      confidence: 0.7,
      persons: [{ description: 'Person A', actions: 'punching' }],
      timeline: [{ start_seconds: 2, end_seconds: null, description: 'Fight starts' }],
      instruments: [{ name: 'Bottle', description: 'Swung', threat_level: 2 }],
    },
  });

  const report = reportFromNotes(notes);
  assert.ok(report);
  assert.equal(report.incident_type, 'fighting');
  assert.equal(report.description, 'Two people fight.');
  assert.equal(report.severity, 3);
  assert.equal(report.confidence, 0.7);
  assert.deepEqual(report.persons, [{ description: 'Person A', actions: 'punching' }]);
  assert.deepEqual(report.timeline, [{ start_seconds: 2, end_seconds: null, description: 'Fight starts' }]);
  assert.deepEqual(report.instruments, [{ name: 'Bottle', description: 'Swung', threat_level: 2 }]);
});

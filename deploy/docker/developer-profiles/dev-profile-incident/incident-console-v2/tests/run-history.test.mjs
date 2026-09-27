// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { buildRunHistory } = await import('../lib/runs/history.ts');
const { describeCode } = await import('../lib/runs/labels.ts');
const { formatTimestamp, parseStoredTimestamp } = await import('../lib/time.ts');

const fixture = (name) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', name), 'utf8'));
const repaired = fixture('contract-v2-repaired-run.json');
const smoke = fixture('contract-v2-smoke-run.json');
const V = repaired.videoId;

const incidentRow = (rows) => ({
  model_run_id: rows.modelRunId, type: rows.incident.type, severity_level: rows.incident.severity_level,
  model_runs: rows.modelRun, reports: [rows.reportRow],
});
const attempt = (id, videoId, status, extra = {}) => ({
  id, model_name: 'nvidia/cosmos-3-super-reasoner', run_datetime: '2026-09-27T12:00:00',
  notes: JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', status, contractVersion: 'incident-contract-v2', videoId, attemptedAt: '2026-09-27T12:00:00.000Z', request: { model: 'nvidia/cosmos-3-super-reasoner', additionalInstruction: null }, response: null, validation: { firstPass: [] }, repair: null, ...extra } }),
});

test('a video history lists successful runs, repaired runs and failed attempts, grouped under the video', () => {
  const contractFailed = attempt('m-cf', V, 'contract_failed', {
    stage: 'contract_validation', failure: { code: 'TIMELINE_START_OUTSIDE_WINDOW', message: 'timeline[0]...' },
    validation: { firstPass: [{ code: 'TIMELINE_START_OUTSIDE_WINDOW', path: 'timeline/0/start_seconds', message: 'timeline[0].start_seconds 0 is outside [1, 3]' }] },
  });
  const requestFailed = attempt('m-rf', V, 'request_failed', { stage: 'gateway', failure: { code: 'GATEWAY_TIMEOUT', message: 'timed out' }, attemptedAt: '2026-09-27T12:05:00.000Z' });
  const otherVideo = attempt('m-other', 'v-some-other-video', 'contract_failed');
  const { runs, counts } = buildRunHistory({
    videoId: V,
    incidentRows: [incidentRow(repaired), incidentRow(smoke)],
    // The repaired run is also found by the notes pre-filter; it must appear once.
    attemptCandidates: [contractFailed, requestFailed, otherVideo, { id: repaired.modelRunId, notes: repaired.modelRun.notes }],
    sharedRunIds: new Set(),
  });

  assert.deepEqual(runs.map((run) => run.modelRunId), ['m-rf', 'm-cf', 'm811cf2b237f50ff9812', 'm86a5c319e26659804b0'], 'newest first, no duplicates, other videos excluded');
  const byId = Object.fromEntries(runs.map((run) => [run.modelRunId, run]));
  assert.equal(byId.m811cf2b237f50ff9812.outcome, 'valid_after_structural_repair');
  assert.deepEqual(byId.m811cf2b237f50ff9812.repair.operations.map((op) => op.op), ['reorder', 'rename-id']);
  assert.equal(byId.m811cf2b237f50ff9812.report.reportId, 'r4a0af1f2a8a1bab313f');
  assert.equal(byId.m86a5c319e26659804b0.outcome, 'valid_first_pass');
  assert.equal(byId.m86a5c319e26659804b0.outcomeInferred, true, 'recorded before outcomes existed');
  assert.equal(byId['m-cf'].report, null, 'failed attempts never have a report');
  assert.equal(byId['m-cf'].failure.violations[0].code, 'TIMELINE_START_OUTSIDE_WINDOW');
  assert.equal(byId['m-rf'].failure.code, 'GATEWAY_TIMEOUT');
  assert.equal(describeCode(byId['m-rf'].failure.code), 'The model did not answer within its time limit');
  assert.deepEqual(counts, { attempts: 4, withReport: 2, valid_first_pass: 1, valid_after_structural_repair: 1, contract_failed: 1, request_failed: 1, legacy: 0 });
});

test('pre-outcome and batch runs are shown as earlier analyses, never as failures', () => {
  const evalRow = { model_run_id: 'P1-cosmos3nano', type: 'Assault', severity_level: 3, model_runs: { id: 'P1-cosmos3nano', model_name: 'nvidia/cosmos-3-nano-reasoner', run_datetime: '2026-09-27T01:00:00', notes: null }, reports: [] };
  const legacyRow = { model_run_id: 'm-legacy', type: 'fighting', severity_level: 2, model_runs: { id: 'm-legacy', model_name: 'nvidia/cosmos-3-nano-reasoner', run_datetime: '2026-09-20T01:00:00', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: V, incident_type: 'fighting' } } }) }, reports: [{ id: 'r-legacy', generated_datetime: '2026-09-20T01:00:00' }] };
  const removedLegacy = { id: 'm-removed', model_name: 'm', run_datetime: '2026-09-19T01:00:00', notes: JSON.stringify({ incidentConsoleV2: { report: { videoId: V, incident_type: 'burglary' } } }) };
  const { runs, counts } = buildRunHistory({ videoId: V, incidentRows: [evalRow, legacyRow], attemptCandidates: [removedLegacy], sharedRunIds: new Set(['P1-cosmos3nano']) });
  const byId = Object.fromEntries(runs.map((run) => [run.modelRunId, run]));
  assert.equal(byId['P1-cosmos3nano'].outcome, 'legacy');
  assert.equal(byId['P1-cosmos3nano'].source, 'shared');
  assert.equal(byId['P1-cosmos3nano'].report, null, 'an eval run without a reports row has no report');
  assert.equal(byId['m-legacy'].outcome, 'legacy');
  assert.equal(byId['m-legacy'].report.type, 'assault', 'legacy types are shown in contract form');
  assert.equal(byId['m-removed'].reportRemoved, true);
  assert.deepEqual(counts, { attempts: 3, withReport: 1, valid_first_pass: 0, valid_after_structural_repair: 0, contract_failed: 0, request_failed: 0, legacy: 3 });
});

test('stored UTC timestamps without a zone are rendered as UTC, not local time', () => {
  assert.equal(parseStoredTimestamp('2026-09-27T11:15:57.575959').toISOString(), '2026-09-27T11:15:57.575Z');
  assert.equal(parseStoredTimestamp('2026-09-27 11:15:57').toISOString(), '2026-09-27T11:15:57.000Z');
  assert.equal(parseStoredTimestamp('2026-09-27T11:15:57.000Z').toISOString(), '2026-09-27T11:15:57.000Z');
  assert.equal(parseStoredTimestamp('2026-09-27T19:15:57+08:00').toISOString(), '2026-09-27T11:15:57.000Z');
  assert.equal(parseStoredTimestamp('not a time'), null);
  assert.equal(formatTimestamp(null, 'n/a'), 'n/a');
  assert.equal(formatTimestamp('2026-09-27T11:15:57'), new Date(Date.UTC(2026, 8, 27, 11, 15, 57)).toLocaleString());
});

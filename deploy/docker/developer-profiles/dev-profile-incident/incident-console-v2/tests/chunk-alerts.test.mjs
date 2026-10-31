// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { buildReportView } = await import('./support/report-view.mjs');
const { alertsByWindow, chunkAlertsFrom } = await import('../src/modules/reports/domain/chunk-alerts.ts');
const { chunkTimelineFrom } = await import('../src/modules/reports/domain/chunk-timeline.ts');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));

/** The smoke run with its notes' response carrying the given fields (each left out when undefined). */
function rowsWith(response) {
  const rows = clone(smoke);
  const wrapper = JSON.parse(rows.modelRun.notes);
  for (const [key, value] of Object.entries(response)) if (value !== undefined) wrapper.incidentConsoleV2.response[key] = value;
  rows.modelRun.notes = JSON.stringify(wrapper);
  return { ...rows, playbackUrl: 'https://signed.example/video.mp4' };
}

// IMG_8206: 20 s windows overlapping by 2 s, as the agent returns them.
const agentTimeline = [
  { start: 0, end: 20, caption: '[0.0s-20.0s] A bag lies on the floor.', events: [] },
  { start: 72, end: 92, caption: '[80.5s-84.6s] A man picks up the bag.', events: [] },
  { start: 90, end: 94.194, caption: '[90.0s-94.2s] A man lies on the floor.', events: [] },
];
const agentAlerts = [
  { rule_id: 'person-falls', rule: 'A person falls.', window_index: 2, start: 90, end: 94.194, reason: 'A man lies on the floor.' },
  {
    rule_id: 'unattended-bag-picked-up',
    rule: 'An unattended bag is picked up.',
    window_index: 1,
    start: 72,
    end: 92,
    reason: ' The man picks up the bag. ',
  },
];

test('chunk alerts view: present in the run notes, ordered by time, with the rule text and reason', () => {
  const view = buildReportView(rowsWith({ chunkTimeline: agentTimeline, chunkAlerts: agentAlerts }));
  assert.deepEqual(view.chunkAlerts, [
    {
      ruleId: 'unattended-bag-picked-up',
      rule: 'An unattended bag is picked up.',
      startSeconds: 72,
      endSeconds: 92,
      reason: 'The man picks up the bag.',
    },
    { ruleId: 'person-falls', rule: 'A person falls.', startSeconds: 90, endSeconds: 94.194, reason: 'A man lies on the floor.' },
  ]);
});

test('chunk alerts view: absent (no alert check, or a skipped one) gives an empty list', () => {
  assert.deepEqual(buildReportView(rowsWith({ chunkTimeline: agentTimeline })).chunkAlerts, []);
  assert.deepEqual(buildReportView(rowsWith({})).chunkAlerts, []);
  assert.deepEqual(buildReportView(rowsWith({ chunkAlerts: null, alerting: { skipped: 'no chunk timeline' } })).chunkAlerts, []);
  assert.deepEqual(chunkAlertsFrom({ skipped: 'x' }), []);
});

test('chunk alerts view: malformed entries are skipped without throwing', () => {
  const alerts = chunkAlertsFrom([
    null,
    'alert',
    [1, 2],
    { rule_id: 'a', rule: 'A', start: '0', end: 20 },
    { rule_id: 'a', rule: 'A', start: 5, end: 5 },
    { rule_id: 'a', rule: 'A', start: -1, end: 5 },
    { rule_id: '', rule: 'A', start: 0, end: 20 },
    { rule_id: 'a', rule: '  ', start: 0, end: 20 },
    { rule_id: 'a', rule: 'A', start: 0, end: Number.NaN },
    { rule_id: 'kept', rule: 'Kept', start: 0, end: 20, reason: 42 },
  ]);
  assert.deepEqual(alerts, [{ ruleId: 'kept', rule: 'Kept', startSeconds: 0, endSeconds: 20, reason: '' }]);
});

test('alert to window: matched on the window bounds, so dropped windows never shift the flags', () => {
  // The console drops an unusable window, so the agent's window_index 2 is position 1 here.
  const windows = chunkTimelineFrom([agentTimeline[0], { start: 72, end: 92, caption: '  ' }, agentTimeline[2]]);
  const byWindow = alertsByWindow(windows, chunkAlertsFrom(agentAlerts));
  assert.deepEqual(
    byWindow.map((alerts) => alerts.map((alert) => alert.ruleId)),
    [[], ['person-falls']],
    'the bag alert has no window left to flag; the fall flags the 90 s window',
  );
  assert.deepEqual(alertsByWindow(windows, []), [[], []]);
  assert.deepEqual(alertsByWindow([], chunkAlertsFrom(agentAlerts)), []);
});

test('alert to window: two rules on one window both flag it', () => {
  const windows = chunkTimelineFrom(agentTimeline);
  const both = chunkAlertsFrom([...agentAlerts, { ...agentAlerts[0], rule_id: 'person-carried', rule: 'Carried.', start: 72, end: 92 }]);
  assert.deepEqual(
    alertsByWindow(windows, both).map((alerts) => alerts.map((alert) => alert.ruleId)),
    [[], ['unattended-bag-picked-up', 'person-carried'], ['person-falls']],
  );
});

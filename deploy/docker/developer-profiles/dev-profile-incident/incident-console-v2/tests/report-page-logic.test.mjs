// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { buildTimelineLanes, timelineDuration, axisPercent, axisTicks } = await import('../lib/reports/timeline-lanes.ts');
const { layoutVersions } = await import('../lib/reports/version-graph.ts');
const { markOfficial, clearOfficial } = await import('../lib/reports/official-client.ts');
const { structuredFromPayload } = await import('../lib/reports/payload-view.ts');

const entity = (id, first, last, extra = {}) => ({ entityId: id, type: 'person', label: 'Guard', description: '', timestampSeconds: 5, firstSeenSeconds: first, lastSeenSeconds: last, evidence: null, ...extra });
const instrument = (id, entityId) => ({ instrumentId: id, entityId, name: id, description: '', threatLevel: 2, timestampSeconds: 7, evidence: null });
const asset = (id) => ({ assetId: id, name: id, description: '', timestampSeconds: 9, evidence: null });

test('timeline lanes: one per entity with held instruments, then unknown holder and assets', () => {
  const lanes = buildTimelineLanes({ entities: [entity('E1', 2, 20), entity('E2', null, null)], instruments: [instrument('I1', 'E1'), instrument('I2', null), instrument('I3', 'E9')], assets: [asset('A1')] });
  assert.deepEqual(lanes.map((lane) => lane.id), ['E1', 'E2', 'unknown-holder', 'assets']);
  assert.deepEqual(lanes[0].span, { start: 2, end: 20 });
  assert.deepEqual(lanes[0].markers.map((marker) => marker.kind), ['entity', 'instrument']);
  assert.equal(lanes[1].span, null, 'an edited revision with no span falls back to its single marker');
  assert.equal(lanes[2].markers.length, 2);
});

test('timeline lanes: no unknown-holder or assets lane when empty; invalid span ignored', () => {
  const lanes = buildTimelineLanes({ entities: [entity('E1', 10, 3)], instruments: [], assets: [] });
  assert.equal(lanes.length, 1);
  assert.equal(lanes[0].span, null);
});

test('timeline axis helpers', () => {
  assert.equal(timelineDuration([], 30), 30);
  assert.equal(timelineDuration(buildTimelineLanes({ entities: [entity('E1', 2, 20)], instruments: [], assets: [] }), null), 20);
  assert.equal(axisPercent(50, 40), 100);
  assert.equal(axisPercent(-1, 40), 0);
  assert.deepEqual(axisTicks(30), [0, 5, 10, 15, 20, 25, 30]);
});

const rev = (revisionId, revisionNo, parentId, kind = 'ai') => ({ revisionId, videoId: 'v', revisionNo, kind, parentId, isOfficial: false });

test('version graph: each AI run starts a lane, human versions follow their parent', () => {
  const { rows, laneCount } = layoutVersions([rev(4, 4, null), rev(3, 3, 2, 'human'), rev(2, 2, 1, 'human'), rev(1, 1, null)]);
  assert.equal(laneCount, 2);
  assert.deepEqual(rows.map((row) => row.lane), [1, 0, 0, 0]);
  const lane0 = rows[1].segments.find((segment) => segment.lane === 0);
  assert.deepEqual(lane0, { lane: 0, fromAbove: false, toBelow: true });
});

test('official client surfaces the route error, such as the agent being unreachable', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push([url, init.method]); return { ok: false, json: async () => ({ error: 'The agent is unreachable' }) }; };
  try {
    await assert.rejects(markOfficial('v 1', 3), /The agent is unreachable/);
    await assert.rejects(clearOfficial('v 1'), /unreachable/);
    assert.deepEqual(calls, [['/api/videos/v%201/official', 'PUT'], ['/api/videos/v%201/official', 'DELETE']]);
    globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
    await markOfficial('v', 1);
  } finally {
    globalThis.fetch = original;
  }
});

test('the entity seen span is mapped into the report view', () => {
  const view = structuredFromPayload({ incident: {}, entities: [{ entity_id: 'E1', type: 'person', description: 'd', timestamp_seconds: 3, first_seen_seconds: 1, last_seen_seconds: 9 }], instruments: [], assets: [] }, []);
  assert.equal(view.entities[0].firstSeenSeconds, 1);
  assert.equal(view.entities[0].lastSeenSeconds, 9);
});

test('the report page has a mark-official star, no Restore, and keeps the layout while loading', async () => {
  const components = new URL('../components/', import.meta.url);
  const versions = await readFile(new URL('report-versions.tsx', components), 'utf8');
  const page = await readFile(new URL('report-page.tsx', components), 'utf8');
  assert.match(versions, /Mark v\$\{revision\.revisionNo\} official/);
  assert.doesNotMatch(versions + page, /restore/i);
  assert.match(page, /Try again/);
  assert.match(page, /No official version has been selected/);
});

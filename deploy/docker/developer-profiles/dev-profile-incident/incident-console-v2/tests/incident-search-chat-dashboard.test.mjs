// SPDX-License-Identifier: Apache-2.0

// P5.7: search, chat and dashboard speak per incident. A search hit names its incident and its camera,
// item ids that repeat across cameras never mix, chat takes the incident id as an integer and cites the
// camera, and the dashboard separates incident counts from video counts.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { fromAgentSearchResponse } = await import('../src/lib/adapters/agent/search.ts');
const { groupByIncident, hitKey, hitsInFrame, relationshipOf, reportHref } = await import('../src/lib/library/search.ts');
const { POST } = await import('../src/app/api/chat/route.ts');
const { dashboardFromRpc } = await import('../src/modules/dashboard/infrastructure/supabase/mappers/dashboard.ts');
const { InMemoryDashboardRepository } = await import('../src/modules/dashboard/infrastructure/memory/dashboard.ts');

const agentHit = (camera, itemId, holder = null) => ({
  result_id: `r-${camera}-${itemId}`,
  rank: 1,
  similarity_score: 0.8,
  item: {
    item_type: holder ? 'instrument' : 'entity',
    item_id: itemId,
    video_id: camera,
    name: itemId,
    label: 'x',
    description: '',
    threat_level: null,
    holder_entity_id: holder,
    crop_image_url: 'https://r2.test/crop.jpg',
    timestamp_seconds: 5,
    bounding_box: null,
  },
  incident: {
    incident_id: 12,
    model_run_id: 'incident-12@2026-10-30T01:00:00Z',
    incident_type: 'assault',
    severity_level: 3,
    title: 'Fight',
    description: '',
    playback_url: '',
    incident_window: [0, 9],
  },
  critic: { verdict: 'unverified', confidence: null, rationale: '' },
});

const response = (hits) => fromAgentSearchResponse({ query_id: 'q', query: 'knife', total_hits: hits.length, execution_time_ms: 1, hits });

test('a hit names its incident (text id) and the camera of the item', () => {
  const [hit] = response([agentHit('front.mp4', 'E1')]).hits;
  assert.equal(hit.incident.incidentId, '12');
  assert.equal(hit.item.videoName, 'front.mp4');
  assert.equal(reportHref(hit), '/reports/12?video=front.mp4&t=5');
  assert.equal(hitKey({ ...hit, resultId: '' }), '12:front.mp4:entity:E1');
});

test('two cameras of one incident group together but never share items, holders or frames', () => {
  const { hits } = response([agentHit('front.mp4', 'E1'), agentHit('rear.mp4', 'E1'), agentHit('rear.mp4', 'I1', 'E1')]);
  const [group, ...rest] = groupByIncident(hits);
  assert.equal(rest.length, 0);
  assert.equal(group.hits.length, 3);
  const [front, rear, rearKnife] = hits;
  assert.deepEqual(relationshipOf(front, hits).holds, [], "the rear camera's knife is not held by the front camera's E1");
  assert.deepEqual(
    relationshipOf(rear, hits).holds.map((held) => held.itemId),
    ['I1'],
  );
  assert.equal(relationshipOf(rearKnife, hits).heldBy.name, 'E1');
  assert.deepEqual(hitsInFrame(front, hits), [front]);
  assert.deepEqual(hitsInFrame(rear, hits), [rear, rearKnife]);
});

// --- chat ---------------------------------------------------------------------------------------

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
let calls;
beforeEach(() => {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test';
  calls = [];
  globalThis.fetch = async (_url, init) => {
    calls.push(JSON.parse(String(init.body)));
    return new Response(
      JSON.stringify({
        session_id: 's1',
        message: {
          role: 'assistant',
          content: 'Both cameras show it.',
          citations: [
            {
              incident_id: 12,
              video_id: 'rear.mp4',
              item_id: 'E1',
              item_type: 'entity',
              timestamp_seconds: 4,
              crop_image_url: 'https://r2.test/a.jpg',
            },
            { incident_id: 12, item_id: 'I1', item_type: 'instrument', timestamp_seconds: 6, crop_image_url: 'https://r2.test/b.jpg' },
          ],
        },
      }),
      { status: 200 },
    );
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const chat = (body) => POST(new Request('http://console.test/api/chat', { method: 'POST', body: JSON.stringify(body) }));
const messages = [{ role: 'user', content: 'Who is there?' }];

test('chat sends the incident id as an integer and cites the camera of each answer', async () => {
  const reply = await chat({ messages, incidentId: '12' });
  assert.equal(reply.status, 200);
  assert.deepEqual(calls[0].context, { scope: 'incident', incident_id: 12 });
  const { citations } = (await reply.json()).message;
  assert.deepEqual(
    citations.map((c) => [c.incidentId, c.videoName]),
    [
      ['12', 'rear.mp4'],
      ['12', null],
    ],
  );
});

test('chat refuses an incident id that is not a positive integer, before any agent call', async () => {
  for (const incidentId of ['front.mp4', '0', '-1', '1.5', '12abc', '']) {
    assert.equal((await chat({ messages, incidentId })).status, 400, JSON.stringify(incidentId));
  }
  assert.equal(calls.length, 0);
});

// --- dashboard ----------------------------------------------------------------------------------

test('the dashboard counts incidents apart from videos', () => {
  const fixture = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'dashboard-rpc.json'), 'utf8'));
  const analytics = dashboardFromRpc(fixture);
  assert.deepEqual(analytics.incidents, { total: 5, withOfficial: 3, awaitingSelection: 1, withoutReport: 1 });
  assert.deepEqual(analytics.videos, { uploaded: 7 });
  assert.ok(analytics.videos.uploaded > analytics.incidents.total, 'several videos can belong to one incident');
});

test('the in-memory dashboard has no incidents and no videos until given some', async () => {
  const analytics = await new InMemoryDashboardRepository().getDashboard({
    periodStart: null,
    periodEnd: null,
    type: null,
    severity: null,
    dayOfWeek: null,
    hour: null,
    timezone: 'UTC',
  });
  assert.deepEqual(analytics.incidents, { total: 0, withOfficial: 0, awaitingSelection: 0, withoutReport: 0 });
  assert.deepEqual(analytics.videos, { uploaded: 0 });
});

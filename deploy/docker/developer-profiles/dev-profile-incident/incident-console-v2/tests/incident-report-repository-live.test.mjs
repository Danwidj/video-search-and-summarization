// SPDX-License-Identifier: Apache-2.0

// SupabaseIncidentReportAdapter against the real mvp3 database. Skipped unless
// INCIDENT_LIVE_DB=1, and it then refuses to run against the frozen midterm
// project. It reads INCIDENT_SUPABASE_URL and INCIDENT_SUPABASE_SERVICE_ROLE_KEY
// from the environment, else from the profile's .env.local, and never prints
// either. Every row it writes is named with the vss-mvp3-p4-2 prefix and is
// removed again by name; it changes no schema.
//
//   INCIDENT_LIVE_DB=1 npm test -- --test-name-pattern 'live'   (from this folder, on a host that reaches PostgREST)

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const MIDTERM_REF = 'rfevukimyftzbxlehwel';
const PREFIX = 'vss-mvp3-p4-2';
const live = process.env.INCIDENT_LIVE_DB === '1';

function setting(name) {
  if (process.env[name]) return process.env[name];
  const file = join(process.cwd(), '..', '.env.local');
  const line = readFileSync(file, 'utf8')
    .split('\n')
    .find((candidate) => candidate.startsWith(`${name}=`));
  return line
    ? line
        .slice(name.length + 1)
        .trim()
        .replace(/^['"]|['"]$/g, '')
    : '';
}

describe('live: SupabaseIncidentReportAdapter on the mvp3 database', { skip: !live && 'set INCIDENT_LIVE_DB=1 to run' }, () => {
  test('every incident function works through the adapter, and only its own rows are touched', async () => {
    const url = setting('INCIDENT_SUPABASE_URL');
    const key = setting('INCIDENT_SUPABASE_SERVICE_ROLE_KEY');
    assert.ok(url && key, 'the Supabase URL and service-role key are required');
    assert.ok(!url.includes(MIDTERM_REF), 'refusing to run against the frozen midterm project');

    const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');
    const { SupabaseIncidentReportAdapter } = await import('../src/modules/reports/infrastructure/supabase/incident-reports.ts');
    const db = new PostgrestClient(url, key);
    const repo = new SupabaseIncidentReportAdapter(db);

    const run = `${PREFIX}-r`;
    const names = [`${PREFIX}-a.mp4`, `${PREFIX}-b.mp4`, `${PREFIX}-c.mp4`];
    const incidentIds = [];
    const envelope = (videos) => ({
      overview: { title: `${PREFIX} title`, type: 'Theft', severity_level: 2, description: 'live test', location: null },
      cameras: videos.map((video) => ({
        video,
        report: { incident: { type: 'theft', start_timestamp: 1, end_timestamp: 9, severity_level: 2, description: video } },
      })),
    });
    const vector = Array.from({ length: 1024 }, (_, index) => (index === 0 ? 1 : 0));
    const crop = (video, itemId) => ({
      video_id: video,
      item_type: 'entity',
      item_id: itemId,
      image: `evidence/${video}/${itemId}.jpg`,
      bounding_box: [0, 0, 100, 100],
      timestamp_seconds: 1,
      item_name: itemId,
      description: '',
      threat_level: null,
      holder_entity_id: null,
      embedding: vector,
    });

    try {
      await db.upsert('model_runs', { id: run, model_name: `${PREFIX}-model`, prompt_version: 'v4', notes: null });
      for (const [index, video] of names.entries()) {
        const incident = await db.insertRow('incidents', {});
        incidentIds.push(Number(incident.id));
        await db.upsert('videos', { id: video, incident_id: incident.id, filepath: video, duration: 10 + index, source: 'live-test' });
      }
      const [first, second] = incidentIds;
      // Put the second video into the first incident too, through a merge, so coverage has two names to check.
      const merged = await repo.mergeIncidents(first, second);
      assert.deepEqual(merged.movedVideoIds, [names[1]]);
      assert.equal(await repo.getIncident(second), null);

      const ai = await repo.createAiRevision({
        incidentId: first,
        modelRunId: run,
        note: `${PREFIX} ai`,
        payload: envelope([names[0]]),
        evidence: [],
        videoNames: [names[0]],
        embedding: vector,
      });
      assert.equal(ai.revisionNo, 1);
      assert.equal(await repo.setRevisionCrops(first, ai.revisionId, [crop(names[0], 'E1'), crop(names[1], 'E2')]), 2);

      const human = await repo.saveHumanRevision({
        incidentId: first,
        parentId: ai.revisionId,
        payload: envelope([names[0]]),
        evidence: [{ item_type: 'entity', item_id: 'E1', image: `evidence/${names[0]}/E1.jpg` }],
        crops: [crop(names[0], 'E1')],
        createdBy: PREFIX,
        note: null,
      });
      assert.deepEqual([human.revisionNo, human.kind, human.parentId, human.videoNames], [2, 'human', ai.revisionId, [names[0]]]);

      const marked = await repo.setOfficialRevision(first, human.revisionId);
      assert.equal(marked.officialRevisionId, human.revisionId);
      const incident = await repo.getIncident(first);
      assert.deepEqual(
        incident.videos.map((video) => video.videoId),
        [names[0], names[1]],
      );
      assert.deepEqual(
        incident.revisions.map((revision) => [revision.revisionNo, revision.isOfficial, revision.videoNames]),
        [
          [2, true, [names[0]]],
          [1, false, [names[0]]],
        ],
      );
      assert.equal((await repo.getRevision(first, null)).revision.revisionId, human.revisionId);

      assert.equal(await repo.replaceVideoCrops(first, names[1], human.revisionId, [crop(names[1], 'E3')]), 1);
      const referenced = (await repo.listReferencedEvidenceImages(first, names[1])) ?? [];
      assert.deepEqual(referenced, [`evidence/${names[1]}/E3.jpg`]);

      await assert.rejects(
        repo.createAiRevision({
          incidentId: first,
          modelRunId: run,
          note: null,
          payload: envelope([]),
          evidence: [],
          videoNames: [names[2]],
          embedding: null,
        }),
        {
          name: 'StoreRejection',
        },
      );
      await repo.setOfficialRevision(first, null);
    } finally {
      // Only rows this test made: clear the official pointer, then drop videos, incidents (revisions and crops follow) and the run.
      for (const id of incidentIds) {
        await db.updateWhere('incidents', { id: String(id) }, { official_revision_id: null }).catch(() => undefined);
      }
      for (const video of names) await db.deleteWhere('evidence_crops', { video_id: video }).catch(() => undefined);
      for (const video of names) await db.deleteWhere('videos', { id: video }).catch(() => undefined);
      for (const id of incidentIds) await db.deleteWhere('incidents', { id: String(id) }).catch(() => undefined);
      await db.deleteWhere('model_runs', { id: run }).catch(() => undefined);
    }
    const left = await db.selectIn('videos', 'id', names, 'id');
    assert.deepEqual(left, [], 'no live-test video is left behind');
  });
});

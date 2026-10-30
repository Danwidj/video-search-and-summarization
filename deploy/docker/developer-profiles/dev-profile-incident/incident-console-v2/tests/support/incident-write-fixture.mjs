// SPDX-License-Identifier: Apache-2.0

// An mvp3 incident for the report write routes: two cameras that both cover the repaired-run report (so item ids
// E1, E2, I1, I2 repeat across cameras), one AI revision covering both, over the fake PostgREST with the incident
// RPCs. Import after registering ./alias-loader.mjs.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { fakePostgrest } from './fake-postgrest.mjs';
import { incidentRpcs } from './incident-database.mjs';
import { aiRevisionRow, unchangedEdit } from './report-view.mjs';

export const repaired = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-repaired-run.json'), 'utf8'));

export const A = 'vss-mvp3-p5-6-a.mp4';
export const B = 'vss-mvp3-p5-6-b.mp4';
export const RUN = 'vss-mvp3-p5-6-run';
export const imageOf = (video, itemId = 'E1') => `evidence/${video}/run/entities/${itemId}.jpg`;

const report = aiRevisionRow(repaired).payload;
const entry = (video) => ({ item_type: 'entity', item_id: 'E1', image: imageOf(video), bounding_box: null, timestamp_seconds: 2 });

export const envelope = (overview = {}) => ({
  overview: { title: 'Two cameras', type: 'theft', severity_level: 3, description: 'Both views', location: null, ...overview },
  cameras: [A, B].map((video) => ({ video, report: structuredClone(report) })),
});

/** Edit E1 of `video` so it keeps the image the parent revision gave it. */
export function editKeepingImage(video) {
  const edit = unchangedEdit(repaired);
  edit.entities[0].image = imageOf(video);
  return edit;
}

export function incidentDatabase({ official = null, evidence = [entry(A), entry(B)] } = {}) {
  const db = fakePostgrest(
    {
      incidents: [
        {
          id: 1,
          official_revision_id: official,
          official_since: official ? '2026-10-01T00:00:00' : null,
          created_at: '2026-10-01T00:00:00',
        },
      ],
      videos: [A, B].map((id) => ({
        id,
        incident_id: 1,
        filepath: id,
        uploaded_datetime: '2026-10-01T01:00:00',
        recorded_at: null,
        duration: 30,
        source: 'upload',
      })),
      model_runs: [{ ...repaired.modelRun, id: RUN }],
      report_revisions: [
        {
          id: 1,
          incident_id: 1,
          revision_no: 1,
          kind: 'ai',
          model_run_id: RUN,
          parent_id: null,
          payload: envelope(),
          evidence,
          video_names: [A, B],
          created_by: null,
          created_at: '2026-10-01T03:00:00',
          note: null,
        },
      ],
      evidence_crops: [],
    },
    { rpc: { ...incidentRpcs }, identity: { report_revisions: 'id' } },
  );
  return db;
}

export const writes = (db) => db.requests.filter((request) => request.method !== 'GET');
export const vector = (seed = 1) => Array.from({ length: 1024 }, (_, index) => seed + index / 10_000);

/**
 * One fetch for the fake PostgREST and the agent's evidence-embeddings endpoint. The agent answers a vector for
 * every item it is sent, and `agentCalls` records each request body.
 */
export function withAgent(db, { agent } = {}) {
  const agentCalls = [];
  globalThis.fetch = async (url, init) => {
    if (!String(url).startsWith('http://agent.test:8000/')) return db.fetch(url, init);
    const body = JSON.parse(init.body);
    agentCalls.push(body);
    if (agent) return agent(body);
    return new Response(
      JSON.stringify((body.evidence ?? []).map((item) => ({ item_type: item.item_type, item_id: item.item_id, embedding: vector(1) }))),
    );
  };
  return agentCalls;
}

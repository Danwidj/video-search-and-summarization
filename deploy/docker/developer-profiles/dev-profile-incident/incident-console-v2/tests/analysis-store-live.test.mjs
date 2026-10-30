// SPDX-License-Identifier: Apache-2.0

// The Supabase adapters against a real database. Skipped unless ANALYSIS_STORE_LIVE_URL and
// ANALYSIS_STORE_LIVE_KEY are set; point them at a scratch (mvp3) project only. Every row it
// creates is named with SEED and removed afterwards.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { after, before, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const url = process.env.ANALYSIS_STORE_LIVE_URL;
const key = process.env.ANALYSIS_STORE_LIVE_KEY;

describe('analysis store against a real database', { skip: !(url && key) }, () => {
  const SEED = 'vss-mvp3-p4-7-live';
  const VIDEO = `${SEED}-clip.mp4`;
  const SECOND = `${SEED}-other.mp4`;
  let db;
  let runs;
  let analyses;
  let incidentId;
  const runIds = [];

  before(async () => {
    const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');
    const { SupabaseModelRunAdapter } = await import('../src/modules/analysis/infrastructure/supabase/model-runs.ts');
    const { SupabaseVideoAnalysisAdapter } = await import('../src/modules/analysis/infrastructure/supabase/video-analyses.ts');
    db = new PostgrestClient(url, key);
    runs = new SupabaseModelRunAdapter(db);
    analyses = new SupabaseVideoAnalysisAdapter(db);
    incidentId = (await db.insertRow('incidents', {})).id;
    for (const id of [VIDEO, SECOND])
      await db.insertRow('videos', { id, incident_id: incidentId, filepath: `${SEED}/${id}`, source: SEED });
  });

  after(async () => {
    if (!db) return;
    // The incident takes its videos and their analyses with it; the runs are removed by id.
    if (incidentId) await db.deleteWhere('incidents', { id: String(incidentId) });
    for (const id of runIds) await db.deleteWhere('model_runs', { id });
  });

  test('records a run, stores two analyses and reads the latest', async () => {
    const { modelRunId } = await import('../src/modules/analysis/domain/ModelRunRepository.ts');
    const at = ['2026-10-30T01:00:00.000Z', '2026-10-30T02:00:00.000Z'];
    const ids = at.map((instant) => modelRunId(VIDEO, instant));
    runIds.push(...ids);
    for (const [index, id] of ids.entries()) {
      await runs.recordRun({
        id,
        modelName: 'seed',
        modelVersion: null,
        promptVersion: 'incident-contract-v4',
        runAt: at[index],
        notes: SEED,
      });
    }
    assert.equal((await runs.getRun(ids[0])).runAt.startsWith('2026-10-30T01:00:00'), true);
    const payload = (type) => ({ incident: { type, severity_level: 2, start_timestamp: 1, end_timestamp: 3 } });
    const first = await analyses.saveAnalysis({ videoId: VIDEO, modelRunId: ids[0], payload: payload('Assault'), evidence: [] });
    const second = await analyses.saveAnalysis({ videoId: VIDEO, modelRunId: ids[1], payload: payload('theft'), evidence: [] });
    assert.equal(first.incidentType, 'assault');
    assert.deepEqual(
      (await analyses.listAnalyses(VIDEO)).map((a) => a.id),
      [first.id, second.id],
    );
    assert.equal((await analyses.latestAnalysis(VIDEO)).id, second.id);
    const latest = await analyses.latestAnalyses([VIDEO, SECOND]);
    assert.deepEqual([...latest.keys()], [VIDEO]);
  });

  test('refuses an analysis for an unknown run', async () => {
    await assert.rejects(analyses.saveAnalysis({ videoId: VIDEO, modelRunId: `${SEED}-missing@x`, payload: {}, evidence: [] }));
  });
});

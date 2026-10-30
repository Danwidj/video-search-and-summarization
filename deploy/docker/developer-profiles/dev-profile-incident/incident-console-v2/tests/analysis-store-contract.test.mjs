// SPDX-License-Identifier: Apache-2.0

// One contract for ModelRunRepository and VideoAnalysisRepository, run against
// the in-memory fakes and the Supabase adapters over a fake PostgREST.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryModelRunRepository } = await import('../src/modules/analysis/infrastructure/memory/model-runs.ts');
const { InMemoryVideoAnalysisRepository } = await import('../src/modules/analysis/infrastructure/memory/video-analyses.ts');
const { SupabaseModelRunAdapter } = await import('../src/modules/analysis/infrastructure/supabase/model-runs.ts');
const { SupabaseVideoAnalysisAdapter } = await import('../src/modules/analysis/infrastructure/supabase/video-analyses.ts');
const { incidentRunSubject, modelRunId } = await import('../src/modules/analysis/domain/ModelRunRepository.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const VIDEOS = ['front-door.mp4', 'lobby.mp4'];
const payload = (type, severity, start, end) => ({
  incident: { type, severity_level: severity, start_timestamp: start, end_timestamp: end, description: 'x' },
  entities: [],
  instruments: [],
  assets: [],
  timeline: [],
});
const run = (subject, at) => ({
  id: modelRunId(subject, at),
  modelName: 'nvidia/cosmos-3-super-reasoner',
  modelVersion: null,
  promptVersion: 'incident-contract-v4',
  runAt: at,
  notes: '{"recordType":"analysis_attempt"}',
});

const implementations = {
  memory: () => {
    const runs = new InMemoryModelRunRepository();
    return { runs, analyses: new InMemoryVideoAnalysisRepository(VIDEOS, runs) };
  },
  supabase: () => {
    const fake = fakePostgrest(
      { videos: VIDEOS.map((id) => ({ id })), model_runs: [], video_analyses: [] },
      { identity: { video_analyses: 'id' } },
    );
    globalThis.fetch = fake.fetch;
    const db = new PostgrestClient('http://postgrest.test', 'key');
    return { runs: new SupabaseModelRunAdapter(db), analyses: new SupabaseVideoAnalysisAdapter(db), fake };
  },
};

test('run ids read <subject>@<UTC timestamp>', () => {
  assert.equal(modelRunId('front-door.mp4', new Date('2026-10-30T01:02:03.000Z')), 'front-door.mp4@2026-10-30T01:02:03.000Z');
  assert.equal(modelRunId(incidentRunSubject(7), '2026-10-30T01:02:03.000Z'), 'incident-7@2026-10-30T01:02:03.000Z');
});

for (const [name, build] of Object.entries(implementations)) {
  describe(`model runs and analyses (${name})`, () => {
    test('a recorded run reads back and re-recording replaces it in place', async () => {
      const { runs } = build();
      const first = run('front-door.mp4', '2026-10-30T01:00:00.000Z');
      assert.equal(await runs.getRun(first.id), null);
      await runs.recordRun(first);
      assert.deepEqual(await runs.getRun(first.id), first);
      await runs.recordRun({ ...first, notes: 'updated' });
      assert.equal((await runs.getRun(first.id)).notes, 'updated');
    });

    test('the latest analysis wins and every analysis stays listed oldest first', async () => {
      const { runs, analyses } = build();
      const [r1, r2] = [run('front-door.mp4', '2026-10-30T01:00:00.000Z'), run('front-door.mp4', '2026-10-30T02:00:00.000Z')];
      await runs.recordRun(r1);
      await runs.recordRun(r2);
      assert.equal(await analyses.latestAnalysis('front-door.mp4'), null);
      const a1 = await analyses.saveAnalysis({
        videoId: 'front-door.mp4',
        modelRunId: r1.id,
        payload: payload('Assault', 3, 4, 9),
        evidence: [],
        createdAt: '2026-10-30T01:00:05',
      });
      const a2 = await analyses.saveAnalysis({
        videoId: 'front-door.mp4',
        modelRunId: r2.id,
        payload: payload('theft', 2, 1, 2),
        evidence: [],
        createdAt: '2026-10-30T02:00:05',
      });
      assert.ok(a2.id > a1.id);
      assert.equal(a1.incidentType, 'assault');
      assert.equal(a1.severityLevel, 3);
      assert.deepEqual([a1.startSeconds, a1.endSeconds], [4, 9]);
      assert.equal((await analyses.latestAnalysis('front-door.mp4')).id, a2.id);
      assert.deepEqual(
        (await analyses.listAnalyses('front-door.mp4')).map((a) => a.id),
        [a1.id, a2.id],
      );
      assert.deepEqual(await analyses.listAnalyses('lobby.mp4'), []);
    });

    test('the same creation time falls back to the highest id', async () => {
      const { runs, analyses } = build();
      const r = run('lobby.mp4', '2026-10-30T03:00:00.000Z');
      await runs.recordRun(r);
      const input = {
        videoId: 'lobby.mp4',
        modelRunId: r.id,
        payload: payload('fire', 4, 0, 1),
        evidence: [],
        createdAt: '2026-10-30T03:00:01',
      };
      await analyses.saveAnalysis(input);
      const second = await analyses.saveAnalysis(input);
      assert.equal((await analyses.latestAnalysis('lobby.mp4')).id, second.id);
    });

    test('latestAnalyses returns one entry per video that has an analysis', async () => {
      const { runs, analyses } = build();
      const r = run('front-door.mp4', '2026-10-30T04:00:00.000Z');
      await runs.recordRun(r);
      const saved = await analyses.saveAnalysis({
        videoId: 'front-door.mp4',
        modelRunId: r.id,
        payload: payload('fire', 1, 0, 1),
        evidence: [],
      });
      const latest = await analyses.latestAnalyses(['front-door.mp4', 'lobby.mp4']);
      assert.deepEqual([...latest.keys()], ['front-door.mp4']);
      assert.equal(latest.get('front-door.mp4').id, saved.id);
      assert.equal((await analyses.latestAnalyses([])).size, 0);
    });

    test('the stored payload is returned unchanged and not shared with the caller', async () => {
      const { runs, analyses } = build();
      const r = run('lobby.mp4', '2026-10-30T05:00:00.000Z');
      await runs.recordRun(r);
      const input = payload('fire', 4, 0, 1);
      const saved = await analyses.saveAnalysis({ videoId: 'lobby.mp4', modelRunId: r.id, payload: input, evidence: [] });
      assert.deepEqual(saved.payload, input);
      assert.deepEqual((await analyses.latestAnalysis('lobby.mp4')).payload, input);
    });
  });
}

describe('unknown references are refused', () => {
  test('memory refuses an unknown video or run', async () => {
    const { runs, analyses } = implementations.memory();
    await runs.recordRun(run('lobby.mp4', '2026-10-30T06:00:00.000Z'));
    const base = { payload: payload('fire', 1, 0, 1), evidence: [] };
    await assert.rejects(
      analyses.saveAnalysis({ ...base, videoId: 'nope.mp4', modelRunId: run('lobby.mp4', '2026-10-30T06:00:00.000Z').id }),
      /unknown video/,
    );
    await assert.rejects(analyses.saveAnalysis({ ...base, videoId: 'lobby.mp4', modelRunId: 'missing@x' }), /unknown model run/);
  });
});

test('the Supabase adapter omits created_at by default and stores no embedding', async () => {
  const { runs, analyses, fake } = implementations.supabase();
  const r = run('lobby.mp4', '2026-10-30T07:00:00.000Z');
  await runs.recordRun(r);
  await analyses.saveAnalysis({ videoId: 'lobby.mp4', modelRunId: r.id, payload: payload('fire', 1, 0, 1), evidence: [] });
  await analyses.latestAnalysis('lobby.mp4');
  const insert = fake.requests.find((request) => request.path === 'video_analyses' && request.method === 'POST');
  assert.equal('created_at' in insert.body, false);
  assert.equal(insert.body.embedding, null);
});

// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { AnalysisClientError, parseAnalysedVideo, reanalyseVideo, reanalysisFailureLines, reportHref, requestAnalysis } = await import(
  '../src/lib/analysis/analyse-client.ts'
);

function withFetch(handler, run) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return run().finally(() => {
    globalThis.fetch = original;
  });
}

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

test('parseAnalysedVideo accepts the P5.1 answer and rejects the old report.videoId shape', () => {
  const answer = {
    incidentId: 12,
    videoName: 'front door.mp4',
    analysisId: 34,
    modelRunId: 'front door.mp4@2026-10-30T07:00:00Z',
    outcome: 'valid_first_pass',
  };
  assert.deepEqual(parseAnalysedVideo(answer), { incidentId: 12, videoName: 'front door.mp4', analysisId: 34 });
  assert.equal(parseAnalysedVideo({ report: { videoId: 'abc', revisionId: 3 } }), null);
  assert.equal(parseAnalysedVideo({ incidentId: '12', videoName: 'a.mp4', analysisId: 1 }), null);
  assert.equal(parseAnalysedVideo({ incidentId: 12, videoName: '', analysisId: 1 }), null);
  assert.equal(parseAnalysedVideo(null), null);
});

test('requestAnalysis posts the body to /api/analysis and returns the ids', async () => {
  const calls = [];
  const analysed = await withFetch(
    async (url, init) => {
      calls.push([url, init.method, JSON.parse(init.body)]);
      return json({ incidentId: 7, videoName: 'clip.mp4', analysisId: 9, outcome: 'valid_first_pass' });
    },
    () => requestAnalysis({ sensorId: 's1', filepath: 'uploads/clip.mp4', filename: 'clip.mp4', model: 'm' }),
  );
  assert.deepEqual(calls, [['/api/analysis', 'POST', { sensorId: 's1', filepath: 'uploads/clip.mp4', filename: 'clip.mp4', model: 'm' }]]);
  assert.deepEqual(analysed, { incidentId: 7, videoName: 'clip.mp4', analysisId: 9 });
});

test('requestAnalysis refuses a 200 answer that lacks the ids instead of carrying undefined forward', async () => {
  await withFetch(
    async () => json({ report: { videoId: 'clip.mp4', revisionId: 3 } }),
    () => assert.rejects(requestAnalysis({ videoName: 'clip.mp4' }), /incident id, video name and analysis id/),
  );
});

test('requestAnalysis throws the route message with the recorded outcome', async () => {
  await withFetch(
    async () => json({ error: 'A video named clip.mp4 already exists', outcome: undefined }, 409),
    () =>
      assert.rejects(requestAnalysis({ videoName: 'clip.mp4' }), (error) => {
        assert.ok(error instanceof AnalysisClientError);
        assert.equal(error.status, 409);
        assert.equal(error.message, 'A video named clip.mp4 already exists');
        assert.equal(error.outcome, null);
        return true;
      }),
  );
  await withFetch(
    async () => new Response('<html>', { status: 502 }),
    () => assert.rejects(requestAnalysis({ videoName: 'clip.mp4' }), /HTTP 502/),
  );
});

test('reanalyseVideo analyses by name, then builds the incident a new version', async () => {
  const calls = [];
  const stages = [];
  const result = await withFetch(
    async (url, init) => {
      calls.push([url, init.method, init.body ? JSON.parse(init.body) : null]);
      if (url === '/api/analysis') return json({ incidentId: 12, videoName: 'front door.mp4', analysisId: 40 });
      return json({ built: { revisionId: 55, revisionNo: 3, videoNames: ['front door.mp4', 'yard.mp4'] } });
    },
    () =>
      reanalyseVideo({ videoName: 'front door.mp4', model: 'm', additionalInstruction: '  ' }, { onStage: (stage) => stages.push(stage) }),
  );
  assert.deepEqual(calls, [
    ['/api/analysis', 'POST', { videoName: 'front door.mp4', model: 'm' }],
    ['/api/reports/12/build', 'POST', {}],
  ]);
  assert.deepEqual(stages, ['analyse', 'build']);
  assert.deepEqual(result, {
    incidentId: 12,
    videoName: 'front door.mp4',
    analysisId: 40,
    version: { revisionId: 55, revisionNo: 3, videoNames: ['front door.mp4', 'yard.mp4'] },
  });
  assert.equal(reportHref(result.incidentId, result.version.revisionId, result.videoName), '/reports/12?revision=55&camera=front+door.mp4');
});

test('reanalyseVideo keeps the reviewer prompt and stops before the build when the analysis fails', async () => {
  const calls = [];
  await withFetch(
    async (url, init) => {
      calls.push([url, JSON.parse(init.body)]);
      return json({ error: 'The model answered badly', outcome: 'contract_failed', codes: ['WINDOW_BEYOND_VIDEO'] }, 422);
    },
    () =>
      assert.rejects(reanalyseVideo({ videoName: 'clip.mp4', model: 'm', additionalInstruction: 'Watch the door' }), (error) => {
        assert.deepEqual(reanalysisFailureLines(error), [
          'The model answered, but the answer broke the incident contract, so no analysis was stored. The attempt is recorded in the history.',
          'The incident window lies outside the video',
        ]);
        return true;
      }),
  );
  assert.deepEqual(calls, [['/api/analysis', { videoName: 'clip.mp4', model: 'm', additionalInstruction: 'Watch the door' }]]);
});

test('reanalysisFailureLines explains a failed request and passes other errors through', () => {
  assert.deepEqual(
    reanalysisFailureLines(new AnalysisClientError('x', { status: 502, outcome: 'request_failed', code: 'FINISH_LENGTH' })),
    [
      'The model request did not produce a usable answer. The attempt is recorded in the history.',
      'The model ran out of its token budget before finishing',
    ],
  );
  assert.deepEqual(reanalysisFailureLines(new Error('No analysis is stored for: yard.mp4. Analyse them first.')), [
    'No analysis is stored for: yard.mp4. Analyse them first.',
  ]);
  assert.deepEqual(reanalysisFailureLines('odd'), ['Re-analysis failed']);
});

test('reportHref opens the incident, with the version and camera only when chosen', () => {
  assert.equal(reportHref(3), '/reports/3');
  assert.equal(reportHref(3, 8), '/reports/3?revision=8');
  assert.equal(reportHref(3, null, 'a b.mp4'), '/reports/3?camera=a+b.mp4');
});

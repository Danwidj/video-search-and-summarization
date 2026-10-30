// SPDX-License-Identifier: Apache-2.0

// The suggestions use cases over the in-memory fakes: evaluating an incident against all others,
// listing the pending ones, accepting (merging) and rejecting.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { evaluateIncident, MatchJudgeError } = await import('../src/modules/matching/application/evaluate-incident.ts');
const { acceptSuggestion, listPendingSuggestions, rejectSuggestion } = await import(
  '../src/modules/matching/application/decide-suggestion.ts'
);
const { InMemoryMatchShortlist, InMemorySuggestionStore } = await import('../src/modules/matching/infrastructure/memory/matching.ts');
const { FakeMatchJudge } = await import('../src/modules/matching/infrastructure/agent/fake-match-judge.ts');
const { InMemoryIncidentReportRepository } = await import('../src/modules/reports/infrastructure/memory/incident-reports.ts');
const { InMemoryModelRunRepository } = await import('../src/modules/analysis/infrastructure/memory/model-runs.ts');
const { InMemoryVideoAnalysisRepository } = await import('../src/modules/analysis/infrastructure/memory/video-analyses.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');

const RUN = 'a.mp4@2026-10-30T00:00:00.000Z';
const signal = new AbortController().signal;

// Incidents 1 and 2 are the same event at the same place; 3 is the same type with no known place; 4 is a different type.
const INCIDENTS = [
  { id: 1, video: 'a.mp4', type: 'fire', location: 'Warehouse 3', embedding: [1, 0, 0], recordedAt: '2026-10-01T10:00:00Z' },
  { id: 2, video: 'b.mp4', type: 'fire', location: 'Warehouse 3', embedding: [0.9, 0.1, 0], recordedAt: '2026-10-01T10:00:20Z' },
  { id: 3, video: 'c.mp4', type: 'fire', location: null, embedding: [0.8, 0.2, 0], recordedAt: null },
  { id: 4, video: 'd.mp4', type: 'collision', location: 'Warehouse 3', embedding: [0.7, 0.3, 0], recordedAt: null },
];

async function world({ judge = new FakeMatchJudge(), withRevisions = [1, 2, 3, 4] } = {}) {
  const reports = new InMemoryIncidentReportRepository({
    incidents: INCIDENTS.map(({ id }) => ({ incidentId: id, officialRevisionId: null, officialSince: null, createdAt: null })),
    videos: INCIDENTS.map(({ id, video, recordedAt }) => ({
      incidentId: id,
      videoId: video,
      storageKey: `uploads/${video}`,
      uploadedAt: null,
      recordedAt,
      durationSeconds: 30,
      source: null,
    })),
    revisions: INCIDENTS.filter(({ id }) => withRevisions.includes(id)).map(({ id, video, type, location }) => ({
      revision: {
        revisionId: id * 10,
        incidentId: id,
        revisionNo: 1,
        kind: 'ai',
        createdBy: null,
        createdAt: null,
        note: null,
        parentId: null,
        modelRunId: RUN,
        model: null,
        videoNames: [video],
      },
      payload: { overview: { title: 't', type, severity_level: 3, description: 'd', location }, cameras: [] },
      evidence: [],
    })),
    modelRuns: { [RUN]: 'model-x' },
  });
  const runs = new InMemoryModelRunRepository();
  await runs.recordRun({
    id: RUN,
    modelName: 'model-x',
    modelVersion: null,
    promptVersion: null,
    runAt: '2026-10-30T00:00:00Z',
    notes: null,
  });
  const analyses = new InMemoryVideoAnalysisRepository(
    INCIDENTS.map(({ video }) => video),
    runs,
  );
  for (const { video, type, location } of INCIDENTS) {
    await analyses.saveAnalysis({ videoId: video, modelRunId: RUN, payload: { incident: { type, location } }, evidence: [] });
  }
  const suggestions = new InMemorySuggestionStore();
  const shortlist = new InMemoryMatchShortlist(
    INCIDENTS.map(({ id, video, embedding }) => ({ videoId: video, incidentId: id, embedding })),
    suggestions,
  );
  return { reports, analyses, suggestions, judge, matching: { shortlist, suggestions, judge } };
}

describe('evaluateIncident structured reasons', () => {
  test('records the agent chips with the suggestion and returns them', async () => {
    const w = await world({ judge: new FakeMatchJudge([], { structured: true }) });
    const result = await evaluateIncident(w, 1, signal);
    assert.deepEqual(
      result.suggestions[0].structuredReasons.map((r) => r.kind),
      ['same_event_type', 'same_place', 'time_overlap'],
    );
    const [pending] = await listPendingSuggestions(w.suggestions);
    assert.deepEqual(
      pending.structuredReasons.map((r) => r.label),
      ['Same event type', 'Same place', 'Time overlap'],
    );
    assert.ok(pending.reasons.length > 0);
  });

  test('without chips from the agent the suggestion keeps only the text reasons', async () => {
    const w = await world();
    const result = await evaluateIncident(w, 1, signal);
    assert.deepEqual(result.suggestions[0].structuredReasons, []);
    const [pending] = await listPendingSuggestions(w.suggestions);
    assert.deepEqual(pending.structuredReasons, []);
    assert.ok(pending.reasons.length > 0);
  });
});

describe('evaluateIncident', () => {
  test('records a pending suggestion for each judged match above the threshold, with reasons and score', async () => {
    const w = await world();
    const result = await evaluateIncident(w, 1, signal);
    assert.deepEqual(
      result.suggestions.map((s) => [s.incidentId, s.score, s.created]),
      [
        [2, 1, true],
        [3, 0.65, true],
      ],
    );
    assert.ok(result.suggestions[0].reasons.length > 0);
    const pending = await listPendingSuggestions(w.suggestions);
    assert.deepEqual(
      pending.map((s) => [s.incidentAId, s.incidentBId, s.status]),
      [
        [1, 2, 'pending'],
        [1, 3, 'pending'],
      ],
    );
  });

  test('a candidate that is a different event type scores 0 and is not suggested', async () => {
    const w = await world();
    const result = await evaluateIncident(w, 1, signal);
    assert.ok(!result.suggestions.some((s) => s.incidentId === 4));
    assert.equal(result.judged, 3);
  });

  test('the judge gets the candidates overview, video names and recorded span', async () => {
    const w = await world();
    await evaluateIncident(w, 1, signal);
    const [call] = w.judge.calls;
    assert.deepEqual(call.analysis, { incident: { type: 'fire', location: 'Warehouse 3' } });
    assert.equal(call.recordedAtStart, Date.parse('2026-10-01T10:00:00Z') / 1000);
    assert.equal(call.recordedAtEnd, Date.parse('2026-10-01T10:00:00Z') / 1000 + 30);
    const two = call.candidates.find((c) => c.incidentId === 2);
    assert.deepEqual(two.videoNames, ['b.mp4']);
    assert.equal(two.overview.location, 'Warehouse 3');
    assert.equal(two.recordedAtStart, Date.parse('2026-10-01T10:00:20Z') / 1000);
    assert.equal(call.candidates.find((c) => c.incidentId === 3).recordedAtStart, null);
  });

  test('batch members find each other whichever order they finish: evaluating the second also finds the first', async () => {
    const w = await world();
    const result = await evaluateIncident(w, 2, signal);
    assert.deepEqual(
      result.suggestions.map((s) => s.incidentId),
      [1, 3],
    );
  });

  test('evaluating both ends of a pair keeps one row', async () => {
    const w = await world();
    await evaluateIncident(w, 1, signal);
    const again = await evaluateIncident(w, 2, signal);
    assert.deepEqual(
      again.suggestions.map((s) => s.incidentId),
      [3],
    );
    assert.equal((await listPendingSuggestions(w.suggestions)).filter((s) => s.incidentBId === 2 || s.incidentAId === 2).length, 2);
  });

  test('a pending pair is not judged again; a rejected pair is never suggested again', async () => {
    const w = await world();
    const first = await evaluateIncident(w, 1, signal);
    const rejected = first.suggestions.find((s) => s.incidentId === 2);
    await rejectSuggestion(w.suggestions, rejected.suggestionId);
    w.judge.calls.length = 0;
    const second = await evaluateIncident(w, 1, signal);
    assert.deepEqual(second.suggestions, []);
    const asked = w.judge.calls.flatMap((call) => call.candidates.map((c) => c.incidentId));
    assert.deepEqual(asked, [4], 'incident 2 is decided and incident 3 is pending, so only the unmatched incident 4 is judged again');
    assert.equal(
      (await evaluateIncident(w, 2, signal)).suggestions.some((s) => s.incidentId === 1),
      false,
    );
  });

  test('a candidate without a report is judged with a null overview', async () => {
    const w = await world({ withRevisions: [] });
    await evaluateIncident(w, 1, signal);
    assert.equal(w.judge.calls[0].candidates[0].overview, null);
  });

  test('a score below the threshold is not suggested', async () => {
    const w = await world();
    const result = await evaluateIncident(w, 1, signal, { minScore: 0.9 });
    assert.deepEqual(
      result.suggestions.map((s) => s.incidentId),
      [2],
    );
  });

  test('a video with no analysis is skipped', async () => {
    const w = await world();
    w.analyses.latestAnalysis = async () => null;
    const result = await evaluateIncident(w, 1, signal);
    assert.deepEqual(result, { incidentId: 1, judged: 0, suggestions: [] });
    assert.equal(w.judge.calls.length, 0);
  });

  test('refuses an unknown incident, a missing judge and a failed judgement', async () => {
    const w = await world();
    await assert.rejects(evaluateIncident(w, 99, signal), (e) => e instanceof StoreRejection && e.reason === 'not-found');
    await assert.rejects(
      evaluateIncident({ ...w, matching: { ...w.matching, judge: null } }, 1, signal),
      (e) => e instanceof MatchJudgeError && e.status === 503,
    );
    const failing = await world({ judge: new FakeMatchJudge([{ kind: 'failed', status: 500, message: 'model down' }]) });
    await assert.rejects(
      evaluateIncident(failing, 1, signal),
      (e) => e instanceof MatchJudgeError && e.status === 502 && e.message === 'model down',
    );
    assert.deepEqual(await listPendingSuggestions(failing.suggestions), []);
  });
});

describe('accept and reject', () => {
  /** The database marks the suggestion accepted inside merge_incidents; the in-memory repository does not know the store. */
  async function withMergeMark() {
    const w = await world();
    const pending = (await evaluateIncident(w, 1, signal)).suggestions;
    const merge = w.reports.mergeIncidents.bind(w.reports);
    w.reports.mergeIncidents = async (target, source) => {
      const result = await merge(target, source);
      for (const s of w.suggestions.suggestions) {
        if ([s.incidentAId, s.incidentBId].sort().join() === [target, source].sort().join() && s.status === 'pending') {
          w.suggestions.markAccepted(s.id);
        }
      }
      return result;
    };
    return { w, pending };
  }

  test('accept merges the pair into the older incident and the suggestion leaves the pending list', async () => {
    const { w, pending } = await withMergeMark();
    const id = pending.find((s) => s.incidentId === 2).suggestionId;
    const accepted = await acceptSuggestion(w, id);
    assert.deepEqual([accepted.merge.incidentId, accepted.merge.sourceIncidentId, accepted.merge.movedVideoIds], [1, 2, ['b.mp4']]);
    assert.deepEqual((await w.reports.getIncident(1)).videos.map((v) => v.videoId).sort(), ['a.mp4', 'b.mp4']);
    assert.equal(await w.reports.getIncident(2), null);
    assert.deepEqual(
      (await listPendingSuggestions(w.suggestions)).map((s) => s.id),
      [pending.find((s) => s.incidentId === 3).suggestionId],
    );
  });

  test('accept can keep the other incident of the pair, and refuses one outside it', async () => {
    const { w, pending } = await withMergeMark();
    const id = pending.find((s) => s.incidentId === 2).suggestionId;
    await assert.rejects(acceptSuggestion(w, id, 3), (e) => e instanceof StoreRejection && e.reason === 'invalid');
    const accepted = await acceptSuggestion(w, id, 2);
    assert.deepEqual([accepted.merge.incidentId, accepted.merge.sourceIncidentId], [2, 1]);
  });

  test('accept refuses an unknown or already decided suggestion', async () => {
    const { w, pending } = await withMergeMark();
    await assert.rejects(acceptSuggestion(w, 999), (e) => e instanceof StoreRejection && e.reason === 'not-found');
    const id = pending.find((s) => s.incidentId === 3).suggestionId;
    await rejectSuggestion(w.suggestions, id);
    await assert.rejects(acceptSuggestion(w, id), (e) => e instanceof StoreRejection && e.reason === 'not-found');
  });

  test('reject is remembered, repeatable, and refuses an unknown id', async () => {
    const w = await world();
    const [first] = (await evaluateIncident(w, 1, signal)).suggestions;
    assert.deepEqual(await rejectSuggestion(w.suggestions, first.suggestionId), { suggestionId: first.suggestionId, status: 'rejected' });
    assert.deepEqual(await rejectSuggestion(w.suggestions, first.suggestionId), { suggestionId: first.suggestionId, status: 'rejected' });
    await assert.rejects(rejectSuggestion(w.suggestions, 999), (e) => e instanceof StoreRejection && e.reason === 'not-found');
  });

  test('listing by incident keeps only the suggestions that name it', async () => {
    const w = await world();
    await evaluateIncident(w, 1, signal);
    assert.equal((await listPendingSuggestions(w.suggestions, 3)).length, 1);
    assert.equal((await listPendingSuggestions(w.suggestions, 4)).length, 0);
  });
});

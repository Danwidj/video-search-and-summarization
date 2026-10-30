// SPDX-License-Identifier: Apache-2.0

// P6.8: the review cards for pending suggestions (use case and route) and the suggestion UI's wiring.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { listSuggestionCards } = await import('../src/modules/matching/application/list-suggestion-cards.ts');
const { InMemorySuggestionStore } = await import('../src/modules/matching/infrastructure/memory/matching.ts');
const { InMemoryIncidentReportRepository } = await import('../src/modules/reports/infrastructure/memory/incident-reports.ts');
const { SupabaseIncidentReportAdapter } = await import('../src/modules/reports/infrastructure/supabase/incident-reports.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');
const { A, B, incidentDatabase } = await import('./support/incident-write-fixture.mjs');
const cardsRoute = await import('../src/app/api/suggestions/cards/route.ts');

const video = (incidentId, videoId, storageKey) => ({
  incidentId,
  videoId,
  storageKey,
  uploadedAt: null,
  recordedAt: null,
  durationSeconds: 30,
  source: null,
});

function world() {
  const reports = new InMemoryIncidentReportRepository({
    incidents: [1, 2, 3].map((incidentId) => ({ incidentId, officialRevisionId: null, officialSince: null, createdAt: null })),
    videos: [
      video(1, 'door-1.mp4', 'uploads/door-1.mp4'),
      video(1, 'door-2.mp4', 'uploads/door-2.mp4'),
      video(2, 'gate.mp4', null),
      video(3, 'van.mp4', 'uploads/van.mp4'),
    ],
    revisions: [
      {
        revision: {
          revisionId: 10,
          incidentId: 1,
          revisionNo: 1,
          kind: 'ai',
          createdBy: null,
          createdAt: null,
          note: null,
          parentId: null,
          modelRunId: null,
          model: null,
          videoNames: ['door-1.mp4'],
        },
        payload: {
          overview: { title: 'Forced entry', type: 'Intrusion', severity_level: 4, description: 'd', location: 'Block 12' },
          cameras: [],
        },
        evidence: [],
      },
    ],
    modelRuns: {},
  });
  return { reports, suggestions: new InMemorySuggestionStore() };
}

const sign = async (key) => `https://signed.test/${key}`;

describe('listSuggestionCards', () => {
  test('describes both incidents of each pending pair, the older one kept, highest score first', async () => {
    const w = world();
    await w.suggestions.record(2, 1, 0.6, ['Same place']);
    await w.suggestions.record(3, 1, 0.9, ['Same place', 'Same event type']);
    const cards = await listSuggestionCards(w, sign);
    assert.deepEqual(
      cards.map((c) => [c.score, c.kept.incidentId, c.joining.incidentId]),
      [
        [0.9, 1, 3],
        [0.6, 1, 2],
      ],
    );
    assert.deepEqual(cards[0].reasons, ['Same place', 'Same event type']);
    assert.equal(cards[0].kept.title, 'Forced entry');
    assert.deepEqual(cards[0].kept.videoNames, ['door-1.mp4', 'door-2.mp4']);
    assert.equal(cards[0].kept.thumbnailUrl, 'https://signed.test/thumbnails/uploads/door-1.mp4.webp');
  });

  test('a side without a version has no title, and one without a stored video has no thumbnail', async () => {
    const w = world();
    await w.suggestions.record(1, 2, 0.8, []);
    const [card] = await listSuggestionCards(w, sign);
    assert.equal(card.joining.title, null);
    assert.equal('thumbnailUrl' in card.joining, false);
  });

  test('a failing signer only drops the thumbnail', async () => {
    const w = world();
    await w.suggestions.record(1, 3, 0.8, []);
    const [card] = await listSuggestionCards(w, async () => {
      throw new Error('no signer');
    });
    assert.equal('thumbnailUrl' in card.kept, false);
  });

  test('only the suggestions naming the incident are listed, and decided ones are left out', async () => {
    const w = world();
    const a = await w.suggestions.record(1, 2, 0.8, []);
    await w.suggestions.record(2, 3, 0.7, []);
    assert.deepEqual(
      (await listSuggestionCards(w, sign, 3)).map((c) => c.joining.incidentId),
      [3],
    );
    await w.suggestions.reject(a.suggestionId);
    assert.deepEqual(
      (await listSuggestionCards(w, sign)).map((c) => c.id),
      [2],
    );
  });
});

describe('listSuggestionCards over the Supabase adapter', () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  // Incident 1 has two videos and a revision; 2 and 3 are one video each with no revision.
  function database() {
    const db = incidentDatabase({ official: 1 });
    for (const [id, video] of [
      [2, 'gate.mp4'],
      [3, 'van.mp4'],
    ]) {
      db.store.incidents.push({ id, official_revision_id: null, official_since: null, created_at: '2026-10-01T00:00:00' });
      db.store.videos.push({ id: video, incident_id: id, filepath: `uploads/${video}`, uploaded_datetime: '2026-10-01T01:00:00' });
    }
    globalThis.fetch = db.fetch;
    return db;
  }
  const reports = () => new SupabaseIncidentReportAdapter(new PostgrestClient('https://supabase.test', 'k'));
  const pending = (pairs) => ({
    listPending: async () => pairs.map(([a, b], id) => ({ id: id + 1, incidentAId: a, incidentBId: b, score: 0.9, reasons: [] })),
  });

  test('reads each side with a few narrow requests and never loads a model run', async () => {
    const db = database();
    const cards = await listSuggestionCards({ suggestions: pending([[1, 2]]), reports: reports() }, sign);
    assert.equal(cards[0].kept.title, 'Two cameras');
    assert.deepEqual(cards[0].kept.videoNames, [A, B]);
    assert.equal(cards[0].joining.title, null);
    assert.deepEqual(cards[0].joining.videoNames, ['gate.mp4']);
    assert.equal(cards[0].joining.thumbnailUrl, 'https://signed.test/thumbnails/uploads/gate.mp4.webp');
    const paths = db.requests.map((request) => request.path);
    assert.ok(!paths.includes('model_runs'), 'a title needs no model run');
    assert.ok(paths.length <= 7, `at most 3 requests per side, saw ${paths.length}: ${paths}`);
  });

  test('a side shared by several suggestions is read once', async () => {
    const db = database();
    const cards = await listSuggestionCards(
      {
        suggestions: pending([
          [1, 2],
          [1, 3],
          [2, 3],
        ]),
        reports: reports(),
      },
      sign,
    );
    assert.equal(cards.length, 3);
    assert.equal(db.requests.filter((request) => request.path === 'incidents').length, 3);
  });
});

describe('GET /api/suggestions/cards', () => {
  const originalEnv = { ...process.env };
  beforeEach(() => {
    Object.assign(process.env, { INCIDENT_SUPABASE_URL: 'https://supabase.test', INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k' });
  });
  afterEach(() => {
    process.env = { ...originalEnv };
  });

  test('rejects an incidentId that is not a positive integer', async () => {
    for (const bad of ['abc', '0', '-1', '1.5']) {
      const response = await cardsRoute.GET(new Request(`http://localhost/api/suggestions/cards?incidentId=${bad}`));
      assert.equal(response.status, 400, bad);
    }
  });
});

describe('suggestion UI wiring', () => {
  const src = join(process.cwd(), 'src');
  const read = (file) => readFileSync(join(src, file), 'utf8');

  test('the report page mounts the banner for its own incident and reloads after a merge', () => {
    assert.match(
      read('sections/reports/components/ReportPage/ReportPage.tsx'),
      /<SuggestionBanner incidentId=\{Number\(incidentId\)\} onMerged=/,
    );
  });

  test('the library has a Matches tab with a pending count and a strip above the incident list', () => {
    const library = read('sections/library/components/LibraryScreen/LibraryScreen.tsx');
    assert.match(library, /value="matches"/);
    assert.match(library, /<PendingStrip count=\{suggestions\.cards\.length\}/);
    assert.match(library, /<SuggestionsTab state=\{suggestions\} \/>/);
  });

  test('accept names the kept incident and reject posts to the reject route', () => {
    const hook = read('sections/suggestions/use-suggestion-cards.ts');
    assert.match(hook, /\/api\/suggestions\/\$\{card\.id\}\/accept/);
    assert.match(hook, /incidentId: card\.kept\.incidentId/);
    assert.match(hook, /\/api\/suggestions\/\$\{card\.id\}\/reject/);
  });

  test('every card shows its reasons, a score and accept and reject', () => {
    const shared = read('sections/suggestions/components/Shared/Shared.tsx');
    for (const id of ['suggestion-reasons', 'suggestion-score', 'suggestion-accept', 'suggestion-reject'])
      assert.match(shared, new RegExp(id));
  });
});

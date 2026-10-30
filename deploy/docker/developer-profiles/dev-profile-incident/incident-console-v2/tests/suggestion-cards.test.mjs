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

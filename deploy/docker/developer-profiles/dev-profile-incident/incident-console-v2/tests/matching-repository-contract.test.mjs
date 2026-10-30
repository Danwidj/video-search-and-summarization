// SPDX-License-Identifier: Apache-2.0

// One SuggestionStore and MatchShortlist contract, run against the in-memory fakes and the Supabase
// adapters over a fake PostgREST whose functions follow 20261030180000_matching.sql. The same
// adapters are proven against the real mvp3 database by the live check in the P4.3 PR.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryMatchShortlist, InMemorySuggestionStore } = await import('../src/modules/matching/infrastructure/memory/matching.ts');
const { SupabaseMatchShortlistAdapter, SupabaseSuggestionAdapter } = await import(
  '../src/modules/matching/infrastructure/supabase/matching.ts'
);
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

// Video embeddings: v1 (incident 1) is closest to v2 (incident 2), then v3 (incident 3); v4 has none.
const VIDEOS = [
  { videoId: 'v1', incidentId: 1, embedding: [1, 0, 0] },
  { videoId: 'v1b', incidentId: 1, embedding: [0, 1, 0] },
  { videoId: 'v2', incidentId: 2, embedding: [0.9, 0.1, 0] },
  { videoId: 'v2b', incidentId: 2, embedding: [0.5, 0.5, 0] },
  { videoId: 'v3', incidentId: 3, embedding: [0.5, 0.5, 0.5] },
  { videoId: 'v4', incidentId: 4, embedding: null },
];

const cosine = (a, b) => a.reduce((sum, x, i) => sum + x * b[i], 0) / (Math.hypot(...a) * Math.hypot(...b));
const pairKey = (a, b) => `${Math.min(a, b)}:${Math.max(a, b)}`;

/** The three functions of the matching migration, over the fake store. */
function rpcOver(videos) {
  const refuse = (message) => {
    throw new Error(message);
  };
  return {
    shortlist_similar_incidents: ({ p_video_id, p_limit, p_min_similarity }, store) => {
      const own = videos.find((video) => video.videoId === p_video_id);
      if (!own?.embedding) return [];
      const decided = new Set(
        store.incident_match_suggestions.filter((s) => s.status !== 'pending').map((s) => pairKey(s.incident_a_id, s.incident_b_id)),
      );
      const best = new Map();
      for (const video of videos) {
        if (!video.embedding || video.incidentId === own.incidentId || decided.has(pairKey(own.incidentId, video.incidentId))) continue;
        const similarity = cosine(own.embedding, video.embedding);
        const current = best.get(video.incidentId);
        if (!current || similarity > current.similarity)
          best.set(video.incidentId, { incident_id: video.incidentId, similarity, best_video_id: video.videoId });
      }
      return [...best.values()]
        .filter((row) => row.similarity >= p_min_similarity)
        .sort((a, b) => b.similarity - a.similarity || a.incident_id - b.incident_id)
        .slice(0, p_limit);
    },
    record_match_suggestion: ({ p_incident_a_id: a, p_incident_b_id: b, p_score, p_reasons }, store) => {
      if (a === b) refuse('an incident cannot be suggested against itself');
      if (p_score < 0 || p_score > 1) refuse('score must be between 0 and 1');
      const rows = store.incident_match_suggestions;
      const existing = rows.find((s) => pairKey(s.incident_a_id, s.incident_b_id) === pairKey(a, b));
      if (existing) return { suggestionId: existing.id, status: existing.status, created: false };
      const row = {
        id: Math.max(0, ...rows.map((s) => s.id)) + 1,
        incident_a_id: a,
        incident_b_id: b,
        score: p_score,
        reasons: p_reasons,
        status: 'pending',
        created_at: '2026-10-30T00:00:00',
        decided_at: null,
      };
      rows.push(row);
      return { suggestionId: row.id, status: 'pending', created: true };
    },
    reject_match_suggestion: ({ p_suggestion_id }, store) => {
      const row = store.incident_match_suggestions.find((s) => s.id === p_suggestion_id);
      if (!row) refuse(`match suggestion ${p_suggestion_id} does not exist`);
      if (row.status === 'accepted') refuse(`match suggestion ${p_suggestion_id} is already accepted`);
      if (row.status === 'pending') Object.assign(row, { status: 'rejected', decided_at: '2026-10-30T01:00:00' });
      return { suggestionId: p_suggestion_id, status: 'rejected' };
    },
  };
}

const implementations = {
  memory: () => {
    const suggestions = new InMemorySuggestionStore();
    return {
      suggestions,
      shortlist: new InMemoryMatchShortlist(VIDEOS, suggestions),
      accept: (id) => suggestions.markAccepted(id),
    };
  },
  supabase: () => {
    const db = fakePostgrest({ incident_match_suggestions: [] }, { rpc: rpcOver(VIDEOS) });
    globalThis.fetch = db.fetch;
    const client = new PostgrestClient('https://supabase.test', 'k');
    return {
      suggestions: new SupabaseSuggestionAdapter(client),
      shortlist: new SupabaseMatchShortlistAdapter(client),
      accept: (id) => {
        db.store.incident_match_suggestions.find((s) => s.id === id).status = 'accepted';
      },
    };
  },
};

const rejection = (reason) => (error) => error instanceof StoreRejection && error.reason === reason;

for (const [name, make] of Object.entries(implementations)) {
  describe(`matching contract: ${name}`, () => {
    test('the shortlist ranks other incidents by their best video and never offers the own incident', async () => {
      const { shortlist } = make();
      const found = await shortlist.shortlist('v1', 5, 0);
      assert.deepEqual(
        found.map((candidate) => [candidate.incidentId, candidate.bestVideoId]),
        [
          [2, 'v2'],
          [3, 'v3'],
        ],
      );
      assert.ok(found[0].similarity > found[1].similarity);
      assert.deepEqual(
        (await shortlist.shortlist('v1', 1, 0)).map((candidate) => candidate.incidentId),
        [2],
      );
      assert.deepEqual(
        (await shortlist.shortlist('v1', 5, 0.95)).map((candidate) => candidate.incidentId),
        [2],
      );
    });

    test('a video with no embedding or no analysis has an empty shortlist', async () => {
      const { shortlist } = make();
      assert.deepEqual(await shortlist.shortlist('v4', 5, 0), []);
      assert.deepEqual(await shortlist.shortlist('missing.mp4', 5, 0), []);
    });

    test('a decided pair (rejected or accepted) is never shortlisted again', async () => {
      const { shortlist, suggestions, accept } = make();
      const rejected = await suggestions.record(1, 2, 0.8, ['same place']);
      await suggestions.reject(rejected.suggestionId);
      assert.deepEqual(
        (await shortlist.shortlist('v1', 5, 0)).map((candidate) => candidate.incidentId),
        [3],
      );
      const accepted = await suggestions.record(3, 1, 0.7, []);
      accept(accepted.suggestionId);
      assert.deepEqual(await shortlist.shortlist('v1', 5, 0), []);
    });

    test('a pending pair stays shortlisted', async () => {
      const { shortlist, suggestions } = make();
      await suggestions.record(1, 2, 0.8, []);
      assert.equal((await shortlist.shortlist('v1', 5, 0)).length, 2);
    });

    test('a suggestion is recorded once per unordered pair and keeps its first score and reasons', async () => {
      const { suggestions } = make();
      const first = await suggestions.record(1, 2, 0.8, ['same place', 'same type']);
      assert.deepEqual(first, { suggestionId: first.suggestionId, status: 'pending', created: true });
      const again = await suggestions.record(2, 1, 0.3, ['other']);
      assert.deepEqual(again, { suggestionId: first.suggestionId, status: 'pending', created: false });
      const [pending] = await suggestions.listPending();
      assert.deepEqual(
        [pending.incidentAId, pending.incidentBId, pending.score, pending.reasons],
        [1, 2, 0.8, ['same place', 'same type']],
      );
    });

    test('a self pair, a bad score or an unknown pair status is refused as invalid', async () => {
      const { suggestions } = make();
      await assert.rejects(suggestions.record(1, 1, 0.5, []), rejection('invalid'));
      await assert.rejects(suggestions.record(1, 2, 1.5, []), rejection('invalid'));
      await assert.rejects(suggestions.record(1, 2, -0.1, []), rejection('invalid'));
    });

    test('pending suggestions list highest score first and can be narrowed to one incident', async () => {
      const { suggestions } = make();
      await suggestions.record(1, 2, 0.5, ['a']);
      await suggestions.record(3, 1, 0.9, ['b']);
      await suggestions.record(2, 3, 0.7, ['c']);
      assert.deepEqual(
        (await suggestions.listPending()).map((s) => s.score),
        [0.9, 0.7, 0.5],
      );
      assert.deepEqual(
        (await suggestions.listPending(1)).map((s) => s.score),
        [0.9, 0.5],
      );
      assert.deepEqual(await suggestions.listPending(99), []);
    });

    test('a rejected suggestion leaves the pending list, stays remembered and rejecting again changes nothing', async () => {
      const { suggestions } = make();
      const { suggestionId } = await suggestions.record(1, 2, 0.8, ['a']);
      assert.deepEqual(await suggestions.reject(suggestionId), { suggestionId, status: 'rejected' });
      assert.deepEqual(await suggestions.listPending(), []);
      assert.deepEqual(await suggestions.reject(suggestionId), { suggestionId, status: 'rejected' });
      assert.deepEqual(await suggestions.record(2, 1, 0.99, []), { suggestionId, status: 'rejected', created: false });
    });

    test('rejecting an unknown suggestion is not-found and an accepted one is invalid', async () => {
      const { suggestions, accept } = make();
      await assert.rejects(suggestions.reject(404), rejection('not-found'));
      const { suggestionId } = await suggestions.record(1, 2, 0.8, []);
      accept(suggestionId);
      await assert.rejects(suggestions.reject(suggestionId), rejection('invalid'));
    });
  });
}

describe('SupabaseSuggestionAdapter', () => {
  test('sends the p_* arguments of the matching functions and reads rows as camelCase', async () => {
    const db = fakePostgrest({ incident_match_suggestions: [] }, { rpc: rpcOver(VIDEOS) });
    globalThis.fetch = db.fetch;
    const adapter = new SupabaseSuggestionAdapter(new PostgrestClient('https://supabase.test', 'k'));
    await adapter.record(1, 2, 0.8, ['a']);
    assert.deepEqual(db.requests[0], {
      method: 'POST',
      path: 'rpc/record_match_suggestion',
      body: { p_incident_a_id: 1, p_incident_b_id: 2, p_score: 0.8, p_reasons: ['a'] },
    });
    assert.deepEqual(await adapter.listPending(), [
      {
        id: 1,
        incidentAId: 1,
        incidentBId: 2,
        score: 0.8,
        reasons: ['a'],
        status: 'pending',
        createdAt: '2026-10-30T00:00:00',
        decidedAt: null,
      },
    ]);
  });

  test('a failure that is not a domain refusal is rethrown unchanged', async () => {
    globalThis.fetch = async () => new Response('boom', { status: 500 });
    const adapter = new SupabaseSuggestionAdapter(new PostgrestClient('https://supabase.test', 'k'));
    await assert.rejects(adapter.reject(1), /HTTP 500/);
  });

  test('an incident that does not exist (foreign key) is not-found', async () => {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({ code: '23503', message: 'insert violates foreign key constraint "incident_match_suggestions_b_fkey"' }),
        {
          status: 409,
        },
      );
    const adapter = new SupabaseSuggestionAdapter(new PostgrestClient('https://supabase.test', 'k'));
    await assert.rejects(adapter.record(1, 99, 0.5, []), rejection('not-found'));
  });
});

describe('SupabaseMatchShortlistAdapter', () => {
  test('sends the p_* arguments of shortlist_similar_incidents', async () => {
    const db = fakePostgrest({ incident_match_suggestions: [] }, { rpc: rpcOver(VIDEOS) });
    globalThis.fetch = db.fetch;
    await new SupabaseMatchShortlistAdapter(new PostgrestClient('https://supabase.test', 'k')).shortlist('v1', 3, 0.2);
    assert.deepEqual(db.requests[0], {
      method: 'POST',
      path: 'rpc/shortlist_similar_incidents',
      body: { p_video_id: 'v1', p_limit: 3, p_min_similarity: 0.2 },
    });
  });
});

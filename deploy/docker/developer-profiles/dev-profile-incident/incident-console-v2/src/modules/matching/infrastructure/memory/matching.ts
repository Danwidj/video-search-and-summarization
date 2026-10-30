// SPDX-License-Identifier: Apache-2.0

// In-memory shortlist and suggestion store for use-case tests. They mirror the database functions:
// one suggestion row per unordered pair of incidents (a rejected pair stays rejected), the
// shortlist never offers the video's own incident or a decided pair, and an incident scores its
// best video by cosine similarity of the latest analysis embeddings.

import { StoreRejection } from '@/modules/shared/domain/common';
import type {
  MatchShortlist,
  MatchSuggestion,
  RecordedSuggestion,
  ShortlistedIncident,
  SuggestionStore,
} from '@/modules/matching/domain/matching';

export class InMemorySuggestionStore implements SuggestionStore {
  readonly suggestions: MatchSuggestion[] = [];

  private nextId = 1;

  async record(incidentAId: number, incidentBId: number, score: number, reasons: string[]): Promise<RecordedSuggestion> {
    if (incidentAId === incidentBId) throw new StoreRejection('invalid', 'an incident cannot be suggested against itself');
    if (!(score >= 0 && score <= 1)) throw new StoreRejection('invalid', 'score must be between 0 and 1');
    const existing = this.find(incidentAId, incidentBId);
    if (existing) return { suggestionId: existing.id, status: existing.status, created: false };
    const suggestion: MatchSuggestion = {
      id: this.nextId++,
      incidentAId,
      incidentBId,
      score,
      reasons: [...reasons],
      status: 'pending',
      createdAt: new Date().toISOString(),
      decidedAt: null,
    };
    this.suggestions.push(suggestion);
    return { suggestionId: suggestion.id, status: 'pending', created: true };
  }

  async listPending(incidentId?: number): Promise<MatchSuggestion[]> {
    return this.suggestions
      .filter((s) => s.status === 'pending' && (incidentId === undefined || s.incidentAId === incidentId || s.incidentBId === incidentId))
      .map((s) => ({ ...s, reasons: [...s.reasons] }))
      .sort((a, b) => b.score - a.score || a.id - b.id);
  }

  async reject(suggestionId: number): Promise<{ suggestionId: number; status: 'rejected' }> {
    const suggestion = this.suggestions.find((s) => s.id === suggestionId);
    if (!suggestion) throw new StoreRejection('not-found', `match suggestion ${suggestionId} does not exist`);
    if (suggestion.status === 'accepted') throw new StoreRejection('invalid', `match suggestion ${suggestionId} is already accepted`);
    if (suggestion.status === 'pending') {
      suggestion.status = 'rejected';
      suggestion.decidedAt = new Date().toISOString();
    }
    return { suggestionId, status: 'rejected' };
  }

  /** What merging an incident pair does in the database (merge_incidents): a pending suggestion becomes accepted. */
  markAccepted(suggestionId: number): void {
    const suggestion = this.suggestions.find((s) => s.id === suggestionId);
    if (!suggestion) throw new Error(`no suggestion ${suggestionId}`);
    suggestion.status = 'accepted';
    suggestion.decidedAt = new Date().toISOString();
  }

  /** Whether the pair has a row of the given statuses; the shortlist skips decided pairs. */
  hasDecided(incidentAId: number, incidentBId: number): boolean {
    const existing = this.find(incidentAId, incidentBId);
    return existing !== undefined && existing.status !== 'pending';
  }

  private find(a: number, b: number): MatchSuggestion | undefined {
    return this.suggestions.find((s) => (s.incidentAId === a && s.incidentBId === b) || (s.incidentAId === b && s.incidentBId === a));
  }
}

/** A video with the embedding of its latest analysis (null when it has none). */
export interface ShortlistVideo {
  videoId: string;
  incidentId: number;
  embedding: number[] | null;
}

function cosine(a: number[], b: number[]): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let index = 0; index < a.length; index += 1) {
    dot += a[index] * b[index];
    normA += a[index] ** 2;
    normB += b[index] ** 2;
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

export class InMemoryMatchShortlist implements MatchShortlist {
  readonly videos: ShortlistVideo[];

  private readonly suggestions: InMemorySuggestionStore;

  constructor(videos: ShortlistVideo[] = [], suggestions: InMemorySuggestionStore = new InMemorySuggestionStore()) {
    this.videos = videos.map((video) => ({ ...video }));
    this.suggestions = suggestions;
  }

  async shortlist(videoId: string, limit: number, minSimilarity: number): Promise<ShortlistedIncident[]> {
    const own = this.videos.find((video) => video.videoId === videoId);
    if (!own?.embedding) return [];
    const best = new Map<number, ShortlistedIncident>();
    for (const video of this.videos) {
      if (!video.embedding || video.incidentId === own.incidentId || this.suggestions.hasDecided(own.incidentId, video.incidentId))
        continue;
      const similarity = cosine(own.embedding, video.embedding);
      const current = best.get(video.incidentId);
      if (!current || similarity > current.similarity || (similarity === current.similarity && video.videoId < current.bestVideoId)) {
        best.set(video.incidentId, { incidentId: video.incidentId, similarity, bestVideoId: video.videoId });
      }
    }
    return [...best.values()]
      .filter((candidate) => candidate.similarity >= minSimilarity)
      .sort((a, b) => b.similarity - a.similarity || a.incidentId - b.incidentId)
      .slice(0, Math.max(limit, 0));
  }
}

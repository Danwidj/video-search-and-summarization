// SPDX-License-Identifier: Apache-2.0

import { StoreRejection } from '@/modules/shared/domain/common';
import { readStoredReasons, storedReasons } from '@/modules/matching/domain/matching';
import type {
  MatchShortlist,
  MatchSuggestion,
  RecordedSuggestion,
  ShortlistedIncident,
  StructuredReason,
  SuggestionStatus,
  SuggestionStore,
} from '@/modules/matching/domain/matching';
import type { PostgrestClient } from '@/lib/postgrest/client';

type Row = Record<string, unknown>;

const STATUSES: SuggestionStatus[] = ['pending', 'accepted', 'rejected'];
const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);

/**
 * record_match_suggestion and reject_match_suggestion RAISE plain exceptions; a domain refusal becomes a
 * StoreRejection, anything else is rethrown unchanged.
 */
function suggestionRefusal(error: unknown): never {
  const message = error instanceof Error ? error.message : '';
  const detail = /"message":"([^"]+)"/.exec(message)?.[1] ?? '';
  if (/does not exist|violates foreign key/i.test(`${detail} ${message}`)) {
    throw new StoreRejection('not-found', detail || 'Incident or suggestion not found');
  }
  if (/against itself|score must be|both incident ids|already accepted/i.test(detail)) throw new StoreRejection('invalid', detail);
  throw error;
}

function suggestionOf(row: Row): MatchSuggestion {
  const { reasons, structuredReasons } = readStoredReasons(row.reasons);
  return {
    id: Number(row.id),
    incidentAId: Number(row.incident_a_id),
    incidentBId: Number(row.incident_b_id),
    score: Number(row.score),
    reasons,
    structuredReasons,
    status: STATUSES.includes(row.status as SuggestionStatus) ? (row.status as SuggestionStatus) : 'pending',
    createdAt: text(row.created_at),
    decidedAt: text(row.decided_at),
  };
}

const byScoreThenId = (a: MatchSuggestion, b: MatchSuggestion) => b.score - a.score || a.id - b.id;

export class SupabaseMatchShortlistAdapter implements MatchShortlist {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async shortlist(videoId: string, limit: number, minSimilarity: number): Promise<ShortlistedIncident[]> {
    const rows = await this.db.rpc('shortlist_similar_incidents', {
      p_video_id: videoId,
      p_limit: limit,
      p_min_similarity: minSimilarity,
    });
    return (Array.isArray(rows) ? rows : []).map((row) => ({
      incidentId: Number(asRow(row).incident_id),
      similarity: Number(asRow(row).similarity),
      bestVideoId: String(asRow(row).best_video_id),
    }));
  }
}

export class SupabaseSuggestionAdapter implements SuggestionStore {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async record(
    incidentAId: number,
    incidentBId: number,
    score: number,
    reasons: string[],
    structuredReasons: StructuredReason[] = [],
  ): Promise<RecordedSuggestion> {
    let result: Row;
    try {
      result = asRow(
        await this.db.rpc('record_match_suggestion', {
          p_incident_a_id: incidentAId,
          p_incident_b_id: incidentBId,
          p_score: score,
          p_reasons: storedReasons(reasons, structuredReasons),
        }),
      );
    } catch (error) {
      suggestionRefusal(error);
    }
    return { suggestionId: Number(result.suggestionId), status: result.status as SuggestionStatus, created: result.created === true };
  }

  async listPending(incidentId?: number): Promise<MatchSuggestion[]> {
    const pending = (filters: Record<string, string>) =>
      this.db.selectMany('incident_match_suggestions', { filters: { status: 'pending', ...filters }, order: 'score.desc,id.asc' });
    const rows =
      incidentId === undefined
        ? await pending({})
        : [...(await pending({ incident_a_id: String(incidentId) })), ...(await pending({ incident_b_id: String(incidentId) }))];
    return rows.map(suggestionOf).sort(byScoreThenId);
  }

  async reject(suggestionId: number): Promise<{ suggestionId: number; status: 'rejected' }> {
    try {
      await this.db.rpc('reject_match_suggestion', { p_suggestion_id: suggestionId });
    } catch (error) {
      suggestionRefusal(error);
    }
    return { suggestionId, status: 'rejected' };
  }
}

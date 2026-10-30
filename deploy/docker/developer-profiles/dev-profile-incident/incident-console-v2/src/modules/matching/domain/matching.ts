// SPDX-License-Identifier: Apache-2.0

// The matching ports (plan section 1): the database shortlists similar incidents for a video, the
// agent judges the shortlist, and the suggestion store keeps what the reviewer is asked to decide.
// A video never matches its own incident, and a decided pair (accepted or rejected) is never
// shortlisted or suggested again.

/** One candidate incident for a video, most similar first. */
export interface ShortlistedIncident {
  incidentId: number;
  /** Cosine similarity of the best video in the incident to the new video. */
  similarity: number;
  /** The video in the incident that scored best. */
  bestVideoId: string;
}

export interface MatchShortlist {
  /** Empty when the video has no analysis or no embedding. */
  shortlist(videoId: string, limit: number, minSimilarity: number): Promise<ShortlistedIncident[]>;
}

/** One candidate as the match judge sees it. */
export interface JudgeCandidate {
  incidentId: number;
  /** The incident's overview block (the contract's incident fields), null when it has none. */
  overview: Record<string, unknown> | null;
  videoNames: string[];
  /** Unix epoch seconds of the earliest and latest recorded time among its videos, when known. */
  recordedAtStart: number | null;
  recordedAtEnd: number | null;
}

export interface JudgeRequest {
  /** The new video's contract-valid analysis payload. */
  analysis: Record<string, unknown>;
  recordedAtStart: number | null;
  recordedAtEnd: number | null;
  candidates: JudgeCandidate[];
}

export interface CandidateJudgement {
  incidentId: number;
  /** 0 to 1. */
  score: number;
  reasons: string[];
}

export type JudgeResult = { kind: 'judged'; judgements: CandidateJudgement[] } | { kind: 'failed'; status: number; message: string };

export interface MatchJudge {
  judge(request: JudgeRequest, signal: AbortSignal): Promise<JudgeResult>;
}

export type SuggestionStatus = 'pending' | 'accepted' | 'rejected';

export interface MatchSuggestion {
  id: number;
  incidentAId: number;
  incidentBId: number;
  score: number;
  reasons: string[];
  status: SuggestionStatus;
  createdAt: string | null;
  decidedAt: string | null;
}

export interface RecordedSuggestion {
  suggestionId: number;
  status: SuggestionStatus;
  /** False when the pair already had a row (of any status), which is kept as it is. */
  created: boolean;
}

export interface SuggestionStore {
  /** One row per unordered pair of incidents. Throws StoreRejection('invalid') for a self pair or a score outside 0 to 1. */
  record(incidentAId: number, incidentBId: number, score: number, reasons: string[]): Promise<RecordedSuggestion>;
  /** Pending suggestions, highest score first; only those naming `incidentId` when given. */
  listPending(incidentId?: number): Promise<MatchSuggestion[]>;
  /**
   * Pending becomes rejected and the row stays, so the pair is never suggested again; rejecting a rejected
   * suggestion changes nothing. Throws StoreRejection('not-found') for an unknown id and ('invalid') for an accepted one.
   */
  reject(suggestionId: number): Promise<{ suggestionId: number; status: 'rejected' }>;
}

/** The ports the matching use cases run on. The judge is null when the agent is not configured. */
export interface MatchingPorts {
  shortlist: MatchShortlist;
  suggestions: SuggestionStore;
  judge: MatchJudge | null;
}

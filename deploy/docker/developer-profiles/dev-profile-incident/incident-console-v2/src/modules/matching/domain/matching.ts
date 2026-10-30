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

/** One outcome of the judge's comparison, for a chip: `kind` says which (for example `same_place`), `label` is the chip text. */
export interface StructuredReason {
  kind: string;
  label: string;
  detail: string;
}

export interface CandidateJudgement {
  incidentId: number;
  /** 0 to 1. */
  score: number;
  reasons: string[];
  /** Absent when the agent does not return it yet; the text reasons are then all there is. */
  structuredReasons?: StructuredReason[];
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
  /** Empty for a suggestion recorded from text reasons only. */
  structuredReasons: StructuredReason[];
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
  record(
    incidentAId: number,
    incidentBId: number,
    score: number,
    reasons: string[],
    structuredReasons?: StructuredReason[],
  ): Promise<RecordedSuggestion>;
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

/** A stored reason entry as the text a reviewer reads: the chip's label and what was compared. */
export const reasonText = (reason: StructuredReason): string => (reason.detail ? `${reason.label}: ${reason.detail}` : reason.label);

/** The reasons as stored: the structured ones when there are any, else the text ones. Read back with `readStoredReasons`. */
export const storedReasons = (reasons: string[], structuredReasons: StructuredReason[]): Array<string | StructuredReason> =>
  structuredReasons.length > 0 ? structuredReasons : reasons;

/** Reads a reasons list from the agent or the store: plain strings (older rows) and `{kind, label, detail}` entries. */
export function readStoredReasons(value: unknown): { reasons: string[]; structuredReasons: StructuredReason[] } {
  const reasons: string[] = [];
  const structuredReasons: StructuredReason[] = [];
  for (const entry of Array.isArray(value) ? value : []) {
    const structured = structuredReasonOf(entry);
    if (structured) {
      structuredReasons.push(structured);
      reasons.push(reasonText(structured));
    } else reasons.push(typeof entry === 'string' ? entry : String(entry));
  }
  return { reasons, structuredReasons };
}

/** A well-formed `{kind, label, detail}`; null for anything else, including a missing label. */
export function structuredReasonOf(value: unknown): StructuredReason | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const { kind, label, detail } = value as Record<string, unknown>;
  if (typeof kind !== 'string' || typeof label !== 'string' || label === '') return null;
  return { kind, label, detail: typeof detail === 'string' ? detail : '' };
}

// SPDX-License-Identifier: Apache-2.0

// Evaluate an incident against every other incident and record what looks like the same event as a
// pending suggestion. Every video of the incident is compared, so the members of a batch find each
// other whichever order they finish in. Decided pairs (accepted or rejected) are skipped by the
// shortlist and pairs already pending are not judged again; the suggestion store keeps one row per pair.

import { StoreRejection } from '@/modules/shared/domain/common';
import type { VideoAnalysisRepository } from '@/modules/analysis/domain/VideoAnalysisRepository';
import type { IncidentId, IncidentReportRepository, IncidentVideo } from '@/modules/reports/domain/IncidentReportRepository';
import type { JudgeCandidate, MatchingPorts, StructuredReason } from '@/modules/matching/domain/matching';

export const DEFAULT_SHORTLIST_LIMIT = 5;
export const DEFAULT_MIN_SIMILARITY = 0.3;
/** A judged score below this is not worth the reviewer's attention. */
export const DEFAULT_MIN_SCORE = 0.5;

export interface EvaluateOptions {
  shortlistLimit?: number;
  minSimilarity?: number;
  minScore?: number;
}

export interface EvaluatePorts {
  reports: Pick<IncidentReportRepository, 'getIncident' | 'getRevision'>;
  analyses: Pick<VideoAnalysisRepository, 'latestAnalysis'>;
  matching: MatchingPorts;
}

/** The agent is not configured, or it refused or failed the judgement; the route answers 503 or 502. */
export class MatchJudgeError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'MatchJudgeError';
    this.status = status;
  }
}

export interface EvaluatedSuggestion {
  suggestionId: number;
  /** The other incident of the pair. */
  incidentId: IncidentId;
  score: number;
  reasons: string[];
  /** Empty while the agent returns text reasons only. */
  structuredReasons: StructuredReason[];
  /** False when the pair already had a row, which is kept as it is. */
  created: boolean;
}

export interface EvaluationResult {
  incidentId: IncidentId;
  /** Candidate incidents the judge scored. */
  judged: number;
  suggestions: EvaluatedSuggestion[];
}

/** Epoch seconds of a video's recording, as a range when its duration is known; null without a recording time. */
function recordedRange(video: IncidentVideo): [number, number] | null {
  const start = video.recordedAt ? Date.parse(video.recordedAt) / 1000 : Number.NaN;
  if (Number.isNaN(start)) return null;
  return [start, start + (video.durationSeconds ?? 0)];
}

function recordedSpan(videos: IncidentVideo[]): { start: number | null; end: number | null } {
  const ranges = videos.map(recordedRange).filter((range): range is [number, number] => range !== null);
  if (ranges.length === 0) return { start: null, end: null };
  return { start: Math.min(...ranges.map(([start]) => start)), end: Math.max(...ranges.map(([, end]) => end)) };
}

export async function evaluateIncident(
  { reports, analyses, matching }: EvaluatePorts,
  incidentId: IncidentId,
  signal: AbortSignal,
  options: EvaluateOptions = {},
): Promise<EvaluationResult> {
  const { shortlistLimit = DEFAULT_SHORTLIST_LIMIT, minSimilarity = DEFAULT_MIN_SIMILARITY, minScore = DEFAULT_MIN_SCORE } = options;
  const { judge } = matching;
  if (!judge) throw new MatchJudgeError(503, 'The agent service is not configured, so matches cannot be judged');
  const incident = await reports.getIncident(incidentId);
  if (!incident) throw new StoreRejection('not-found', `Incident not found: ${incidentId}`);

  const alreadyPending = new Set(
    (await matching.suggestions.listPending(incidentId)).map((s) => (s.incidentAId === incidentId ? s.incidentBId : s.incidentAId)),
  );
  const candidates = new Map<IncidentId, JudgeCandidate>();
  const candidateOf = async (candidateId: IncidentId): Promise<JudgeCandidate | null> => {
    const known = candidates.get(candidateId);
    if (known) return known;
    const other = await reports.getIncident(candidateId);
    if (!other) return null;
    const span = recordedSpan(other.videos);
    const revision = await reports.getRevision(candidateId, null);
    const candidate: JudgeCandidate = {
      incidentId: candidateId,
      overview: revision ? { ...revision.envelope.overview } : null,
      videoNames: other.videos.map((video) => video.videoId),
      recordedAtStart: span.start,
      recordedAtEnd: span.end,
    };
    candidates.set(candidateId, candidate);
    return candidate;
  };

  // The best judgement per candidate incident over all of this incident's videos.
  const best = new Map<IncidentId, { score: number; reasons: string[]; structuredReasons: StructuredReason[] }>();
  let judged = 0;
  for (const video of incident.videos) {
    const analysis = await analyses.latestAnalysis(video.videoId);
    if (!analysis) continue;
    const hits = (await matching.shortlist.shortlist(video.videoId, shortlistLimit, minSimilarity)).filter(
      (hit) => hit.incidentId !== incidentId && !alreadyPending.has(hit.incidentId),
    );
    const shortlisted = (await Promise.all(hits.map((hit) => candidateOf(hit.incidentId)))).filter((c): c is JudgeCandidate => c !== null);
    if (shortlisted.length === 0) continue;
    const span = recordedSpan([video]);
    const result = await judge.judge(
      { analysis: analysis.payload, recordedAtStart: span.start, recordedAtEnd: span.end, candidates: shortlisted },
      signal,
    );
    if (result.kind === 'failed') throw new MatchJudgeError(result.status >= 500 ? 502 : result.status, result.message);
    const asked = new Set(shortlisted.map((c) => c.incidentId));
    for (const judgement of result.judgements) {
      if (!asked.has(judgement.incidentId)) continue;
      judged += 1;
      const current = best.get(judgement.incidentId);
      if (!current || judgement.score > current.score)
        best.set(judgement.incidentId, {
          score: judgement.score,
          reasons: judgement.reasons,
          structuredReasons: judgement.structuredReasons ?? [],
        });
    }
  }

  const suggestions: EvaluatedSuggestion[] = [];
  for (const [candidateId, { score, reasons, structuredReasons }] of [...best].sort((a, b) => b[1].score - a[1].score || a[0] - b[0])) {
    if (score < minScore) continue;
    const recorded = await matching.suggestions.record(incidentId, candidateId, score, reasons, structuredReasons);
    suggestions.push({
      suggestionId: recorded.suggestionId,
      incidentId: candidateId,
      score,
      reasons,
      structuredReasons,
      created: recorded.created,
    });
  }
  return { incidentId, judged, suggestions };
}

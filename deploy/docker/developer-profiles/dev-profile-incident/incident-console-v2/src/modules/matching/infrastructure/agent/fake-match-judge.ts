// SPDX-License-Identifier: Apache-2.0

// In-memory MatchJudge for tests, following the agent's documented rules in short: an event type
// mismatch scores 0; otherwise 0.45 for the type plus up to 0.40 for the location (exactly equal =
// full, a missing location on either side = half, else none) plus 0.15 when both sides give
// overlapping recorded times. A script can force results or failures instead.

import type { CandidateJudgement, JudgeCandidate, JudgeRequest, JudgeResult, MatchJudge } from '@/modules/matching/domain/matching';

const incidentOf = (analysis: Record<string, unknown>): Record<string, unknown> =>
  analysis.incident && typeof analysis.incident === 'object' ? (analysis.incident as Record<string, unknown>) : {};

function judgeCandidate(request: JudgeRequest, candidate: JudgeCandidate): CandidateJudgement {
  const incident = incidentOf(request.analysis);
  const overview = candidate.overview ?? {};
  if (overview.type !== incident.type) {
    return {
      incidentId: candidate.incidentId,
      score: 0,
      reasons: [`event type mismatch: new video is ${JSON.stringify(incident.type)}, candidate is ${JSON.stringify(overview.type)}`],
    };
  }
  const reasons = [`event types match (${JSON.stringify(incident.type)})`];
  let score = 0.45;
  const [place, other] = [incident.location, overview.location];
  if (typeof place !== 'string' || typeof other !== 'string') {
    score += 0.2;
    reasons.push('location not available for one or both sides - neutral');
  } else if (place.toLowerCase() === other.toLowerCase()) {
    score += 0.4;
    reasons.push(`locations match closely (${JSON.stringify(place)})`);
  } else {
    reasons.push(`locations do not overlap (${JSON.stringify(place)} vs ${JSON.stringify(other)})`);
  }
  const [start, end, otherStart, otherEnd] = [
    request.recordedAtStart,
    request.recordedAtEnd,
    candidate.recordedAtStart,
    candidate.recordedAtEnd,
  ];
  if (start !== null && end !== null && otherStart !== null && otherEnd !== null) {
    const overlap = start <= otherEnd && otherStart <= end;
    if (overlap) score += 0.15;
    reasons.push(overlap ? 'recorded times overlap' : 'recorded times do not overlap');
  }
  return { incidentId: candidate.incidentId, score: Math.round(score * 10000) / 10000, reasons };
}

export class FakeMatchJudge implements MatchJudge {
  readonly calls: JudgeRequest[] = [];

  private readonly script: Array<JudgeResult | Error>;

  /** Results returned in order, the last one repeating; an Error entry is thrown instead. */
  constructor(script: Array<JudgeResult | Error> = []) {
    this.script = script;
  }

  async judge(request: JudgeRequest, _signal: AbortSignal): Promise<JudgeResult> {
    const call = this.calls.push(request) - 1;
    const scripted = this.script[Math.min(call, this.script.length - 1)];
    if (scripted instanceof Error) throw scripted;
    if (scripted) return scripted;
    return { kind: 'judged', judgements: request.candidates.map((candidate) => judgeCandidate(request, candidate)) };
  }
}

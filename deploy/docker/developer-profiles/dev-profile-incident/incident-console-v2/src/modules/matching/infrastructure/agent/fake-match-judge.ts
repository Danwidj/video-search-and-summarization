// SPDX-License-Identifier: Apache-2.0

// In-memory MatchJudge for tests, following the agent's documented rules in short: an event type
// mismatch scores 0; otherwise 0.45 for the type plus up to 0.40 for the location (exactly equal =
// full, a missing location on either side = half, else none) plus 0.15 when both sides give
// overlapping recorded times. A script can force results or failures instead. With `structured`, each
// judgement also carries the agent's chips (the newer agent's `structured_reasons`).

import type {
  CandidateJudgement,
  JudgeCandidate,
  JudgeRequest,
  JudgeResult,
  MatchJudge,
  StructuredReason,
} from '@/modules/matching/domain/matching';

const incidentOf = (analysis: Record<string, unknown>): Record<string, unknown> =>
  analysis.incident && typeof analysis.incident === 'object' ? (analysis.incident as Record<string, unknown>) : {};

function judgeCandidate(request: JudgeRequest, candidate: JudgeCandidate, structured: boolean): CandidateJudgement {
  const chips: StructuredReason[] = [];
  const incident = incidentOf(request.analysis);
  const overview = candidate.overview ?? {};
  if (overview.type !== incident.type) {
    return {
      incidentId: candidate.incidentId,
      score: 0,
      reasons: [`event type mismatch: new video is ${JSON.stringify(incident.type)}, candidate is ${JSON.stringify(overview.type)}`],
      ...(structured
        ? {
            structuredReasons: [
              { kind: 'different_event_type', label: 'Different event type', detail: `${incident.type} vs ${overview.type}` },
            ],
          }
        : {}),
    };
  }
  const reasons = [`event types match (${JSON.stringify(incident.type)})`];
  chips.push({ kind: 'same_event_type', label: 'Same event type', detail: String(incident.type) });
  let score = 0.45;
  const [place, other] = [incident.location, overview.location];
  if (typeof place !== 'string' || typeof other !== 'string') {
    score += 0.2;
    reasons.push('location not available for one or both sides - neutral');
    chips.push({ kind: 'place_unknown', label: 'No place to compare', detail: 'A location is missing on one or both sides' });
  } else if (place.toLowerCase() === other.toLowerCase()) {
    score += 0.4;
    reasons.push(`locations match closely (${JSON.stringify(place)})`);
    chips.push({ kind: 'same_place', label: 'Same place', detail: place });
  } else {
    reasons.push(`locations do not overlap (${JSON.stringify(place)} vs ${JSON.stringify(other)})`);
    chips.push({ kind: 'different_place', label: 'Different place', detail: `${place} vs ${other}` });
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
    chips.push(
      overlap
        ? { kind: 'time_overlap', label: 'Time overlap', detail: 'The recorded times overlap' }
        : { kind: 'time_apart', label: 'Time apart', detail: 'The recorded times do not overlap' },
    );
  }
  return {
    incidentId: candidate.incidentId,
    score: Math.round(score * 10000) / 10000,
    reasons,
    ...(structured ? { structuredReasons: chips } : {}),
  };
}

export class FakeMatchJudge implements MatchJudge {
  readonly calls: JudgeRequest[] = [];

  private readonly script: Array<JudgeResult | Error>;

  private readonly structured: boolean;

  /** Results returned in order, the last one repeating; an Error entry is thrown instead. */
  constructor(script: Array<JudgeResult | Error> = [], options: { structured?: boolean } = {}) {
    this.script = script;
    this.structured = options.structured ?? false;
  }

  async judge(request: JudgeRequest, _signal: AbortSignal): Promise<JudgeResult> {
    const call = this.calls.push(request) - 1;
    const scripted = this.script[Math.min(call, this.script.length - 1)];
    if (scripted instanceof Error) throw scripted;
    if (scripted) return scripted;
    return { kind: 'judged', judgements: request.candidates.map((candidate) => judgeCandidate(request, candidate, this.structured)) };
  }
}

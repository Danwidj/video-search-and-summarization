// SPDX-License-Identifier: Apache-2.0

// HttpMatchJudge: the vss-agent's "Agent judge" contract (plan section 1), POST /api/v1/incidents/match-judge.
// Stateless: it takes a new video's analysis and candidate incidents and returns a 0 to 1 score and
// plain-language reasons per candidate
// and, from a newer agent, the same reasons as structured chips. Only a network failure or a timeout is thrown (as
// AgentRequestError); every HTTP answer becomes a result.

import { AgentRequestError } from '@/modules/analysis/domain/IncidentAgent';
import {
  structuredReasonOf,
  type CandidateJudgement,
  type JudgeRequest,
  type JudgeResult,
  type MatchJudge,
  type StructuredReason,
} from '@/modules/matching/domain/matching';

function failed(status: number, message: string): JudgeResult {
  return { kind: 'failed', status, message };
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

/** The FastAPI error detail as text; the whole body when it is not the usual `{detail}` JSON. */
function errorMessage(body: string, statusText: string): string {
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (detail !== undefined) return JSON.stringify(detail);
  } catch {
    // not JSON: fall through to the raw body
  }
  return body || statusText;
}

function judgementOf(value: unknown): CandidateJudgement | null {
  if (!isRecord(value)) return null;
  const { incident_id: incidentId, score, reasons, structured_reasons: structured } = value;
  if (typeof incidentId !== 'number' || !Number.isInteger(incidentId)) return null;
  if (typeof score !== 'number' || !(score >= 0 && score <= 1)) return null;
  if (!Array.isArray(reasons) || !reasons.every((reason) => typeof reason === 'string')) return null;
  const structuredReasons = structuredReasonsOf(structured);
  return { incidentId, score, reasons: reasons as string[], ...(structuredReasons.length > 0 ? { structuredReasons } : {}) };
}

/** The agent's chips, or none when the field is absent or any entry is malformed: the text reasons then stand alone. */
function structuredReasonsOf(value: unknown): StructuredReason[] {
  if (!Array.isArray(value)) return [];
  const parsed = value.map(structuredReasonOf);
  return parsed.every((reason) => reason !== null) ? (parsed as StructuredReason[]) : [];
}

export function parseJudgeResponse(status: number, ok: boolean, statusText: string, body: string): JudgeResult {
  if (!ok) return failed(status, errorMessage(body, statusText));
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return failed(502, 'The agent answered the match judge with a body that is not JSON');
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.judgements)) return failed(502, 'The agent match judgement has no judgements list');
  const judgements = parsed.judgements.map(judgementOf);
  if (judgements.some((judgement) => judgement === null)) {
    return failed(502, 'The agent match judgement holds an entry without an incident id, a 0 to 1 score and reasons');
  }
  return { kind: 'judged', judgements: judgements as CandidateJudgement[] };
}

export class HttpMatchJudge implements MatchJudge {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  async judge(request: JudgeRequest, signal: AbortSignal): Promise<JudgeResult> {
    // The endpoint refuses an empty candidate list; with nothing to judge there is nothing to ask.
    if (request.candidates.length === 0) return { kind: 'judged', judgements: [] };
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/api/v1/incidents/match-judge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis: request.analysis,
          recorded_at_start: request.recordedAtStart,
          recorded_at_end: request.recordedAtEnd,
          candidates: request.candidates.map((candidate) => ({
            incident_id: candidate.incidentId,
            overview: candidate.overview,
            video_names: candidate.videoNames,
            recorded_at_start: candidate.recordedAtStart,
            recorded_at_end: candidate.recordedAtEnd,
          })),
        }),
        signal,
      });
    } catch (error) {
      const isTimeout = error instanceof DOMException && error.name === 'TimeoutError';
      throw new AgentRequestError(
        isTimeout ? 'AGENT_TIMEOUT' : 'AGENT_FETCH_FAILED',
        error instanceof Error ? error.message : String(error),
      );
    }
    const body = await response.text().catch(() => '');
    return parseJudgeResponse(response.status, response.ok, response.statusText, body);
  }
}

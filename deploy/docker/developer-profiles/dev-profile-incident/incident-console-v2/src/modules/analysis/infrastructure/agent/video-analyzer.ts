// SPDX-License-Identifier: Apache-2.0

// VideoAnalyzer: the vss-agent's "Agent analyse" contract (plan section 1). The agent
// analyses one video by name, stores the analysis, its crops and the model run, and
// creates no report revision. Only a network failure or a timeout is thrown (as
// AgentRequestError); every HTTP answer becomes a result for the caller to act on.

import { AgentRequestError } from '@/modules/analysis/domain/IncidentAgent';
import type { VideoAnalysisRequest, VideoAnalysisResult, VideoAnalyzer } from '@/modules/analysis/domain/VideoAnalyzer';

export type { VideoAnalysisRequest, VideoAnalysisResult, VideoAnalyzer };

type Json = Record<string, unknown>;

const isRecord = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value);
const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);

/** The FastAPI error detail of an error body; undefined when the body is not JSON. */
function errorDetail(body: string): unknown {
  try {
    return (JSON.parse(body) as { detail?: unknown }).detail;
  } catch {
    return undefined;
  }
}

function failed(status: number, message: string): VideoAnalysisResult {
  return { kind: 'failed', status, message };
}

/** The agent accepts only a finite length above zero; anything else is left for it to read itself. */
function isUsableDuration(seconds: number | null): seconds is number {
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0;
}

export function parseAnalysisResponse(status: number, ok: boolean, statusText: string, body: string): VideoAnalysisResult {
  if (ok) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch {
      return failed(502, 'The agent answered the analysis with a body that is not JSON');
    }
    if (!isRecord(parsed)) return failed(502, 'The agent answered the analysis with something other than an object');
    const { analysis_id: analysisId, model_run_id: modelRunId, outcome, payload } = parsed;
    if (typeof analysisId !== 'number' || !Number.isInteger(analysisId))
      return failed(502, 'The agent analysis has no integer analysis_id');
    if (typeof modelRunId !== 'string' || !modelRunId) return failed(502, 'The agent analysis has no model_run_id');
    if (typeof outcome !== 'string' || !outcome) return failed(502, 'The agent analysis has no outcome');
    if (!isRecord(payload)) return failed(502, 'The agent analysis has no payload object');
    return { kind: 'analysed', analysisId, modelRunId, outcome, payload };
  }
  const detail = errorDetail(body);
  if (status === 422 && isRecord(detail) && typeof detail.raw_output === 'string') {
    return {
      kind: 'contract_refused',
      message: text(detail.message) ?? 'The model output did not satisfy the incident contract',
      rawOutput: detail.raw_output,
      finishReason: text(detail.finish_reason),
      model: text(detail.model),
      contractVersion: text(detail.contract_version),
    };
  }
  return failed(status, body || statusText);
}

export class HttpVideoAnalyzer implements VideoAnalyzer {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  async analyze(request: VideoAnalysisRequest, signal: AbortSignal): Promise<VideoAnalysisResult> {
    const endpoint = `${this.baseUrl}/api/v1/incidents/${encodeURIComponent(request.videoName)}/analyze`;
    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_key: request.videoKey,
          model_run_id: request.modelRunId,
          model: request.model,
          skip_rp1: true,
          ...(request.reviewerPrompt ? { reviewer_prompt: request.reviewerPrompt } : {}),
          ...(isUsableDuration(request.videoDurationSeconds) ? { video_duration_seconds: request.videoDurationSeconds } : {}),
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
    return parseAnalysisResponse(response.status, response.ok, response.statusText, body);
  }
}

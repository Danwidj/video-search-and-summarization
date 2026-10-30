// SPDX-License-Identifier: Apache-2.0

// IncidentSynthesizer: the vss-agent's "Agent synthesise" contract (plan section 1).
// Stateless: it takes each video's analysis payload and returns one incident overview
// plus its search embedding. Only a network failure or a timeout is thrown (as
// AgentRequestError); every HTTP answer becomes a result.

import { AgentRequestError } from '@/modules/analysis/domain/IncidentAgent';

/** The width of the agent's search embedding (the database column is vector(1024)). */
export const EMBEDDING_DIMENSIONS = 1024;

export interface VideoAnalysisInput {
  videoName: string;
  /** The video's contract-valid analysis payload, unchanged. */
  payload: Record<string, unknown>;
}

export type SynthesisResult =
  | {
      kind: 'synthesised';
      /** The contract's `incident` block fields. */
      overview: Record<string, unknown>;
      embedding: number[];
    }
  | { kind: 'failed'; status: number; message: string };

export interface IncidentSynthesizer {
  synthesize(videos: VideoAnalysisInput[], signal: AbortSignal): Promise<SynthesisResult>;
}

function failed(status: number, message: string): SynthesisResult {
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

export function parseSynthesisResponse(status: number, ok: boolean, statusText: string, body: string): SynthesisResult {
  if (!ok) return failed(status, errorMessage(body, statusText));
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return failed(502, 'The agent answered the synthesis with a body that is not JSON');
  }
  if (!isRecord(parsed) || !isRecord(parsed.overview)) return failed(502, 'The agent synthesis has no overview object');
  const embedding = parsed.embedding;
  if (
    !Array.isArray(embedding) ||
    embedding.length !== EMBEDDING_DIMENSIONS ||
    !embedding.every((value) => typeof value === 'number' && Number.isFinite(value))
  ) {
    return failed(502, `The agent synthesis embedding is not ${EMBEDDING_DIMENSIONS} numbers`);
  }
  return { kind: 'synthesised', overview: parsed.overview, embedding: embedding as number[] };
}

export class HttpIncidentSynthesizer implements IncidentSynthesizer {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  async synthesize(videos: VideoAnalysisInput[], signal: AbortSignal): Promise<SynthesisResult> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/api/v1/incidents/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ videos: videos.map((video) => ({ video_name: video.videoName, payload: video.payload })) }),
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
    return parseSynthesisResponse(response.status, response.ok, response.statusText, body);
  }
}

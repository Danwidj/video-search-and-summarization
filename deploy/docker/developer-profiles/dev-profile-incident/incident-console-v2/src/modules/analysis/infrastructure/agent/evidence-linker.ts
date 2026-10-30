// SPDX-License-Identifier: Apache-2.0

// EvidenceLinker: the vss-agent's "Agent link-evidence" contract. Stateless and text-only: it takes
// each video's analysis payload and returns the groups of items that are the same person or object
// across the videos. The agent answers an empty list when the model fails, so a failure here means
// only that the agent itself could not be reached or refused the request. Callers treat any failure
// as "no groups". Network failures and timeouts are thrown as AgentRequestError.

import { AgentRequestError } from '@/modules/analysis/domain/IncidentAgent';
import type { VideoAnalysisInput } from '@/modules/analysis/infrastructure/agent/incident-synthesizer';
import { type EvidenceGroup, parseEvidenceGroups } from '@/modules/reports/domain/envelope';

export type LinkResult = { kind: 'linked'; groups: EvidenceGroup[] } | { kind: 'failed'; status: number; message: string };

export interface EvidenceLinker {
  link(videos: VideoAnalysisInput[], signal: AbortSignal): Promise<LinkResult>;
}

export function parseLinkResponse(status: number, ok: boolean, statusText: string, body: string): LinkResult {
  if (!ok) return { kind: 'failed', status, message: body.slice(0, 300) || statusText };
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return { kind: 'failed', status: 502, message: 'The agent answered the evidence link with a body that is not JSON' };
  }
  const groups = (parsed as { evidence_groups?: unknown } | null)?.evidence_groups;
  if (!Array.isArray(groups)) return { kind: 'failed', status: 502, message: 'The agent evidence link has no evidence_groups list' };
  return { kind: 'linked', groups: parseEvidenceGroups(groups) };
}

export class HttpEvidenceLinker implements EvidenceLinker {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  async link(videos: VideoAnalysisInput[], signal: AbortSignal): Promise<LinkResult> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/api/v1/incidents/link-evidence`, {
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
    return parseLinkResponse(response.status, response.ok, response.statusText, body);
  }
}

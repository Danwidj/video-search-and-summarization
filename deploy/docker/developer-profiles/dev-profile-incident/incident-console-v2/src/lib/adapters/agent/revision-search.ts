// SPDX-License-Identifier: Apache-2.0

// RevisionSearchRepository over the vss-agent's POST /api/v1/incidents/revisions/search:
// camelCase request in, camelCase hits out.

import { readUpstream } from '@/lib/http';
import type { RevisionSearchHit, RevisionSearchRepository, RevisionSearchRequest } from '@/lib/ports/revision-search';

export function toAgentRevisionSearchBody(request: RevisionSearchRequest): Record<string, unknown> {
  const { query, topK, minSimilarity } = request;
  return {
    query,
    ...(topK != null ? { top_k: topK } : {}),
    ...(minSimilarity != null ? { min_similarity: minSimilarity } : {}),
  };
}

type Row = Record<string, unknown>;
const row = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const textOrNull = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const num = (value: unknown, fallback = 0): number => (typeof value === 'number' && Number.isFinite(value) ? value : fallback);
const numOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

function fromAgentHit(raw: unknown): RevisionSearchHit {
  const hit = row(raw);
  return {
    revisionId: num(hit.revision_id),
    videoId: text(hit.video_id),
    revisionNo: num(hit.revision_no, 1),
    kind: hit.kind === 'human' ? 'human' : 'ai',
    modelRunId: textOrNull(hit.model_run_id),
    title: textOrNull(hit.title),
    description: textOrNull(hit.description),
    incidentType: textOrNull(hit.incident_type),
    severityLevel: numOrNull(hit.severity_level),
    startSeconds: numOrNull(hit.start_seconds),
    endSeconds: numOrNull(hit.end_seconds),
    similarityScore: num(hit.similarity_score),
  };
}

export function fromAgentRevisionSearchResponse(payload: unknown): RevisionSearchHit[] {
  if (!Array.isArray(payload)) throw new Error('Agent returned an invalid revision search response');
  return payload.map(fromAgentHit);
}

export class AgentRevisionSearchRepository implements RevisionSearchRepository {
  private readonly agentUrl: string;
  private readonly signal?: AbortSignal;

  constructor(agentUrl: string, signal?: AbortSignal) {
    this.agentUrl = agentUrl;
    this.signal = signal;
  }

  async search(request: RevisionSearchRequest): Promise<RevisionSearchHit[]> {
    const response = await fetch(`${this.agentUrl.replace(/\/$/, '')}/api/v1/incidents/revisions/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toAgentRevisionSearchBody(request)),
      signal: this.signal,
    });
    return fromAgentRevisionSearchResponse(await readUpstream(response, 'Agent /api/v1/incidents/revisions/search'));
  }
}

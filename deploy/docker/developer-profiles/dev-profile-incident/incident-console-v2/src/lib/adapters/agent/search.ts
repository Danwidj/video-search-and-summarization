// SPDX-License-Identifier: Apache-2.0

// EvidenceSearchRepository over the vss-agent's POST /api/v1/incidents/search
// (search-contract-v1): camelCase request in, camelCase result out.

import { readUpstream } from '@/lib/http';
import type { EvidenceSearchHit, EvidenceSearchRepository, EvidenceSearchRequest, EvidenceSearchResult } from '@/modules/search/domain/search';

export function toAgentSearchBody(request: EvidenceSearchRequest): Record<string, unknown> {
  const { query, topK, minSimilarity, hideRejected, filters } = request;
  const agentFilters = filters ? {
    ...(filters.incidentTypes?.length ? { incident_types: filters.incidentTypes } : {}),
    ...(filters.minSeverity != null ? { min_severity: filters.minSeverity } : {}),
    ...(filters.maxSeverity != null ? { max_severity: filters.maxSeverity } : {}),
    ...(filters.itemTypes?.length ? { item_types: filters.itemTypes } : {}),
  } : {};
  return {
    query,
    ...(topK != null ? { top_k: topK } : {}),
    ...(minSimilarity != null ? { min_similarity: minSimilarity } : {}),
    ...(hideRejected != null ? { hide_rejected: hideRejected } : {}),
    ...(Object.keys(agentFilters).length ? { filters: agentFilters } : {}),
  };
}

type Row = Record<string, unknown>;
const row = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const num = (value: unknown, fallback = 0): number => (typeof value === 'number' && Number.isFinite(value) ? value : fallback);
const numOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

function fromAgentHit(raw: unknown): EvidenceSearchHit {
  const hit = row(raw);
  const item = row(hit.item);
  const incident = row(hit.incident);
  const critic = row(hit.critic);
  const box = Array.isArray(item.bounding_box) && item.bounding_box.length === 4 && item.bounding_box.every((n) => typeof n === 'number') ? (item.bounding_box as [number, number, number, number]) : null;
  const window = Array.isArray(incident.incident_window) ? incident.incident_window : [];
  return {
    resultId: text(hit.result_id),
    rank: num(hit.rank, 1),
    similarityScore: num(hit.similarity_score),
    item: {
      itemType: item.item_type as EvidenceSearchHit['item']['itemType'],
      itemId: text(item.item_id),
      name: text(item.name),
      label: text(item.label),
      description: text(item.description),
      threatLevel: numOrNull(item.threat_level),
      holderEntityId: typeof item.holder_entity_id === 'string' ? item.holder_entity_id : null,
      cropImageUrl: text(item.crop_image_url),
      timestampSeconds: num(item.timestamp_seconds),
      boundingBox: box,
    },
    incident: {
      videoId: text(incident.incident_id),
      modelRunId: text(incident.model_run_id),
      incidentType: text(incident.incident_type),
      severityLevel: num(incident.severity_level, 1),
      title: typeof incident.title === 'string' ? incident.title : null,
      description: text(incident.description),
      playbackUrl: text(incident.playback_url),
      incidentWindow: [num(window[0]), num(window[1])],
    },
    critic: {
      verdict: (['confirmed', 'rejected', 'unverified'].includes(text(critic.verdict)) ? critic.verdict : 'unverified') as EvidenceSearchHit['critic']['verdict'],
      confidence: numOrNull(critic.confidence),
      rationale: text(critic.rationale),
    },
  };
}

export function fromAgentSearchResponse(payload: unknown): EvidenceSearchResult {
  const body = row(payload);
  if (!Array.isArray(body.hits)) throw new Error('Agent returned an invalid search response');
  return {
    queryId: text(body.query_id),
    query: text(body.query),
    totalHits: num(body.total_hits, body.hits.length),
    executionTimeMs: num(body.execution_time_ms),
    hits: body.hits.map(fromAgentHit),
  };
}

export class AgentSearchRepository implements EvidenceSearchRepository {
  private readonly agentUrl: string;
  private readonly signal?: AbortSignal;

  constructor(agentUrl: string, signal?: AbortSignal) {
    this.agentUrl = agentUrl;
    this.signal = signal;
  }

  async search(request: EvidenceSearchRequest): Promise<EvidenceSearchResult> {
    const response = await fetch(`${this.agentUrl.replace(/\/$/, '')}/api/v1/incidents/search`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(toAgentSearchBody(request)), signal: this.signal,
    });
    return fromAgentSearchResponse(await readUpstream(response, 'Agent /api/v1/incidents/search'));
  }
}

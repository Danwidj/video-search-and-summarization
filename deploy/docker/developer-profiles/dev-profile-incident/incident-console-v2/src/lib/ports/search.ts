// SPDX-License-Identifier: Apache-2.0

// EvidenceSearchRepository (MVP2): natural-language search over evidence crops.
// Adapter: lib/adapters/agent/search.ts, over the vss-agent's POST
// /api/v1/incidents/search (search-contract-v1, .docs/vm-api-contracts.md). The
// agent embeds the query, ranks each video's searchable revision's evidence_crops
// (the official one, else the newest) with search_evidence_items, runs the
// always-on critic and records the query and its hits itself. These types are that
// contract (services/agent/src/vss_agents/api/incident_search.py SearchRequest /
// SearchResponse) in camelCase.

export type EvidenceItemType = 'entity' | 'instrument' | 'asset';
export type CriticVerdict = 'confirmed' | 'rejected' | 'unverified';

export interface EvidenceSearchFilters {
  incidentTypes?: string[];
  /** 1 to 5. */
  minSeverity?: number;
  maxSeverity?: number;
  /** All three when absent. */
  itemTypes?: EvidenceItemType[];
}

/** An absent field takes the agent's default. */
export interface EvidenceSearchRequest {
  /** 1 to 500 characters. */
  query: string;
  /** 1 to 50; default 10. */
  topK?: number;
  /** 0 to 1; default 0, so no cutoff (the critic judges relevance). */
  minSimilarity?: number;
  /** Default true: hits the critic rejected are left out. */
  hideRejected?: boolean;
  filters?: EvidenceSearchFilters;
}

export interface EvidenceSearchHit {
  /** The hit's query_results id. */
  resultId: string;
  /** From 1, numbered before rejected hits are left out. */
  rank: number;
  /** 0 to 1. */
  similarityScore: number;
  item: {
    itemType: EvidenceItemType;
    itemId: string;
    name: string;
    /** Short detector label. */
    label: string;
    description: string;
    threatLevel: number | null;
    holderEntityId: string | null;
    /** Signed by the agent; used as given. */
    cropImageUrl: string;
    timestampSeconds: number;
    /** [ymin, xmin, ymax, xmax] normalised to 0-1000, detector-produced; null when there is none. */
    boundingBox: [number, number, number, number] | null;
  };
  /** The incident (video) the evidence comes from, as its searchable revision describes it. */
  incident: {
    /** videos.id. */
    videoId: string;
    /** The run the searched revision derives from. */
    modelRunId: string;
    incidentType: string;
    /** 1 to 5. */
    severityLevel: number;
    title: string | null;
    description: string;
    /** Signed by the agent; used as given. */
    playbackUrl: string;
    /** [start, end] in seconds. */
    incidentWindow: [number, number];
  };
  critic: {
    verdict: CriticVerdict;
    /** 0 to 1; null (or 0) when the critic could not judge. */
    confidence: number | null;
    rationale: string;
  };
}

export interface EvidenceSearchResult {
  queryId: string;
  query: string;
  totalHits: number;
  executionTimeMs: number;
  hits: EvidenceSearchHit[];
}

export interface EvidenceSearchRepository {
  /** One search. The backend records the query and its hits. */
  search(request: EvidenceSearchRequest): Promise<EvidenceSearchResult>;
}

// SPDX-License-Identifier: Apache-2.0

// EvidenceSearchRepository (MVP2): natural-language search over evidence crops.
// Adapter: lib/adapters/agent/search.ts, over the vss-agent's POST
// /api/v1/incidents/search (search-contract-v1, .docs/vm-api-contracts.md). The
// agent embeds the query, ranks each incident's searchable revision's evidence_crops
// (the official one, else the newest; every camera's) with search_evidence_items and
// records the query and its hits itself. A hit names its incident and, on the item, the camera
// (the source video's name). The VLM critic is dormant (off unless the agent sets
// INCIDENT_SEARCH_CRITIC), so every hit's critic verdict is 'unverified'. These types are that
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
  /** Searches only this incident, every camera. With it, the query may be empty: the incident's evidence in video time order. */
  incidentId?: string;
  /** Searches only this camera (videos.id, the video's name). Also lets the query be empty. */
  videoName?: string;
}

/** An absent field takes the agent's default. */
export interface EvidenceSearchRequest {
  /** 1 to 500 characters; empty only with filters.incidentId or filters.videoName. */
  query: string;
  /** 1 to 50; default 10. */
  topK?: number;
  /** 0 to 1; default 0, so no cutoff. */
  minSimilarity?: number;
  /** Only meaningful when the agent's critic is on: leaves out the hits it rejected. */
  hideRejected?: boolean;
  filters?: EvidenceSearchFilters;
}

export interface EvidenceSearchHit {
  /** The hit's query_results id. */
  resultId: string;
  /** From 1. */
  rank: number;
  /** 0 to 1; 0 for a listing with no query. */
  similarityScore: number;
  item: {
    itemType: EvidenceItemType;
    itemId: string;
    /** The camera: the name of the video the item was seen in. Item ids repeat across cameras. */
    videoName: string;
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
  /** The incident the evidence comes from, as its searchable revision describes it. */
  incident: {
    /** incidents.id, as a string (the route segment of its report page). */
    incidentId: string;
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

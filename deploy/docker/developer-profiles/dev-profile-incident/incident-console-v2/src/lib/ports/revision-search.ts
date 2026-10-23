// SPDX-License-Identifier: Apache-2.0

// RevisionSearchRepository (MVP2): "Find incidents" text search over saved report
// revisions. Adapter: lib/adapters/agent/revision-search.ts, over the vss-agent's
// POST /api/v1/incidents/revisions/search. The agent embeds the query and ranks the
// revisions that have a stored vector, best first. These types are that contract
// (services/agent/src/vss_agents/api/incident_revision_search.py) in camelCase.

export interface RevisionSearchRequest {
  /** 1 to 1000 characters. */
  query: string;
  /** 1 to 50; the agent's default is 10. */
  topK?: number;
  /** -1 to 1; the agent's default is 0. */
  minSimilarity?: number;
}

export interface RevisionSearchHit {
  revisionId: number;
  videoId: string;
  revisionNo: number;
  kind: 'ai' | 'human';
  modelRunId: string | null;
  title: string | null;
  description: string | null;
  incidentType: string | null;
  severityLevel: number | null;
  startSeconds: number | null;
  endSeconds: number | null;
  similarityScore: number;
}

export interface RevisionSearchRepository {
  /** Hits best first; empty when nothing matches. */
  search(request: RevisionSearchRequest): Promise<RevisionSearchHit[]>;
}

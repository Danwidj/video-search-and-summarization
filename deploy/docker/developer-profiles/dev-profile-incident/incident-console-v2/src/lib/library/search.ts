// SPDX-License-Identifier: Apache-2.0

// Pure helpers behind the library page's Find evidence tab: what /api/search
// returns, the client-side filters, the holder / holds relationship and the
// grouping by incident. No React and no server code, so tests can import it.

import type { EvidenceItemType, EvidenceSearchHit, EvidenceSearchResult } from '@/modules/search/domain/search';

/** The version a hit came from: the incident's official revision, else its newest (what search reads). */
export interface SearchedVersion {
  revisionId: number;
  revisionNo: number;
  isOfficial: boolean;
  /** The library title of the incident, which a hit's own incident title can lack. */
  title?: string;
  thumbnailUrl?: string;
}

/** /api/search's body. */
export interface LibrarySearchResponse extends EvidenceSearchResult {
  /** By incident id; an incident missing here could not be looked up. */
  versions: Record<string, SearchedVersion>;
}

export interface EvidenceFilters {
  /** Threat 1 to 5; hits below it, or with no threat level, are left out. */
  minThreat: number;
}

export function filterHits(hits: EvidenceSearchHit[], { minThreat }: EvidenceFilters): EvidenceSearchHit[] {
  return hits.filter((hit) => minThreat <= 1 || (hit.item.threatLevel ?? 0) >= minThreat);
}

export interface HitRelationship {
  /** Set when another item of this incident, at the same moment, holds this one. */
  heldBy: { itemId: string; name: string } | null;
  /** Items this entity holds, found among the same incident's hits. */
  holds: { itemId: string; name: string }[];
}

/** The holder / holds relationship, as far as the other hits of the same incident show it. */
export function relationshipOf(hit: EvidenceSearchHit, hits: EvidenceSearchHit[]): HitRelationship {
  // Item ids (E1, I2) repeat in every camera's report, so a relationship holds only within one camera.
  const sameIncident = hits.filter(
    (other) => other.incident.incidentId === hit.incident.incidentId && other.item.videoName === hit.item.videoName,
  );
  const holderId = hit.item.holderEntityId;
  const holder = holderId ? sameIncident.find((other) => other.item.itemType === 'entity' && other.item.itemId === holderId) : undefined;
  return {
    heldBy: holderId ? { itemId: holderId, name: holder?.item.name ?? '' } : null,
    holds:
      hit.item.itemType === 'entity'
        ? sameIncident
            .filter((other) => other.item.holderEntityId === hit.item.itemId)
            .map((other) => ({ itemId: other.item.itemId, name: other.item.name }))
        : [],
  };
}

export interface IncidentGroup {
  incidentId: string;
  incident: EvidenceSearchHit['incident'];
  hits: EvidenceSearchHit[];
  /** Best similarity among the hits, 0 to 1. */
  best: number;
}

/** Hits regrouped under their incident, the group with the best hit first; each group keeps the hits' ranked order. */
export function groupByIncident(hits: EvidenceSearchHit[]): IncidentGroup[] {
  const groups = new Map<string, IncidentGroup>();
  for (const hit of hits) {
    const group = groups.get(hit.incident.incidentId);
    if (group) {
      group.hits.push(hit);
      group.best = Math.max(group.best, hit.similarityScore);
    } else {
      groups.set(hit.incident.incidentId, {
        incidentId: hit.incident.incidentId,
        incident: hit.incident,
        hits: [hit],
        best: hit.similarityScore,
      });
    }
  }
  return [...groups.values()].sort((a, b) => b.best - a.best);
}

export const matchPercent = (hit: EvidenceSearchHit): number => Math.round(hit.similarityScore * 100);

/** Hits of the same camera taken at the same video second: the boxes the frame viewer draws together. */
export function hitsInFrame(hit: EvidenceSearchHit, hits: EvidenceSearchHit[]): EvidenceSearchHit[] {
  return hits.filter(
    (other) =>
      other.incident.incidentId === hit.incident.incidentId &&
      other.item.videoName === hit.item.videoName &&
      other.item.timestampSeconds === hit.item.timestampSeconds,
  );
}

/** The report page for a hit: its version, the camera (?video=) and the second the hit was taken at (?t=). */
export function reportHref(hit: EvidenceSearchHit, version?: SearchedVersion): string {
  const query = new URLSearchParams();
  if (version) query.set('revision', String(version.revisionId));
  if (hit.item.videoName) query.set('video', hit.item.videoName);
  query.set('t', String(Math.floor(hit.item.timestampSeconds)));
  return `/reports/${encodeURIComponent(hit.incident.incidentId)}?${query}`;
}

/** The ?t= second a report page opens at; null when absent or not a non-negative number. */
export function parseStartSeconds(value: string | null | undefined): number | null {
  if (value == null || value.trim() === '') return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export const hitKey = (hit: EvidenceSearchHit): string =>
  hit.resultId || `${hit.incident.incidentId}:${hit.item.videoName}:${hit.item.itemType}:${hit.item.itemId}`;

export const ITEM_KINDS: ('all' | EvidenceItemType)[] = ['all', 'entity', 'instrument', 'asset'];

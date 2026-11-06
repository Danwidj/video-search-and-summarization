// SPDX-License-Identifier: Apache-2.0

// Pure helpers behind the library page's Find evidence tab: what /api/search
// returns, the card title, the client-side sort and the grouping by incident. No React and no server code, so tests can import it.

import type { EvidenceItemType, EvidenceSearchHit, EvidenceSearchResult } from '@/modules/search/domain/search';

/** The version a hit came from: the video's official revision, else its newest (what search reads). */
export interface SearchedVersion {
  revisionId: number;
  revisionNo: number;
  isOfficial: boolean;
  /** The library title of the video, which a hit's own incident title can lack. */
  title?: string;
  /** The uploaded video's file name, shown under the incident title and used by the Video filter. */
  filename?: string;
  /** When this version was created (ISO); the Date sort orders by it. */
  generatedAt?: string;
  thumbnailUrl?: string;
}

/** /api/search's body. */
export interface LibrarySearchResponse extends EvidenceSearchResult {
  /** By video id; a video missing here could not be looked up. */
  versions: Record<string, SearchedVersion>;
}

export const KIND_NAME: Record<EvidenceItemType, string> = { entity: 'Entity', instrument: 'Instrument', asset: 'Asset' };

const GENERIC_NAMES = new Set(['human', 'animal', 'unknown', 'person']);

/** One name per card: the report label saved as the item name, else the detector label, else the evidence type. Never "human", "animal" or "unknown". */
export function hitTitle(item: Pick<EvidenceSearchHit['item'], 'name' | 'label' | 'itemType'>): string {
  const named = [item.name, item.label].map((value) => value?.trim()).find((value) => value && !GENERIC_NAMES.has(value.toLowerCase()));
  return named || KIND_NAME[item.itemType];
}

export type EvidenceSort = 'match' | 'date' | 'threat' | 'severity';

export const SORT_LABEL: Record<EvidenceSort, string> = { match: 'Best match', date: 'Date', threat: 'Threat', severity: 'Severity' };

/** The video a hit belongs to, as the Video filter names it: the file name, else the incident title, else the id. */
export const videoName = (hit: EvidenceSearchHit, versions: Record<string, SearchedVersion>): string =>
  versions[hit.incident.videoId]?.filename || versions[hit.incident.videoId]?.title || hit.incident.title || hit.incident.videoId;

/**
 * Hits reordered for display, in the browser. "match" keeps the order the search returned (best match first, or video order for a
 * listing). Threat sorts by the item's threat, then the incident's severity, then newest; Severity by severity, then threat, then
 * newest; Date by newest. Every tie falls back to the returned rank, and a missing threat counts as 0.
 */
export function sortHits(hits: EvidenceSearchHit[], sort: EvidenceSort, versions: Record<string, SearchedVersion>): EvidenceSearchHit[] {
  if (sort === 'match') return hits;
  const created = (hit: EvidenceSearchHit) => versions[hit.incident.videoId]?.generatedAt ?? '';
  const threat = (hit: EvidenceSearchHit) => hit.item.threatLevel ?? 0;
  const newest = (a: EvidenceSearchHit, b: EvidenceSearchHit) => created(b).localeCompare(created(a));
  const severity = (a: EvidenceSearchHit, b: EvidenceSearchHit) => b.incident.severityLevel - a.incident.severityLevel;
  const byThreat = (a: EvidenceSearchHit, b: EvidenceSearchHit) => threat(b) - threat(a);
  const order = sort === 'date' ? [newest] : sort === 'threat' ? [byThreat, severity, newest] : [severity, byThreat, newest];
  return hits
    .map((hit, index) => ({ hit, index }))
    .sort((a, b) => {
      for (const compare of order) {
        const result = compare(a.hit, b.hit);
        if (result) return result;
      }
      return a.index - b.index;
    })
    .map(({ hit }) => hit);
}

export interface IncidentGroup {
  videoId: string;
  incident: EvidenceSearchHit['incident'];
  hits: EvidenceSearchHit[];
  /** Best similarity among the hits, 0 to 1. */
  best: number;
}

/** Hits regrouped under their incident, the group with the best hit first; each group keeps the hits' ranked order. */
export function groupByIncident(hits: EvidenceSearchHit[]): IncidentGroup[] {
  const groups = new Map<string, IncidentGroup>();
  for (const hit of hits) {
    const group = groups.get(hit.incident.videoId);
    if (group) {
      group.hits.push(hit);
      group.best = Math.max(group.best, hit.similarityScore);
    } else {
      groups.set(hit.incident.videoId, { videoId: hit.incident.videoId, incident: hit.incident, hits: [hit], best: hit.similarityScore });
    }
  }
  return [...groups.values()].sort((a, b) => b.best - a.best);
}

export const matchPercent = (hit: EvidenceSearchHit): number => Math.round(hit.similarityScore * 100);

/** The report page for a hit: its version, and the second the box was found at, fraction kept (?t=). */
export function reportHref(hit: EvidenceSearchHit, version?: SearchedVersion): string {
  const query = new URLSearchParams();
  if (version) query.set('revision', String(version.revisionId));
  query.set('t', String(+Math.max(0, hit.item.timestampSeconds).toFixed(3)));
  return `/reports/${encodeURIComponent(hit.incident.videoId)}?${query}`;
}

/** The ?t= second a report page opens at; null when absent or not a non-negative number. */
export function parseStartSeconds(value: string | null | undefined): number | null {
  if (value == null || value.trim() === '') return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export const hitKey = (hit: EvidenceSearchHit): string => hit.resultId || `${hit.incident.videoId}:${hit.item.itemType}:${hit.item.itemId}`;

export const ITEM_KINDS: ('all' | EvidenceItemType)[] = ['all', 'entity', 'instrument', 'asset'];

// SPDX-License-Identifier: Apache-2.0

// The pending suggestions with what the review screens show for each side of the pair: the incident's
// title, its video names and its first video's thumbnail. Read only.

import { isValidR2Key, thumbnailKeyForVideo } from '@/lib/r2/key';
import type { IncidentId, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';
import type { SuggestionStore } from '@/modules/matching/domain/matching';

export interface SuggestionSide {
  incidentId: IncidentId;
  /** The overview title of the incident's shown version; null when it has no version yet. */
  title: string | null;
  videoNames: string[];
  /** The signed upload-time screenshot of the first video; absent when there is none. */
  thumbnailUrl?: string;
}

export interface SuggestionCard {
  id: number;
  score: number;
  reasons: string[];
  /** The newer incident (higher id): by default it joins `kept`. */
  joining: SuggestionSide;
  /** The older incident (lower id): by default it keeps its id and takes the other's videos. */
  kept: SuggestionSide;
}

export interface SuggestionCardPorts {
  suggestions: Pick<SuggestionStore, 'listPending'>;
  reports: Pick<IncidentReportRepository, 'getIncident' | 'getRevision'>;
}

/** Pending suggestions, highest score first, each with both incidents described; only those naming `incidentId` when given. */
export async function listSuggestionCards(
  { suggestions, reports }: SuggestionCardPorts,
  sign: (storageKey: string) => Promise<string | undefined>,
  incidentId?: IncidentId,
): Promise<SuggestionCard[]> {
  const sides = new Map<IncidentId, Promise<SuggestionSide | null>>();
  const sideOf = (id: IncidentId): Promise<SuggestionSide | null> => {
    const known = sides.get(id);
    if (known) return known;
    const loaded = (async (): Promise<SuggestionSide | null> => {
      const incident = await reports.getIncident(id);
      if (!incident) return null;
      const title = (await reports.getRevision(id, null))?.envelope.overview.title ?? null;
      const first = incident.videos[0]?.storageKey;
      let thumbnailUrl: string | undefined;
      try {
        thumbnailUrl = isValidR2Key(first) ? await sign(thumbnailKeyForVideo(first)) : undefined;
      } catch {
        thumbnailUrl = undefined;
      }
      return {
        incidentId: id,
        title,
        videoNames: incident.videos.map((video) => video.videoId),
        ...(thumbnailUrl ? { thumbnailUrl } : {}),
      };
    })();
    sides.set(id, loaded);
    return loaded;
  };

  const cards: SuggestionCard[] = [];
  for (const suggestion of await suggestions.listPending(incidentId)) {
    const [kept, joining] = await Promise.all([
      sideOf(Math.min(suggestion.incidentAId, suggestion.incidentBId)),
      sideOf(Math.max(suggestion.incidentAId, suggestion.incidentBId)),
    ]);
    if (kept && joining) cards.push({ id: suggestion.id, score: suggestion.score, reasons: suggestion.reasons, joining, kept });
  }
  return cards;
}

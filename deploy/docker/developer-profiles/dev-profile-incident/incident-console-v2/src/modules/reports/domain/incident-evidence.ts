// SPDX-License-Identifier: Apache-2.0

// The evidence of every camera of a revision as one list for the report page. Item ids (E1, I1, A1) repeat from
// camera to camera, so each item carries the video it was seen in. Pure functions, no I/O, browser-safe.

import type { ItemEvidence, ReportView } from '@/modules/reports/domain/report-view';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

/** One entity, instrument or asset of one camera, flattened for the evidence list and its detail pop-up. */
export interface IncidentEvidenceItem {
  /** The real video file name of the camera that saw it. */
  video: string;
  /** False when the video has left the incident, so there is no player to seek. */
  playable: boolean;
  kind: EvidenceItemType;
  /** The camera's own id (E1, I1, A1); not unique across cameras. */
  id: string;
  title: string;
  description: string;
  /** When the item is most clearly visible; null when not recorded. */
  seconds: number | null;
  evidence: ItemEvidence | null;
  /** Entities: the names of the instruments they hold. */
  holds: string[];
  /** Entities: the span on screen; null when not recorded. */
  onScreen: { firstSeenSeconds: number; lastSeenSeconds: number } | null;
  /** Instruments: the threat rating; null when unrated. */
  threatLevel: number | null;
  /** Instruments: the holder's "E1 · label" title; null when nobody holds it. */
  holder: string | null;
  /** Assets: who was last seen handling it ("E2 (person in white shirt)") and when; null when absent. */
  lastHandledBy: { who: string; seconds: number | null } | null;
}

/** The time an item is shown at: its own, else its evidence crop's. */
const itemSeconds = (own: number | null, evidence: ItemEvidence | null): number | null => own ?? evidence?.timestampSeconds ?? null;

/** One camera's items in time order (items with no time last), ties kept in entity, instrument, asset order. */
export function cameraEvidenceItems(video: string, playable: boolean, structured: ReportView['structured']): IncidentEvidenceItem[] {
  const holderOf = new Map(structured.entities.map((entity) => [entity.entityId, `${entity.entityId} · ${entity.label || entity.type}`]));
  const handlerName = (entityId: string) => {
    const entity = structured.entities.find((candidate) => candidate.entityId === entityId);
    const label = entity && (entity.label || entity.type);
    return label ? `${entityId} (${label})` : entityId;
  };
  const items: IncidentEvidenceItem[] = [
    ...structured.entities.map((entity) => ({
      video,
      playable,
      kind: 'entity' as const,
      id: entity.entityId,
      title: entity.label || entity.type,
      description: entity.description,
      seconds: itemSeconds(entity.timestampSeconds, entity.evidence),
      evidence: entity.evidence,
      holds: structured.instruments.filter((instrument) => instrument.entityId === entity.entityId).map((instrument) => instrument.name),
      onScreen:
        entity.firstSeenSeconds !== null && entity.lastSeenSeconds !== null
          ? { firstSeenSeconds: entity.firstSeenSeconds, lastSeenSeconds: entity.lastSeenSeconds }
          : null,
      threatLevel: null,
      holder: null,
      lastHandledBy: null,
    })),
    ...structured.instruments.map((instrument) => ({
      video,
      playable,
      kind: 'instrument' as const,
      id: instrument.instrumentId,
      title: instrument.name,
      description: instrument.description,
      seconds: itemSeconds(instrument.timestampSeconds, instrument.evidence),
      evidence: instrument.evidence,
      holds: [],
      onScreen: null,
      threatLevel: instrument.threatLevel,
      holder: (instrument.entityId && holderOf.get(instrument.entityId)) || null,
      lastHandledBy: null,
    })),
    ...structured.assets.map((asset) => ({
      video,
      playable,
      kind: 'asset' as const,
      id: asset.assetId,
      title: asset.name,
      description: asset.description,
      seconds: itemSeconds(asset.timestampSeconds, asset.evidence),
      evidence: asset.evidence,
      holds: [],
      onScreen: null,
      threatLevel: null,
      holder: null,
      lastHandledBy: asset.lastHandledBy
        ? {
            who: handlerName(asset.lastHandledBy.entityId),
            seconds: asset.lastHandledBy.seconds,
          }
        : null,
    })),
  ];
  // Array.prototype.sort is stable, so equal times keep the order above.
  return items.sort((a, b) => {
    if (a.seconds === b.seconds) return 0;
    if (a.seconds === null) return 1;
    if (b.seconds === null) return -1;
    return a.seconds - b.seconds;
  });
}

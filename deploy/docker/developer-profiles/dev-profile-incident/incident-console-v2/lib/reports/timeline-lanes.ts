// SPDX-License-Identifier: Apache-2.0

// Browser-safe layout of the report page's timeline: one lane per entity (a
// bar from its first to its last seen second, with the instruments it holds
// on the same lane), a "Holder unknown" lane for instruments nobody visibly
// holds, and one lane for the assets.

import type { ReportView } from '@/lib/reports/report-view';
import type { EvidenceItemType } from '@/lib/reports/revision';

export interface LaneMarker {
  id: string;
  kind: EvidenceItemType;
  label: string;
  /** The second the item is most clearly visible; null when the report has none. */
  seconds: number | null;
}

export interface TimelineLane {
  id: string;
  kind: 'entity' | 'unknown-holder' | 'assets';
  title: string;
  /** First to last seen; null when the revision has no valid span, and the lane shows only its markers. */
  span: { start: number; end: number } | null;
  markers: LaneMarker[];
  /** The entity's evidence image, for the lane header. */
  imageUrl: string | null;
}

type Structured = ReportView['structured'];

function validSpan(start: number | null, end: number | null): { start: number; end: number } | null {
  return start !== null && end !== null && start >= 0 && end >= start ? { start, end } : null;
}

export function buildTimelineLanes({ entities, instruments, assets }: Structured): TimelineLane[] {
  const holders = new Set(entities.map((entity) => entity.entityId));
  const instrumentMarker = (instrument: Structured['instruments'][number]): LaneMarker => ({ id: instrument.instrumentId, kind: 'instrument', label: instrument.name, seconds: instrument.timestampSeconds });

  const lanes: TimelineLane[] = entities.map((entity) => ({
    id: entity.entityId,
    kind: 'entity',
    title: `${entity.entityId} · ${entity.label || entity.type}`,
    span: validSpan(entity.firstSeenSeconds, entity.lastSeenSeconds),
    markers: [
      { id: entity.entityId, kind: 'entity', label: entity.label || entity.type, seconds: entity.timestampSeconds },
      ...instruments.filter((instrument) => instrument.entityId === entity.entityId).map(instrumentMarker),
    ],
    imageUrl: entity.evidence?.imageUrl ?? null,
  }));

  const unheld = instruments.filter((instrument) => !instrument.entityId || !holders.has(instrument.entityId));
  if (unheld.length) lanes.push({ id: 'unknown-holder', kind: 'unknown-holder', title: 'Holder unknown', span: null, markers: unheld.map(instrumentMarker), imageUrl: null });
  if (assets.length) lanes.push({ id: 'assets', kind: 'assets', title: 'Assets', span: null, markers: assets.map((asset) => ({ id: asset.assetId, kind: 'asset', label: asset.name, seconds: asset.timestampSeconds })), imageUrl: null });
  return lanes;
}

/** The time axis length: the video's own length when known, else just past the last time any lane uses. */
export function timelineDuration(lanes: TimelineLane[], videoSeconds: number | null): number {
  if (videoSeconds !== null && Number.isFinite(videoSeconds) && videoSeconds > 0) return videoSeconds;
  const times = lanes.flatMap((lane) => [lane.span?.end ?? 0, ...lane.markers.map((marker) => marker.seconds ?? 0)]);
  return Math.max(1, ...times);
}

/** Position on the axis as a percentage, kept inside it. */
export function axisPercent(seconds: number, duration: number): number {
  return Math.min(100, Math.max(0, (seconds / duration) * 100));
}

/** Evenly spaced ruler ticks, at most `count` of them, on whole seconds. */
export function axisTicks(duration: number, count = 6): number[] {
  const step = Math.max(1, Math.ceil(duration / count / 5) * 5);
  const ticks: number[] = [];
  for (let at = 0; at <= duration; at += step) ticks.push(at);
  return ticks;
}

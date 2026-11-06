// SPDX-License-Identifier: Apache-2.0

// Browser-safe layout of the versions list drawn as branches: every AI run
// starts its own lane and a human version sits on the lane of the version it
// was edited from. Rows stay newest first, as the revisions route returns them.

import type { RevisionSummary } from '@/modules/reports/domain/revision';

/** The most characters of a human version's note its row shows; the row's hover title has the whole note. */
export const VERSION_NOTE_MAX_CHARS = 10;

/** A version's note as its row shows it: whole when it fits, else its first characters and an ellipsis. Counts characters, so an emoji is never split. */
export function shortVersionNote(note: string): string {
  const characters = Array.from(note);
  return characters.length <= VERSION_NOTE_MAX_CHARS ? note : `${characters.slice(0, VERSION_NOTE_MAX_CHARS).join('')}…`;
}

export interface GraphSegment {
  lane: number;
  /** The lane's line reaches this row from the one above it. */
  fromAbove: boolean;
  /** The lane's line continues to the row below. */
  toBelow: boolean;
}

export interface VersionGraphRow {
  revision: RevisionSummary;
  lane: number;
  segments: GraphSegment[];
}

export function layoutVersions(revisions: RevisionSummary[]): { rows: VersionGraphRow[]; laneCount: number } {
  const laneOf = new Map<number, number>();
  let laneCount = 0;
  for (const revision of [...revisions].sort((a, b) => a.revisionNo - b.revisionNo)) {
    const inherited = revision.parentId === null ? undefined : laneOf.get(revision.parentId);
    laneOf.set(revision.revisionId, inherited ?? laneCount++);
  }

  const extent = new Map<number, { first: number; last: number }>();
  revisions.forEach((revision, index) => {
    const lane = laneOf.get(revision.revisionId) ?? 0;
    const known = extent.get(lane);
    extent.set(lane, { first: known ? Math.min(known.first, index) : index, last: known ? Math.max(known.last, index) : index });
  });

  const rows = revisions.map((revision, index) => ({
    revision,
    lane: laneOf.get(revision.revisionId) ?? 0,
    segments: [...extent]
      .filter(([, { first, last }]) => index >= first && index <= last)
      .map(([lane, { first, last }]) => ({ lane, fromAbove: index > first, toBelow: index < last })),
  }));
  return { rows, laneCount };
}

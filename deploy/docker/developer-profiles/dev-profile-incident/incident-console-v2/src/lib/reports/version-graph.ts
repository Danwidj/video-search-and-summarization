// SPDX-License-Identifier: Apache-2.0

// Browser-safe layout of the versions list drawn as branches: every AI run
// starts its own lane and a human version sits on the lane of the version it
// was edited from. Rows stay newest first, as the revisions route returns them.

import type { RevisionSummary } from '@/modules/reports/domain/revision';

export interface GraphSegment {
  lane: number;
  /** The lane's line reaches this row from the one above it. */
  fromAbove: boolean;
  /** The lane's line continues to the row below. */
  toBelow: boolean;
}

/** What the layout reads of a version; the revisions route's rows carry more and keep it. */
export type GraphRevision = Pick<RevisionSummary, 'revisionId' | 'revisionNo' | 'parentId'>;

export interface VersionGraphRow<T extends GraphRevision = RevisionSummary> {
  revision: T;
  lane: number;
  segments: GraphSegment[];
}

export function layoutVersions<T extends GraphRevision>(revisions: T[]): { rows: VersionGraphRow<T>[]; laneCount: number } {
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

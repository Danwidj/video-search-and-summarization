// SPDX-License-Identifier: Apache-2.0

// The draft item the box tool hands to Edit mode (contract: reviewer box -> AI describe -> track). Boxes are
// [ymin, xmin, ymax, xmax] on 0-1000, seconds are video seconds. Browser-safe, no I/O.

export type BoxItemType = 'entity' | 'instrument' | 'asset';
export const BOX_ITEM_TYPES: readonly BoxItemType[] = ['entity', 'instrument', 'asset'];

export type Box = [number, number, number, number];

/** What the describe route proposed for the boxed crop, kept on the item for audit. */
export interface BoxProposal {
  itemType: BoxItemType;
  name: string;
  description: string;
  holder: string | null;
  threatLevel: number | null;
  confidence: number;
}

export interface ReviewerTrackSample {
  t: number;
  box: Box;
  conf: number;
}

/** A reviewer track: the AI track's sample shape plus where it came from and whether the tracker lost the item. */
export interface ReviewerTrack {
  source: 'reviewer';
  samples: ReviewerTrackSample[];
  span: [number, number];
  partial: boolean;
  lostAt: number | null;
}

export interface BoxToolItem {
  itemType: BoxItemType;
  name: string;
  description: string;
  holder?: string;
  threatLevel?: number;
  aiProposal: BoxProposal | null;
  /** Null: the item is kept as a still image (stillSeconds and stillBox say where). */
  track: ReviewerTrack | null;
  stillSeconds?: number;
  stillBox?: Box;
}

// SPDX-License-Identifier: Apache-2.0

// The slice of an evidence hit: a played time range of the incident's existing video (no clip file). Pure, browser-safe.

import type { EvidenceSearchHit } from '@/modules/search/domain/search';

/** How far either side of the box second a hit's slice reaches when the agent sent none (an agent older than the slice columns). */
const FALLBACK_PADDING_SECONDS = 3;

/** [start, end] in seconds: the stored slice, else the box second plus or minus the padding; never negative, end after start. */
export function hitSlice(item: EvidenceSearchHit['item']): { start: number; end: number } {
  const start = item.sliceStartSeconds ?? item.timestampSeconds - FALLBACK_PADDING_SECONDS;
  const end = item.sliceEndSeconds ?? item.timestampSeconds + FALLBACK_PADDING_SECONDS;
  const from = Math.max(0, start);
  return { start: from, end: Math.max(from, end) };
}

/** The media-fragment URL that plays the slice of the video: the browser stops at the end and clamps to the video's length. */
export function sliceUrl(playbackUrl: string, slice: { start: number; end: number }): string {
  return `${playbackUrl.split('#')[0]}#t=${+slice.start.toFixed(3)},${+slice.end.toFixed(3)}`;
}

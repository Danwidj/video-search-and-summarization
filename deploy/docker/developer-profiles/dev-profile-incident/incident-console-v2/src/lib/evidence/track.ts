// SPDX-License-Identifier: Apache-2.0

// Pure rules for Edit mode's track scrubber. The samples and the box at a second come from the report's track module
// (modules/reports/domain/track.ts); this adds the scrubber's whole seconds: the frame route cuts whole seconds and
// image_timestamp_seconds is an integer, so the scrubber stops only at whole seconds inside the track.

import type { SecondsRange } from '@/lib/evidence/frame-picker';
import { type TrackSample, trackBoxAt } from '@/modules/reports/domain/track';

/**
 * The whole seconds the scrubber may stop at: the first whole second at or after the track starts to the last at or
 * before it ends. A track shorter than a second between two whole seconds stops at its nearest whole second.
 */
export function trackSpan(samples: readonly TrackSample[]): SecondsRange {
  const first = Math.ceil(samples[0].t);
  const last = Math.floor(samples[samples.length - 1].t);
  if (first <= last) return { first, last };
  const middle = Math.round((samples[0].t + samples[samples.length - 1].t) / 2);
  return { first: middle, last: middle };
}

/** A scrubber value as a second on the track: rounded to a whole second and clamped to the span. */
export function trackSecond(value: number, span: SecondsRange): number {
  const seconds = Number.isFinite(value) ? Math.round(value) : span.first;
  return Math.min(span.last, Math.max(span.first, seconds));
}

/**
 * The track's box to pick at a second, on the 0-1000 grid: interpolated between close samples as the player draws it,
 * and across a gap held at the nearest sample (never none), since every second of the span is a valid pick.
 */
export function scrubberBoxAt(samples: readonly TrackSample[], seconds: number): TrackSample['box'] {
  const box = trackBoxAt(samples, seconds, Number.POSITIVE_INFINITY) ?? samples[0].box;
  return box.map((value) => Math.round(value)) as TrackSample['box'];
}

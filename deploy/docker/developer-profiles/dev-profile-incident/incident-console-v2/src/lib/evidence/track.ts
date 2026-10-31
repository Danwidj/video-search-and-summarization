// SPDX-License-Identifier: Apache-2.0

// Pure rules for a person track in Edit mode. The agent stores a matched entity's track beside its evidence as
// `<itemId>-track.json`: [{t, box, score}], t in video seconds, box [ymin, xmin, ymax, xmax] on the 0-1000 grid, at
// most five samples a second. The frame picker's scrubber moves over the track's span in whole seconds (the frame
// route cuts whole seconds and image_timestamp_seconds is an integer), and the box at a second is the nearest sample's.

import { boxRegion } from '@/lib/evidence/frame-geometry';
import type { SecondsRange } from '@/lib/evidence/frame-picker';

export interface TrackSample {
  t: number;
  box: [number, number, number, number];
}

/**
 * A track file's samples, oldest first; null when the file is not a non-empty list of {t, box} samples with a finite
 * second and a drawable box, so a malformed file is ignored as a whole rather than half drawn.
 */
export function parseTrack(value: unknown): TrackSample[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const samples: TrackSample[] = [];
  for (const raw of value) {
    const sample = raw as { t?: unknown; box?: unknown } | null;
    if (!sample || typeof sample !== 'object' || typeof sample.t !== 'number' || !Number.isFinite(sample.t) || sample.t < 0) return null;
    const box = Array.isArray(sample.box) ? sample.box : null;
    if (!box || !boxRegion(box)) return null;
    samples.push({ t: sample.t, box: box.map((n: number) => Math.round(Math.min(1000, Math.max(0, n)))) as TrackSample['box'] });
  }
  return samples.sort((a, b) => a.t - b.t);
}

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

/** The track's box at a second: the box of the sample nearest to it (held between samples, never extrapolated). */
export function trackBoxAt(samples: readonly TrackSample[], seconds: number): TrackSample['box'] {
  let nearest = samples[0];
  for (const sample of samples) {
    if (Math.abs(sample.t - seconds) < Math.abs(nearest.t - seconds)) nearest = sample;
  }
  return nearest.box;
}

// SPDX-License-Identifier: Apache-2.0

// Pure rules for the frame picker in Edit mode: a reviewer scrubs the video to
// a second and drags a rectangle on that frame. The rectangle becomes the
// region sent to the crop route, and the same rectangle is stored on the item
// as its image_box, so the save path carries it unchanged.

import { MIN_CROP_SIDE } from '@/lib/evidence/frame-request';
import type { FrameRegion } from '@/lib/evidence/frame-geometry';

export interface FramePoint {
  x: number;
  y: number;
}

/** What the picker hands back once a crop exists: the cropped JPEG held in the browser, its object URL for the preview, the frame second and the box. */
export interface FramePick {
  blob: Blob;
  previewUrl: string;
  timestampSeconds: number;
  box: number[];
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

/**
 * The rectangle between two drag points (fractions 0-1 of the frame), in either
 * direction and clipped to the frame. Null when it is thinner than the crop
 * minimum, which is a stray click rather than a selection.
 */
export function dragRegion(from: FramePoint, to: FramePoint): FrameRegion | null {
  const x0 = clamp01(Math.min(from.x, to.x));
  const x1 = clamp01(Math.max(from.x, to.x));
  const y0 = clamp01(Math.min(from.y, to.y));
  const y1 = clamp01(Math.max(from.y, to.y));
  const w = x1 - x0;
  const h = y1 - y0;
  if (w < MIN_CROP_SIDE || h < MIN_CROP_SIDE) return null;
  return { x: x0, y: y0, w, h };
}

/** A region as the stored bounding box: [ymin, xmin, ymax, xmax] rounded to the 0-1000 grid. */
export function regionBox(region: FrameRegion): number[] {
  const grid = (fraction: number) => Math.round(fraction * 1000);
  return [grid(region.y), grid(region.x), grid(region.y + region.h), grid(region.x + region.w)];
}

/** The seconds an entity is on screen, so a picked frame keeps its most-visible second inside them. */
export interface SecondsRange {
  first: number;
  last: number;
}

/**
 * A picked second: never negative, never past the end of the video when its length is known,
 * and inside the given range when there is one.
 */
export function pickSeconds(seconds: number, durationSeconds: number | null, range: SecondsRange | null = null): number {
  const floor = Math.max(range?.first ?? 0, seconds);
  const ceiling = range === null ? durationSeconds : Math.min(range.last, durationSeconds ?? range.last);
  return ceiling === null ? floor : Math.min(floor, ceiling);
}

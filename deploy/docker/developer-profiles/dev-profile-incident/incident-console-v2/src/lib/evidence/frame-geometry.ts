// SPDX-License-Identifier: Apache-2.0

// Pure geometry for EvidenceFrame and FrameViewer. A bounding box is
// [ymin, xmin, ymax, xmax] normalised to 0-1000 over the video frame (the
// evidence entry's bounding_box). Components turn these fractions into CSS.

export type BoundingBox = readonly [number, number, number, number];

/** A rectangle as fractions (0-1) of the frame. */
export interface FrameRegion {
  x: number;
  y: number;
  w: number;
  h: number;
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** The box as a frame region; null unless it is four finite numbers with positive width and height. */
export function boxRegion(box: readonly number[] | null | undefined): FrameRegion | null {
  if (box?.length !== 4 || !box.every(Number.isFinite)) return null;
  const [ymin, xmin, ymax, xmax] = box.map((n) => clamp(n, 0, 1000));
  if (ymax <= ymin || xmax <= xmin) return null;
  return { x: xmin / 1000, y: ymin / 1000, w: (xmax - xmin) / 1000, h: (ymax - ymin) / 1000 };
}

/** CSS percentages that place a box over its frame. */
export function boxStyle(box: readonly number[] | null | undefined): { left: string; top: string; width: string; height: string } | null {
  const region = boxRegion(box);
  if (!region) return null;
  const pct = (n: number) => `${+(n * 100).toFixed(3)}%`;
  return { left: pct(region.x), top: pct(region.y), width: pct(region.w), height: pct(region.h) };
}

/**
 * The part of a frame to show in a crop tile: the box plus padding, widened or
 * heightened to the tile's aspect ratio so nothing is stretched, centred on the
 * box and kept inside the frame. Both aspects are width / height.
 */
export function cropRegion(
  box: readonly number[] | null | undefined,
  frameAspect: number,
  tileAspect: number,
  padding = 0.25,
): FrameRegion | null {
  const region = boxRegion(box);
  if (!region || !(frameAspect > 0) || !(tileAspect > 0)) return null;
  const padW = region.w * (1 + padding * 2);
  const padH = region.h * (1 + padding * 2);
  // Region height h and width w satisfy (w * frameAspect) / h = tileAspect.
  let h = Math.max(padH, (padW * frameAspect) / tileAspect);
  let w = (h * tileAspect) / frameAspect;
  if (w > 1) {
    w = 1;
    h = frameAspect / tileAspect;
  }
  if (h > 1) {
    h = 1;
    w = tileAspect / frameAspect;
  }
  const cx = region.x + region.w / 2;
  const cy = region.y + region.h / 2;
  return { x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h };
}

/** Inline style for a full frame image positioned so that only `region` shows inside an overflow-hidden tile. */
export function cropImageStyle(region: FrameRegion): { width: string; height: string; left: string; top: string } {
  const pct = (n: number) => `${+(n * 100).toFixed(3)}%`;
  return { width: pct(1 / region.w), height: pct(1 / region.h), left: pct(-region.x / region.w), top: pct(-region.y / region.h) };
}

/**
 * The part of a tile a whole frame fills when it is shown without cutting any of it (object-contain): the frame's width and
 * height as fractions of the tile, so that a box drawn in percentages of the frame lines up on the picture.
 */
export function containFrame(frameAspect: number, tileAspect: number): { w: number; h: number } {
  if (!(frameAspect > 0) || !(tileAspect > 0)) return { w: 1, h: 1 };
  return frameAspect >= tileAspect ? { w: 1, h: tileAspect / frameAspect } : { w: frameAspect / tileAspect, h: 1 };
}

// A crop whose short side is under SMALL_CROP_SHORT_SIDE px is too small to read: it is cut with a wider margin and enlarged to
// SMALL_CROP_MIN_SHORT_SIDE px. The numbers match the agent's (crop_evidence.py), so a reviewer's cut looks like an AI cut.
export const SMALL_CROP_SHORT_SIDE = 96;
export const SMALL_CROP_MARGIN = 0.4;
export const SMALL_CROP_MIN_SHORT_SIDE = 192;

/** What to cut for an item's stored image: the region, and the pixel size to enlarge it to (null when it is left as cut). */
export interface CropPlan {
  region: FrameRegion;
  scaleTo: { w: number; h: number } | null;
}

/**
 * The cut for a box on a frame of `frameWidth` x `frameHeight` px. A box under SMALL_CROP_SHORT_SIDE px on its short side is
 * cut with SMALL_CROP_MARGIN of context on every side (kept inside the frame) and enlarged so the context is readable. The
 * item's own box is not changed: it stays the exact box the reviewer drew.
 */
export function cropPlan(region: FrameRegion, frameWidth: number, frameHeight: number): CropPlan {
  const short = Math.min(region.w * frameWidth, region.h * frameHeight);
  if (!(frameWidth > 0) || !(frameHeight > 0) || short >= SMALL_CROP_SHORT_SIDE) return { region, scaleTo: null };
  const x = clamp(region.x - region.w * SMALL_CROP_MARGIN, 0, 1);
  const y = clamp(region.y - region.h * SMALL_CROP_MARGIN, 0, 1);
  const wide: FrameRegion = {
    x,
    y,
    w: clamp(region.x + region.w * (1 + SMALL_CROP_MARGIN), 0, 1) - x,
    h: clamp(region.y + region.h * (1 + SMALL_CROP_MARGIN), 0, 1) - y,
  };
  const widePx = { w: wide.w * frameWidth, h: wide.h * frameHeight };
  const scale = SMALL_CROP_MIN_SHORT_SIDE / Math.min(widePx.w, widePx.h);
  return { region: wide, scaleTo: scale > 1 ? { w: Math.round(widePx.w * scale), h: Math.round(widePx.h * scale) } : null };
}

export type EvidenceFrameState = 'image' | 'frame-crop' | 'full-frame' | 'pending' | 'missing';

/** What an evidence tile can show: the whole frame when asked for, else its stored image, else a crop of the frame, else a placeholder. */
export function evidenceFrameState(input: {
  src?: string | null;
  frameSrc?: string | null;
  box?: readonly number[] | null;
  pending?: boolean;
  failed?: boolean;
  /** Show the whole frame (with the box when there is one) instead of cutting it. */
  fullFrame?: boolean;
}): EvidenceFrameState {
  if (input.fullFrame && input.frameSrc && !input.failed) return 'full-frame';
  if (input.src && !input.failed) return 'image';
  if (input.frameSrc && boxRegion(input.box) && !input.failed) return 'frame-crop';
  return input.pending ? 'pending' : 'missing';
}

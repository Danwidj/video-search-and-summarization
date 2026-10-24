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
  if (!box || box.length !== 4 || !box.every(Number.isFinite)) return null;
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

export type EvidenceFrameState = 'image' | 'frame-crop' | 'pending' | 'missing';

/** What an evidence tile can show: its stored image first, else a crop of the frame, else a placeholder. */
export function evidenceFrameState(input: {
  src?: string | null;
  frameSrc?: string | null;
  box?: readonly number[] | null;
  pending?: boolean;
  failed?: boolean;
}): EvidenceFrameState {
  if (input.src && !input.failed) return 'image';
  if (input.frameSrc && boxRegion(input.box) && !input.failed) return 'frame-crop';
  return input.pending ? 'pending' : 'missing';
}

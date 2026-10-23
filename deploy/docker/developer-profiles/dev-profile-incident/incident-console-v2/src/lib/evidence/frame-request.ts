// SPDX-License-Identifier: Apache-2.0

// Validation of a reviewer's frame and crop request. Pure, so the routes and
// the use cases share one set of rules and one set of messages.

import type { FrameRegion } from '@/lib/evidence/frame-geometry';

/** Allowed overshoot from float rounding in a drawn rectangle. */
const EDGE_TOLERANCE = 1e-6;
/** Smallest crop side as a fraction of the frame; anything thinner is a stray click. */
export const MIN_CROP_SIDE = 0.01;

export const ITEM_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** A request refused for what it asked, with the HTTP status a route answers. */
export class FrameRequestError extends Error {
  status: 400 | 404 | 409 | 422 | 502 | 503;

  constructor(status: FrameRequestError['status'], message: string) {
    super(message);
    this.name = 'FrameRequestError';
    this.status = status;
  }
}

/** A video second: a finite number, zero or more. Strings are accepted for query parameters. */
export function parseSeconds(value: unknown): number {
  const seconds = typeof value === 'string' && value.trim() !== '' ? Number(value) : value;
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
    throw new FrameRequestError(400, 'The timestamp must be a number of seconds, zero or more');
  }
  return seconds;
}

/** The timestamp must fall inside the video when its length is known. */
export function assertWithinVideo(seconds: number, durationSeconds: number | null): void {
  if (durationSeconds !== null && seconds >= durationSeconds) {
    throw new FrameRequestError(422, `The timestamp ${seconds} s is outside the video, which is ${+durationSeconds.toFixed(3)} s long`);
  }
}

/** A rectangle as fractions (0-1) of the frame: {x, y, w, h} from the top-left, entirely inside the frame. */
export function parseRegion(value: unknown): FrameRegion {
  const region = value as Record<string, unknown> | null;
  const keys = ['x', 'y', 'w', 'h'] as const;
  if (!region || typeof region !== 'object' || !keys.every((key) => typeof region[key] === 'number' && Number.isFinite(region[key]))) {
    throw new FrameRequestError(400, 'The rectangle must be {x, y, w, h}, four numbers as fractions of the frame');
  }
  const { x, y, w, h } = region as unknown as FrameRegion;
  if (x < 0 || y < 0 || x > 1 || y > 1 || x + w > 1 + EDGE_TOLERANCE || y + h > 1 + EDGE_TOLERANCE) {
    throw new FrameRequestError(422, 'The rectangle must lie inside the frame: x and y from 0 to 1, with x + w and y + h at most 1');
  }
  if (w < MIN_CROP_SIDE || h < MIN_CROP_SIDE) {
    throw new FrameRequestError(422, `The rectangle must be at least ${MIN_CROP_SIDE * 100}% of the frame wide and high`);
  }
  return { x, y, w: Math.min(w, 1 - x), h: Math.min(h, 1 - y) };
}

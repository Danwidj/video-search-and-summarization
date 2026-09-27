// SPDX-License-Identifier: Apache-2.0

// Browser-safe part of validation policy core-scored-v1's contextual rule
// (lib/contract/validate.ts; eval/contract.py timestamp_within_video): whether a
// whole-second timestamp can name a moment of a video of known length.

/**
 * Timestamps are whole seconds. A moment t within a video of D seconds, written
 * as a whole second, is at most ceil(t) < D + 1; so an integer timestamp T lies
 * within the video iff 0 <= T < D + WHOLE_SECOND_RESOLUTION.
 */
export const WHOLE_SECOND_RESOLUTION = 1;

export function timestampWithinVideo(seconds: number, videoDurationSeconds: number): boolean {
  return seconds >= 0 && seconds < videoDurationSeconds + WHOLE_SECOND_RESOLUTION;
}

// SPDX-License-Identifier: Apache-2.0

/** The video panel never shrinks below this share of the column, so the player stays usable. */
export const VIDEO_MIN_PERCENT = 20;
/** Timeline and versions each keep their 15% minimum, so the video cannot take more than this. */
export const VIDEO_MAX_PERCENT = 70;

export interface WorkspaceLayout {
  video: number;
  timeline: number;
  versions: number;
}

/**
 * Panel sizes (percent of the column height) that make the video fill the column width at its aspect ratio, so the
 * player is flush with no bars. The timeline and versions split what is left evenly, as the 27.5% : 27.5% default did.
 * `null` while the column has no size (a hidden or not yet laid-out column).
 */
export function videoFitLayout(width: number, height: number, aspect: number): WorkspaceLayout | null {
  if (!(width > 0) || !(height > 0) || !(aspect > 0)) return null;
  const video = Math.min(Math.max((width / aspect / height) * 100, VIDEO_MIN_PERCENT), VIDEO_MAX_PERCENT);
  const rest = (100 - video) / 2;
  return { video, timeline: rest, versions: rest };
}

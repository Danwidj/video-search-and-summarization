// SPDX-License-Identifier: Apache-2.0

/** The video panel never shrinks below this share of the column, so the player stays usable. */
export const VIDEO_MIN_PERCENT = 20;
/** Timeline and versions each keep their 15% minimum, so the video cannot take more than this. */
export const VIDEO_MAX_PERCENT = 70;
/** The timeline and versions panels never shrink below this share of the column. */
const PANEL_MIN_PERCENT = 15;

export interface WorkspaceLayout {
  video: number;
  timeline: number;
  versions: number;
}

/**
 * Panel sizes (percent of the column height) that make the video fill the column width at its aspect ratio, so the
 * player is flush with no bars. The timeline takes the height its lanes need (`timelinePx`) and versions take the rest,
 * each keeping its 15% minimum; without `timelinePx` they split what is left evenly, as the 27.5% : 27.5% default did.
 * `null` while the column has no size (a hidden or not yet laid-out column).
 */
export function videoFitLayout(width: number, height: number, aspect: number, timelinePx?: number): WorkspaceLayout | null {
  if (!(width > 0) || !(height > 0) || !(aspect > 0)) return null;
  const video = Math.min(Math.max((width / aspect / height) * 100, VIDEO_MIN_PERCENT), VIDEO_MAX_PERCENT);
  const rest = 100 - video;
  if (timelinePx === undefined) return { video, timeline: rest / 2, versions: rest / 2 };
  const timeline = Math.min(
    Math.max((timelinePx / height) * 100, PANEL_MIN_PERCENT),
    Math.max(rest - PANEL_MIN_PERCENT, PANEL_MIN_PERCENT),
  );
  return { video, timeline, versions: rest - timeline };
}

const TIMELINE_CHROME_PX = 120; // header and legend, time axis and padding
const TIMELINE_LANE_PX = 30; // one lane row and its gap

/** The height (px) the timeline needs to show `lanes` lanes without scrolling; an empty timeline needs room for its note. */
export function timelinePanelHeight(lanes: number): number {
  return lanes === 0 ? 110 : TIMELINE_CHROME_PX + lanes * TIMELINE_LANE_PX;
}

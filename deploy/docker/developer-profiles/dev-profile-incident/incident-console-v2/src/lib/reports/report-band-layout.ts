// SPDX-License-Identifier: Apache-2.0

// Pure sizing rules for the report's video, timeline and version-history band.
// Values are fractions of the available desktop width and always total one.

export interface ReportBandWidths {
  video: number;
  timeline: number;
  versions: number;
}

export type ReportBandBoundary = 'video-timeline' | 'timeline-versions' | 'video-versions';

export const DEFAULT_REPORT_BAND_WIDTHS: ReportBandWidths = { video: 0.3, timeline: 0.5, versions: 0.2 };
export const DEFAULT_TWO_PANE_BAND_WIDTHS: ReportBandWidths = { video: 0.7, timeline: 0, versions: 0.3 };
export const DEFAULT_REPORT_BAND_HEIGHT = 270;
export const MIN_REPORT_BAND_HEIGHT = 190;
export const MAX_REPORT_BAND_HEIGHT = 600;

const MIN_SECTION_WIDTH = 0.15;
const KEYBOARD_STEP = 0.02;
const HEIGHT_KEYBOARD_STEP = 20;
const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));

/** Move one boundary to a fraction of the whole band while keeping every section usable. */
export function resizeReportBand(widths: ReportBandWidths, boundary: ReportBandBoundary, position: number): ReportBandWidths {
  if (boundary === 'video-versions') {
    const video = clamp(position, MIN_SECTION_WIDTH, 1 - MIN_SECTION_WIDTH);
    return { video, timeline: 0, versions: 1 - video };
  }
  if (boundary === 'video-timeline') {
    const video = clamp(position, MIN_SECTION_WIDTH, 1 - widths.versions - MIN_SECTION_WIDTH);
    return { video, timeline: 1 - video - widths.versions, versions: widths.versions };
  }
  const split = clamp(position, widths.video + MIN_SECTION_WIDTH, 1 - MIN_SECTION_WIDTH);
  return { video: widths.video, timeline: split - widths.video, versions: 1 - split };
}

/** Keyboard equivalent of dragging a boundary left or right. */
export function nudgeReportBand(widths: ReportBandWidths, boundary: ReportBandBoundary, direction: -1 | 1): ReportBandWidths {
  const position =
    boundary === 'video-timeline' ? widths.video : boundary === 'video-versions' ? widths.video : widths.video + widths.timeline;
  return resizeReportBand(widths, boundary, position + direction * KEYBOARD_STEP);
}

/** Resize the whole video/timeline/version band without letting it disappear or take over the page. */
export function resizeReportBandHeight(height: number): number {
  return clamp(height, MIN_REPORT_BAND_HEIGHT, MAX_REPORT_BAND_HEIGHT);
}

/** Keyboard equivalent of dragging the band's bottom edge up or down. */
export function nudgeReportBandHeight(height: number, direction: -1 | 1): number {
  return resizeReportBandHeight(height + direction * HEIGHT_KEYBOARD_STEP);
}

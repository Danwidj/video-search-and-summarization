// SPDX-License-Identifier: Apache-2.0

/**
 * The dashboard's Ask for a chart jump: the header button scrolls to the chart
 * request section and puts the cursor in its request box. Kept free of React so
 * the scroll and focus are tested without a browser (tests/dashboard-charts.test.mjs).
 */

/** The section's anchor id: the dashboard's Ask for a chart button scrolls to it. */
export const CHART_REQUEST_ID = 'ask-for-a-chart';
/** The request box the jump focuses. */
export const CHART_REQUEST_INPUT_ID = 'chart-request-text';

type JumpTarget = { scrollIntoView(options: ScrollIntoViewOptions): void };
type FocusTarget = { focus(options?: FocusOptions): void };
type JumpWindow = { matchMedia(query: string): { matches: boolean } };

/**
 * Scrolls smoothly to the chart request (instantly when the viewer prefers reduced
 * motion), then focuses the request box without scrolling a second time.
 * Returns false when the section is not on the page.
 */
export function jumpToChartRequest(doc: { getElementById(id: string): unknown }, win: JumpWindow): boolean {
  const section = doc.getElementById(CHART_REQUEST_ID) as JumpTarget | null;
  if (!section) return false;
  const reduceMotion = win.matchMedia('(prefers-reduced-motion: reduce)').matches;
  section.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
  (doc.getElementById(CHART_REQUEST_INPUT_ID) as FocusTarget | null)?.focus({ preventScroll: true });
  return true;
}

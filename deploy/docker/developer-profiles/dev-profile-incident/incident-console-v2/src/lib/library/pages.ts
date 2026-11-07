// SPDX-License-Identifier: Apache-2.0

// The page buttons of a Library list. Pure, so tests can import it.

/** A page number to show as a button, or 'gap' for the ellipsis between pages that are not next to each other. */
export type PageItem = number | 'gap';

/**
 * The first 2 and last 2 pages, plus the current one when it is in the middle: 1 2 gap 7 gap 13 14. With 4 pages or
 * fewer, every page. Neighbouring pages join without a gap (page 3 of 14 is 1 2 3 gap 13 14).
 */
export function pageItems(current: number, total: number): PageItem[] {
  const shown = [...new Set([1, 2, total - 1, total, current].filter((page) => page >= 1 && page <= total))].sort((a, b) => a - b);
  if (total <= 4) return shown;
  return shown.flatMap((page, index): PageItem[] => (index > 0 && page - shown[index - 1] > 1 ? ['gap', page] : [page]));
}

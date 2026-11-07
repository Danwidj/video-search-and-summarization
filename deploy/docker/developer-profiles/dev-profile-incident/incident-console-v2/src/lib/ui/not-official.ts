// SPDX-License-Identifier: Apache-2.0

/**
 * How a not yet official mark is drawn in a chart: the light grey fill (`--color-not-official`) with a dashed outline in
 * `--color-not-official-line`. Official marks stay solid teal. One place, so every bar and swatch matches.
 */
export const NOT_OFFICIAL_STROKE = {
  stroke: 'var(--color-not-official-line)',
  strokeWidth: 1.25,
  strokeDasharray: '4 3',
} as const;

/** Below this width or height in px a segment is too small for a dash to read; it keeps the fill and a plain thin line. */
export const MIN_DASHED_SIZE = 10;

/** The outline props for a segment of this size: dashed when it is big enough, a solid hairline when it is not. */
export function notOfficialStroke(width: number, height: number) {
  const dashed = Math.abs(width) >= MIN_DASHED_SIZE && Math.abs(height) >= MIN_DASHED_SIZE;
  return dashed ? NOT_OFFICIAL_STROKE : { ...NOT_OFFICIAL_STROKE, strokeDasharray: undefined, strokeWidth: 1 };
}

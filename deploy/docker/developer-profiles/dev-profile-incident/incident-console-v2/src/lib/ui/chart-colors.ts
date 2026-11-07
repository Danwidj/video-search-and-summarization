// SPDX-License-Identifier: Apache-2.0

/**
 * Colours for generated charts, as hex: a canvas cannot read CSS variables, so the agent and the
 * browser both get these values. Official and not yet official equal the `--color-version-official` and
 * `--color-not-official` tokens (app/styles.css); a test keeps them equal. `--chart-2` and `--chart-4` are not used for data:
 * they fail the 3:1 non-text contrast rule against white. Every colour here passes 3:1.
 */
export const CHART_COLORS = {
  official: '#0b7a8f',
  notOfficial: '#8cc5cf',
  /** One series with no official split. */
  total: '#174f3b',
  /** Slices of a donut that is not a severity or status chart, in order. */
  categorical: ['#174f3b', '#d9754c', '#12211b', '#765300', '#3e5c76'],
} as const;

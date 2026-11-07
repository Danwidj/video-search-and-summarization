// SPDX-License-Identifier: Apache-2.0

/** The three colour bands severity and threat level share (the tokens are in app/styles.css). */
export type LevelBand = 'high' | 'medium' | 'low';

/** 5 and 4 are high, 3 medium, 2 and 1 low; null for no level. The one mapping for severity and threat level. */
export function levelBand(level: number | null | undefined): LevelBand | null {
  if (level === null || level === undefined || level <= 0) return null;
  const rounded = Math.round(level);
  if (rounded >= 4) return 'high';
  return rounded === 3 ? 'medium' : 'low';
}

/**
 * Classes for a severity (or threat) pill: the band token for the text and a tint and border derived from it
 * (`.sev-pill-*` in app/styles.css), readable over any video frame and WCAG AA for text.
 */
export function severityClass(level: number | null | undefined): string {
  const band = levelBand(level);
  return band ? `sev-pill-${band}` : 'border border-ink/10 bg-ink/5 text-ink/70';
}

export const severityStyle = severityClass;

/** The band colours as CSS variables, for inline styles and chart fills in the DOM. */
export const severityVar = { high: 'var(--color-sev-high)', medium: 'var(--color-sev-medium)', low: 'var(--color-sev-low)' } as const;

/** The same colours as hex for canvases and the agent, which cannot read CSS variables; a test keeps them equal to styles.css. */
export const severityChartColor = { high: '#991b1b', medium: '#765300', low: '#174f3b' } as const;

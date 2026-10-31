// SPDX-License-Identifier: Apache-2.0

/**
 * Returns solid, opaque Tailwind utility classes (background, border, text)
 * for a severity level (1-5), designed to remain clearly readable over any
 * video frame while keeping each severity level distinguishable and meeting
 * WCAG AA text contrast (>= 4.5:1).
 */
export function severityClass(level: number | null | undefined): string {
  if (level === null || level === undefined || level <= 0) {
    return 'border border-[#d5ded7] bg-[#edf2ee] text-[#394a40]';
  }
  const rounded = Math.round(level);
  if (rounded >= 5) return 'border border-[#f69898] bg-[#fce4e4] text-[#991b1b]';
  if (rounded === 4) return 'border border-[#f7a992] bg-[#ffe8df] text-[#9b3518]';
  if (rounded === 3) return 'border border-[#f3cc68] bg-[#fff1c7] text-[#765300]';
  if (rounded === 2) return 'border border-[#a6db70] bg-[#e6f4ce] text-[#174f3b]';
  return 'border border-[#c2e2af] bg-[#f0f7e6] text-[#174f3b]';
}

export const severityStyle = severityClass;

/**
 * Chart fills for the dashboard severity bands (high 4-5, medium 3, low 1-2): the severity badges' text colours, so the
 * donut matches the badges. Each passes WCAG AA against white, and each band is also named in text beside the chart.
 */
export const severityChartColor = { high: '#991b1b', medium: '#765300', low: '#174f3b' } as const;

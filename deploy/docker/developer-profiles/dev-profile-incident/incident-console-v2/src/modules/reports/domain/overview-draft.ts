// SPDX-License-Identifier: Apache-2.0

// Browser-safe draft of the incident overview the edit pane edits beside a camera's report. The overview has the
// contract's `incident` block fields; saving it appends a human revision that replaces only the overview (the
// cameras and the coverage are kept by the store). Blank text is saved as absent, the same as the envelope reads it.

import type { Overview } from '@/modules/reports/domain/envelope';

export type OverviewDraft = Overview;

/** The fields the reviewer can change, in the order the pane lists them. */
export const OVERVIEW_FIELDS = ['title', 'type', 'severity_level', 'description', 'location'] as const;

const MAX_TEXT = { title: 500, type: 200, description: 10_000, location: 500 } as const;

const blank = (value: string | null): string | null => (value?.trim() ? value.trim() : null);

/** A draft that starts as the opened version's overview. */
export function overviewDraftFrom(overview: Overview): OverviewDraft {
  return { ...overview };
}

/** The edit request's `overview`: trimmed text, blank as null. */
export function overviewFromDraft(draft: OverviewDraft): Overview {
  return {
    title: blank(draft.title),
    type: blank(draft.type),
    severity_level: draft.severity_level,
    description: blank(draft.description),
    location: blank(draft.location),
  };
}

/** How many overview fields differ from the opened version (after trimming, so stray spaces are not a change). */
export function overviewChangeCount(base: Overview, draft: OverviewDraft): number {
  const next = overviewFromDraft(draft);
  const before = overviewFromDraft(base);
  return OVERVIEW_FIELDS.filter((field) => next[field] !== before[field]).length;
}

/** Reasons the draft cannot be saved; empty when it can. */
export function overviewProblems(draft: OverviewDraft): string[] {
  const problems: string[] = [];
  const next = overviewFromDraft(draft);
  for (const field of ['title', 'type', 'description', 'location'] as const) {
    const value = next[field];
    if (value !== null && value.length > MAX_TEXT[field]) problems.push(`The ${field} is longer than ${MAX_TEXT[field]} characters.`);
  }
  if (next.severity_level !== null && !(Number.isInteger(next.severity_level) && next.severity_level >= 1 && next.severity_level <= 5)) {
    problems.push('The severity must be a whole number from 1 to 5.');
  }
  return problems;
}

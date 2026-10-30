// SPDX-License-Identifier: Apache-2.0

// Browser-safe split of a version's coverage verdict into the notes shown beside it: one for current videos the
// version does not include and one for videos it includes that have since left the incident. A complete version
// has none. The wording matches CoverageView.note from the revisions route.

import type { CoverageVerdict } from '@/modules/reports/domain/envelope';

export interface CoverageNoteLine {
  kind: 'gap' | 'removed';
  text: string;
}

export function coverageNoteLines(verdict: CoverageVerdict | null | undefined): CoverageNoteLine[] {
  if (!verdict) return [];
  const lines: CoverageNoteLine[] = [];
  if (verdict.status === 'lacks' || verdict.status === 'lacks-and-removed') {
    lines.push({ kind: 'gap', text: `Does not include: ${verdict.missing.join(', ')}` });
  }
  if (verdict.status === 'removed' || verdict.status === 'lacks-and-removed') {
    lines.push({ kind: 'removed', text: `Includes a removed video: ${verdict.removed.join(', ')}` });
  }
  return lines;
}

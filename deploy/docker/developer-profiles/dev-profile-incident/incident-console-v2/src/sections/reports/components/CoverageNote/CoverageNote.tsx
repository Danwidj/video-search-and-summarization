// SPDX-License-Identifier: Apache-2.0

import { Badge } from '@/components/ui/badge';
import { coverageNoteLines } from '@/lib/reports/coverage-notes';
import type { CoverageView } from '@/modules/reports/application/types';

const STYLE = {
  gap: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200',
  removed: 'border-orange-400/60 bg-orange-500/10 text-orange-800 dark:text-orange-200',
} as const;

/** What a version does not cover, with the Badge the version list uses; nothing when the version is complete. */
export function CoverageNote({ coverage, className = '' }: { coverage: CoverageView | null | undefined; className?: string }) {
  const lines = coverageNoteLines(coverage?.verdict);
  if (!lines.length) return null;
  return (
    <span className={`flex flex-col items-start gap-1 ${className}`}>
      {lines.map((line) => (
        <Badge
          className={`h-auto whitespace-normal px-1.5 text-left text-[10.5px] ${STYLE[line.kind]}`}
          data-testid={line.kind === 'gap' ? 'coverage-gap' : 'coverage-removed'}
          key={line.kind}
          variant="outline"
        >
          {line.text}
        </Badge>
      ))}
    </span>
  );
}

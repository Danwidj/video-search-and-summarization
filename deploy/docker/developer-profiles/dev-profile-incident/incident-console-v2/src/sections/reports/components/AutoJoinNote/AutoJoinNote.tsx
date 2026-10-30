// SPDX-License-Identifier: Apache-2.0

import type { AutoJoinRecord } from '@/modules/reports/domain/IncidentReportRepository';
import { ReasonList } from '@/sections/suggestions/components/Shared';

/**
 * Says the selected camera's video was joined to this incident by the matching rule rather than by a reviewer:
 * the score and why. Moving it out is the existing Remove video control, which also stops it being joined again.
 */
export function AutoJoinNote({ autoJoin, video }: { autoJoin: AutoJoinRecord; video: string }) {
  return (
    <div
      className="flex flex-col gap-2 border-b border-border bg-muted/30 px-5 py-2.5 text-xs sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:px-8"
      data-testid="auto-join-note"
    >
      <p className="font-semibold">
        <span className="break-all">{video}</span> was joined to this incident automatically (match score{' '}
        <span className="font-mono" data-testid="auto-join-score">
          {autoJoin.score.toFixed(2)}
        </span>
        ).
      </p>
      <ReasonList className="min-w-0" layout="chips" reasons={autoJoin.reasons} structuredReasons={autoJoin.structuredReasons} />
      <p className="text-muted-foreground">
        Not the same event? Use Remove video, then Move to its own incident; it will not be joined again.
      </p>
    </div>
  );
}

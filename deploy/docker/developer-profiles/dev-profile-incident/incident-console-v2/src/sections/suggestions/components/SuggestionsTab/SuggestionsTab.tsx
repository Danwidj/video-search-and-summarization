// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { MergeIcon } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { DecisionButtons, ReasonList, ScoreReadout, SideLink } from '@/sections/suggestions/components/Shared';
import { matchesSortNote } from '@/lib/library/view';
import type { SuggestionCards } from '@/sections/suggestions/use-suggestion-cards';
import type { SuggestionCard } from '@/sections/suggestions/types';

const LABEL = 'font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground';

function SuggestionRow({
  card,
  busy,
  onAccept,
  onReject,
}: {
  card: SuggestionCard;
  busy: boolean;
  onAccept: (card: SuggestionCard) => void;
  onReject: (card: SuggestionCard) => void;
}) {
  return (
    <li className="rounded-2xl border border-border bg-card p-4 shadow-xs lg:p-5" data-testid="suggestion-card">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1.2fr)_auto] xl:gap-6">
        <div className="flex min-w-0 flex-col gap-1">
          <p className={LABEL}>Possibly the same incident</p>
          <SideLink side={card.joining} />
          <div className="ml-1.5 flex items-center gap-1.5 text-muted-foreground">
            <MergeIcon className="size-3.5" />
            <span className="text-[11px]">would join</span>
          </div>
          <SideLink side={card.kept} />
        </div>
        <div className="min-w-0">
          <p className={LABEL}>Why it matched</p>
          <ReasonList className="mt-2" reasons={card.reasons} structuredReasons={card.structuredReasons} />
        </div>
        <div className="flex flex-col gap-3 xl:w-44">
          <div>
            <p className={LABEL}>Score</p>
            <div className="mt-1">
              <ScoreReadout score={card.score} />
            </div>
          </div>
          <DecisionButtons busy={busy} card={card} className="xl:flex-col" onAccept={onAccept} onReject={onReject} />
        </div>
      </div>
    </li>
  );
}

/** The library's Matches tab: every pending suggestion, highest score first, to accept or reject. */
export function SuggestionsTab({ state }: { state: SuggestionCards }) {
  const { cards, loading, error, busyId, notice, accept, reject, reload } = state;
  return (
    <div data-testid="suggestions-tab">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Suggested matches</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            New videos are compared with your incidents. Suggestions are never applied automatically. Place and event type decide the score;
            time overlap is only a hint.
          </p>
        </div>
        {matchesSortNote(cards.length) && <p className="text-xs text-muted-foreground">{matchesSortNote(cards.length)}</p>}
      </div>
      {notice && (
        <Alert className="mt-4" data-testid="suggestion-notice">
          <AlertTitle>{notice.title}</AlertTitle>
          <AlertDescription>
            {notice.detail}
            {notice.keptIncidentId ? (
              <>
                {' '}
                <Link className="font-semibold text-primary hover:underline" href={`/reports/${notice.keptIncidentId}`}>
                  Open incident {notice.keptIncidentId}
                </Link>
              </>
            ) : null}
          </AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert className="mt-4" data-testid="suggestion-error" variant="destructive">
          <AlertDescription className="flex flex-wrap items-center gap-3">
            {error}
            <Button onClick={() => void reload()} size="sm" type="button" variant="outline">
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {loading ? (
        <div className="mt-4 space-y-4" role="status">
          <Skeleton className="h-36 w-full rounded-2xl" />
          <Skeleton className="h-36 w-full rounded-2xl" />
          <span className="sr-only">Loading match suggestions</span>
        </div>
      ) : cards.length > 0 ? (
        <>
          <ul aria-label="Pending suggestions" className="mt-4 flex flex-col gap-4">
            {cards.map((card) => (
              <SuggestionRow busy={busyId === card.id} card={card} key={card.id} onAccept={accept} onReject={reject} />
            ))}
          </ul>
          <p className="mt-4 text-xs text-muted-foreground">
            Accept merges the two incidents into one; the report is regenerated only when you ask. Reject is remembered: the pair is not
            suggested again.
          </p>
        </>
      ) : (
        !error && (
          <div className="mt-6 rounded-2xl border border-dashed border-ink/20 p-14 text-center" data-testid="suggestions-empty">
            <h2 className="text-xl font-semibold">No suggested matches.</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              New uploads are compared with your incidents automatically. Rejected pairs are not suggested again.
            </p>
          </div>
        )
      )}
    </div>
  );
}

/** One line above the incident list when matches wait for a decision; nothing without any. */
export function PendingStrip({ count, onReview }: { count: number; onReview: () => void }) {
  if (count === 0) return null;
  return (
    <div
      className="mb-4 flex flex-col gap-2 rounded-xl border border-amber-300 bg-amber-50/80 px-4 py-2.5 text-sm text-amber-950 sm:flex-row sm:items-center sm:justify-between"
      data-testid="pending-strip"
      role="status"
    >
      <span>
        <strong className="font-semibold">
          {count} suggested {count === 1 ? 'match' : 'matches'}
        </strong>{' '}
        from your latest uploads {count === 1 ? 'is' : 'are'} waiting for your decision.
      </span>
      <button className="text-left text-xs font-semibold text-moss hover:underline" onClick={onReview} type="button">
        Review matches →
      </button>
    </div>
  );
}

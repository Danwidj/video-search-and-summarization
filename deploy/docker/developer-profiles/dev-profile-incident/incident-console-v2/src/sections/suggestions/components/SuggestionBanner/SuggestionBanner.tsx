// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { AcceptMatchDialog } from '@/sections/suggestions/components/AcceptMatchDialog';
import { DecisionButtons, ReasonDetails, ReasonList, ScoreReadout, SideLink } from '@/sections/suggestions/components/Shared';
import type { SuggestionCard } from '@/sections/suggestions/types';
import { useSuggestionCards } from '@/sections/suggestions/use-suggestion-cards';

/**
 * Pending match suggestions that name this incident, with the other incident, why it matched and the score. Accept asks
 * for the same confirmation as a manual merge. Nothing shows without a pending suggestion. `onMerged` runs after an
 * accept that kept this incident, so the page reloads. `disabled` holds the decisions back, for example with an unsaved edit.
 */
export function SuggestionBanner({
  incidentId,
  onMerged,
  disabled = false,
}: {
  incidentId: number;
  onMerged?: () => void;
  disabled?: boolean;
}) {
  const router = useRouter();
  const { cards, error, busyId, accept, reject } = useSuggestionCards(incidentId);
  const [confirming, setConfirming] = useState<SuggestionCard | null>(null);

  async function acceptCard(card: SuggestionCard) {
    await accept(card);
    if (card.kept.incidentId === incidentId) onMerged?.();
    else router.push(`/reports/${card.kept.incidentId}`);
  }

  if (cards.length === 0 && !error && !confirming) return null;
  const n = cards.length;
  return (
    <div className="border-b border-amber-300 bg-amber-50/80 px-5 py-3 text-amber-950 sm:px-8" data-testid="match-banner" role="status">
      {n > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <p className="text-sm font-semibold">
              Possible match: {n === 1 ? 'another incident may be' : `${n} other incidents may be`} the same event as this one
            </p>
            <Link className="text-xs font-semibold text-moss hover:underline" href="/library?tab=matches">
              See all in the library →
            </Link>
          </div>
          <ul className="mt-2.5 space-y-2">
            {cards.map((card) => {
              const other = card.kept.incidentId === incidentId ? card.joining : card.kept;
              return (
                <li className="min-w-0 rounded-xl border border-ink/10 bg-white p-3" data-testid="match-banner-row" key={card.id}>
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                    <SideLink className="lg:w-[19rem] lg:shrink-0" side={other} />
                    <div className="min-w-0 flex-1">
                      <ReasonList layout="chips" reasons={card.reasons} structuredReasons={card.structuredReasons} />
                    </div>
                    <div className="flex items-center justify-between gap-3 lg:justify-end">
                      <ScoreReadout compact score={card.score} />
                      <DecisionButtons
                        busy={busyId === card.id}
                        card={card}
                        className="shrink-0"
                        disabled={disabled}
                        onAccept={setConfirming}
                        onReject={reject}
                        small
                      />
                    </div>
                  </div>
                  <ReasonDetails className="mt-2.5" structuredReasons={card.structuredReasons} />
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs text-amber-900/80" data-testid="match-banner-hint">
            {disabled
              ? 'Save or discard your edit to decide these matches.'
              : 'Matches scoring 0.5 or more join automatically; these lower scores merge only when you accept and confirm. A rejected match is not suggested again.'}
          </p>
        </>
      )}
      {error && (
        <Alert className="mt-2" data-testid="suggestion-error" variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <AcceptMatchDialog card={confirming} onAccept={acceptCard} onClose={() => setConfirming(null)} />
    </div>
  );
}

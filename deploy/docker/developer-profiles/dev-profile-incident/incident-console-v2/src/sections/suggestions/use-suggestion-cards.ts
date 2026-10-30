// SPDX-License-Identifier: Apache-2.0
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { SuggestionCard } from '@/sections/suggestions/types';

export interface SuggestionNotice {
  title: string;
  detail: string;
  /** The incident that kept its id after an accept. */
  keptIncidentId?: number;
}

async function send(path: string, body?: unknown): Promise<void> {
  const response = await fetch(path, {
    method: 'POST',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(payload?.error || `Request failed (${response.status})`);
  }
}

/** The pending suggestions (those naming `incidentId` when given) and the accept and reject actions. */
export function useSuggestionCards(incidentId?: number) {
  const [cards, setCards] = useState<SuggestionCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<SuggestionNotice | null>(null);
  const sequence = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++sequence.current;
    try {
      const response = await fetch(`/api/suggestions/cards${incidentId === undefined ? '' : `?incidentId=${incidentId}`}`, {
        cache: 'no-store',
      });
      const payload = (await response.json()) as { suggestions?: SuggestionCard[]; error?: string };
      if (!response.ok || !payload.suggestions) throw new Error(payload.error || 'Could not load the match suggestions');
      if (mine !== sequence.current) return;
      setCards(payload.suggestions);
      setError('');
    } catch (cause) {
      if (mine === sequence.current) setError(cause instanceof Error ? cause.message : 'Could not load the match suggestions');
    } finally {
      if (mine === sequence.current) setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** True when the decision was saved. */
  async function decide(card: SuggestionCard, run: () => Promise<SuggestionNotice>): Promise<boolean> {
    setBusyId(card.id);
    setNotice(null);
    try {
      setNotice(await run());
      await reload();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the decision');
      return false;
    } finally {
      setBusyId(null);
    }
  }

  /** Merges the pair; the older incident keeps its id (the server's default). */
  const accept = (card: SuggestionCard) =>
    decide(card, async () => {
      await send(`/api/suggestions/${card.id}/accept`, { incidentId: card.kept.incidentId });
      return {
        title: `Merged into incident ${card.kept.incidentId}`,
        detail: `The report has not changed; regenerate it to include ${card.joining.videoNames.join(', ')}.`,
        keptIncidentId: card.kept.incidentId,
      };
    });

  const reject = (card: SuggestionCard) =>
    decide(card, async () => {
      await send(`/api/suggestions/${card.id}/reject`);
      return { title: 'Match rejected', detail: 'This pair will not be suggested again.' };
    });

  return { cards, loading, error, busyId, notice, dismissNotice: () => setNotice(null), accept, reject, reload };
}

export type SuggestionCards = ReturnType<typeof useSuggestionCards>;

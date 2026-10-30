// SPDX-License-Identifier: Apache-2.0
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { incidentNotices, incidentScope, LIBRARY_SCOPE } from '@/lib/reports/incident-notices';
import { acceptSuggestionRequest, requestReportBuild } from '@/lib/reports/merge-client';
import { mergedNotice, mergeThenRebuild } from '@/lib/reports/merge-flow';
import { buildAfterApart, type BuildAfterDecisionDeps } from '@/sections/suggestions/build-after-decision';
import type { SuggestionCard } from '@/sections/suggestions/types';

async function send<T = unknown>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(payload?.error || `Request failed (${response.status})`);
  }
  return (await response.json().catch(() => ({}))) as T;
}

/** Whether any pending suggestion still names the incident; a failed read counts as yes, so nothing is built on a guess. */
async function hasPending(incidentId: number): Promise<boolean> {
  try {
    const response = await fetch(`/api/suggestions/cards?incidentId=${incidentId}`, { cache: 'no-store' });
    const payload = (await response.json()) as { suggestions?: unknown[] };
    return !response.ok || !payload.suggestions || payload.suggestions.length > 0;
  } catch {
    return true;
  }
}

const afterDecision: BuildAfterDecisionDeps = { hasPending, build: requestReportBuild };

/**
 * The pending suggestions (those naming `incidentId` when given) and the accept and reject actions. Their notices go to
 * the inline notice of the incident page, or of the library's Matches tab when no incident is given.
 */
export function useSuggestionCards(incidentId?: number) {
  const [cards, setCards] = useState<SuggestionCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);
  const noticeScope = incidentId === undefined ? LIBRARY_SCOPE : incidentScope(incidentId);
  const sequence = useRef(0);

  const reload = useCallback(async (): Promise<SuggestionCard[] | null> => {
    const mine = ++sequence.current;
    try {
      const response = await fetch(`/api/suggestions/cards${incidentId === undefined ? '' : `?incidentId=${incidentId}`}`, {
        cache: 'no-store',
      });
      const payload = (await response.json()) as { suggestions?: SuggestionCard[]; error?: string };
      if (!response.ok || !payload.suggestions) throw new Error(payload.error || 'Could not load the match suggestions');
      if (mine === sequence.current) {
        setCards(payload.suggestions);
        setError('');
      }
      return payload.suggestions;
    } catch (cause) {
      if (mine === sequence.current) setError(cause instanceof Error ? cause.message : 'Could not load the match suggestions');
      return null;
    } finally {
      if (mine === sequence.current) setLoading(false);
    }
  }, [incidentId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** True when the decision was saved. */
  async function decide(card: SuggestionCard, run: () => Promise<{ title: string; detail: string }>): Promise<boolean> {
    setBusyId(card.id);
    incidentNotices.clear(noticeScope);
    try {
      incidentNotices.set(noticeScope, await run());
      await reload();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the decision');
      return false;
    } finally {
      setBusyId(null);
    }
  }

  /**
   * Merges the pair (the older incident keeps its id), builds the kept incident's report once and leaves the result as a
   * notice on that incident. Throws an Error worded for the reviewer when the merge was refused; nothing is built then.
   */
  async function accept(card: SuggestionCard): Promise<void> {
    const keptIncidentId = card.kept.incidentId;
    const rebuilt = await mergeThenRebuild(
      { merge: () => acceptSuggestionRequest(card.id, keptIncidentId), build: requestReportBuild },
      keptIncidentId,
    );
    incidentNotices.set(
      incidentId === undefined ? LIBRARY_SCOPE : incidentScope(keptIncidentId),
      mergedNotice({
        keptIncidentId,
        videoCount: card.kept.videoNames.length + card.joining.videoNames.length,
        rebuilt,
      }),
    );
    void reload();
  }

  const reject = (card: SuggestionCard) =>
    decide(card, async () => {
      await send(`/api/suggestions/${card.id}/reject`);
      // An incident that has no report yet and nothing left to decide gets its first one now.
      const results = await buildAfterApart(
        afterDecision,
        [card.kept, card.joining].map((side) => ({ incidentId: side.incidentId, hasReport: side.title !== null })),
      );
      const failed = results.includes(false);
      return {
        title: 'Match rejected',
        detail: `This pair will not be suggested again.${results.length ? (failed ? ' A report could not be built; open the incident to regenerate it.' : ' The report was built.') : ''}`,
      };
    });

  return { cards, loading, error, busyId, accept, reject, reload };
}

export type SuggestionCards = ReturnType<typeof useSuggestionCards>;

// SPDX-License-Identifier: Apache-2.0

// List the pending suggestions and decide one. Accepting merges the pair (the database marks the
// suggestion accepted in the same transaction); rejecting keeps the row so the pair is never
// suggested again.

import { StoreRejection } from '@/modules/shared/domain/common';
import type { IncidentId, IncidentReportRepository, MergeResult } from '@/modules/reports/domain/IncidentReportRepository';
import { type MatchSuggestion, type SuggestionStore, storedReasons } from '@/modules/matching/domain/matching';

/** Pending suggestions, highest score first; only those naming `incidentId` when given. */
export function listPendingSuggestions(suggestions: SuggestionStore, incidentId?: IncidentId): Promise<MatchSuggestion[]> {
  return suggestions.listPending(incidentId);
}

export interface AcceptedSuggestion {
  suggestionId: number;
  merge: MergeResult;
}

/**
 * Merges the suggestion's pair. `targetIncidentId` picks which of the two is kept (the other is deleted);
 * it defaults to the older incident, the lower id. Throws StoreRejection: 'not-found' when there is no
 * pending suggestion with this id, 'invalid' when the target is not one of the pair.
 * `automatic` is the rule's decision rather than a reviewer's: the merge also records the score and
 * reasons on the videos it moves, so the incident can show why they joined.
 */
export async function acceptSuggestion(
  { suggestions, reports }: { suggestions: SuggestionStore; reports: Pick<IncidentReportRepository, 'mergeIncidents'> },
  suggestionId: number,
  targetIncidentId?: IncidentId,
  options: { automatic?: boolean } = {},
): Promise<AcceptedSuggestion> {
  const suggestion = (await suggestions.listPending()).find((s) => s.id === suggestionId);
  if (!suggestion) throw new StoreRejection('not-found', `No pending match suggestion ${suggestionId}`);
  const { incidentAId, incidentBId } = suggestion;
  const target = targetIncidentId ?? Math.min(incidentAId, incidentBId);
  if (target !== incidentAId && target !== incidentBId) {
    throw new StoreRejection('invalid', `Incident ${target} is not part of match suggestion ${suggestionId}`);
  }
  const source = target === incidentAId ? incidentBId : incidentAId;
  const merge = await reports.mergeIncidents(
    target,
    source,
    options.automatic ? { score: suggestion.score, reasons: storedReasons(suggestion.reasons, suggestion.structuredReasons) } : undefined,
  );
  return { suggestionId, merge };
}

export function rejectSuggestion(
  suggestions: SuggestionStore,
  suggestionId: number,
): Promise<{ suggestionId: number; status: 'rejected' }> {
  return suggestions.reject(suggestionId);
}

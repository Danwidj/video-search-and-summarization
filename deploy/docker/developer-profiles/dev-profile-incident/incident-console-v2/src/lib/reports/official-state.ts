// SPDX-License-Identifier: Apache-2.0

// Which version is official as the star column shows it. The versions list refetches after a mark or a clear, so
// until it lands the answer of the click that just succeeded (`local`) wins over the list: undefined follows the list.

import type { RevisionSummary } from '@/modules/reports/domain/revision';

/** The official revision id the list shows: `local` when set (null is a clear), else the list's own, else none. */
export function officialRevisionIdOf(
  revisions: readonly Pick<RevisionSummary, 'revisionId' | 'isOfficial'>[],
  local?: number | null,
): number | null {
  if (local !== undefined) return local;
  return revisions.find((revision) => revision.isOfficial)?.revisionId ?? null;
}

/** Marking `revisionId` replaces another official version, so it asks first. */
export function shouldConfirmReplace(
  revisions: readonly Pick<RevisionSummary, 'revisionId' | 'isOfficial'>[],
  revisionId: number,
  local?: number | null,
): boolean {
  const official = officialRevisionIdOf(revisions, local);
  return official !== null && official !== revisionId;
}

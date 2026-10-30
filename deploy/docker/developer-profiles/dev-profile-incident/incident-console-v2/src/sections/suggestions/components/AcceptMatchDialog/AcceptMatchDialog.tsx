// SPDX-License-Identifier: Apache-2.0
'use client';

import { MergeConfirmDialog } from '@/sections/reports/components/MergeConfirmDialog';
import type { SuggestionCard } from '@/sections/suggestions/types';

/**
 * The confirmation Accept goes through, the same dialog as the manual merge: the newer incident of the pair joins the
 * older one, which keeps its id. `onAccept` merges and rebuilds, and throws an Error worded for the reviewer on a refusal.
 */
export function AcceptMatchDialog({
  card,
  onAccept,
  onClose,
}: {
  card: SuggestionCard | null;
  onAccept: (card: SuggestionCard) => Promise<void>;
  onClose: () => void;
}) {
  if (!card) return null;
  return (
    <MergeConfirmDialog
      key={card.id}
      onCancel={onClose}
      onConfirm={async () => {
        await onAccept(card);
        onClose();
      }}
      open
      source={card.joining}
      target={card.kept}
      targetHasOfficial={card.kept.hasOfficial}
    />
  );
}

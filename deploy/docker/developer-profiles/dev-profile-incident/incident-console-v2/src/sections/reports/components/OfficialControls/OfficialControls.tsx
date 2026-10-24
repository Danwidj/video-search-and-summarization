// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { clearOfficial, markOfficial } from '@/lib/reports/official-client';

/**
 * Explicit official-revision selection for a video. Nothing becomes official
 * by itself; a reviewer marks one revision, which also embeds its evidence for
 * search, and can move or clear the mark. No name is recorded.
 */
export function OfficialControls({
  videoId,
  revisionId,
  isOfficial,
  hasOfficial,
  onChanged,
}: {
  videoId: string;
  revisionId: number;
  isOfficial: boolean;
  hasOfficial: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function change(action: 'select' | 'clear') {
    if (
      action === 'select' &&
      hasOfficial &&
      !window.confirm('Another version is currently the official report for this video. Replace it with this one?')
    )
      return;
    setBusy(true);
    try {
      await (action === 'select' ? markOfficial(videoId, revisionId) : clearOfficial(videoId));
      onChanged();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Update failed');
    } finally {
      setBusy(false);
    }
  }

  return isOfficial ? (
    <button className="action" data-testid="clear-official" disabled={busy} onClick={() => void change('clear')} type="button">
      {busy ? 'Clearing…' : 'Clear official report'}
    </button>
  ) : (
    <button className="action" data-testid="make-official" disabled={busy} onClick={() => void change('select')} type="button">
      {busy ? 'Marking official…' : 'Make this the official report'}
    </button>
  );
}

// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

/**
 * Explicit official-report selection for a video. The newest analysis never
 * becomes official by itself; a reviewer chooses, and can change or clear it.
 */
export function OfficialControls({ videoId, modelRunId, isOfficial, hasOfficial, onChanged }: { videoId: string; modelRunId: string; isOfficial: boolean; hasOfficial: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);

  async function change(action: 'select' | 'clear') {
    const name = window.prompt(action === 'select' ? 'Your name is required to make this the official report.' : 'Your name is required to clear the official report.');
    if (!name?.trim()) return;
    if (action === 'select' && hasOfficial && !window.confirm('Another analysis is currently the official report for this video. Replace it with this one?')) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/videos/${encodeURIComponent(videoId)}/official`, {
        method: action === 'select' ? 'PUT' : 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(action === 'select' ? { modelRunId, selectedBy: name.trim() } : { clearedBy: name.trim() }),
      });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Update failed');
      onChanged();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Update failed');
    } finally {
      setBusy(false);
    }
  }

  return isOfficial
    ? <button className="action" data-testid="clear-official" disabled={busy} onClick={() => void change('clear')} type="button">Clear official report</button>
    : <button className="action" data-testid="make-official" disabled={busy} onClick={() => void change('select')} type="button">Make this the official report</button>;
}

// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';

import type { RevisionSummary } from '@/lib/reports/revision';
import { formatTimestamp } from '@/lib/time';

/**
 * The incident's History: every version, newest first. Open shows a version
 * (and starts the edit form from it). Nothing here changes or deletes an old version.
 */
export function RevisionHistory({ videoId, currentRevisionId, refreshKey, onOpen }: { videoId: string; currentRevisionId: number; refreshKey: number; onOpen: (revisionId: number) => void }) {
  const [revisions, setRevisions] = useState<RevisionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/reports/${encodeURIComponent(videoId)}/revisions`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as { revisions?: RevisionSummary[]; error?: string };
        if (!response.ok || !payload.revisions) throw new Error(payload.error || `History request failed with HTTP ${response.status}`);
        setRevisions(payload.revisions);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        setError(cause instanceof Error ? cause.message : 'Could not load the history');
      });
    return () => controller.abort();
  }, [videoId, refreshKey]);

  return (
    <section className="print-hidden border-t border-ink/10 px-6 py-6 sm:px-8" data-testid="revision-history">
      <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">History</h3>
      {error && <p className="mt-3 text-sm text-clay">{error}</p>}
      {!revisions && !error && <p className="mt-3 text-sm text-ink/45">Loading history…</p>}
      {revisions && (
        <ol className="mt-3 space-y-2">
          {revisions.map((revision) => (
            <li className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border p-3 text-sm ${revision.revisionId === currentRevisionId ? 'border-moss/40 bg-moss/5' : 'border-ink/10'}`} data-testid="revision-row" key={revision.revisionId}>
              <span className="font-mono text-xs font-bold text-moss">v{revision.revisionNo}</span>
              <span className="rounded-full bg-canvas px-2 py-0.5 text-[11px] font-semibold text-ink/60">{revision.kind === 'human' ? 'Human' : 'AI'}</span>
              <span className="text-ink/70">{revision.kind === 'human' ? revision.createdBy ?? 'Unknown reviewer' : revision.model ?? 'Unknown model'}</span>
              <span className="text-xs text-ink/45">{formatTimestamp(revision.createdAt, 'time unknown')}</span>
              {revision.note && <span className="text-xs italic text-ink/55">{revision.note}</span>}
              {revision.isOfficial && <span className="rounded-full bg-signal/20 px-2 py-0.5 text-[11px] font-semibold text-moss">Official</span>}
              <span className="ml-auto flex gap-3">
                {revision.revisionId === currentRevisionId
                  ? <span className="text-xs font-semibold text-ink/45">Open now</span>
                  : <button className="text-xs font-semibold text-moss" onClick={() => onOpen(revision.revisionId)} type="button">Open</button>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

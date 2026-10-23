// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useState } from 'react';

import { clearOfficial, markOfficial } from '@/lib/reports/official-client';
import type { RevisionSummary } from '@/modules/reports/domain/revision';
import { layoutVersions } from '@/lib/reports/version-graph';
import { formatTimestamp } from '@/lib/time';

const LANE_WIDTH = 16;

/** The incident's versions as branches, newest first. A star marks a version official; the filled star clears it. A saved version is never changed. */
export function ReportVersions({ videoId, revisions, error, currentRevisionId, onOpen, onOfficialChanged, mode = 'view', compareRevisionId = null, onCompare }: {
  videoId: string;
  revisions: RevisionSummary[] | null;
  error: string | null;
  currentRevisionId: number;
  onOpen: (revisionId: number) => void;
  onOfficialChanged: () => void;
  /** Edit mode compares the draft with an A version instead of opening one to read. */
  mode?: 'view' | 'edit';
  compareRevisionId?: number | null;
  onCompare?: (revisionId: number) => void;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const hasOfficial = (revisions ?? []).some((revision) => revision.isOfficial);

  async function toggleOfficial(revision: RevisionSummary) {
    if (!revision.isOfficial && hasOfficial && !window.confirm('Another version is currently the official report for this video. Replace it with this one?')) return;
    setBusyId(revision.revisionId);
    setActionError(null);
    try {
      await (revision.isOfficial ? clearOfficial(videoId) : markOfficial(videoId, revision.revisionId));
      onOfficialChanged();
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : 'Update failed');
    } finally {
      setBusyId(null);
    }
  }

  const layout = revisions ? layoutVersions(revisions) : null;
  return (
    <section aria-label="Versions" className="flex min-h-0 flex-col" data-testid="revision-history">
      <div className="flex items-center justify-between gap-2 px-3 pt-2">
        <h3 className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink/45">Versions{revisions ? ` · ${revisions.length}` : ''}</h3>
        <Link className="text-[11px] font-semibold text-moss" href={`/videos/${encodeURIComponent(videoId)}`}>Analysis history</Link>
      </div>
      {error && <p className="px-3 py-2 text-xs text-clay">{error}</p>}
      {actionError && <p className="mx-3 my-1 rounded-lg bg-[#fff6f2] p-2 text-xs text-[#8c3d25]" data-testid="official-error" role="alert">{actionError}</p>}
      {!revisions && !error && <p className="px-3 py-2 text-xs text-ink/45">Loading versions…</p>}
      {layout && (
        <ol className="min-h-0 overflow-auto px-2 py-1">
          {layout.rows.map(({ revision, lane, segments }) => {
            const current = revision.revisionId === currentRevisionId;
            const comparing = revision.revisionId === compareRevisionId;
            return (
              <li className={`flex items-stretch gap-2 rounded-xl px-1 py-1.5 text-xs ${current || comparing ? 'bg-moss/10' : ''}`} data-testid="revision-row" key={revision.revisionId}>
                <span aria-hidden className="relative shrink-0" style={{ width: layout.laneCount * LANE_WIDTH }}>
                  {segments.map((segment) => <i className="absolute w-px bg-ink/25" key={segment.lane} style={{ left: segment.lane * LANE_WIDTH + LANE_WIDTH / 2, top: segment.fromAbove ? 0 : '50%', bottom: segment.toBelow ? 0 : '50%' }} />)}
                  <i className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ${revision.kind === 'human' ? 'border-moss bg-moss' : 'border-[#5f7896] bg-white'}`} style={{ left: lane * LANE_WIDTH + LANE_WIDTH / 2 }} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2">
                    <b>v{revision.revisionNo}</b>
                    <span className="text-ink/50">{formatTimestamp(revision.createdAt, 'time unknown')}</span>
                    {revision.isOfficial && <span className="rounded-full bg-[#fff1c7] px-2 text-[10.5px] font-bold text-[#765300]">★ Official</span>}
                  </span>
                  <span className="flex items-center gap-1.5 text-ink/60">
                    <span className="rounded-full bg-canvas px-1.5 text-[10.5px] font-semibold">{revision.kind === 'human' ? 'Human' : 'AI'}</span>
                    <span className="truncate">{revision.kind === 'ai' ? revision.model ?? 'Unknown model' : revision.note ?? ''}</span>
                  </span>
                </span>
                <button
                  aria-label={revision.isOfficial ? `Clear v${revision.revisionNo} as the official version` : `Mark v${revision.revisionNo} official`}
                  aria-pressed={revision.isOfficial}
                  className="self-center text-base leading-none text-[#b58a00] disabled:opacity-40"
                  data-testid={revision.isOfficial ? 'clear-official' : 'make-official'}
                  disabled={busyId !== null}
                  onClick={() => void toggleOfficial(revision)}
                  title={revision.isOfficial ? 'Official version: click to clear' : 'Mark official'}
                  type="button"
                >{revision.isOfficial ? '★' : '☆'}</button>
                {mode === 'edit'
                  ? <button aria-label={`Compare v${revision.revisionNo} as A`} aria-pressed={comparing} className={`self-center rounded-full px-2 py-0.5 text-[10.5px] font-bold ${comparing ? 'bg-moss text-white' : 'border border-ink/15 font-semibold'}`} onClick={() => onCompare?.(revision.revisionId)} type="button">A</button>
                  : current
                    ? <span className="self-center rounded-full bg-moss px-2 py-0.5 text-[10.5px] font-bold text-white">Viewing</span>
                    : <button className="self-center rounded-full border border-ink/15 px-2 py-0.5 text-[10.5px] font-semibold" onClick={() => onOpen(revision.revisionId)} type="button">View</button>}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

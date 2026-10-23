// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';

import { IncidentThumbnail, SeverityChip } from '@/components/library/shared';
import type { ReportLibraryItem } from '@/modules/reports/domain/storage';
import { formatTimestamp } from '@/lib/time';

export function IncidentCard({ item, busy, onDelete, onOpen, onSearchEvidence }: {
  item: ReportLibraryItem;
  busy: boolean;
  onDelete: (item: ReportLibraryItem) => void;
  onOpen: (item: ReportLibraryItem) => void;
  onSearchEvidence: (item: ReportLibraryItem) => void;
}) {
  const href = `/reports/${encodeURIComponent(item.videoId)}?revision=${item.revisionId}`;
  const versions = item.versionCount ?? 0;
  const evidence = item.evidenceCount ?? 0;
  return (
    <article className="flex flex-col overflow-hidden rounded-[1.5rem] border border-ink/10 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-panel focus:ring-2 focus:ring-signal" id={`report-${item.revisionId}`} tabIndex={-1}>
      <div className="relative">
        <IncidentThumbnail urls={[item.thumbnailUrl, item.evidenceThumbnailUrl]} />
        <span className="absolute left-3 top-3"><SeverityChip level={item.severity} /></span>
      </div>
      <div className="flex flex-1 flex-col p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-moss">{item.incident_type}</p>
        <h2 className="mt-2 line-clamp-2 min-h-[3.2rem] text-xl font-semibold tracking-[-0.025em]">{item.title}</h2>
        <p className="mt-2 line-clamp-2 text-sm leading-6 text-ink/60">{item.description}</p>
        <div className="mt-3 min-h-[2.4rem]">
          {item.isOfficial
            ? <><p className="inline-block rounded-full bg-moss px-2.5 py-0.5 text-[11px] font-bold text-white" data-testid="library-official-marker">Official v{item.revisionNo} · {item.kind === 'human' ? 'Human' : 'AI'}</p>{item.officialSince && <p className="mt-1 text-[11px] text-ink/45">Made official {formatTimestamp(item.officialSince)}</p>}</>
            : <p className="inline-block rounded-full bg-[#fff1c7] px-2.5 py-0.5 text-[11px] font-bold text-[#765300]" data-testid="library-no-official-marker">No official version</p>}
        </div>
        {item.outcome === 'valid_after_structural_repair' && <p className="mt-2 inline-block w-fit rounded-full bg-[#fff1c7] px-2.5 py-0.5 text-[11px] font-bold text-[#765300]" data-testid="library-repair-marker">Contract repair applied (IDs only)</p>}
        <p className="mt-3 truncate text-xs text-ink/45">{item.filename} · {evidence} evidence · {versions} {versions === 1 ? 'version' : 'versions'}</p>
        <div className="mt-auto flex flex-wrap gap-2 pt-4">
          <Link className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white" href={href} onClick={() => onOpen(item)}>Open report</Link>
          <button className="action" disabled={evidence === 0} onClick={() => onSearchEvidence(item)} title={evidence === 0 ? 'This version has no evidence to search' : undefined} type="button">Search evidence</button>
          <Link className="action" href={`/videos/${encodeURIComponent(item.videoId)}`} onClick={() => onOpen(item)}>History</Link>
          <button className="action text-clay" disabled={busy} onClick={() => onDelete(item)} type="button">Delete</button>
        </div>
      </div>
    </article>
  );
}

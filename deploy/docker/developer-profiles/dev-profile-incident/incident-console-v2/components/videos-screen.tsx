// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { formatTimestamp } from '@/lib/time';

interface VideoItem { videoId: string; filename: string; uploadedAt: string | null; source: string | null; analysesWithReport: number; officialRunId: string | null }

/** Videos and their analysis history; `?filter=without-report` shows uploads with no successful analysis. */
export function VideosScreen() {
  const query = useSearchParams();
  const router = useRouter();
  const filter = query.get('filter') === 'without-report' ? 'without-report' : 'all';
  const page = Math.max(1, Number(query.get('page') || '1') || 1);
  const [state, setState] = useState<{ videos: VideoItem[]; totalItems: number; totalPages: number } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setState(null);
    void fetch(`/api/videos?filter=${filter}&page=${page}`, { cache: 'no-store' })
      .then(async (response) => {
        const payload = (await response.json()) as { videos?: VideoItem[]; pagination?: { totalItems: number; totalPages: number }; error?: string };
        if (!response.ok || !payload.videos) throw new Error(payload.error || 'Could not load videos');
        setState({ videos: payload.videos, totalItems: payload.pagination?.totalItems ?? 0, totalPages: payload.pagination?.totalPages ?? 0 });
      })
      .catch((cause: Error) => setError(cause.message));
  }, [filter, page]);

  const go = (next: Record<string, string>) => router.push(`/videos?${new URLSearchParams({ filter, page: '1', ...next })}`);

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-16 pt-2 lg:px-12">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-moss">Videos</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-[-0.04em]">Uploaded videos</h1>
      <p className="mt-2 text-sm text-ink/55">Each video keeps its full analysis history. Reports list only successful analyses.</p>
      <div className="mt-6 flex gap-2" role="tablist">
        {([['all', 'All videos'], ['without-report', 'Without a report']] as const).map(([value, label]) => (
          <button aria-selected={filter === value} className={`rounded-full px-4 py-2 text-xs font-semibold ${filter === value ? 'bg-ink text-white' : 'border border-ink/15'}`} key={value} onClick={() => go({ filter: value })} role="tab" type="button">{label}</button>
        ))}
      </div>
      {error && <p className="mt-6 text-clay">{error}</p>}
      {!state && !error && <div className="mt-6 h-40 animate-pulse rounded-2xl bg-white" role="status" />}
      {state && (
        <>
          <p className="mt-6 text-sm text-ink/50">{state.totalItems} {state.totalItems === 1 ? 'video' : 'videos'}</p>
          <ul className="mt-3 divide-y divide-ink/10 overflow-hidden rounded-2xl border border-ink/10 bg-white">
            {state.videos.map((video) => (
              <li className="flex flex-col gap-1 p-4 sm:flex-row sm:items-center sm:justify-between" key={video.videoId}>
                <div className="min-w-0">
                  <p className="truncate font-semibold">{video.filename}</p>
                  <p className="text-xs text-ink/50">Uploaded {formatTimestamp(video.uploadedAt)} · {video.analysesWithReport} {video.analysesWithReport === 1 ? 'report' : 'reports'}{video.officialRunId ? ' · official report selected' : ''}</p>
                </div>
                <Link className="shrink-0 text-xs font-semibold text-moss" href={`/videos/${encodeURIComponent(video.videoId)}`}>Analysis history →</Link>
              </li>
            ))}
            {!state.videos.length && <li className="p-6 text-sm italic text-ink/45">No videos match.</li>}
          </ul>
          {state.totalPages > 1 && (
            <div className="mt-4 flex items-center justify-center gap-3 text-sm">
              <button className="action" disabled={page <= 1} onClick={() => go({ page: String(page - 1) })} type="button">Previous</button>
              <span>Page {page} of {state.totalPages}</span>
              <button className="action" disabled={page >= state.totalPages} onClick={() => go({ page: String(page + 1) })} type="button">Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

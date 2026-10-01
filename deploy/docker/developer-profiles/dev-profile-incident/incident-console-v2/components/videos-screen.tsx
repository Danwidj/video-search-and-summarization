// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { formatTimestamp } from '@/lib/time';

interface VideoItem { videoId: string; filename: string; uploadedAt: string | null; source: string | null; analysesWithReport: number; officialRunId: string | null }
interface ReportPreview { videoId: string; title: string; description: string; incident_type: string; severity: number; isOfficial?: boolean; thumbnailUrl?: string }

/** Videos and their analysis history; `?filter=without-report` shows uploads with no successful analysis. */
export function VideosScreen() {
  const query = useSearchParams();
  const router = useRouter();
  const requested = query.get('filter');
  const filter = requested === 'without-report' || requested === 'awaiting-selection' ? requested : 'all';
  const page = Math.max(1, Number(query.get('page') || '1') || 1);
  const [state, setState] = useState<{ videos: VideoItem[]; reports: Record<string, ReportPreview>; totalItems: number; totalPages: number } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setState(null);
    void Promise.all([
      fetch(`/api/videos?filter=${filter}&page=${page}`, { cache: 'no-store' }).then(async (response) => {
        const payload = (await response.json()) as { videos?: VideoItem[]; pagination?: { totalItems: number; totalPages: number }; error?: string };
        if (!response.ok || !payload.videos) throw new Error(payload.error || 'Could not load videos');
        return payload;
      }),
      fetch('/api/reports?all=true', { cache: 'no-store' }).then(async (response) => {
        const payload = (await response.json()) as { reports?: ReportPreview[] };
        return response.ok && Array.isArray(payload.reports) ? payload.reports : [];
      }),
    ])
      .then(([videosPayload, reports]) => {
        const reportMap: Record<string, ReportPreview> = {};
        for (const report of reports) {
          const current = reportMap[report.videoId];
          if (!current || (report.isOfficial && !current.isOfficial)) reportMap[report.videoId] = report;
        }
        setState({ videos: videosPayload.videos!, reports: reportMap, totalItems: videosPayload.pagination?.totalItems ?? 0, totalPages: videosPayload.pagination?.totalPages ?? 0 });
      })
      .catch((cause: Error) => setError(cause.message));
  }, [filter, page]);

  const go = (next: Record<string, string>) => router.push(`/videos?${new URLSearchParams({ filter, page: '1', ...next })}`);

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-8 pt-2 lg:px-12">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-moss">Videos</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-[-0.04em]">Uploaded videos</h1>
      <p className="mt-2 text-sm text-ink/55">Each video keeps its full analysis history. Reports list only successful analyses.</p>
      <div className="mt-6 flex gap-2" role="tablist">
        {([['all', 'All videos'], ['awaiting-selection', 'Awaiting official report'], ['without-report', 'Without a report']] as const).map(([value, label]) => (
          <button aria-selected={filter === value} className={`rounded-full px-4 py-2 text-xs font-semibold ${filter === value ? 'bg-ink text-white' : 'border border-ink/15'}`} key={value} onClick={() => go({ filter: value })} role="tab" type="button">{label}</button>
        ))}
      </div>
      {error && <p className="mt-6 text-clay">{error}</p>}
      {!state && !error && <div className="mt-6 h-40 animate-pulse rounded-2xl bg-white" role="status" />}
      {state && (
        <>
          <p className="mt-6 text-sm text-ink/50">{state.totalItems} {state.totalItems === 1 ? 'video' : 'videos'}</p>
          <ul className="mt-3 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {state.videos.map((video) => <VideoCard key={video.videoId} report={state.reports[video.videoId]} video={video} />)}
            {!state.videos.length && <li className="rounded-2xl border border-dashed border-ink/15 bg-white p-8 text-sm italic text-ink/45 md:col-span-2 xl:col-span-3">No videos match.</li>}
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

function VideoCard({ video, report }: { video: VideoItem; report?: ReportPreview }) {
  const status = video.officialRunId ? 'Official report selected' : video.analysesWithReport ? 'Needs official report' : 'Needs analysis';
  const statusClass = video.officialRunId ? 'bg-signal/15 text-moss' : video.analysesWithReport ? 'bg-amber-400/20 text-ink/65' : 'bg-ink/8 text-ink/55';
  return <li className="overflow-hidden rounded-3xl border border-ink/10 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-panel">
    <Link className="block" href={`/videos/${encodeURIComponent(video.videoId)}`}>
      <VideoThumbnail status={status} videoId={video.videoId} />
      <div className="p-5">
        <div className="flex items-start justify-between gap-3"><span className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${statusClass}`}>{status}</span><span className="shrink-0 text-xs text-ink/40">{video.analysesWithReport} {video.analysesWithReport === 1 ? 'report' : 'reports'}</span></div>
        {report ? <><p className="mt-3 text-xs font-semibold uppercase tracking-[0.12em] text-moss">{report.incident_type}</p><h2 className="mt-2 line-clamp-2 text-xl font-semibold tracking-[-0.025em]">{report.title || `${report.incident_type} report`}</h2><p className="mt-3 line-clamp-3 text-sm leading-6 text-ink/60">{report.description || 'Successful analysis available for review.'}</p><div className="mt-4 flex items-center gap-2 text-xs text-ink/50"><span className="rounded bg-clay/10 px-2 py-1 font-semibold text-clay">Severity {report.severity}/5</span>{report.isOfficial && <span>Official report</span>}</div></> : <><h2 className="mt-4 text-xl font-semibold">{video.analysesWithReport ? 'Report awaiting selection' : 'No successful analysis yet'}</h2><p className="mt-3 text-sm leading-6 text-ink/55">{video.analysesWithReport ? 'A report is ready to review and select as official.' : 'Run an analysis to generate an incident report.'}</p></>}
        <p className="mt-4 truncate text-xs text-ink/40">{video.filename} · {formatTimestamp(video.uploadedAt)}</p><div className="mt-5 border-t border-ink/8 pt-4 text-xs font-semibold text-moss">Open analysis history →</div>
      </div>
    </Link>
  </li>;
}

function VideoThumbnail({ status, videoId }: { status: string; videoId: string }) {
  const [failed, setFailed] = useState(false);
  const [playbackUrl, setPlaybackUrl] = useState('');
  useEffect(() => { const controller = new AbortController(); fetch(`/api/videos/${encodeURIComponent(videoId)}/runs`, { cache: 'no-store', signal: controller.signal }).then(async (response) => { const payload = await response.json() as { video?: { playbackUrl?: string | null } }; if (response.ok && payload.video?.playbackUrl) setPlaybackUrl(payload.video.playbackUrl); }).catch(() => undefined); return () => controller.abort(); }, [videoId]);
  return <div className="relative aspect-video overflow-hidden bg-[#dfe3dc]" aria-label="Video preview">{playbackUrl && !failed ? <video autoPlay className="h-full w-full object-cover" controls={false} loop muted onError={() => setFailed(true)} playsInline preload="metadata" src={playbackUrl} /> : <><div className="absolute inset-0 bg-gradient-to-br from-white/35 to-transparent" /><div className="absolute inset-x-8 bottom-8 space-y-3"><div className="h-3 w-2/3 rounded-full bg-ink/15" /><div className="h-3 w-full rounded-full bg-ink/10" /><div className="h-3 w-4/5 rounded-full bg-ink/10" /></div><div className="absolute left-1/2 top-1/2 h-14 w-20 -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white/55 shadow-sm"><div className="absolute left-1/2 top-1/2 h-0 w-0 -translate-x-1/3 -translate-y-1/2 border-y-[10px] border-l-[16px] border-y-transparent border-l-ink/25" /></div></>}<span className="absolute left-3 top-3 rounded-full bg-white/90 px-3 py-1.5 text-xs font-semibold text-ink">{status}</span></div>;
}

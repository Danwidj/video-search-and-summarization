// SPDX-License-Identifier: Apache-2.0

'use client';

import { ReanalysisCard } from '@/components/reanalysis-card';
import { RunHistoryList, useRunHistory } from '@/components/run-history';
import { formatTimestamp } from '@/lib/time';

/** A video and its analysis history: the video is the parent; runs are its history. */
export function VideoHistoryScreen({ videoId }: { videoId: string }) {
  const { history, error, reload } = useRunHistory(videoId);
  if (error) return <div className="mx-auto max-w-3xl px-6 py-16 text-center"><p className="text-clay">{error}</p></div>;
  if (!history) return <div className="mx-auto max-w-7xl px-6 py-16" role="status"><div className="h-64 animate-pulse rounded-[2rem] bg-white" /></div>;
  const { video } = history;
  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-6 sm:px-6 lg:px-12">
      <article className="overflow-hidden rounded-[2rem] border border-ink/10 bg-white shadow-panel">
        <header className="border-b border-ink/10 bg-[#eef2e9] p-6 sm:p-8">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-moss">Video · analysis history</p>
          <h1 className="mt-3 break-all text-2xl font-semibold tracking-[-0.03em] sm:text-3xl">{video.filename}</h1>
          <p className="mt-2 text-sm text-ink/55">Uploaded {formatTimestamp(video.uploadedAt)}{video.source ? ` · ${video.source}` : ''} · {video.videoId}</p>
          <p className="mt-1 text-xs text-ink/45">{history.officialRunId ? 'An official report has been selected for this video.' : 'No official report has been selected for this video.'}</p>
        </header>
        <div className="grid gap-0 lg:grid-cols-[1fr_1fr]">
          <div className="border-b border-ink/10 p-6 lg:border-b-0 lg:border-r">
            {video.playbackUrl ? <video className="aspect-video w-full rounded-2xl bg-black object-contain" controls src={video.playbackUrl} /> : <p className="rounded-xl border border-dashed border-ink/15 p-6 text-sm text-ink/45">This video has no playable stored object.</p>}
            <h2 className="mt-6 text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Analyse again</h2>
            <div className="mt-2"><ReanalysisCard onAttempted={() => void reload()} videoId={videoId} /></div>
          </div>
          <div className="p-6">
            <h2 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Analysis history</h2>
            <p className="mt-1 text-xs text-ink/45">Every analysis of this video, newest first. Failed attempts are kept here with their reason; they never become reports.</p>
            <div className="mt-3"><RunHistoryList history={history} onChanged={() => void reload()} /></div>
          </div>
        </div>
      </article>
    </div>
  );
}

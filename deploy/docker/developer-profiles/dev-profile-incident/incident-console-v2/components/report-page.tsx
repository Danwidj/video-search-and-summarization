// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import { AdvancedReportTools } from '@/components/advanced-report-tools';
import { ReportPane } from '@/components/report-pane';
import { ReportTimeline } from '@/components/report-timeline';
import { ReportVersions } from '@/components/report-versions';
import { StructuredEditor } from '@/components/structured-editor';
import { reportHeading, type ReportView } from '@/lib/reports/report-view';
import type { RevisionSummary } from '@/lib/reports/revision';

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; report: ReportView };

/** revisionId null opens the incident's official version, else its newest. */
export function ReportPage({ videoId, revisionId }: { videoId: string; revisionId: number | null }) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [revisions, setRevisions] = useState<RevisionSummary[] | null>(null);
  const [revisionsError, setRevisionsError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  // The player's own length, a second guard (besides the recorded length) before jumping to a time.
  const [playerDuration, setPlayerDuration] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => (previous.status === 'ready' ? previous : { status: 'loading' }));
    fetch(`/api/reports/${encodeURIComponent(videoId)}${revisionId === null ? '' : `?revision=${revisionId}`}`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as { report?: ReportView; error?: string };
        if (!response.ok || !payload.report) throw new Error(payload.error || `Report request failed with HTTP ${response.status}`);
        setState({ status: 'ready', report: payload.report });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setState({ status: 'error', message: error instanceof Error ? error.message : 'Could not load the report' });
      });
    return () => controller.abort();
  }, [attempt, revisionId, videoId]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/reports/${encodeURIComponent(videoId)}/revisions`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as { revisions?: RevisionSummary[]; error?: string };
        if (!response.ok || !payload.revisions) throw new Error(payload.error || `Versions request failed with HTTP ${response.status}`);
        setRevisions(payload.revisions);
        setRevisionsError(null);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        setRevisionsError(cause instanceof Error ? cause.message : 'Could not load the versions');
      });
    return () => controller.abort();
  }, [videoId, attempt]);

  const seek = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    void video.play().catch(() => undefined);
  }, []);

  if (state.status === 'loading') {
    return (
      <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-6 sm:px-6 lg:px-12" role="status">
        <div className="animate-pulse overflow-hidden rounded-[2rem] border border-ink/10 bg-white shadow-panel">
          <div className="h-12 border-b border-ink/10 bg-ink/5" />
          <div className="grid gap-px bg-ink/10 lg:grid-cols-[minmax(0,26rem)_1fr_16rem]"><div className="aspect-video bg-ink/10" /><div className="bg-white" /><div className="bg-white" /></div>
          <div className="space-y-3 p-8"><div className="h-4 rounded bg-ink/10" /><div className="h-4 rounded bg-ink/10" /><div className="h-4 w-3/4 rounded bg-ink/10" /></div>
          <span className="sr-only">Loading incident report</span>
        </div>
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-clay">Report unavailable</p>
          <h1 className="mt-3 text-3xl font-semibold">We couldn&apos;t reopen this analysis.</h1>
          <p className="mt-4 text-sm leading-6 text-ink/60">{state.message}</p>
          <div className="mt-7 flex justify-center gap-3">
            <button className="rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
            <Link className="rounded-full border border-ink/15 px-5 py-3 text-sm font-semibold" href="/">New analysis</Link>
          </div>
        </div>
      </div>
    );
  }

  const { report } = state;
  const openVersion = (id: number) => { setEditing(false); router.push(`/reports/${encodeURIComponent(videoId)}?revision=${id}`); };
  const officialRevision = (revisions ?? []).find((revision) => revision.isOfficial);

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-2 sm:px-6 lg:px-12">
      <article className="report-sheet overflow-clip rounded-[2rem] border border-ink/10 bg-white shadow-panel" data-testid="report-page">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-ink/10 px-5 py-3 text-sm">
          <Link className="font-semibold text-moss" href="/reports" id="back-to-reports">← Reports</Link>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold" title={report.run.filename}>{reportHeading(report)}<span className="ml-2 font-normal text-ink/45">{report.run.filename}</span></h1>
        </div>

        <div className="sticky top-0 z-20 grid border-b border-ink/10 bg-white lg:h-[clamp(190px,30vh,300px)] lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)_16rem]" data-testid="report-band">
          <video
            className="aspect-video w-full bg-black object-contain lg:h-full"
            controls
            onLoadedMetadata={(event) => { const length = event.currentTarget.duration; setPlayerDuration(Number.isFinite(length) && length > 0 ? length : null); }}
            onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
            ref={videoRef}
            src={report.run.playbackUrl}
          />
          <div className="hidden min-h-0 overflow-hidden border-l border-ink/10 sm:flex sm:flex-col">
            <ReportTimeline currentTime={currentTime} onSeek={seek} structured={report.structured} videoSeconds={playerDuration ?? report.modelOutput?.timelineCheck.videoDurationSeconds ?? null} />
          </div>
          <div className="min-h-0 overflow-hidden border-l border-ink/10 max-lg:max-h-72">
            <ReportVersions currentRevisionId={report.revisionId} error={revisionsError} onOfficialChanged={() => setAttempt((value) => value + 1)} onOpen={openVersion} revisions={revisions} videoId={videoId} />
          </div>
        </div>

        {!officialRevision && revisions && (
          <p className="border-b border-[#e8d49a] bg-[#fffaf0] px-5 py-2 text-xs text-[#765300]" data-testid="official-status">
            No official version has been selected for this video. Star a version to make it official.
          </p>
        )}

        <ReportPane onSeek={seek} playerDuration={playerDuration} report={report} />

        {editing && (
          <section className="border-t border-ink/10 px-5 py-5 sm:px-8">
            <StructuredEditor onCancel={() => setEditing(false)} onSaved={(id) => { setEditing(false); openVersion(id); }} report={report} />
          </section>
        )}

        <div className="sticky bottom-0 z-20 flex items-center justify-between gap-3 border-t border-ink/10 bg-white/95 px-5 py-3 text-sm backdrop-blur">
          <span className="text-ink/60"><b>v{report.revision.revisionNo}</b> {report.official.isOfficial ? 'is the official version' : 'is not the official version'}</span>
          <button className="rounded-full bg-moss px-5 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={editing} onClick={() => setEditing(true)} type="button">Edit from v{report.revision.revisionNo}</button>
        </div>
      </article>
      <AdvancedReportTools report={report} />
    </div>
  );
}

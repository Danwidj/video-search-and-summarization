// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { IncidentReport } from '@/components/incident-report';
import { AdvancedReportTools } from '@/components/advanced-report-tools';
import type { AnalysisReport } from '@/lib/analysis/schema';

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; report: AnalysisReport };

export function ReportScreen({ videoId, modelRunId }: { videoId: string; modelRunId: string }) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetch(`/api/reports/${encodeURIComponent(videoId)}?run=${encodeURIComponent(modelRunId)}`, {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = (await response.json()) as { report?: AnalysisReport; error?: string };
        if (!response.ok || !payload.report) throw new Error(payload.error || `Report request failed with HTTP ${response.status}`);
        setState({ status: 'ready', report: payload.report });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setState({ status: 'error', message: error instanceof Error ? error.message : 'Could not load the report' });
      });
    return () => controller.abort();
  }, [attempt, modelRunId, videoId]);

  if (state.status === 'loading') {
    return (
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-12" role="status">
        <div className="animate-pulse rounded-[2rem] border border-ink/10 bg-white p-8 shadow-panel">
          <div className="h-3 w-32 rounded bg-ink/10" />
          <div className="mt-5 h-10 w-2/3 rounded bg-ink/10" />
          <div className="mt-10 grid gap-6 lg:grid-cols-2">
            <div className="aspect-video rounded-2xl bg-ink/10" />
            <div className="space-y-3"><div className="h-4 rounded bg-ink/10" /><div className="h-4 rounded bg-ink/10" /><div className="h-4 w-3/4 rounded bg-ink/10" /></div>
          </div>
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

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-6 sm:px-6 lg:px-12">
      <IncidentReport onNewAnalysis={() => { window.location.href = '/'; }} report={state.report} />
      <AdvancedReportTools report={state.report} />
    </div>
  );
}

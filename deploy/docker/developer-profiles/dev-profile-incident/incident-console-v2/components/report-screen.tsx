// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useTransition, type ReactNode } from 'react';

import { AdvancedReportTools } from '@/components/advanced-report-tools';
import { AppHeader } from '@/components/app-header';
import { IncidentReport } from '@/components/incident-report';
import type { ReportView } from '@/lib/reports/report-view';

/** The frame around every state of the report page (loaded, loading, missing, failed). */
export function ReportWorkspace({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="reports" subtitle="Report workspace" />
      <div className="print-hidden mx-auto max-w-[1500px] px-6 pt-1 lg:px-12"><Link className="text-sm font-semibold text-moss" href="/reports" id="back-to-reports">← Back to all reports</Link></div>
      {children}
    </main>
  );
}

/**
 * The report the server loaded. After an edit or an official-report change,
 * router.refresh() renders the page on the server again with the stored state.
 */
export function ReportScreen({ report }: { report: ReportView }) {
  const router = useRouter();
  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-6 sm:px-6 lg:px-12">
      <IncidentReport key={`${report.modelRunId}-${report.review.editedAt ?? ''}`} onEdited={() => router.refresh()} onNewAnalysis={() => { window.location.href = '/'; }} report={report} />
      <AdvancedReportTools report={report} />
    </div>
  );
}

export function ReportLoading() {
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

/** A failed load; "Try again" renders the page on the server again (and resets the error boundary, when one caught it). */
export function ReportUnavailable({ message, reset }: { message: string; reset?: () => void }) {
  const router = useRouter();
  const [retrying, startRetry] = useTransition();
  return (
    <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-clay">Report unavailable</p>
        <h1 className="mt-3 text-3xl font-semibold">We couldn&apos;t reopen this analysis.</h1>
        <p className="mt-4 text-sm leading-6 text-ink/60">{message}</p>
        <div className="mt-7 flex justify-center gap-3">
          <button className="rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" disabled={retrying} onClick={() => startRetry(() => { router.refresh(); reset?.(); })} type="button">Try again</button>
          <Link className="rounded-full border border-ink/15 px-5 py-3 text-sm font-semibold" href="/">New analysis</Link>
        </div>
      </div>
    </div>
  );
}

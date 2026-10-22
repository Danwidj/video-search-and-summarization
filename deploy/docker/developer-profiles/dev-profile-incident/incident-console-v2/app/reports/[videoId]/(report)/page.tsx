// SPDX-License-Identifier: Apache-2.0

// The report page is a Server Component: it loads the report through the
// getReport use case (as GET /api/reports/[videoId] does) and signs the
// playback URL here, so the browser receives the finished ReportView. The
// (report) route group keeps loading.tsx, error.tsx and not-found.tsx to this
// page, away from the sibling compare/ page.

import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ReportScreen, ReportUnavailable, ReportWorkspace } from '@/components/report-screen';
import { getDbAdapters } from '@/lib/adapters/supabase';
import { getReport } from '@/lib/application/reports';
import { getServiceConfiguration } from '@/lib/env';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import type { ReportView } from '@/lib/reports/report-view';

// Review state changes between visits: render on every request, never from a cache.
export const dynamic = 'force-dynamic';

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ videoId: string }>;
  searchParams: Promise<{ run?: string | string[] }>;
}) {
  const [{ videoId }, { run }] = await Promise.all([params, searchParams]);
  const modelRunId = Array.isArray(run) ? run[0] : run;
  if (!modelRunId) return <ReportWorkspace><MissingRun /></ReportWorkspace>;

  let report: ReportView | null;
  try {
    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);
    report = await getReport(incidents, { videoId, modelRunId }, (storageKey) => createR2PlaybackUrl(config, storageKey));
  } catch (error) {
    // Show the reason (unconfigured store, unreachable PostgREST, unsigned video) as the API route does;
    // error.tsx only sees a redacted message in production.
    return <ReportWorkspace><ReportUnavailable message={error instanceof Error ? error.message : 'Could not load the report'} /></ReportWorkspace>;
  }
  if (!report) notFound();

  return <ReportWorkspace><ReportScreen report={report} /></ReportWorkspace>;
}

function MissingRun() {
  return (
    <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
      <div><h1 className="text-3xl font-semibold">This report link is incomplete.</h1><p className="mt-3 text-ink/55">The model-run identifier is missing.</p><Link className="mt-6 inline-block rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/">Start a new analysis</Link></div>
    </div>
  );
}

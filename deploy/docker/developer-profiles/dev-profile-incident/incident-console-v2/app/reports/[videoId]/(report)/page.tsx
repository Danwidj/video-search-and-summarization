// SPDX-License-Identifier: Apache-2.0

// The report page is a Server Component: it loads the report through the
// getReport use case (load-report.ts, as GET /api/reports/[videoId] does) and
// signs the playback URL on the server, so the browser receives the finished
// ReportView. The (report) route group keeps loading.tsx, error.tsx and
// not-found.tsx to this page, away from the sibling compare/ page.

import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ReportScreen, ReportUnavailable, ReportWorkspace } from '@/components/report-screen';

import { loadReportPage } from './load-report';

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
  const load = await loadReportPage(videoId, run);
  if (load.kind === 'not-found') notFound();

  return (
    <ReportWorkspace>
      {load.kind === 'missing-run' ? <MissingRun /> : load.kind === 'failed' ? <ReportUnavailable message={load.message} /> : <ReportScreen report={load.report} />}
    </ReportWorkspace>
  );
}

function MissingRun() {
  return (
    <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
      <div><h1 className="text-3xl font-semibold">This report link is incomplete.</h1><p className="mt-3 text-ink/55">The model-run identifier is missing.</p><Link className="mt-6 inline-block rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/">Start a new analysis</Link></div>
    </div>
  );
}

// SPDX-License-Identifier: Apache-2.0

import Link from 'next/link';

import { AppHeader } from '@/components/app-header';
import { ReportScreen } from '@/components/report-screen';

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ videoId: string }>;
  searchParams: Promise<{ run?: string }>;
}) {
  const [{ videoId }, { run }] = await Promise.all([params, searchParams]);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="reports" subtitle="Report workspace" />
      <div className="print-hidden mx-auto max-w-[1500px] px-6 pt-1 lg:px-12"><Link className="text-sm font-semibold text-moss" href="/reports" id="back-to-reports">← Back to all reports</Link></div>
      {run ? <ReportScreen modelRunId={run} videoId={videoId} /> : <MissingRun />}
    </main>
  );
}

function MissingRun() {
  return (
    <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
      <div><h1 className="text-3xl font-semibold">This report link is incomplete.</h1><p className="mt-3 text-ink/55">The model-run identifier is missing.</p><Link className="mt-6 inline-block rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/">Start a new analysis</Link></div>
    </div>
  );
}

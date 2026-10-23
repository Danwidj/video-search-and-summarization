// SPDX-License-Identifier: Apache-2.0

import Link from 'next/link';

import { AppHeader } from '@/components/app-header';
import { ReportScreen } from '@/components/report-screen';

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ videoId: string }>;
  searchParams: Promise<{ revision?: string }>;
}) {
  const [{ videoId }, { revision }] = await Promise.all([params, searchParams]);

  const parsed = revision === undefined ? null : Number(revision);
  const revisionId = parsed !== null && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="reports" subtitle="Report workspace" />
      <div className="print-hidden mx-auto max-w-[1500px] px-6 pt-1 lg:px-12"><Link className="text-sm font-semibold text-moss" href="/reports" id="back-to-reports">← Back to all reports</Link></div>
      <ReportScreen revisionId={revisionId} videoId={videoId} />
    </main>
  );
}

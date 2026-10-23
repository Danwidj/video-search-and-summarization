// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/components/app-header';
import { ReportPage as ReportView } from '@/components/report-page';

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
      <ReportView revisionId={revisionId} videoId={videoId} />
    </main>
  );
}

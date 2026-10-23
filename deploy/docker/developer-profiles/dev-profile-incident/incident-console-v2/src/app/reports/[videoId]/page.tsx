// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/components/app-header';
import { ReportPage as ReportView } from '@/components/report-page';
import { parseStartSeconds } from '@/lib/library/search';

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ videoId: string }>;
  searchParams: Promise<{ revision?: string; t?: string }>;
}) {
  const [{ videoId }, { revision, t }] = await Promise.all([params, searchParams]);

  const parsed = revision === undefined ? null : Number(revision);
  const revisionId = parsed !== null && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
  const startSeconds = parseStartSeconds(t);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="library" subtitle="Report workspace" />
      <ReportView revisionId={revisionId} startSeconds={startSeconds} videoId={videoId} />
    </main>
  );
}

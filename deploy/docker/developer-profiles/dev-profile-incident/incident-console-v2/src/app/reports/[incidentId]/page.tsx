// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/sections/shell/components/AppHeader';
import { ReportPage as ReportView } from '@/sections/reports/components/ReportPage';
import { parseStartSeconds } from '@/lib/library/search';

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ incidentId: string }>;
  searchParams: Promise<{ revision?: string; camera?: string; t?: string }>;
}) {
  const [{ incidentId }, { revision, camera, t }] = await Promise.all([params, searchParams]);

  const parsed = revision === undefined ? null : Number(revision);
  const revisionId = parsed !== null && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
  const startSeconds = parseStartSeconds(t);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="library" subtitle="Report workspace" />
      <ReportView camera={camera?.trim() || null} revisionId={revisionId} startSeconds={startSeconds} incidentId={incidentId} />
    </main>
  );
}

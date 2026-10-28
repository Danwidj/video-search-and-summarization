// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { ReportView } from '@/modules/reports/domain/report-view';
import type { RevisionSummary } from '@/modules/reports/domain/revision';
import { ReanalysisCard } from '@/sections/analysis/components/ReanalysisCard';
import { RunHistoryList } from '@/sections/analysis/components/RunHistory';
import { useRunHistory } from '@/sections/analysis/hooks/use-run-history';

export function AdvancedReportTools({ report }: { report: ReportView }) {
  return (
    <>
      <section className="print-hidden mt-6 ">
        <AnalysisHistoryCard report={report} />
      </section>
      <RunComparisonLauncher report={report} />
    </>
  );
}

function RunComparisonLauncher({ report }: { report: ReportView }) {
  const [other, setOther] = useState<RevisionSummary | null>(null);
  useEffect(() => {
    void fetch(`/api/reports/${encodeURIComponent(report.videoId)}/revisions`)
      .then((r) => r.json())
      .then((p: { revisions?: RevisionSummary[] }) => {
        setOther((p.revisions || []).find((item) => item.kind === 'ai' && item.revisionId !== report.revisionId) || null);
      })
      .catch(() => setOther(null));
  }, [report]);
  if (!other) return null;
  return (
    <div className="print-hidden mt-6">
      <Alert className="border-signal/25 bg-signal/5 p-5">
        <AlertTitle className="text-sm font-bold">Another AI version is available for this video.</AlertTitle>
        <AlertDescription className="mt-1">
          <Link
            className="font-bold text-moss hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-hidden"
            href={`/reports/${encodeURIComponent(report.videoId)}/compare?left=${report.revisionId}&right=${other.revisionId}`}
          >
            Compare versions side by side →
          </Link>
        </AlertDescription>
      </Alert>
    </div>
  );
}

/** Re-analysis of this video plus its analysis history. */
function AnalysisHistoryCard({ report }: { report: ReportView }) {
  const { history, error, reload } = useRunHistory(report.videoId);
  return (
    <Card className="rounded-3xl border border-ink/10 bg-white p-6 shadow-xs" data-testid="analysis-history-card">
      <p className="font-mono text-xs uppercase tracking-[.15em] text-moss">Analysis</p>
      <h2 className="mt-2 text-xl font-semibold">Analyse this video again</h2>
      <div className="mt-3">
        <ReanalysisCard onAttempted={() => void reload()} videoId={report.videoId} />
      </div>
      <div className="mt-6 border-t border-ink/10 pt-5">
        <p className="text-xs font-bold uppercase tracking-wider text-ink-caption">Analysis history for this video</p>
        {error && <p className="mt-2 text-xs text-clay">{error}</p>}
        {history ? (
          <div className="mt-2">
            <RunHistoryList compact currentRunId={report.modelRunId} history={history} />
          </div>
        ) : (
          !error && (
            <div className="mt-2 space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-32" />
            </div>
          )
        )}
        <div className="mt-4 flex flex-wrap gap-4 text-xs font-semibold">
          <Link
            className="text-moss hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-hidden"
            href={`/videos/${encodeURIComponent(report.videoId)}`}
          >
            Full analysis history →
          </Link>
        </div>
      </div>
    </Card>
  );
}

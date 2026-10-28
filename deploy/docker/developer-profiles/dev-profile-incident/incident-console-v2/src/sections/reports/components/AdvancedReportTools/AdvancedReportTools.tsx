// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { ReportView } from '@/modules/reports/domain/report-view';
import { ReanalysisCard } from '@/sections/analysis/components/ReanalysisCard';
import { RunHistoryList } from '@/sections/analysis/components/RunHistory';
import { useRunHistory } from '@/sections/analysis/hooks/use-run-history';

export function AdvancedReportTools({ report }: { report: ReportView }) {
  return (
    <section className="print-hidden mt-6">
      <AnalysisHistoryCard report={report} />
    </section>
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
        <p className="text-xs font-bold uppercase tracking-wider text-ink/40">Analysis history for this video</p>
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

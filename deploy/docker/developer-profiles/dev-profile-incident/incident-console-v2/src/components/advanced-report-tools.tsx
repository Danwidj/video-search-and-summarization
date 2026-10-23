// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { ReanalysisCard } from '@/components/reanalysis-card';
import { RunHistoryList, useRunHistory } from '@/components/run-history';
import type { ReportView } from '@/modules/reports/domain/report-view';
import type { RevisionSummary } from '@/modules/reports/domain/revision';

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
  useEffect(() => { void fetch(`/api/reports/${encodeURIComponent(report.videoId)}/revisions`).then((r) => r.json()).then((p: { revisions?: RevisionSummary[] }) => { setOther((p.revisions || []).find((item) => item.kind === 'ai' && item.revisionId !== report.revisionId) || null); }).catch(() => setOther(null)); }, [report]);
  if (!other) return null;
  return <div className="print-hidden mt-6 rounded-2xl border border-signal/25 bg-signal/5 p-5 text-sm"><strong>Another AI version is available for this video.</strong><Link className="ml-3 font-bold text-moss" href={`/reports/${encodeURIComponent(report.videoId)}/compare?left=${report.revisionId}&right=${other.revisionId}`}>Compare versions side by side →</Link></div>;
}

/** Re-analysis of this video plus its analysis history. */
function AnalysisHistoryCard({ report }: { report: ReportView }) {
  const { history, error, reload } = useRunHistory(report.videoId);
  return (
    <section className="rounded-3xl border border-ink/10 bg-white p-6" data-testid="analysis-history-card">
      <p className="font-mono text-xs uppercase tracking-[.15em] text-moss">Analysis</p>
      <h2 className="mt-2 text-xl font-semibold">Analyse this video again</h2>
      <div className="mt-3"><ReanalysisCard onAttempted={() => void reload()} videoId={report.videoId} /></div>
      <div className="mt-6 border-t border-ink/10 pt-5">
        <p className="text-xs font-bold uppercase tracking-wider text-ink/40">Analysis history for this video</p>
        {error && <p className="mt-2 text-xs text-clay">{error}</p>}
        {history ? <div className="mt-2"><RunHistoryList compact currentRunId={report.modelRunId} history={history} /></div> : !error && <p className="mt-2 text-xs text-ink/45">Loading…</p>}
        <div className="mt-4 flex flex-wrap gap-4 text-xs font-semibold">
          <Link className="text-moss" href={`/videos/${encodeURIComponent(report.videoId)}`}>Full analysis history →</Link>
        </div>
      </div>
    </section>
  );
}

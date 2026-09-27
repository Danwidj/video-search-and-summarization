// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { describeCode, OUTCOME_DESCRIPTIONS, OUTCOME_LABELS, type RunOutcome } from '@/lib/runs/labels';
import type { RunHistoryEntry, VideoRunHistory } from '@/lib/runs/types';
import { formatTimestamp } from '@/lib/time';

const OUTCOME_STYLES: Record<RunOutcome, string> = {
  valid_first_pass: 'bg-signal/15 text-moss',
  valid_after_structural_repair: 'bg-[#fff1c7] text-[#765300]',
  contract_failed: 'bg-[#ffe8df] text-[#9b3518]',
  request_failed: 'bg-[#ffe8df] text-[#9b3518]',
  legacy: 'bg-ink/5 text-ink/60',
};

export function useRunHistory(videoId: string) {
  const [history, setHistory] = useState<VideoRunHistory | null>(null);
  const [error, setError] = useState('');
  const reload = useCallback(() => {
    setError('');
    return fetch(`/api/videos/${encodeURIComponent(videoId)}/runs`, { cache: 'no-store' })
      .then(async (response) => {
        const payload = (await response.json()) as VideoRunHistory & { error?: string };
        if (!response.ok) throw new Error(payload.error || 'Could not load the analysis history');
        setHistory(payload);
      })
      .catch((cause: Error) => setError(cause.message));
  }, [videoId]);
  useEffect(() => { void reload(); }, [reload]);
  return { history, error, reload };
}

export function OutcomeBadge({ outcome, inferred = false }: { outcome: RunOutcome; inferred?: boolean }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-[11px] font-bold ${OUTCOME_STYLES[outcome]}`} data-outcome={outcome} title={OUTCOME_DESCRIPTIONS[outcome]}>
      {OUTCOME_LABELS[outcome]}{inferred && outcome !== 'legacy' ? ' (not recorded)' : ''}
    </span>
  );
}

/** A video's analysis history. Failed attempts are listed with their reason and never as reports. */
export function RunHistoryList({ history, currentRunId, compact = false }: { history: VideoRunHistory; currentRunId?: string; compact?: boolean }) {
  const runs = compact ? history.runs.slice(0, 6) : history.runs;
  const { counts } = history;
  return (
    <div data-testid="run-history">
      <p className="text-xs text-ink/50">
        {counts.attempts} {counts.attempts === 1 ? 'analysis' : 'analyses'} · {counts.withReport} with a report
        {counts.valid_after_structural_repair ? ` · ${counts.valid_after_structural_repair} IDs repaired` : ''}
        {counts.contract_failed ? ` · ${counts.contract_failed} contract failed` : ''}
        {counts.request_failed ? ` · ${counts.request_failed} request failed` : ''}
        {counts.legacy ? ` · ${counts.legacy} earlier` : ''}
      </p>
      <ol className="mt-3 space-y-2">
        {runs.map((run) => <RunRow current={run.modelRunId === currentRunId} key={run.modelRunId} run={run} videoId={history.video.videoId} />)}
      </ol>
      {compact && history.runs.length > runs.length && <p className="mt-2 text-xs text-ink/45">{history.runs.length - runs.length} more in the full history.</p>}
    </div>
  );
}

function RunRow({ run, videoId, current }: { run: RunHistoryEntry; videoId: string; current: boolean }) {
  const failed = run.outcome === 'contract_failed' || run.outcome === 'request_failed';
  return (
    <li className={`rounded-xl border p-3 text-xs ${current ? 'border-signal bg-signal/5' : 'border-ink/10 bg-white'}`} data-run={run.modelRunId}>
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-ink">{run.model}</strong>
        <OutcomeBadge inferred={run.outcomeInferred} outcome={run.outcome} />
        {run.isOfficial && <span className="rounded-full bg-moss px-2.5 py-0.5 text-[11px] font-bold text-white">Official report</span>}
        {run.source === 'shared' && <span className="rounded-full bg-ink/5 px-2 py-0.5 text-[11px] text-ink/55">batch run</span>}
        {current && <span className="text-[11px] font-semibold text-moss">viewing</span>}
      </div>
      <p className="mt-1 text-ink/50">
        {formatTimestamp(run.attemptedAt)}
        {run.report ? ` · ${run.report.type ?? 'unclassified'} · severity ${run.report.severityLevel ?? '—'}/5` : ''}
        {run.reportRemoved ? ' · report deleted' : ''}
        {failed ? ' · no report' : ''}
      </p>
      {run.additionalInstruction && <p className="mt-1 text-ink/55">Additional instruction: “{run.additionalInstruction}”</p>}
      {run.failure && (
        <div className="mt-2 rounded-lg bg-[#fff6f2] p-2 text-[#8c3d25]">
          <p className="font-semibold">{run.outcome === 'request_failed' ? describeCode(run.failure.code) : 'Contract violations'}</p>
          {run.outcome === 'contract_failed' && (
            <ul className="mt-1 list-disc pl-4">{run.failure.violations.map((violation, index) => <li key={index}>{describeCode(violation.code)}: {violation.message}</li>)}</ul>
          )}
          {run.outcome === 'request_failed' && run.failure.message && <p className="mt-1 text-[#8c3d25]/80">{run.failure.message}</p>}
        </div>
      )}
      {run.repair && (
        <p className="mt-2 text-[#765300]">Contract repair applied (IDs only) · {run.repair.ruleSet}: {run.repair.operations.map((operation) => String(operation.op)).join(', ')}</p>
      )}
      {run.report && !current && (
        <Link className="mt-2 inline-block font-semibold text-moss" href={`/reports/${encodeURIComponent(videoId)}?run=${encodeURIComponent(run.modelRunId)}`}>Open report →</Link>
      )}
    </li>
  );
}

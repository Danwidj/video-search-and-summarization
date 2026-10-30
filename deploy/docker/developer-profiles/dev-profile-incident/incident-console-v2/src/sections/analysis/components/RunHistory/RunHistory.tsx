// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { OfficialControls } from '@/sections/reports/components/OfficialControls';
import { describeCode, OUTCOME_DESCRIPTIONS, OUTCOME_LABELS, type RunOutcome } from '@/modules/videos/domain/run-labels';
import type { RunHistoryEntry, VideoRunHistory } from '@/modules/videos/domain/run-types';
import { formatTimestamp } from '@/lib/time';

const OUTCOME_CONFIG: Record<RunOutcome, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }> = {
  valid_first_pass: {
    variant: 'outline',
    className: 'border-primary/40 bg-primary/10 text-primary font-bold',
  },
  valid_after_structural_repair: {
    variant: 'outline',
    className: 'border-amber-500/40 bg-amber-500/10 text-amber-800 font-bold',
  },
  contract_failed: {
    variant: 'destructive',
    className: 'font-bold',
  },
  request_failed: {
    variant: 'destructive',
    className: 'font-bold',
  },
  legacy: {
    variant: 'secondary',
    className: 'font-bold text-muted-foreground',
  },
};

export function OutcomeBadge({ outcome, inferred = false }: { outcome: RunOutcome; inferred?: boolean }) {
  const conf = OUTCOME_CONFIG[outcome];
  return (
    <Badge className={conf.className} data-outcome={outcome} title={OUTCOME_DESCRIPTIONS[outcome]} variant={conf.variant}>
      {OUTCOME_LABELS[outcome]}
      {inferred && outcome !== 'legacy' ? ' (not recorded)' : ''}
    </Badge>
  );
}

/** A video's analysis history. Failed attempts are listed with their reason and never as reports. */
export function RunHistoryList({
  history,
  currentRunId,
  compact = false,
  onChanged,
}: {
  history: VideoRunHistory;
  currentRunId?: string | null;
  compact?: boolean;
  onChanged?: () => void;
}) {
  const runs = compact ? history.runs.slice(0, 6) : history.runs;
  const { counts } = history;
  return (
    <div data-testid="run-history">
      <p className="text-xs text-muted-foreground">
        {counts.attempts} analysis {counts.attempts === 1 ? 'run' : 'runs'} · {counts.withReport} produced a report (edits add further
        versions, not runs)
        {counts.valid_after_structural_repair ? ` · ${counts.valid_after_structural_repair} IDs repaired` : ''}
        {counts.contract_failed ? ` · ${counts.contract_failed} contract failed` : ''}
        {counts.request_failed ? ` · ${counts.request_failed} request failed` : ''}
        {counts.legacy ? ` · ${counts.legacy} earlier` : ''}
      </p>
      <ol className="mt-3 space-y-2">
        {runs.map((run) => (
          <RunRow
            current={run.modelRunId === currentRunId}
            hasOfficial={history.officialRevisionId !== null}
            key={run.modelRunId}
            onChanged={onChanged}
            run={run}
            videoId={history.video.videoId}
          />
        ))}
      </ol>
      {compact && history.runs.length > runs.length && (
        <p className="mt-2 text-xs text-muted-foreground">{history.runs.length - runs.length} more in the full history.</p>
      )}
    </div>
  );
}

function RunRow({
  run,
  videoId,
  current,
  hasOfficial,
  onChanged,
}: {
  run: RunHistoryEntry;
  videoId: string;
  current: boolean;
  hasOfficial: boolean;
  onChanged?: () => void;
}) {
  const failed = run.outcome === 'contract_failed' || run.outcome === 'request_failed';
  return (
    <li
      className={`rounded-xl border p-4 text-xs transition-colors ${current ? 'border-primary bg-primary/5' : 'border-border bg-card text-card-foreground'}`}
      data-run={run.modelRunId}
    >
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-foreground">{run.model}</strong>
        <OutcomeBadge inferred={run.outcomeInferred} outcome={run.outcome} />
        {run.isOfficial && (
          <Badge className="text-[11px] font-bold" variant="default">
            Official report
          </Badge>
        )}
        {run.source === 'shared' && (
          <Badge className="text-[11px]" variant="secondary">
            batch run
          </Badge>
        )}
        {current && (
          <Badge className="border-primary/30 text-[11px] font-semibold text-primary" variant="outline">
            viewing
          </Badge>
        )}
      </div>
      <p className="mt-1 text-muted-foreground">
        {formatTimestamp(run.attemptedAt)}
        {run.revision ? ` · ${run.revision.type ?? 'unclassified'} · severity ${run.revision.severityLevel ?? '—'}/5` : ''}
        {failed ? ' · no report' : ''}
      </p>
      {run.additionalInstruction && <p className="mt-1 text-muted-foreground">Additional instruction: “{run.additionalInstruction}”</p>}
      {run.failure && (
        <Alert className="mt-2 text-xs" variant="destructive">
          <AlertTitle className="font-semibold">
            {run.outcome === 'request_failed' ? describeCode(run.failure.code) : 'Contract violations'}
          </AlertTitle>
          <AlertDescription>
            {run.outcome === 'contract_failed' && (
              <ul className="mt-1 list-disc pl-4">
                {run.failure.violations.map((violation) => (
                  <li key={`${violation.code}:${violation.message}`}>
                    {describeCode(violation.code)}: {violation.message}
                  </li>
                ))}
              </ul>
            )}
            {run.outcome === 'request_failed' && run.failure.message && <p className="mt-1 text-destructive/80">{run.failure.message}</p>}
          </AlertDescription>
        </Alert>
      )}
      {run.enrichmentIssues && run.enrichmentIssues.length > 0 && (
        <p className="mt-2 text-muted-foreground" data-testid="enrichment-issues">
          Unscored model output: {run.enrichmentIssues.map(describeCode).join('; ')}
        </p>
      )}
      {run.repair && (
        <p className="mt-2 text-amber-800">
          Contract repair applied (IDs only) · {run.repair.ruleSet}:{' '}
          {run.repair.operations.map((operation) => String(operation.op)).join(', ')}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {run.revision && !current && (
          <Button asChild className="h-auto p-0 font-semibold text-primary" size="sm" variant="link">
            <Link href={`/reports/${encodeURIComponent(videoId)}?revision=${run.revision.revisionId}`}>Open report →</Link>
          </Button>
        )}
        {run.revision && onChanged && (
          <OfficialControls
            hasOfficial={hasOfficial}
            isOfficial={Boolean(run.isOfficial)}
            onChanged={onChanged}
            revisionId={run.revision.revisionId}
            videoId={videoId}
          />
        )}
      </div>
    </li>
  );
}

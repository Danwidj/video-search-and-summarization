// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Check, Loader2, Video, X } from 'lucide-react';
import { cn } from 'cn';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { BATCH_STAGES, type BatchItem, type BatchStatus, batchStageLabels, itemProgress } from '@/sections/analysis/batch-upload';
import { formatElapsed } from '@/sections/analysis/stage-progress';

const statusLabel: Record<BatchStatus, string> = {
  queued: 'Queued',
  uploading: 'Uploading',
  converting: 'Converting',
  analysing: 'Analysing',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

function announcement(item: BatchItem): string {
  switch (item.status) {
    case 'failed':
      return `${item.name} stopped at ${batchStageLabels[item.failedAt ?? 'uploading']}: ${item.error ?? 'the step failed'}.`;
    case 'done':
      return `${item.name}: report ready.`;
    case 'queued':
      return `${item.name}: queued.`;
    case 'cancelled':
      return `${item.name}: cancelled before it was stored.`;
    case 'uploading':
      return `${item.name}: uploading${item.uploadProgress > 0 ? ` (${item.uploadProgress}%)` : ''}.`;
    default:
      return `${item.name}: ${batchStageLabels[item.status]}.`;
  }
}

/** The message as a sentence, so what follows it reads on. */
const sentence = (text: string | null): string => (text && !/[.!?]$/.test(text) ? `${text}.` : (text ?? ''));

/** Seconds the file has spent in its current step; restarts when the step changes and ticks only while it runs. */
function useStepSeconds(status: BatchStatus): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    setSeconds(0);
    if (status !== 'converting' && status !== 'analysing') return;
    const started = Date.now();
    const timer = setInterval(() => setSeconds((Date.now() - started) / 1000), 1000);
    return () => clearInterval(timer);
  }, [status]);
  return seconds;
}

export interface BatchFileRowProps {
  item: BatchItem;
  onRemove(key: string): void;
}

export function BatchFileRow({ item, onRemove }: BatchFileRowProps) {
  const progress = itemProgress(item);
  const reached = item.status === 'failed' ? (item.failedAt ?? 'uploading') : item.status;
  const stageIndex = BATCH_STAGES.indexOf(reached as (typeof BATCH_STAGES)[number]);
  const stepSeconds = useStepSeconds(item.status);
  return (
    <li className="rounded-2xl border border-border bg-card p-3.5 sm:p-4" data-file={item.name} data-status={item.status}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
            <Video className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="break-all text-sm font-semibold">{item.name}</p>
            <p className="text-xs text-muted-foreground">{(item.size / 1024 / 1024).toFixed(1)} MB</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge
            className={cn(item.status === 'failed' && 'border-destructive/30 bg-destructive/10 text-destructive')}
            variant={item.status === 'done' ? 'default' : 'secondary'}
          >
            {statusLabel[item.status]}
          </Badge>
          {item.status === 'queued' && (
            <Button
              aria-label={`Remove ${item.name} from the queue`}
              onClick={() => onRemove(item.key)}
              size="sm"
              type="button"
              variant="ghost"
            >
              <X data-icon="inline-start" />
              Remove
            </Button>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <Progress
          aria-label={`Progress for ${item.name}`}
          aria-valuenow={progress}
          aria-valuetext={announcement(item)}
          className={cn('h-1.5 w-full', item.status === 'failed' && '[&>div]:bg-destructive')}
          value={progress}
        />
        <span className="font-mono text-xs font-semibold">{progress}%</span>
      </div>

      <ol className="mt-3 grid grid-cols-3 gap-1.5" aria-label={`Stages for ${item.name}`}>
        {BATCH_STAGES.map((stage, index) => {
          const done = item.status === 'done' || (stageIndex !== -1 && index < stageIndex);
          const failed = item.status === 'failed' && index === stageIndex;
          const active = item.status === stage;
          return (
            <li
              aria-current={active ? 'step' : undefined}
              className={cn(
                'flex flex-col gap-1 rounded-xl border p-2 text-[11px]',
                done && 'border-primary/30 bg-primary/10 text-primary',
                active && 'border-primary bg-primary/5 font-medium text-primary shadow-xs',
                failed && 'border-destructive/40 bg-destructive/10 text-destructive',
                !done && !active && !failed && 'border-border bg-card/40 text-muted-foreground',
              )}
              key={stage}
            >
              <span className="flex items-center font-mono text-[11px] font-semibold">
                {done ? <Check className="size-3" aria-hidden="true" /> : null}
                {failed ? <X className="size-3" aria-hidden="true" /> : null}
                {active ? <Loader2 className="size-3 animate-spin" aria-hidden="true" /> : null}
                {!done && !failed && !active ? String(index + 1).padStart(2, '0') : null}
                {done && <span className="sr-only">(completed)</span>}
                {active && <span className="sr-only">(current step)</span>}
                {failed && <span className="sr-only">(failed)</span>}
                {active && stage === 'uploading' && item.uploadProgress > 0 && (
                  <span className="ml-auto text-primary/80">{item.uploadProgress}%</span>
                )}
                {active && stage !== 'uploading' && <span className="ml-auto text-primary/80">{formatElapsed(stepSeconds)}</span>}
              </span>
              <span className="leading-snug">{batchStageLabels[stage]}</span>
            </li>
          );
        })}
      </ol>

      {item.status === 'failed' && (
        <Alert className="mt-3" variant="destructive">
          <AlertDescription>
            <strong className="font-semibold">Stopped at {batchStageLabels[item.failedAt ?? 'uploading']}.</strong> {sentence(item.error)}{' '}
            The other videos carry on.
          </AlertDescription>
        </Alert>
      )}

      {item.status === 'done' && item.report && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">
            {item.converted ? 'Converted to H.264 MP4 and analysed.' : 'Stored as uploaded and analysed.'}
          </span>
          <Link
            className="font-semibold text-primary hover:underline"
            href={`/reports/${encodeURIComponent(item.report.videoId)}?revision=${item.report.revisionId}`}
          >
            Open report →
          </Link>
        </div>
      )}
    </li>
  );
}

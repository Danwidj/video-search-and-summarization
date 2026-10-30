// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Check, Loader2, RotateCcw, Video, X } from 'lucide-react';
import { cn } from 'cn';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { BATCH_STAGES, type BatchItem, batchStageLabels, formatElapsed, itemProgress } from '@/sections/analysis/batch-upload';

const statusLabel = {
  queued: 'Waiting',
  running: 'In progress',
  waiting: 'Waiting for the batch',
  checked: 'Checked, waiting to build',
  deciding: 'Awaiting your decision',
  failed: 'Failed',
  done: 'Report ready',
} as const;

function announcement(item: BatchItem): string {
  const label = batchStageLabels[item.stage];
  if (item.status === 'failed') return `${item.name} stopped at ${label}: ${item.error ?? 'the step failed'}.`;
  if (item.status === 'done') return `${item.name}: report ready.`;
  if (item.status === 'queued') return `${item.name}: waiting to start.`;
  if (item.status === 'waiting') return `${item.name}: analysed, waiting for the rest of the batch.`;
  if (item.status === 'checked') return `${item.name}: matches checked, report is built next.`;
  if (item.status === 'deciding') return `${item.name}: matches checked, report waits for your decision.`;
  return `${item.name}: ${label}${item.stage === 'upload' && item.uploadProgress > 0 ? ` (${item.uploadProgress}%)` : ''}.`;
}

/** The message as a sentence, so what follows it reads on. */
const sentence = (text: string | null): string => (text && !/[.!?]$/.test(text) ? `${text}.` : (text ?? ''));

/** Seconds the file has spent in its current step; restarts when the step changes and ticks only while it runs. */
function useStepSeconds(running: boolean, stage: BatchItem['stage']): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    setSeconds(0);
    if (!running || !stage) return;
    const started = Date.now();
    const timer = setInterval(() => setSeconds((Date.now() - started) / 1000), 1000);
    return () => clearInterval(timer);
  }, [running, stage]);
  return seconds;
}

export interface BatchFileRowProps {
  item: BatchItem;
  onRetry(key: string): void;
}

export function BatchFileRow({ item, onRetry }: BatchFileRowProps) {
  const progress = itemProgress(item);
  const stageIndex = BATCH_STAGES.indexOf(item.stage);
  const stepSeconds = useStepSeconds(item.status === 'running', item.stage);
  return (
    <li className="rounded-2xl border border-border bg-card p-3.5 sm:p-4" data-file={item.name}>
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
        <Badge
          className={cn('shrink-0', item.status === 'failed' && 'border-destructive/30 bg-destructive/10 text-destructive')}
          variant={item.status === 'done' ? 'default' : 'secondary'}
        >
          {statusLabel[item.status]}
        </Badge>
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

      <ol className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-4" aria-label={`Stages for ${item.name}`}>
        {BATCH_STAGES.map((stage, index) => {
          const done = item.status === 'done' || (item.status !== 'queued' && index < stageIndex);
          const failed = item.status === 'failed' && index === stageIndex;
          const active = item.status === 'running' && index === stageIndex;
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
                {active && stage === 'upload' && item.uploadProgress > 0 && (
                  <span className="ml-auto text-primary/80">{item.uploadProgress}%</span>
                )}
                {active && stage !== 'upload' && <span className="ml-auto text-primary/80">{formatElapsed(stepSeconds)}</span>}
              </span>
              <span className="leading-snug">{batchStageLabels[stage]}</span>
            </li>
          );
        })}
      </ol>

      {item.status === 'running' && item.stage === 'analyse' && (
        <p className="mt-2 text-xs text-muted-foreground">Analysing takes about a minute per video, so this bar holds here a while.</p>
      )}

      {item.status === 'failed' && (
        <Alert className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between" variant="destructive">
          <AlertDescription>
            <strong className="font-semibold">Stopped at {batchStageLabels[item.stage]}.</strong> {sentence(item.error)} The other videos
            carry on.
          </AlertDescription>
          <Button className="shrink-0" onClick={() => onRetry(item.key)} size="sm" type="button" variant="outline">
            <RotateCcw data-icon="inline-start" />
            Retry this video
          </Button>
        </Alert>
      )}

      {(item.status === 'done' || item.status === 'checked' || item.status === 'deciding') && item.analysed && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">
            {item.autoJoined
              ? `Joined incident ${item.autoJoined.incidentId} automatically (match score ${item.autoJoined.score.toFixed(2)}).${item.matches ? ` ${item.matches} other ${item.matches === 1 ? 'match is' : 'matches are'} left to decide.` : ''}`
              : item.matches
                ? `${item.matches} suggested ${item.matches === 1 ? 'match' : 'matches'} found for this video.`
                : 'No match found in this batch or your other incidents.'}
          </span>
          <Link className="font-semibold text-primary hover:underline" href={`/reports/${item.analysed.incidentId}`}>
            Open incident {item.analysed.incidentId} →
          </Link>
        </div>
      )}
    </li>
  );
}

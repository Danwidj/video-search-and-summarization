// SPDX-License-Identifier: Apache-2.0
'use client';

import { RefreshCwIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { type RegeneratedVersion, regeneratedMessage, regenerateReport, regenerateStageAt } from '@/lib/reports/regenerate';

type Status =
  | { state: 'idle' }
  | { state: 'running'; startedAt: number }
  | { state: 'done'; message: string }
  | { state: 'failed'; message: string };

/**
 * Builds a new AI version of the incident from the latest stored analysis of each current video (no video is
 * re-processed), shows progress while it runs, and hands the new version to onDone so the page selects it. A failure
 * keeps the version being viewed and offers Retry. Disabled while the page holds an unsaved edit.
 */
export function RegenerateReport({
  incidentId,
  videoCount,
  disabled = false,
  onDone,
}: {
  incidentId: string;
  videoCount: number;
  disabled?: boolean;
  onDone: (version: RegeneratedVersion) => void;
}) {
  const [status, setStatus] = useState<Status>({ state: 'idle' });
  const [elapsedMs, setElapsedMs] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);

  const startedAt = status.state === 'running' ? status.startedAt : null;
  useEffect(() => {
    if (startedAt === null) return;
    const timer = setInterval(() => setElapsedMs(Date.now() - startedAt), 500);
    return () => clearInterval(timer);
  }, [startedAt]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  async function run() {
    if (status.state === 'running') return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setElapsedMs(0);
    setStatus({ state: 'running', startedAt: Date.now() });
    try {
      const version = await regenerateReport(incidentId, controller.signal);
      setStatus({ state: 'done', message: regeneratedMessage(version) });
      onDone(version);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') return;
      setStatus({ state: 'failed', message: cause instanceof Error ? cause.message : 'Could not build a new version' });
    }
  }

  const running = status.state === 'running';
  const stage = regenerateStageAt(elapsedMs);

  return (
    <div className="border-b border-border" data-testid="regenerate">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <span className="text-[11px] text-muted-foreground">Build a new version from the stored analyses</span>
        <Button
          className="shrink-0 font-semibold"
          data-testid="regenerate-button"
          disabled={disabled || running}
          onClick={() => void run()}
          size="sm"
          type="button"
          variant="outline"
        >
          <RefreshCwIcon aria-hidden="true" className={running ? 'animate-spin' : undefined} />
          {running ? 'Regenerating…' : 'Regenerate'}
        </Button>
      </div>
      {running && (
        <div aria-live="polite" className="px-3 pb-2" data-testid="regenerate-progress">
          <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px]">
            <span className="font-semibold">{stage.label}</span>
            <span className="font-mono text-muted-foreground">{stage.percent}%</span>
          </div>
          <Progress aria-label="Regenerate progress" value={stage.percent} />
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Using stored analyses of {videoCount} video{videoCount === 1 ? '' : 's'}. No video is re-processed.
          </p>
        </div>
      )}
      {status.state === 'done' && (
        <p className="px-3 pb-2 text-[11px] text-muted-foreground" data-testid="regenerate-done" role="status">
          {status.message}
        </p>
      )}
      {status.state === 'failed' && (
        <Alert className="mx-3 mb-2 w-auto p-2 text-[11px]" data-testid="regenerate-error" role="alert" variant="destructive">
          <AlertDescription className="flex items-center gap-2">
            <span className="min-w-0 flex-1">
              Could not build a new version: {status.message}. The version you are viewing is unchanged.
            </span>
            <Button data-testid="regenerate-retry" onClick={() => void run()} size="xs" type="button" variant="outline">
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

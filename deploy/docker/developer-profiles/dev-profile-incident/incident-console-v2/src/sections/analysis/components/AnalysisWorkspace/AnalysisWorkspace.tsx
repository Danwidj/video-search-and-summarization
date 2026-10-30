// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Plus, Upload } from 'lucide-react';
import { cn } from 'cn';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { BatchFileRow } from '@/sections/analysis/components/BatchFileRow';
import { useBatchUpload } from '@/sections/analysis/hooks/use-batch-upload';
import { getStageAnnouncement, getStageProgress, type StageKey, stageLabels, stageOrder } from '@/sections/analysis/stage-progress';

export type { StageKey };
export { getStageAnnouncement, getStageProgress, stageLabels, stageOrder };

interface ModelOption {
  id: string;
  label: string;
}

const VIDEO_NAME = /\.(mp4|mkv|mov|webm)$/i;

export function AnalysisWorkspace() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState('');
  const { items, summary, add, retry, cancelUploads } = useBatchUpload();

  useEffect(() => {
    let active = true;
    void fetch('/api/models', { cache: 'no-store' })
      .then((response) => response.json() as Promise<{ models?: ModelOption[]; defaultModel?: string }>)
      .then((payload) => {
        if (!active) return;
        setModels(payload.models || []);
        setModel(payload.defaultModel || payload.models?.[0]?.id || '');
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  function chooseFiles(selected: File[]) {
    const videos = selected.filter((file) => file.type.startsWith('video/') || VIDEO_NAME.test(file.name));
    const skipped = selected.length - videos.length;
    setError(
      skipped > 0
        ? `Skipped ${skipped} ${skipped === 1 ? 'file' : 'files'} that ${skipped === 1 ? 'is' : 'are'} not an MP4, MKV, MOV, or WebM video.`
        : null,
    );
    if (videos.length > 0) add(videos, model);
  }

  const empty = items.length === 0;
  const matches = items.reduce((sum, item) => sum + (item.matches ?? 0), 0);
  const noun = summary.total === 1 ? 'video' : 'videos';
  const announcement = empty
    ? ''
    : `Batch of ${summary.total} ${noun}: ${summary.done} ready, ${summary.running} running, ${summary.failed} failed.`;

  return (
    <Card
      className="relative rounded-4xl border border-border bg-white/80 p-4 shadow-panel backdrop-blur-sm md:p-6 ring-0 flex flex-col gap-0"
      aria-label="Video analysis workspace"
    >
      <input
        accept="video/mp4,video/x-matroska,video/quicktime,video/webm,.mp4,.mkv,.mov,.webm"
        className="sr-only"
        multiple
        onChange={(event) => {
          chooseFiles(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
        ref={inputRef}
        type="file"
      />

      {models.length > 0 && (
        <Card className="mb-4 flex flex-col gap-2 rounded-2xl border border-border bg-card px-4 py-3 ring-0 shadow-none sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-4">
          {/* The select keeps its natural width (the longest model name) and never shrinks; the note wraps below it instead. */}
          <label
            className="flex flex-col gap-1 text-xs font-bold uppercase tracking-[0.12em] text-ink/45 sm:shrink-0 sm:flex-row sm:items-center sm:gap-3"
            htmlFor="analysis-model"
          >
            <span className="whitespace-nowrap">Vision-language model</span>
            <Select onValueChange={(value) => setModel(value)} value={model}>
              <SelectTrigger className="normal-case tracking-normal sm:w-auto sm:min-w-[19rem] sm:shrink-0" id="analysis-model">
                <SelectValue placeholder="Choose model" />
              </SelectTrigger>
              <SelectContent>
                {models.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </Card>
      )}

      {empty ? (
        <Card
          className={cn(
            'relative flex flex-col items-center justify-center rounded-3xl border-2 border-dashed py-14 px-6 text-center transition-colors cursor-pointer select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:py-20 sm:px-10',
            dragging ? 'border-primary bg-primary/10' : 'border-border bg-muted/30 hover:border-primary/50 hover:bg-muted/50',
          )}
          role="button"
          tabIndex={0}
          aria-labelledby="upload-title"
          aria-describedby="upload-description"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            if (event.currentTarget.contains(event.relatedTarget as Node)) return;
            setDragging(false);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            chooseFiles(Array.from(event.dataTransfer.files));
          }}
        >
          <CardHeader className="flex flex-col items-center gap-3 p-0">
            <div className="upload-orbit mx-auto flex size-16 items-center justify-center rounded-full border border-primary/20 bg-background text-primary shadow-lg shadow-primary/10">
              <Upload className="size-8" aria-hidden="true" />
            </div>
            <Badge variant="secondary" className="font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">
              New analysis
            </Badge>
            <CardTitle className="text-2xl font-semibold tracking-tight text-foreground" id="upload-title">
              Drop videos here
            </CardTitle>
            <CardDescription className="max-w-sm text-sm leading-6 text-muted-foreground" id="upload-description">
              MP4, MKV, MOV, or WebM. Choose one video or several. Each is analysed on its own, so one failure does not stop the others.
            </CardDescription>
          </CardHeader>
          <CardContent className="mt-6 flex flex-col items-center p-0">
            <Button variant="outline" size="sm" className="pointer-events-none rounded-full" tabIndex={-1} type="button">
              <Upload data-icon="inline-start" />
              Browse video files
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-4" data-testid="batch">
          <div className="flex flex-col gap-2.5">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="font-medium text-foreground">
                Batch of {summary.total} {noun}: {summary.done} ready
                {summary.running > 0 ? `, ${summary.running} running` : ''}
                {summary.failed > 0 ? `, ${summary.failed} failed` : ''}
              </span>
              <span className="font-mono font-semibold text-foreground">{summary.percent}%</span>
            </div>
            <Progress
              aria-label="Batch progress"
              aria-valuenow={summary.percent}
              aria-valuetext={announcement}
              className="h-2 w-full"
              value={summary.percent}
            />
            <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
              {announcement}
            </div>
          </div>

          <ul className="flex flex-col gap-3" aria-label="Videos in this batch">
            {items.map((item) => (
              <BatchFileRow item={item} key={item.key} onRetry={retry} />
            ))}
          </ul>

          {summary.settled && matches > 0 && (
            <Alert className="border-amber-500/30 bg-amber-500/10 text-amber-900">
              <AlertDescription>
                <strong className="font-semibold">
                  {matches} suggested {matches === 1 ? 'match is' : 'matches are'} waiting for your review.
                </strong>{' '}
                Nothing is merged until you accept it.
              </AlertDescription>
            </Alert>
          )}

          <div className="flex flex-wrap gap-3">
            {summary.settled ? (
              <Button asChild className="h-11 flex-1 rounded-full text-sm font-semibold" size="lg">
                <Link href="/library">Go to library</Link>
              </Button>
            ) : (
              <>
                <Button className="h-11 flex-1 rounded-full text-sm font-semibold" disabled size="lg" type="button">
                  Working on {summary.running} {summary.running === 1 ? 'video' : 'videos'}…
                </Button>
                <Button
                  className="h-11 rounded-full text-sm font-semibold"
                  onClick={cancelUploads}
                  size="lg"
                  type="button"
                  variant="outline"
                >
                  Cancel unfinished uploads
                </Button>
              </>
            )}
            <Button
              className="h-11 rounded-full text-sm font-semibold"
              onClick={() => inputRef.current?.click()}
              size="lg"
              type="button"
              variant="outline"
            >
              <Plus data-icon="inline-start" />
              Add videos
            </Button>
          </div>
        </div>
      )}

      {error && (
        <Alert variant="destructive" className="mt-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </Card>
  );
}

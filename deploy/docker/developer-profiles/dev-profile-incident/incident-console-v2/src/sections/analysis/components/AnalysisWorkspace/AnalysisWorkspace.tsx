// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { checkUploadName, type UploadNameReport, useVideoUpload } from '@/sections/analysis/hooks/use-video-upload';

type StageKey = 'idle' | 'uploading' | 'preparing' | 'analyzing' | 'saving' | 'complete' | 'error';

interface ApiError {
  error?: string;
}

interface ModelOption {
  id: string;
  label: string;
}

const stageLabels: Array<{ key: StageKey; label: string }> = [
  { key: 'uploading', label: 'Uploading video' },
  { key: 'preparing', label: 'Preparing secure access' },
  { key: 'analyzing', label: 'Understanding the incident' },
  { key: 'saving', label: 'Structuring and saving report' },
  { key: 'complete', label: 'Report ready' },
];

const stageOrder: Record<StageKey, number> = {
  idle: -1,
  uploading: 0,
  preparing: 1,
  analyzing: 2,
  saving: 3,
  complete: 4,
  error: -1,
};

async function apiJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

/** The warning to show before an upload whose stored name differs from the file's own, or null. */
function nameWarning(original: string, report: UploadNameReport): { name: string; message: string } | null {
  const notes: string[] = [];
  if (report.unsafeChars.length > 0) notes.push(`unsafe characters (${report.unsafeChars.join(' ')}) were replaced with _`);
  if (report.truncated) notes.push('the name was too long and was shortened');
  if (report.exists) notes.push(`a file named ${report.existingName} is already stored, so nothing will be overwritten`);
  if (notes.length === 0) return null;
  return { name: report.name, message: `${original} will be stored as ${report.name}: ${notes.join('; ')}.` };
}

export function AnalysisWorkspace() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [stage, setStage] = useState<StageKey>('idle');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [nameNotice, setNameNotice] = useState<string | null>(null);
  const [storedName, setStoredName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState('');
  const { upload } = useVideoUpload();

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

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // A newly selected file starts the one-shot pipeline immediately, unless its name needs a warning first.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only a new file re-runs the check
  useEffect(() => {
    if (!file || stage !== 'idle') return;
    let active = true;
    void checkUploadName(file.name)
      .then((report) => (active ? nameWarning(file.name, report) : null))
      .catch(() => null)
      .then((warning) => {
        if (!active) return;
        if (warning) {
          setNameNotice(warning.message);
          setStoredName(warning.name);
        } else void analyze();
      });
    return () => {
      active = false;
    };
  }, [file]);

  function chooseFile(selected: File | null) {
    if (!selected) return;
    if (!selected.type.startsWith('video/') && !/\.(mp4|mkv|mov|webm)$/i.test(selected.name)) {
      setError('Choose an MP4, MKV, MOV, or WebM video.');
      return;
    }
    setFile(selected);
    setNameNotice(null);
    setStoredName(null);
    setError(null);
    setStage('idle');
    setUploadProgress(0);
  }

  async function analyze() {
    if (!file) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    setNameNotice(null);
    setUploadProgress(0);

    try {
      setStage('uploading');
      const { sensorId, filePath, filename } = await upload(file, controller.signal, setUploadProgress);

      setStage('preparing');
      await apiJson('/api/uploads/complete', { sensorId, filename });

      setStage('analyzing');
      const result = await apiJson<{ report: { videoId: string; revisionId: number } }>('/api/analysis', {
        sensorId,
        filepath: filePath,
        filename,
        ...(model ? { model } : {}),
      });
      setStage('saving');
      setStage('complete');
      router.push(`/reports/${encodeURIComponent(result.report.videoId)}?revision=${result.report.revisionId}`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Analysis failed';
      setError(message === 'Upload was cancelled' ? 'Analysis cancelled.' : message);
      setStage('error');
    } finally {
      abortRef.current = null;
    }
  }

  const activeIndex = stageOrder[stage];
  const busy = ['uploading', 'preparing', 'analyzing', 'saving'].includes(stage);

  return (
    <Card
      className="relative rounded-4xl border border-border bg-white/80 p-4 shadow-panel backdrop-blur-sm md:p-6 ring-0 flex flex-col gap-0"
      aria-labelledby="upload-title"
    >
      <input
        accept="video/mp4,video/x-matroska,video/quicktime,video/webm,.mp4,.mkv,.mov,.webm"
        className="sr-only"
        onChange={(event) => chooseFile(event.target.files?.[0] || null)}
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
            <Select disabled={busy} onValueChange={(value) => setModel(value)} value={model}>
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
          <p className="text-xs text-ink/45 sm:min-w-48 sm:flex-1 sm:text-right">
            Choose before selecting a video. Analysis can take several minutes.
          </p>
        </Card>
      )}

      {file && previewUrl ? (
        <div className="overflow-hidden rounded-[1.45rem] bg-ink text-white">
          <div className="relative aspect-video w-full min-w-0 min-h-0 overflow-hidden bg-black flex items-center justify-center">
            <video className="max-h-full max-w-full object-contain" controls preload="metadata" src={previewUrl}>
              <track kind="captions" />
            </video>
          </div>
          <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="truncate font-semibold">{file.name}</p>
              <p className="mt-1 text-xs text-white/55">{(file.size / 1024 / 1024).toFixed(1)} MB · ready for analysis</p>
            </div>
            {!busy && (
              <Button
                variant="ghost"
                size="sm"
                className="text-signal hover:text-signal/80 hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => inputRef.current?.click()}
                type="button"
              >
                Replace video
              </Button>
            )}
          </div>
        </div>
      ) : (
        <button
          className={`block w-full rounded-[1.45rem] border border-dashed px-6 py-16 text-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:px-10 sm:py-24 ${dragging ? 'border-primary bg-primary/10' : 'border-border bg-muted/30 hover:border-primary/50'}`}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            chooseFile(event.dataTransfer.files[0] || null);
          }}
          type="button"
        >
          <span className="upload-orbit mx-auto grid h-20 w-20 place-items-center rounded-full border border-primary/20 bg-background shadow-lg shadow-primary/10">
            <svg
              aria-hidden="true"
              className="h-8 w-8 text-primary"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="1.7"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14.5v3A2.5 2.5 0 007.5 20h9a2.5 2.5 0 002.5-2.5v-3"
              />
            </svg>
          </span>
          <span className="mt-7 block font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">New analysis</span>
          <span className="mt-3 block text-2xl font-semibold tracking-tight text-foreground" id="upload-title">
            Drop a video here
          </span>
          <span className="mx-auto mt-3 block max-w-sm text-sm leading-6 text-muted-foreground">
            MP4, MKV, MOV, or WebM. Analysis starts automatically after selection.
          </span>
        </button>
      )}

      {file && (
        <div className="mt-5">
          {stage !== 'idle' && (
            <ol className="mb-5 grid gap-2 sm:grid-cols-5">
              {stageLabels.map((item, index) => {
                const done = stage === 'complete' || index < activeIndex;
                const active = index === activeIndex;
                return (
                  <li
                    className={`rounded-xl border px-3 py-3 text-xs transition-colors ${done ? 'border-primary/30 bg-primary/10 text-primary' : active ? 'border-primary bg-primary/5 text-primary' : 'border-border text-muted-foreground'}`}
                    key={item.key}
                  >
                    <span className="mb-2 block font-mono font-semibold">{done ? '✓' : String(index + 1).padStart(2, '0')}</span>
                    {item.label}
                  </li>
                );
              })}
            </ol>
          )}

          {stage === 'uploading' && <Progress className="mb-4" value={uploadProgress} />}
          {nameNotice && stage === 'idle' && (
            <Alert className="mb-4 border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200">
              <AlertDescription>{nameNotice}</AlertDescription>
            </Alert>
          )}
          {error && (
            <Alert variant="destructive" className="mb-4">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="flex gap-3">
            <Button size="lg" className="flex-1 rounded-full text-sm font-semibold" disabled={busy} onClick={analyze} type="button">
              {busy
                ? stageLabels.find((item) => item.key === stage)?.label
                : stage === 'error'
                  ? 'Retry analysis'
                  : nameNotice && storedName
                    ? `Continue as ${storedName}`
                    : 'Analyze video'}
            </Button>
            {busy && (
              <Button
                variant="outline"
                size="lg"
                className="rounded-full text-sm font-semibold"
                onClick={() => abortRef.current?.abort()}
                type="button"
              >
                Cancel
              </Button>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

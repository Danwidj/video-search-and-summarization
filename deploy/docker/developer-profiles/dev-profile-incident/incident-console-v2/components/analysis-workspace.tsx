// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { IncidentReport } from '@/components/incident-report';
import type { AnalysisReport } from '@/lib/analysis/schema';
import { isValidR2Key } from '@/lib/r2/key';
import { chunkedUpload } from '@/lib/upload/chunked-upload';

type StageKey = 'idle' | 'uploading' | 'preparing' | 'analyzing' | 'saving' | 'complete' | 'error';

interface UploadInitialization {
  url?: string;
}

interface ApiError {
  error?: string;
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

function safeFilename(name: string): string {
  const dot = name.lastIndexOf('.');
  const stem = (dot > 0 ? name.slice(0, dot) : name).replace(/\s+/g, '-').replace(/[^A-Za-z0-9._-]/g, '');
  const extension = dot > 0 ? name.slice(dot).replace(/[^A-Za-z0-9.]/g, '') : '';
  return `${stem || 'incident-video'}${extension}`;
}

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

/**
 * Uploads the video directly to R2 via the console's own server-side route.
 * Needed only when the chunk-upload response has no durable R2 object key —
 * the real VST/NvStreamer case, since only mock-backend's own reimplementation
 * fakes that field by doing its own R2 upload.
 */
async function uploadToR2(file: File, sensorId: string, filename: string, signal: AbortSignal): Promise<string> {
  const form = new FormData();
  form.append('file', file, filename);
  form.append('sensorId', sensorId);
  form.append('filename', filename);
  const response = await fetch('/api/uploads/r2', { method: 'POST', body: form, signal });
  const payload = (await response.json()) as { filePath?: string } & ApiError;
  if (!response.ok || !isValidR2Key(payload.filePath)) {
    throw new Error(payload.error || 'Could not upload the video to R2');
  }
  return payload.filePath;
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
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (file && stage === 'idle') void analyze();
    // A newly selected file intentionally starts the one-shot pipeline immediately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  function chooseFile(selected: File | null) {
    if (!selected) return;
    if (!selected.type.startsWith('video/') && !/\.(mp4|mkv|mov|webm)$/i.test(selected.name)) {
      setError('Choose an MP4, MKV, MOV, or WebM video.');
      return;
    }
    setFile(selected);
    setReport(null);
    setError(null);
    setStage('idle');
    setUploadProgress(0);
  }

  async function analyze() {
    if (!file) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    setReport(null);
    setUploadProgress(0);

    try {
      const filename = safeFilename(file.name);
      setStage('uploading');
      const initialized = await apiJson<UploadInitialization>('/api/uploads', { filename });
      if (!initialized.url) throw new Error('The upload service did not return an upload URL');

      const uploaded = await chunkedUpload({
        file,
        fileName: filename,
        uploadUrl: initialized.url,
        // The development mock records only the current request body and does
        // not reassemble multiple chunks. A single request keeps the R2 object
        // as a valid video and matches v1's verified upload behavior. Restore
        // the helper's default chunk size when the real nvstreamer backend is
        // the active upload target and large-video limits are exercised.
        chunkSize: Math.max(file.size, 1),
        onProgress: setUploadProgress,
        abortSignal: controller.signal,
      });
      if (!uploaded.sensorId) {
        throw new Error('Upload completed without a sensor ID');
      }

      // Mock-backend's chunk-upload response already carries a valid R2 key
      // (it does its own R2 upload); real VST/NvStreamer never returns one,
      // so fall back to uploading the file to R2 ourselves in that case.
      const filePath = isValidR2Key(uploaded.filePath)
        ? uploaded.filePath
        : await uploadToR2(file, uploaded.sensorId, filename, controller.signal);

      setStage('preparing');
      await apiJson('/api/uploads/complete', { sensorId: uploaded.sensorId, filename });

      setStage('analyzing');
      const result = await apiJson<{ report: AnalysisReport }>('/api/analysis', {
        sensorId: uploaded.sensorId,
        filepath: filePath,
        filename,
      });
      setStage('saving');
      setReport(result.report);
      window.localStorage.setItem('incident-console-v2:last-report', JSON.stringify(result.report));
      setStage('complete');
      router.push(`/reports/${encodeURIComponent(result.report.videoId)}?run=${encodeURIComponent(result.report.modelRunId)}`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Analysis failed';
      setError(message === 'Upload was cancelled' ? 'Analysis cancelled.' : message);
      setStage('error');
    } finally {
      abortRef.current = null;
    }
  }

  function reset() {
    abortRef.current?.abort();
    setFile(null);
    setReport(null);
    setStage('idle');
    setError(null);
    setUploadProgress(0);
    window.localStorage.removeItem('incident-console-v2:last-report');
    if (inputRef.current) inputRef.current.value = '';
  }

  if (report) return <IncidentReport onNewAnalysis={reset} report={report} />;

  const activeIndex = stageOrder[stage];
  const busy = ['uploading', 'preparing', 'analyzing', 'saving'].includes(stage);

  return (
    <section className="relative rounded-[2rem] border border-ink/10 bg-white/80 p-4 shadow-panel backdrop-blur md:p-6" aria-labelledby="upload-title">
      <input
        accept="video/mp4,video/x-matroska,video/quicktime,video/webm,.mp4,.mkv,.mov,.webm"
        className="sr-only"
        onChange={(event) => chooseFile(event.target.files?.[0] || null)}
        ref={inputRef}
        type="file"
      />

      {file && previewUrl ? (
        <div className="overflow-hidden rounded-[1.45rem] bg-ink text-white">
          <video className="aspect-video w-full bg-black object-contain" controls preload="metadata" src={previewUrl} />
          <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="truncate font-semibold">{file.name}</p>
              <p className="mt-1 text-xs text-white/55">{(file.size / 1024 / 1024).toFixed(1)} MB · ready for analysis</p>
            </div>
            {!busy && (
              <button className="text-sm font-semibold text-signal" onClick={() => inputRef.current?.click()} type="button">
                Replace video
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          className={`block w-full rounded-[1.45rem] border border-dashed px-6 py-16 text-center transition sm:px-10 sm:py-24 ${dragging ? 'border-signal bg-signal/10' : 'border-ink/20 bg-[#e9eee5] hover:border-moss/50'}`}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0] || null); }}
          type="button"
        >
          <span className="upload-orbit mx-auto grid h-20 w-20 place-items-center rounded-full border border-moss/20 bg-white shadow-lg shadow-moss/10">
            <svg aria-hidden="true" className="h-8 w-8 text-moss" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.7">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14.5v3A2.5 2.5 0 007.5 20h9a2.5 2.5 0 002.5-2.5v-3" />
            </svg>
          </span>
          <span className="mt-7 block font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-moss">New analysis</span>
          <span className="mt-3 block text-2xl font-semibold tracking-tight" id="upload-title">Drop a video here</span>
          <span className="mx-auto mt-3 block max-w-sm text-sm leading-6 text-ink/55">MP4, MKV, MOV, or WebM. Analysis starts automatically after selection.</span>
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
                  <li className={`rounded-xl border px-3 py-3 text-xs ${done ? 'border-signal/30 bg-signal/10 text-moss' : active ? 'border-moss/30 bg-moss/5 text-moss' : 'border-ink/8 text-ink/35'}`} key={item.key}>
                    <span className="mb-2 block font-mono">{done ? '✓' : String(index + 1).padStart(2, '0')}</span>
                    {item.label}
                  </li>
                );
              })}
            </ol>
          )}

          {stage === 'uploading' && (
            <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-ink/10">
              <div className="h-full rounded-full bg-signal transition-all" style={{ width: `${uploadProgress}%` }} />
            </div>
          )}
          {error && <p className="mb-4 rounded-xl border border-clay/25 bg-clay/10 px-4 py-3 text-sm text-[#8c3d25]">{error}</p>}

          <div className="flex gap-3">
            <button
              className="flex-1 rounded-full bg-ink px-6 py-3.5 text-sm font-semibold text-white transition hover:bg-moss disabled:cursor-wait disabled:opacity-60"
              disabled={busy}
              onClick={analyze}
              type="button"
            >
              {busy ? stageLabels.find((item) => item.key === stage)?.label : stage === 'error' ? 'Retry analysis' : 'Analyze video'}
            </button>
            {busy && <button className="rounded-full border border-ink/15 px-5 text-sm font-semibold" onClick={() => abortRef.current?.abort()} type="button">Cancel</button>}
          </div>
        </div>
      )}
    </section>
  );
}

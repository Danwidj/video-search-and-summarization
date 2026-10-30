// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  type BatchDeps,
  type BatchItem,
  isAlreadyStored,
  newBatchItem,
  runBatchItem,
  runPool,
  summariseBatch,
} from '@/sections/analysis/batch-upload';
import { useVideoUpload } from '@/sections/analysis/hooks/use-video-upload';
import { requestAnalysis } from '@/lib/analysis/analyse-client';

/** Files that upload and analyse at once; the VLM is the slow step, so a small pool is enough. */
const CONCURRENCY = 2;

interface ApiError {
  error?: string;
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const payload = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

export function useBatchUpload() {
  const { upload } = useVideoUpload();
  const [items, setItems] = useState<BatchItem[]>([]);
  const files = useRef(new Map<string, File>());
  const aborts = useRef(new Map<string, AbortController>());
  const counter = useRef(0);
  const model = useRef('');

  useEffect(() => {
    const running = aborts.current;
    return () => {
      for (const controller of running.values()) controller.abort();
    };
  }, []);

  const patch = useCallback((key: string, change: Partial<BatchItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }, []);

  const depsFor = useCallback(
    (key: string): BatchDeps => ({
      upload: (file, onProgress) => {
        const controller = new AbortController();
        aborts.current.set(key, controller);
        return upload(file, controller.signal, onProgress).finally(() => aborts.current.delete(key));
      },
      complete: async ({ sensorId, filename }) => {
        await post('/api/uploads/complete', { sensorId, filename });
      },
      analyse: async ({ uploaded, model: chosen }) => {
        const common = { ...(chosen ? { model: chosen } : {}) };
        try {
          return await requestAnalysis({
            ...common,
            sensorId: uploaded.sensorId,
            filepath: uploaded.filePath,
            filename: uploaded.filename,
          });
        } catch (error) {
          // A retry after a failed analysis finds the video already stored: analyse it again instead.
          if (!isAlreadyStored(error)) throw error;
          return requestAnalysis({ ...common, videoName: uploaded.filename });
        }
      },
      build: async (incidentId) => {
        await post(`/api/reports/${incidentId}/build`, {});
      },
      evaluate: async (incidentId) => {
        const result = await post<{ suggestions?: unknown[] }>('/api/suggestions/evaluate', { incidentId });
        return { suggestions: result.suggestions?.length ?? 0 };
      },
    }),
    [upload],
  );

  const run = useCallback(
    (keys: string[], start: BatchItem[]) =>
      runPool(keys, CONCURRENCY, async (key) => {
        const file = files.current.get(key);
        const item = start.find((entry) => entry.key === key);
        if (!file || !item) return;
        await runBatchItem(file, item, model.current, depsFor(key), (change) => patch(key, change));
      }),
    [depsFor, patch],
  );

  /** Adds files to the batch and starts them; files already running keep going. */
  const add = useCallback(
    (chosen: File[], modelId: string) => {
      model.current = modelId;
      const added = chosen.map((file) => {
        const key = `file-${++counter.current}`;
        files.current.set(key, file);
        return newBatchItem(file, key);
      });
      setItems((current) => [...current, ...added]);
      void run(
        added.map((item) => item.key),
        added,
      );
    },
    [run],
  );

  /** Retries one failed file from the stage it stopped at. */
  const retry = useCallback(
    (key: string) => {
      const item = items.find((entry) => entry.key === key);
      if (!item) return;
      if (item.status !== 'failed') return;
      patch(key, { status: 'queued', error: null });
      void run([key], [item]);
    },
    [items, patch, run],
  );

  /** Cancels uploads still in flight; files past the upload run on server side and cannot be recalled. */
  const cancelUploads = useCallback(() => {
    for (const controller of aborts.current.values()) controller.abort();
  }, []);

  return { items, summary: summariseBatch(items), add, retry, cancelUploads };
}

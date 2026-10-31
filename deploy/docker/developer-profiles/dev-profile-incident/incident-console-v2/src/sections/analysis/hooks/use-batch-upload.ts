// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  type BatchDeps,
  type BatchItem,
  cancelQueued,
  drainQueue,
  newBatchItem,
  removeQueued,
  runBatchItem,
  shouldAbortRunning,
  summariseBatch,
} from '@/sections/analysis/batch-upload';
import { useVideoUpload } from '@/sections/analysis/hooks/use-video-upload';

interface ApiError {
  error?: string;
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const payload = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

/**
 * The upload page's queue: files run one at a time through the same upload
 * (use-video-upload.ts) and analysis request as a single upload.
 */
export function useBatchUpload() {
  const { upload } = useVideoUpload();
  const [items, setItems] = useState<BatchItem[]>([]);
  // The ref is the source of truth, so the queue reads files added or removed while one runs.
  const current = useRef<BatchItem[]>([]);
  const files = useRef(new Map<string, File>());
  const models = useRef(new Map<string, string>());
  const abort = useRef<AbortController | null>(null);
  const counter = useRef(0);
  const draining = useRef(false);

  const commit = useCallback((next: BatchItem[]) => {
    current.current = next;
    setItems(next);
  }, []);

  const patch = useCallback(
    (key: string, change: Partial<BatchItem>) => commit(current.current.map((item) => (item.key === key ? { ...item, ...change } : item))),
    [commit],
  );

  useEffect(() => () => abort.current?.abort(), []);

  const deps: BatchDeps = {
    upload: (file, onProgress, onUploaded) => {
      const controller = new AbortController();
      abort.current = controller;
      return upload(file, controller.signal, onProgress, onUploaded).finally(() => {
        abort.current = null;
      });
    },
    analyse: async ({ filePath, filename, model }) => {
      const { report } = await post<{ report: { videoId: string; revisionId: number } }>('/api/analysis', {
        filepath: filePath,
        filename,
        ...(model ? { model } : {}),
      });
      return { videoId: report.videoId, revisionId: report.revisionId };
    },
  };
  const depsRef = useRef(deps);
  depsRef.current = deps;

  const drain = useCallback(async () => {
    if (draining.current) return;
    draining.current = true;
    try {
      await drainQueue(
        () => current.current,
        async (key) => {
          const file = files.current.get(key);
          if (!file) return patch(key, { status: 'failed', failedAt: 'uploading', error: 'The file is no longer available' });
          await runBatchItem(file, models.current.get(key) ?? '', depsRef.current, (change) => patch(key, change));
          files.current.delete(key);
        },
      );
    } finally {
      draining.current = false;
    }
  }, [patch]);

  /** Queues files with the model chosen now and starts the queue if it is idle. */
  const add = useCallback(
    (chosen: File[], model: string) => {
      const added = chosen.map((file) => {
        const key = `file-${++counter.current}`;
        files.current.set(key, file);
        models.current.set(key, model);
        return newBatchItem(file, key);
      });
      commit([...current.current, ...added]);
      void drain();
    },
    [commit, drain],
  );

  /** Drops a file that has not started. */
  const remove = useCallback(
    (key: string) => {
      const next = removeQueued(current.current, key);
      if (next.length !== current.current.length) files.current.delete(key);
      commit(next);
    },
    [commit],
  );

  /** Cancels every queued file, and the running one while its bytes still upload. */
  const cancel = useCallback(() => {
    const abortRunning = shouldAbortRunning(current.current);
    commit(cancelQueued(current.current));
    if (abortRunning) abort.current?.abort();
  }, [commit]);

  /** Empties a settled batch so the drop zone shows again. */
  const clear = useCallback(() => {
    if (!summariseBatch(current.current).settled) return;
    files.current.clear();
    models.current.clear();
    commit([]);
  }, [commit]);

  return { items, summary: summariseBatch(items), add, remove, cancel, clear };
}

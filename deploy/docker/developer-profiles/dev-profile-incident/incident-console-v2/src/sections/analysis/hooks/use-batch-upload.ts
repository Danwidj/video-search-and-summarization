// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';

import type { AnalysisJob } from '@/modules/jobs/domain/job';
import {
  applyJobs,
  type BatchDeps,
  type BatchItem,
  canRetryUpload,
  cancelQueued,
  drainQueue,
  newBatchItem,
  removeQueued,
  requeue,
  runBatchItem,
  shouldAbortRunning,
  summariseBatch,
  waitingJobIds,
} from '@/sections/analysis/batch-upload';
import { useVideoUpload } from '@/sections/analysis/hooks/use-video-upload';

interface BatchJobs {
  jobs: AnalysisJob[];
  enqueue: BatchDeps['enqueue'];
  retry(id: number): Promise<void>;
  cancel(id: number): Promise<void>;
}

/**
 * The upload page's queue: files upload one at a time through the same upload
 * as a single upload (use-video-upload.ts), then each becomes a background
 * analysis job; the rows follow their jobs from the polled list (use-analysis-jobs.ts).
 */
export function useBatchUpload(jobs: BatchJobs) {
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

  // Each poll of the jobs list moves the rows whose job changed.
  useEffect(() => {
    if (current.current.some((item) => item.jobId !== null)) commit(applyJobs(current.current, jobs.jobs));
  }, [jobs.jobs, commit]);

  const deps: BatchDeps = {
    upload: (file, onProgress, onUploaded) => {
      const controller = new AbortController();
      abort.current = controller;
      return upload(file, controller.signal, onProgress, onUploaded).finally(() => {
        abort.current = null;
      });
    },
    enqueue: jobs.enqueue,
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
          // Keep the file only while Retry can re-send it (its upload or conversion failed).
          const item = current.current.find((entry) => entry.key === key);
          if (!item || !canRetryUpload(item)) files.current.delete(key);
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

  /** Cancels every file not uploaded yet, the running one while its bytes still upload, and the batch's queued jobs. */
  const cancel = useCallback(() => {
    const abortRunning = shouldAbortRunning(current.current);
    const waiting = waitingJobIds(current.current);
    commit(cancelQueued(current.current));
    if (abortRunning) abort.current?.abort();
    for (const id of waiting) void jobs.cancel(id);
  }, [commit, jobs.cancel]);

  /** Retry on a failed row: re-sends a file whose upload failed, or queues a failed job again. */
  const retry = useCallback(
    (key: string) => {
      const item = current.current.find((entry) => entry.key === key);
      if (!item) return;
      if (item.jobId !== null) {
        void jobs.retry(item.jobId);
        return;
      }
      if (!files.current.has(key)) return;
      commit(requeue(current.current, key));
      void drain();
    },
    [commit, drain, jobs.retry],
  );

  /** Empties a settled batch so the drop zone shows again. */
  const clear = useCallback(() => {
    if (!summariseBatch(current.current).settled) return;
    files.current.clear();
    models.current.clear();
    commit([]);
  }, [commit]);

  return { items, summary: summariseBatch(items), add, remove, cancel, retry, clear };
}

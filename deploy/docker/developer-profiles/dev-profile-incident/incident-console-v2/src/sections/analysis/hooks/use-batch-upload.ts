// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  type BatchDeps,
  type BatchCheckResult,
  type BatchItem,
  buildBatchIncident,
  followJoin,
  checkBatchItem,
  isAlreadyStored,
  newBatchItem,
  planBatch,
  retryChange,
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

async function buildReport(incidentId: number): Promise<void> {
  await post(`/api/reports/${incidentId}/build`, {});
}

/** Incidents named by a pending suggestion; null when the list could not be read, so nothing is built on a guess. */
async function pendingIncidentIds(): Promise<Set<number> | null> {
  try {
    const response = await fetch('/api/suggestions/cards', { cache: 'no-store' });
    const payload = (await response.json()) as { suggestions?: { kept: { incidentId: number }; joining: { incidentId: number } }[] };
    if (!response.ok || !payload.suggestions) return null;
    return new Set(payload.suggestions.flatMap((card) => [card.kept.incidentId, card.joining.incidentId]));
  } catch {
    return null;
  }
}

export function useBatchUpload() {
  const { upload } = useVideoUpload();
  const [items, setItems] = useState<BatchItem[]>([]);
  // The ref is the source of truth, so a decision made while a step runs sees the latest state.
  const current = useRef<BatchItem[]>([]);
  const files = useRef(new Map<string, File>());
  const aborts = useRef(new Map<string, AbortController>());
  const counter = useRef(0);
  const model = useRef('');
  const settling = useRef(false);
  const again = useRef(false);
  const settleRef = useRef<() => Promise<void>>(async () => undefined);

  const commit = useCallback((next: BatchItem[]) => {
    current.current = next;
    setItems(next);
  }, []);

  useEffect(() => {
    const running = aborts.current;
    return () => {
      for (const controller of running.values()) controller.abort();
    };
  }, []);

  const patch = useCallback(
    (key: string, change: Partial<BatchItem>) => {
      commit(current.current.map((item) => (item.key === key ? { ...item, ...change } : item)));
    },
    [commit],
  );

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
      build: buildReport,
      evaluate: async (incidentId) => {
        const result = await post<{ suggestions?: unknown[]; joined?: BatchCheckResult['joined'] & { suggestionId?: number } }>(
          '/api/suggestions/evaluate',
          { incidentId },
        );
        const joined = result.joined
          ? { keptIncidentId: result.joined.keptIncidentId, mergedIncidentId: result.joined.mergedIncidentId, score: result.joined.score }
          : null;
        // The merged incident is gone: files that pointed at it follow the join before anything reads their incident.
        if (joined) commit(followJoin(current.current, joined));
        return { suggestions: result.suggestions?.length ?? 0, joined };
      },
    }),
    [commit, upload],
  );

  /**
   * Moves the batch on: checks matches once every file is analysed or failed, then builds the reports
   * whose suggestions are all decided. Runs one pass at a time; a request made meanwhile repeats the pass.
   */
  const settle = useCallback(async () => {
    if (settling.current) {
      again.current = true;
      return;
    }
    settling.current = true;
    try {
      do {
        again.current = false;
        const toCheck = planBatch(current.current, null).check;
        if (toCheck.length > 0) {
          for (const key of toCheck) patch(key, { status: 'running', stage: 'matches', error: null });
          // One at a time: a join deletes an incident, so the next check must start from the merged state.
          await runPool(toCheck, 1, async (key) => {
            const item = current.current.find((entry) => entry.key === key);
            if (item) await checkBatchItem(item, depsFor(key), (change) => patch(key, change));
          });
        }
        // Undecided suggestions are read after the checks, so a pair found by a later file is not missed.
        const ids = current.current.some((item) => item.status === 'deciding') ? await pendingIncidentIds() : null;
        const { build } = planBatch(current.current, ids);
        for (const { keys } of build) for (const key of keys) patch(key, { status: 'running', stage: 'report', error: null });
        // Not awaited: a decision made while reports build is not held up by them.
        void runPool(build, CONCURRENCY, ({ incidentId, keys }) =>
          buildBatchIncident(incidentId, keys, { build: buildReport }, (key, change) => patch(key, change)),
        ).then(() => {
          if (build.length > 0) void settleRef.current();
        });
      } while (again.current);
    } finally {
      settling.current = false;
    }
  }, [depsFor, patch]);
  settleRef.current = settle;

  const run = useCallback(
    async (keys: string[]) => {
      await runPool(keys, CONCURRENCY, async (key) => {
        const file = files.current.get(key);
        const item = current.current.find((entry) => entry.key === key);
        if (!file || !item) return;
        await runBatchItem(file, item, model.current, depsFor(key), (change) => patch(key, change));
        void settleRef.current();
      });
    },
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
      commit([...current.current, ...added]);
      void run(added.map((item) => item.key));
    },
    [commit, run],
  );

  /** Retries one failed file from the stage it stopped at. */
  const retry = useCallback(
    (key: string) => {
      const item = current.current.find((entry) => entry.key === key);
      if (!item) return;
      if (item.status !== 'failed') return;
      const change = retryChange(item);
      patch(key, change);
      if (change.status === 'queued') void run([key]);
      else void settleRef.current();
    },
    [patch, run],
  );

  /** Cancels uploads still in flight; files past the upload run on server side and cannot be recalled. */
  const cancelUploads = useCallback(() => {
    for (const controller of aborts.current.values()) controller.abort();
  }, []);

  return { items, summary: summariseBatch(items), add, retry, cancelUploads };
}

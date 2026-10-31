// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';

import type { AnalysisJob } from '@/modules/jobs/domain/job';

/** How often the upload page reads the jobs list. */
export const JOBS_POLL_MS = 3000;

interface ApiError {
  error?: string;
}

export async function jobsRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    cache: 'no-store',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  const payload = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

/**
 * The background analysis jobs (GET /api/jobs), read every JOBS_POLL_MS while
 * the page is open, so a reopened tab shows the same jobs and their progress.
 * retry and cancel act on one job and read the list again at once.
 */
export function useAnalysisJobs() {
  const [jobs, setJobs] = useState<AnalysisJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const active = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const { jobs: next } = await jobsRequest<{ jobs: AnalysisJob[] }>('/api/jobs');
      if (!active.current) return;
      setJobs(next);
      setError(null);
    } catch (caught) {
      if (active.current) setError(caught instanceof Error ? caught.message : 'Could not read the analysis jobs');
    } finally {
      if (active.current) setLoaded(true);
    }
  }, []);

  useEffect(() => {
    active.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), JOBS_POLL_MS);
    return () => {
      active.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const act = useCallback(
    async (id: number, action: 'retry' | 'cancel') => {
      try {
        await jobsRequest(`/api/jobs/${id}/${action}`, { method: 'POST', body: '{}' });
      } catch (caught) {
        if (active.current) setError(caught instanceof Error ? caught.message : `Could not ${action} the job`);
      }
      await refresh();
    },
    [refresh],
  );

  const enqueue = useCallback(
    async (input: { filePath: string; filename: string; model: string }) => {
      const { job } = await jobsRequest<{ job: AnalysisJob }>('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({ filepath: input.filePath, filename: input.filename, ...(input.model ? { model: input.model } : {}) }),
      });
      void refresh();
      return job;
    },
    [refresh],
  );

  const retry = useCallback((id: number) => act(id, 'retry'), [act]);
  const cancel = useCallback((id: number) => act(id, 'cancel'), [act]);

  return { jobs, loaded, error, refresh, enqueue, retry, cancel };
}

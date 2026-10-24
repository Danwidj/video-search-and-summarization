// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from 'react';

import type { VideoRunHistory } from '@/modules/videos/domain/run-types';

export function useRunHistory(videoId: string) {
  const [history, setHistory] = useState<VideoRunHistory | null>(null);
  const [error, setError] = useState('');
  const reload = useCallback(() => {
    setError('');
    return fetch(`/api/videos/${encodeURIComponent(videoId)}/runs`, { cache: 'no-store' })
      .then(async (response) => {
        const payload = (await response.json()) as VideoRunHistory & { error?: string };
        if (!response.ok) throw new Error(payload.error || 'Could not load the analysis history');
        setHistory(payload);
      })
      .catch((cause: Error) => setError(cause.message));
  }, [videoId]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { history, error, reload };
}

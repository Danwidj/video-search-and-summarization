// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';

import { getViewerTimeZone } from '@/lib/time';
import type { ChartAnswer, ChartType, GeneratedChart } from '@/modules/dashboard/domain/generated-chart';

export type ChartRequestState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'chart'; chart: GeneratedChart }
  | { status: 'unsupported' }
  | { status: 'needs_bar' }
  | { status: 'error'; message: string };

const FAILED = 'Could not build the chart';

/** One request: only its own text, the chosen chart type and the time zone are sent. */
export async function requestChart(
  request: string,
  chartType: ChartType,
  timezone: string,
  signal?: AbortSignal,
): Promise<ChartRequestState> {
  const response = await fetch('/api/dashboard/chart', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request, chartType, timezone }),
    cache: 'no-store',
    signal,
  });
  const payload = (await response.json().catch(() => null)) as (ChartAnswer & { error?: string }) | null;
  if (!response.ok || !payload) return { status: 'error', message: payload?.error || FAILED };
  return payload.kind === 'chart' ? { status: 'chart', chart: payload.chart } : { status: payload.kind };
}

/** Holds one result only: each submit replaces it, and no earlier request is kept. */
export function useChartRequest() {
  const [state, setState] = useState<ChartRequestState>({ status: 'idle' });
  const inFlight = useRef<AbortController | null>(null);
  useEffect(() => () => inFlight.current?.abort(), []);
  const submit = useCallback(async (request: string, chartType: ChartType) => {
    const controller = new AbortController();
    inFlight.current = controller;
    setState({ status: 'loading' });
    try {
      setState(await requestChart(request, chartType, getViewerTimeZone(), controller.signal));
    } catch {
      if (!controller.signal.aborted) setState({ status: 'error', message: FAILED });
    }
  }, []);
  return { state, submit };
}

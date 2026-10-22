// SPDX-License-Identifier: Apache-2.0

// The report page's server-side load, kept out of page.tsx so it runs under
// node --test: the getReport use case over the configured ports (as
// GET /api/reports/[videoId] calls it), with the playback URL signed here.

import { getDbAdapters } from '@/lib/adapters/supabase';
import { getReport } from '@/lib/application/reports';
import { getServiceConfiguration } from '@/lib/env';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import type { ReportView } from '@/lib/reports/report-view';

export type ReportPageLoad =
  | { kind: 'missing-run' }
  | { kind: 'found'; report: ReportView }
  | { kind: 'not-found' }
  | { kind: 'failed'; message: string };

/** The report of one run; `run` is the page's `?run=` search parameter (the first one when repeated). */
export async function loadReportPage(videoId: string, run: string | string[] | undefined): Promise<ReportPageLoad> {
  const modelRunId = Array.isArray(run) ? run[0] : run;
  if (!modelRunId) return { kind: 'missing-run' };

  try {
    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);
    const report = await getReport(incidents, { videoId, modelRunId }, (storageKey) => createR2PlaybackUrl(config, storageKey));
    return report ? { kind: 'found', report } : { kind: 'not-found' };
  } catch (error) {
    // The reason (unconfigured store, unreachable PostgREST, unsigned video), as the API route returns it;
    // error.tsx only sees a redacted message in production.
    return { kind: 'failed', message: error instanceof Error ? error.message : 'Could not load the report' };
  }
}

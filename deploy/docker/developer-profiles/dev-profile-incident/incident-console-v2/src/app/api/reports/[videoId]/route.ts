// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getReport } from '@/modules/reports/application/get-report';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';

export const dynamic = 'force-dynamic';

/** One revision of the incident's report: ?revision=<id>, else the official revision, else the newest. */
export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const raw = new URL(request.url).searchParams.get('revision');
    const revisionId = raw === null ? null : Number(raw);
    if (revisionId !== null && (!Number.isSafeInteger(revisionId) || revisionId < 1)) {
      return NextResponse.json({ error: 'The revision must be a positive whole number' }, { status: 400 });
    }

    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);
    const report = await getReport(incidents, videoId, revisionId, (storageKey) => createR2PlaybackUrl(config, storageKey));
    if (!report) return NextResponse.json({ error: 'Report not found' }, { status: 404 });
    return NextResponse.json({ report });
  } catch (error) {
    return errorResponse(error, 'Could not load the report');
  }
}

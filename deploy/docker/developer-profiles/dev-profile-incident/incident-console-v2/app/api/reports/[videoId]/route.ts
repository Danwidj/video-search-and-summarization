// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { getReport } from '@/lib/application/reports';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';

export const dynamic = 'force-dynamic';

export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const modelRunId = new URL(request.url).searchParams.get('run');
    if (!modelRunId) return NextResponse.json({ error: 'A model run ID is required' }, { status: 400 });

    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);
    const report = await getReport(incidents, { videoId, modelRunId }, (storageKey) => createR2PlaybackUrl(config, storageKey));
    if (!report) return NextResponse.json({ error: 'Report not found' }, { status: 404 });
    return NextResponse.json({ report });
  } catch (error) {
    return errorResponse(error, 'Could not load the report');
  }
}

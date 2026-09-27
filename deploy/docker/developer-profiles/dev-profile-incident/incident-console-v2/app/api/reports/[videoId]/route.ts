// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { buildReportView } from '@/lib/reports/view';

export const dynamic = 'force-dynamic';

export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const modelRunId = new URL(request.url).searchParams.get('run');
    if (!modelRunId) return NextResponse.json({ error: 'A model run ID is required' }, { status: 400 });

    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const [modelRun, video, review, incident, entities, instruments, assets, reportRow] = await Promise.all([
      db.selectOne('model_runs', { id: modelRunId }),
      db.selectOne('videos', { id: videoId }),
      db.selectOne('review_status', { incident_id: videoId, model_run_id: modelRunId }),
      db.selectOne('incidents', { incident_id: videoId, model_run_id: modelRunId }),
      db.selectMany('entities', { filters: { incident_id: videoId, model_run_id: modelRunId } }),
      db.selectMany('instruments', { filters: { incident_id: videoId, model_run_id: modelRunId } }),
      db.selectMany('assets', { filters: { incident_id: videoId, model_run_id: modelRunId } }),
      db.selectOne('reports', { incident_id: videoId, model_run_id: modelRunId }),
    ]);
    if (!modelRun || !video || !incident) return NextResponse.json({ error: 'Report not found' }, { status: 404 });
    if (typeof video.filepath !== 'string' || !video.filepath) throw new Error('The report has no linked R2 video');

    const playbackUrl = await createR2PlaybackUrl(config, video.filepath);
    const report = buildReportView({ videoId, modelRunId, playbackUrl, video, modelRun, incident, entities, instruments, assets, review, reportRow });
    return NextResponse.json({ report });
  } catch (error) {
    return errorResponse(error, 'Could not load the report');
  }
}

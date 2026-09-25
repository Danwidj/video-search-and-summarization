// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import type { AnalysisReport } from '@/lib/analysis/schema';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { reportFromNotes } from '@/lib/reports/storage';

export const dynamic = 'force-dynamic';

export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const modelRunId = new URL(request.url).searchParams.get('run');
    if (!modelRunId) return NextResponse.json({ error: 'A model run ID is required' }, { status: 400 });

    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const [modelRun, video, review, incident, entities, instruments, assets, reportMetadata] = await Promise.all([
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

    const stored = reportFromNotes(modelRun.notes);
    if (typeof video.filepath !== 'string' || !video.filepath) throw new Error('The report has no linked R2 video');

    const playbackUrl = await createR2PlaybackUrl(config, video.filepath);
    const fallback: AnalysisReport = {
      videoId,
      modelRunId,
      reportId: typeof reportMetadata?.id === 'string' ? reportMetadata.id : `${videoId}-${modelRunId}`,
      filename: video.filepath.split('/').pop() || videoId,
      playbackUrl,
      model: typeof modelRun.model_name === 'string' ? modelRun.model_name : 'Unknown model',
      generatedAt: typeof reportMetadata?.generated_datetime === 'string' ? reportMetadata.generated_datetime : typeof modelRun.run_datetime === 'string' ? modelRun.run_datetime : '',
      promptVersion: typeof modelRun.prompt_version === 'string' ? modelRun.prompt_version : undefined,
      title: `${typeof incident.type === 'string' ? incident.type : 'Incident'} report`,
      incident_type: typeof incident.type === 'string' ? incident.type : 'Unclassified',
      description: typeof incident.description === 'string' ? incident.description : 'No summary was recorded.',
      incident_start: typeof incident.start_timestamp === 'string' ? incident.start_timestamp : '',
      incident_end: typeof incident.end_timestamp === 'string' ? incident.end_timestamp : '',
      incident_start_confirmed: false,
      duration_seconds: typeof incident.duration === 'number' ? incident.duration : null,
      severity: typeof incident.severity_level === 'number' ? incident.severity_level : 1,
      severity_reason: 'No separate severity rationale was retained for this report.',
      confidence: typeof incident.confidence_score === 'number' ? incident.confidence_score : 0,
      timeline: [],
      persons: entities.map((row) => ({ description: String(row.description || 'Person'), actions: '' })),
      instruments: instruments.map((row) => ({ name: String(row.name || 'Unknown'), description: String(row.description || 'No description'), threat_level: typeof row.threat_level === 'number' ? row.threat_level : null })),
      assets: assets.map((row) => ({ name: String(row.name || 'Unknown'), description: String(row.description || 'No description') })),
      uncertainties: [],
      location: '',
    };
    const report: AnalysisReport = stored && stored.videoId === videoId && stored.modelRunId === modelRunId ? {
      ...stored,
      incident_type: fallback.incident_type,
      description: fallback.description,
      incident_start: fallback.incident_start,
      incident_end: fallback.incident_end,
      duration_seconds: fallback.duration_seconds,
      severity: fallback.severity,
      confidence: fallback.confidence,
      persons: fallback.persons.length > 0 ? fallback.persons : stored.persons,
      instruments: fallback.instruments.length > 0 ? fallback.instruments : stored.instruments,
      assets: fallback.assets.length > 0 ? fallback.assets : stored.assets,
    } : fallback;
    return NextResponse.json({
      report: {
        ...report,
        playbackUrl,
        promptVersion: typeof modelRun.prompt_version === 'string' ? modelRun.prompt_version : report.promptVersion,
        reviewStatus: typeof review?.status === 'string' ? review.status : 'unreviewed',
        verifiedBy: typeof review?.verified_by === 'string' ? review.verified_by : undefined,
        verifiedAt: typeof review?.verified_at === 'string' ? review.verified_at : undefined,
      },
    });
  } catch (error) {
    return errorResponse(error, 'Could not load the report');
  }
}

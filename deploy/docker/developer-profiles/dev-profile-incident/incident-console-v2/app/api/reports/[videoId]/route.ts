// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import type { AnalysisReport } from '@/lib/analysis/contract-types';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { reportsFromNotes, toSeconds } from '@/lib/reports/storage';

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

    if (typeof video.filepath !== 'string' || !video.filepath) throw new Error('The report has no linked R2 video');
    const playbackUrl = await createR2PlaybackUrl(config, video.filepath);

    const metadata = {
      videoId,
      modelRunId,
      reportId: typeof reportMetadata?.id === 'string' ? reportMetadata.id : `${videoId}-${modelRunId}`,
      filename: video.filepath.split('/').pop() || videoId,
      playbackUrl,
      model: typeof modelRun.model_name === 'string' ? modelRun.model_name : 'Unknown model',
      generatedAt: typeof reportMetadata?.generated_datetime === 'string' ? reportMetadata.generated_datetime : typeof modelRun.run_datetime === 'string' ? modelRun.run_datetime : '',
      promptVersion: typeof modelRun.prompt_version === 'string' ? modelRun.prompt_version : undefined,
    };

    // Relational fallback, for runs whose notes hold no report (e.g. eval, seed or agent-only rows).
    const start = toSeconds(incident.start_timestamp);
    const end = Math.max(start, toSeconds(incident.end_timestamp));
    const fallback: AnalysisReport = {
      ...metadata,
      legacy: true,
      incident: {
        type: typeof incident.type === 'string' ? incident.type : 'Unclassified',
        title: `${typeof incident.type === 'string' ? incident.type : 'Incident'} report`,
        start_timestamp: start,
        end_timestamp: end,
        duration: typeof incident.duration === 'number' ? incident.duration : end - start,
        description: typeof incident.description === 'string' ? incident.description : 'No summary was recorded.',
        severity_level: typeof incident.severity_level === 'number' ? incident.severity_level : 1,
        severity_reason: '',
        confidence_score: typeof incident.confidence_score === 'number' ? incident.confidence_score : null,
        location: null,
      },
      entities: entities.map((row) => ({
        entity_id: String(row.entity_id || ''),
        type: String(row.type || 'unknown'),
        description: String(row.description || ''),
      })),
      instruments: instruments.map((row) => ({
        instrument_id: String(row.instrument_id || ''),
        entity_id: typeof row.entity_id === 'string' ? row.entity_id : null,
        name: String(row.name || 'Unknown'),
        description: String(row.description || ''),
        threat_level: typeof row.threat_level === 'number' ? row.threat_level : 1,
      })),
      assets: assets.map((row) => ({
        asset_id: String(row.asset_id || ''),
        name: String(row.name || 'Unknown'),
        description: String(row.description || ''),
      })),
      timeline: [],
      uncertainties: [],
    };

    // Notes hold the preserved AI report and, after a human edit, the editedReport copy shown by default.
    const stored = reportsFromNotes(modelRun.notes);
    const matches = stored && (!stored.original.videoId || stored.original.videoId === videoId)
      && (!stored.original.modelRunId || stored.original.modelRunId === modelRunId);
    const original: AnalysisReport = matches ? { ...stored!.original, ...metadata, rawModelOutput: stored!.original.rawModelOutput, reportText: stored!.original.reportText, reportTextError: stored!.original.reportTextError } : fallback;
    const current: AnalysisReport = matches && stored!.edited ? { ...original, ...stored!.edited, ...metadata, rawModelOutput: original.rawModelOutput, reportText: original.reportText } : original;

    return NextResponse.json({
      report: {
        ...current,
        originalReport: original,
        playbackUrl,
        reviewStatus: typeof review?.status === 'string' ? review.status : 'unreviewed',
        verifiedBy: typeof review?.verified_by === 'string' ? review.verified_by : undefined,
        verifiedAt: typeof review?.verified_at === 'string' ? review.verified_at : undefined,
      },
    });
  } catch (error) {
    return errorResponse(error, 'Could not load the report');
  }
}

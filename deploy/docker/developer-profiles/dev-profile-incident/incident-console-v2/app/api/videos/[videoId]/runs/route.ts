// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { analysisErrorResponse } from '@/lib/analysis/responses';
import { runContractAnalysis } from '@/lib/analysis/run-contract-analysis';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { isValidR2Key } from '@/lib/r2/key';
import { buildRunHistory } from '@/lib/runs/history';
import type { VideoRunHistory } from '@/lib/runs/types';

export const dynamic = 'force-dynamic';
// The slowest allowlisted model's timeout (contracts/inference.json) plus persistence.
export const maxDuration = 360;

function database() {
  const config = getServiceConfiguration();
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return { config, db: new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!) };
}

/** The video's analysis history: every attempt, successful or failed, newest first. */
export async function GET(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const { config, db } = database();
    const video = await db.selectOne('videos', { id: videoId });
    if (!video) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    const [incidentRows, attemptCandidates] = await Promise.all([
      db.selectMany('incidents', {
        filters: { incident_id: videoId },
        select: 'model_run_id,type,severity_level,model_runs(id,model_name,prompt_version,run_datetime,notes),reports(id,generated_datetime)',
      }),
      db.selectContaining('model_runs', 'notes', `"videoId":"${videoId}"`, 'id,model_name,prompt_version,run_datetime,notes'),
    ]);
    const runIds = incidentRows.map((row) => String(row.model_run_id));
    const usage = runIds.length ? await db.selectIn('incidents', 'model_run_id', runIds, 'model_run_id') : [];
    const perRun = new Map<string, number>();
    for (const row of usage) perRun.set(String(row.model_run_id), (perRun.get(String(row.model_run_id)) ?? 0) + 1);
    const sharedRunIds = new Set([...perRun].filter(([, count]) => count > 1).map(([id]) => id));

    const { runs, counts } = buildRunHistory({ videoId, incidentRows, attemptCandidates, sharedRunIds });
    const filepath = typeof video.filepath === 'string' ? video.filepath : '';
    let playbackUrl: string | null = null;
    if (isValidR2Key(filepath)) {
      try { playbackUrl = await createR2PlaybackUrl(config, filepath); } catch { playbackUrl = null; }
    }
    const officialRunId = typeof video.selected_model_run_id === 'string' ? video.selected_model_run_id : null;
    const history: VideoRunHistory = {
      video: {
        videoId,
        filename: filepath.split('/').pop() || videoId,
        uploadedAt: typeof video.uploaded_datetime === 'string' ? video.uploaded_datetime : null,
        source: typeof video.source === 'string' ? video.source : null,
        playbackUrl,
      },
      runs: runs.map((run) => ({ ...run, isOfficial: run.modelRunId === officialRunId })),
      counts,
      officialRunId,
    };
    return NextResponse.json(history);
  } catch (error) {
    return errorResponse(error, 'Could not load the analysis history');
  }
}

/**
 * Re-analyse the stored video with an allowlisted model: the same canonical
 * request, strict validation and ID-only recovery as a new upload, always a
 * new run, never touching the video row (so its upload time is kept) or any
 * earlier run or report.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const body = (await request.json().catch(() => null)) as { model?: unknown; additionalInstruction?: unknown } | null;
    if (!body || typeof body !== 'object') return NextResponse.json({ error: 'A JSON body with model is required' }, { status: 400 });
    const { config, db } = database();
    if (config.analysisMode !== 'gateway') {
      return NextResponse.json({ error: 'Re-analysis with a selected model is only available in gateway analysis mode' }, { status: 409 });
    }
    if (!config.gatewayUrl) throw new Error('VLM_GATEWAY_URL is not configured');
    const video = await db.selectOne('videos', { id: videoId }, 'id,filepath');
    if (!video) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    if (!isValidR2Key(video.filepath)) return NextResponse.json({ error: 'This video has no stored R2 object to analyse' }, { status: 409 });

    const { run } = await runContractAnalysis({ videoId, r2Key: String(video.filepath), model: body.model, additionalInstruction: body.additionalInstruction }, config);
    return NextResponse.json({
      run: { videoId: run.videoId, modelRunId: run.modelRunId, reportId: run.reportId, model: run.request.model, promptVersion: run.contractVersion, outcome: run.status },
    });
  } catch (error) {
    return analysisErrorResponse(error, 'Re-analysis failed');
  }
}

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
    const [revisionRows, attemptCandidates] = await Promise.all([
      db.selectMany('report_revisions', {
        filters: { video_id: videoId, kind: 'ai' },
        select: 'id,model_run_id,incident_type,severity_level,created_at,model_runs(id,model_name,prompt_version,run_datetime,notes)',
      }),
      db.selectContaining('model_runs', 'notes', `"videoId":"${videoId}"`, 'id,model_name,prompt_version,run_datetime,notes'),
    ]);
    const runIds = revisionRows.map((row) => String(row.model_run_id));
    const usage = runIds.length ? await db.selectIn('report_revisions', 'model_run_id', runIds, 'model_run_id,video_id') : [];
    const videosPerRun = new Map<string, Set<string>>();
    for (const row of usage) {
      const set = videosPerRun.get(String(row.model_run_id)) ?? new Set<string>();
      set.add(String(row.video_id));
      videosPerRun.set(String(row.model_run_id), set);
    }
    const sharedRunIds = new Set([...videosPerRun].filter(([, set]) => set.size > 1).map(([id]) => id));

    const { runs, counts } = buildRunHistory({ videoId, revisionRows, attemptCandidates, sharedRunIds });
    const filepath = typeof video.filepath === 'string' ? video.filepath : '';
    let playbackUrl: string | null = null;
    if (isValidR2Key(filepath)) {
      try { playbackUrl = await createR2PlaybackUrl(config, filepath); } catch { playbackUrl = null; }
    }
    const officialRevisionId = typeof video.official_revision_id === 'number' ? video.official_revision_id : null;
    const history: VideoRunHistory = {
      video: {
        videoId,
        filename: filepath.split('/').pop() || videoId,
        uploadedAt: typeof video.uploaded_datetime === 'string' ? video.uploaded_datetime : null,
        source: typeof video.source === 'string' ? video.source : null,
        playbackUrl,
      },
      runs: runs.map((run) => ({ ...run, isOfficial: run.revision !== null && run.revision.revisionId === officialRevisionId })),
      counts,
      officialRevisionId,
    };
    return NextResponse.json(history);
  } catch (error) {
    return errorResponse(error, 'Could not load the analysis history');
  }
}

/**
 * Re-analyse the stored video with an allowlisted model: the same canonical
 * request, strict validation and ID-only recovery as a new upload, always a
 * new run and a new AI revision, never touching the video row (so its upload
 * time is kept) or any earlier run or revision. additionalInstruction is the
 * reviewer prompt typed in the console.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const body = (await request.json().catch(() => null)) as { model?: unknown; additionalInstruction?: unknown } | null;
    if (!body || typeof body !== 'object') return NextResponse.json({ error: 'A JSON body with model is required' }, { status: 400 });
    const { config, db } = database();
    // Agent mode runs the agent's configured model; choosing another model is gateway-only.
    if (config.analysisMode === 'agent') {
      if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
      if (body.model && body.model !== config.vlmModel) {
        return NextResponse.json({ error: 'Model selection is only available in gateway analysis mode' }, { status: 409 });
      }
    } else if (!config.gatewayUrl) {
      throw new Error('VLM_GATEWAY_URL is not configured');
    }
    const video = await db.selectOne('videos', { id: videoId }, 'id,filepath');
    if (!video) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    if (!isValidR2Key(video.filepath)) return NextResponse.json({ error: 'This video has no stored R2 object to analyse' }, { status: 409 });

    const { run, revisionId } = await runContractAnalysis({ videoId, r2Key: String(video.filepath), model: body.model ?? config.vlmModel, additionalInstruction: body.additionalInstruction }, config);
    return NextResponse.json({
      run: { videoId: run.videoId, modelRunId: run.modelRunId, revisionId, model: run.request.model, promptVersion: run.contractVersion, outcome: run.status },
    });
  } catch (error) {
    return analysisErrorResponse(error, 'Re-analysis failed');
  }
}

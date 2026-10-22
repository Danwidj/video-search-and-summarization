// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { analysisErrorResponse } from '@/lib/analysis/responses';
import { runContractAnalysis } from '@/lib/analysis/run-contract-analysis';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { isValidR2Key } from '@/lib/r2/key';
import type { VideoRunHistory } from '@/lib/runs/types';

export const dynamic = 'force-dynamic';
// The slowest allowlisted model's timeout (contracts/inference.json) plus persistence.
export const maxDuration = 360;

/** The video's analysis history: every attempt, successful or failed, newest first. */
export async function GET(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const config = getServiceConfiguration();
    const found = await getDbAdapters(config).videos.listRuns(videoId);
    if (!found) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    const { video, runs, counts } = found;
    const filepath = video.storageKey ?? '';
    let playbackUrl: string | null = null;
    if (isValidR2Key(filepath)) {
      try { playbackUrl = await createR2PlaybackUrl(config, filepath); } catch { playbackUrl = null; }
    }
    const history: VideoRunHistory = {
      video: { videoId, filename: filepath.split('/').pop() || videoId, uploadedAt: video.uploadedAt, source: video.source, playbackUrl },
      runs,
      counts,
      officialRunId: video.officialRunId,
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
    const config = getServiceConfiguration();
    const { analysisRuns, videos } = getDbAdapters(config);
    if (config.analysisMode !== 'gateway') {
      return NextResponse.json({ error: 'Re-analysis with a selected model is only available in gateway analysis mode' }, { status: 409 });
    }
    if (!config.gatewayUrl) throw new Error('VLM_GATEWAY_URL is not configured');
    const video = await videos.getVideo(videoId);
    if (!video) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    if (!isValidR2Key(video.storageKey)) return NextResponse.json({ error: 'This video has no stored R2 object to analyse' }, { status: 409 });

    const { run } = await runContractAnalysis(
      { videoId, r2Key: video.storageKey, model: body.model, additionalInstruction: body.additionalInstruction },
      config,
      analysisRuns,
    );
    return NextResponse.json({
      run: { videoId: run.videoId, modelRunId: run.modelRunId, reportId: run.reportId, model: run.request.model, promptVersion: run.contractVersion, outcome: run.status },
    });
  } catch (error) {
    return analysisErrorResponse(error, 'Re-analysis failed');
  }
}

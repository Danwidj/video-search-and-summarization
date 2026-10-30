// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getAnalyseVideoPorts } from '@/lib/container';
import { analysisErrorResponse } from '@/lib/http/analysis-responses';
import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import { analyseVideo, type AnalyseVideoInput } from '@/modules/analysis/application/analyse-video';

export const dynamic = 'force-dynamic';
// The slowest allowlisted model's timeout (contracts/inference.json) plus persistence;
// ANALYSIS_DEADLINE_MS in analyse-video.ts keeps the agent call inside it.
export const maxDuration = 360;

interface AnalysisRequest {
  /** Present for a new upload; the video's id is then `filename`. */
  sensorId?: string;
  filepath?: string;
  filename?: string;
  /** Present, with no filepath, to analyse a video that is already stored again. */
  videoName?: string;
  model?: string;
  additionalInstruction?: string;
}

function requireAnalysisConfiguration(): ServiceConfiguration {
  const config = getServiceConfiguration();
  if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return config;
}

/**
 * Analyses one video with the agent and stores the analysis; nothing else. A new upload
 * ({ sensorId, filepath, filename }) creates its incident and video first; { videoName } adds
 * an analysis to a video already stored. Answers { incidentId, videoName, analysisId, ... }.
 */
export async function POST(request: Request) {
  try {
    let body: AnalysisRequest;
    try {
      body = (await request.json()) as AnalysisRequest;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`reading the analysis request failed: ${detail}`);
    }

    const upload = Boolean(body.filepath);
    if (upload ? !body.sensorId || !body.filename : !body.videoName) {
      return NextResponse.json(
        { error: 'sensorId, filepath, and filename are required for an upload; videoName alone re-analyses a stored video' },
        { status: 400 },
      );
    }

    let config: ServiceConfiguration;
    try {
      config = requireAnalysisConfiguration();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`validating service configuration failed: ${detail}`);
    }

    const common = { model: body.model ?? config.vlmModel, additionalInstruction: body.additionalInstruction };
    const input: AnalyseVideoInput = upload
      ? {
          ...common,
          kind: 'upload',
          videoName: body.filename as string,
          storageKey: body.filepath as string,
          sensorId: body.sensorId as string,
        }
      : { ...common, kind: 'reanalysis', videoName: body.videoName as string };

    const result = await analyseVideo(input, getAnalyseVideoPorts(config));
    return NextResponse.json(result);
  } catch (error) {
    return analysisErrorResponse(error, 'Video analysis failed');
  }
}

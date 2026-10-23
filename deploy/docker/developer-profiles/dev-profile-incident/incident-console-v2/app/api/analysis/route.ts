// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { fetchEvidenceEmbeddings } from '@/lib/agent/evidence-embeddings';
import { storeSearchableCrops, type SearchableCropsResult } from '@/lib/application/reports';
import { analysisErrorResponse } from '@/lib/analysis/responses';
import { runContractAnalysis } from '@/lib/analysis/run-contract-analysis';
import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import { compactId } from '@/lib/ids';

// The slowest allowlisted model's timeout (contracts/inference.json) plus persistence.
export const maxDuration = 360;

interface AnalysisRequest {
  sensorId?: string;
  filepath?: string;
  filename?: string;
  model?: string;
  additionalInstruction?: string;
}

function requireAnalysisConfiguration(config: ServiceConfiguration = getServiceConfiguration()): ServiceConfiguration {
  if (config.analysisMode === 'agent') {
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
  } else {
    if (!config.gatewayUrl) throw new Error('VLM_GATEWAY_URL is not configured');
  }
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return config;
}

/** What the upload flow needs to open the new run's report page. */
interface AnalysisRunSummary {
  videoId: string;
  modelRunId: string;
  /** The new AI revision. */
  revisionId: number;
  model: string;
  promptVersion: string;
  /** valid_first_pass or valid_after_structural_repair; failures are returned as errors. */
  outcome: string;
  /** Evidence crops stored so the video is searchable before it has an official revision. */
  searchable: SearchableCropsResult;
}

export async function POST(request: Request) {
  try {
    let input: AnalysisRequest;
    try {
      input = (await request.json()) as AnalysisRequest;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`reading the analysis request failed: ${detail}`);
    }

    if (!input.sensorId || !input.filepath || !input.filename) {
      return NextResponse.json({ error: 'sensorId, filepath, and filename are required' }, { status: 400 });
    }

    let config: ServiceConfiguration;
    try {
      config = requireAnalysisConfiguration();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`validating service configuration failed: ${detail}`);
    }

    const { run, revisionId } = await runContractAnalysis(
      {
        videoId: compactId('v', input.sensorId),
        r2Key: input.filepath,
        model: input.model ?? config.vlmModel,
        additionalInstruction: input.additionalInstruction,
        newVideo: { sensorId: input.sensorId, uploadedAt: new Date().toISOString() },
      },
      config,
    );

    const searchable = await storeSearchableCrops(getDbAdapters(config), run.videoId, revisionId, (id) => fetchEvidenceEmbeddings(config, id));
    const report: AnalysisRunSummary = {
      videoId: run.videoId,
      modelRunId: run.modelRunId,
      revisionId,
      model: run.request.model,
      promptVersion: run.contractVersion,
      outcome: run.status,
      searchable,
    };

    return NextResponse.json({ report });
  } catch (error) {
    return analysisErrorResponse(error, 'Video analysis failed');
  }
}

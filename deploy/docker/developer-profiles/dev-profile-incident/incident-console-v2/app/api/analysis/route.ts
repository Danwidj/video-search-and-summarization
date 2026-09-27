// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';

import { persistAgentBookkeeping, prepareAgentVideo } from '@/lib/analysis/persistence';
import { AnalysisRequestError, runContractAnalysis } from '@/lib/analysis/run-contract-analysis';
import { incidentAnalysisSchema, type AnalysisReport } from '@/lib/analysis/schema';
import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import { errorResponse, readUpstream } from '@/lib/http';
import { compactId } from '@/lib/ids';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl, verifyR2Video } from '@/lib/r2/config';

// The slowest allowlisted model's timeout (contracts/inference.json) plus persistence.
export const maxDuration = 360;

interface AnalysisRequest {
  sensorId?: string;
  filepath?: string;
  filename?: string;
  model?: string;
  reasoning?: boolean;
  promptOverride?: string;
  prompt_override?: string;
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
  reportId: string;
  model: string;
  promptVersion: string;
  /** valid_first_pass or valid_after_structural_repair; failures are returned as errors. */
  outcome: string;
}

async function analyzeViaGateway(
  input: AnalysisRequest & { sensorId: string; filepath: string; filename: string },
  config: ServiceConfiguration,
): Promise<AnalysisRunSummary> {
  const { run } = await runContractAnalysis(
    {
      videoId: compactId('v', input.sensorId),
      r2Key: input.filepath,
      model: input.model ?? config.vlmModel,
      newVideo: { sensorId: input.sensorId, uploadedAt: new Date().toISOString() },
    },
    config,
  );
  return { videoId: run.videoId, modelRunId: run.modelRunId, reportId: run.reportId, model: run.request.model, promptVersion: run.contractVersion, outcome: run.status };
}

async function analyzeViaAgent(
  input: AnalysisRequest & { sensorId: string; filepath: string; filename: string },
  config: ServiceConfiguration,
): Promise<AnalysisReport> {
  let operation = 'creating the signed R2 video URL';
  try {
    operation = 'verifying the R2 video object';
    await verifyR2Video(config, input.filepath);
    operation = 'creating the signed R2 video URL';
    const playbackUrl = await createR2PlaybackUrl(config, input.filepath);

    const generatedAt = new Date().toISOString();
    const videoId = compactId('v', input.sensorId);
    const modelRunId = compactId('m', `${videoId}:${generatedAt}:${randomUUID()}`);
    const reportId = compactId('r', `${videoId}:${modelRunId}`);

    const requestBody: { model_run_id: string; reasoning?: boolean; prompt_override?: string } = {
      model_run_id: modelRunId,
    };
    if (typeof input.reasoning === 'boolean') {
      requestBody.reasoning = input.reasoning;
    }
    const promptOverride = input.promptOverride || input.prompt_override;
    if (promptOverride) {
      requestBody.prompt_override = promptOverride;
    }

    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    operation = 'saving the video to PostgREST';
    await prepareAgentVideo(db, { videoId }, {
      r2Key: input.filepath,
      sensorId: input.sensorId,
      uploadedAt: generatedAt,
    });

    operation = 'calling the incident agent';
    const endpoint = `${config.agentUrl!.replace(/\/$/, '')}/api/v1/incidents/${videoId}/analyze`;
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    operation = 'parsing the incident agent response';
    const agentPayload = (await readUpstream(response, 'Incident agent')) as Record<string, unknown> | null;
    if (!agentPayload || typeof agentPayload !== 'object') {
      throw new Error('Incident agent returned an empty report');
    }

    const rawOutput = JSON.stringify(agentPayload);

    operation = 'validating the incident report';
    const analysis = incidentAnalysisSchema.parse(agentPayload);

    const report: AnalysisReport = {
      ...analysis,
      videoId,
      modelRunId,
      reportId,
      filename: input.filename,
      playbackUrl,
      model: (typeof agentPayload.model === 'string' && agentPayload.model) || (typeof agentPayload.model_name === 'string' && agentPayload.model_name) || 'vss-agent',
      generatedAt,
      rawModelOutput: rawOutput,
      normalizedModelOutput: rawOutput,
    };

    await persistAgentBookkeeping(db, report, {
      r2Key: input.filepath,
      sensorId: input.sensorId,
      uploadedAt: generatedAt,
    }, (nextOperation) => { operation = nextOperation; });

    return report;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`${operation} failed: ${detail}`);
  }
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

    // The agent still uses its own contract and model configuration (plan phase
    // 3 of .docs/prompt-contract-plan.md), so model selection is gateway-only.
    if (config.analysisMode === 'agent' && input.model && input.model !== config.vlmModel) {
      return NextResponse.json({ error: 'Model selection is only available in gateway analysis mode' }, { status: 409 });
    }

    const report =
      config.analysisMode === 'agent'
        ? await analyzeViaAgent(input as AnalysisRequest & { sensorId: string; filepath: string; filename: string }, config)
        : await analyzeViaGateway(input as AnalysisRequest & { sensorId: string; filepath: string; filename: string }, config);

    return NextResponse.json({ report });
  } catch (error) {
    if (error instanceof AnalysisRequestError) {
      return NextResponse.json({ error: error.message, ...(error.details || {}) }, { status: error.status });
    }
    return errorResponse(error, 'Video analysis failed');
  }
}

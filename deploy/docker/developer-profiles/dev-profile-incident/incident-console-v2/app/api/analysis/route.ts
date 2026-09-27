// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';

import { ContractError, contractVersion, validateContractReport } from '@/lib/analysis/contract';
import type { AnalysisReport } from '@/lib/analysis/contract-types';
import { runP1, runRP1 } from '@/lib/analysis/generate';
import { persistAgentBookkeeping, persistGatewayAnalysis, prepareAgentVideo } from '@/lib/analysis/persistence';
import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import { GatewayClient } from '@/lib/gateway/client';
import { errorResponse, readUpstream } from '@/lib/http';
import { compactId } from '@/lib/ids';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl, verifyR2Video } from '@/lib/r2/config';

// P1 with 64 frames or a reasoning model, plus RP1, can take several minutes.
export const maxDuration = 300;

interface AnalysisRequest {
  sensorId?: string;
  filepath?: string;
  filename?: string;
}

type ValidRequest = { sensorId: string; filepath: string; filename: string };

/** A model output that breaks the contract: surfaced as HTTP 422, never repaired. */
class ContractViolation extends Error {}

function requireAnalysisConfiguration(config: ServiceConfiguration = getServiceConfiguration()): ServiceConfiguration {
  if (config.analysisMode === 'agent') {
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
  } else {
    if (!config.gatewayUrl) throw new Error('VLM_GATEWAY_URL is not configured');
  }
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return config;
}

function newIdentifiers(sensorId: string) {
  const generatedAt = new Date().toISOString();
  const videoId = compactId('v', sensorId);
  const modelRunId = compactId('m', `${videoId}:${generatedAt}:${randomUUID()}`);
  const reportId = compactId('r', `${videoId}:${modelRunId}`);
  return { generatedAt, videoId, modelRunId, reportId };
}

async function analyzeViaGateway(input: ValidRequest, config: ServiceConfiguration): Promise<AnalysisReport> {
  let operation = 'verifying the R2 video object';
  try {
    await verifyR2Video(config, input.filepath);
    operation = 'creating the signed R2 video URL';
    const playbackUrl = await createR2PlaybackUrl(config, input.filepath);
    const gateway = new GatewayClient(config.gatewayUrl!);

    operation = 'extracting the incident (P1)';
    let p1;
    try {
      p1 = await runP1(gateway, config.vlmModel, playbackUrl);
    } catch (error) {
      if (error instanceof ContractError) throw new ContractViolation(error.message);
      throw error;
    }

    operation = 'writing the incident report (RP1)';
    const rp1 = await runRP1(gateway, p1.report);

    const ids = newIdentifiers(input.sensorId);
    const report: AnalysisReport = {
      ...p1.report,
      ...ids,
      filename: input.filename,
      playbackUrl,
      model: p1.model,
      promptVersion: contractVersion(),
      rawModelOutput: p1.rawModelOutput,
      ...rp1,
    };

    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    await persistGatewayAnalysis(db, report, {
      r2Key: input.filepath,
      sensorId: input.sensorId,
      uploadedAt: ids.generatedAt,
    }, (nextOperation) => { operation = nextOperation; });
    return report;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (error instanceof ContractViolation) throw new ContractViolation(`${operation} failed: ${detail}`);
    throw new Error(`${operation} failed: ${detail}`);
  }
}

interface AgentAnalyzeResponse {
  report?: unknown;
  report_text?: string | null;
  report_text_error?: string | null;
  model?: string;
  contract_version?: string;
  raw_output?: string;
}

async function analyzeViaAgent(input: ValidRequest, config: ServiceConfiguration): Promise<AnalysisReport> {
  let operation = 'verifying the R2 video object';
  try {
    await verifyR2Video(config, input.filepath);
    operation = 'creating the signed R2 video URL';
    const playbackUrl = await createR2PlaybackUrl(config, input.filepath);
    const ids = newIdentifiers(input.sensorId);

    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    operation = 'saving the video to PostgREST';
    await prepareAgentVideo(db, ids, { r2Key: input.filepath, sensorId: input.sensorId, uploadedAt: ids.generatedAt });

    operation = 'calling the incident agent';
    const endpoint = `${config.agentUrl!.replace(/\/$/, '')}/api/v1/incidents/${ids.videoId}/analyze`;
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // The agent runs the same P1 -> RP1 call on the same signed URL, so it needs no R2 credentials.
      body: JSON.stringify({ model_run_id: ids.modelRunId, video_url: playbackUrl }),
    });
    if (response.status === 422) {
      const payload = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ContractViolation(`the agent rejected the model output: ${String(payload.detail ?? 'contract violation')}`);
    }
    const payload = (await readUpstream(response, 'Incident agent')) as AgentAnalyzeResponse | null;

    operation = 'validating the agent report against the contract';
    let validated;
    try {
      validated = validateContractReport(payload?.report);
    } catch (error) {
      if (error instanceof ContractError) throw new ContractViolation(error.message);
      throw error;
    }

    const report: AnalysisReport = {
      ...validated,
      ...ids,
      filename: input.filename,
      playbackUrl,
      model: payload?.model || 'vss-agent',
      promptVersion: payload?.contract_version || contractVersion(),
      rawModelOutput: payload?.raw_output,
      reportText: payload?.report_text ?? undefined,
      reportTextError: payload?.report_text_error ?? undefined,
    };

    await persistAgentBookkeeping(db, report, {
      r2Key: input.filepath,
      sensorId: input.sensorId,
      uploadedAt: ids.generatedAt,
    }, (nextOperation) => { operation = nextOperation; });
    return report;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (error instanceof ContractViolation) throw new ContractViolation(`${operation} failed: ${detail}`);
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

    const valid = input as ValidRequest;
    const report = config.analysisMode === 'agent' ? await analyzeViaAgent(valid, config) : await analyzeViaGateway(valid, config);
    return NextResponse.json({ report });
  } catch (error) {
    if (error instanceof ContractViolation) {
      return NextResponse.json({ error: `The model output did not match the incident contract: ${error.message}` }, { status: 422 });
    }
    return errorResponse(error, 'Video analysis failed');
  }
}

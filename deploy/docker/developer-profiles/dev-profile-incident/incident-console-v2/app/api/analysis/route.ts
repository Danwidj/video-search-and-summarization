// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';

import { parseIncidentAnalysis } from '@/lib/analysis/parse';
import { INCIDENT_ANALYSIS_PROMPT, INCIDENT_PROMPT_VERSION } from '@/lib/analysis/prompt';
import { incidentAnalysisSchema, type AnalysisReport } from '@/lib/analysis/schema';
import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import { GatewayClient } from '@/lib/gateway/client';
import { errorResponse, readUpstream } from '@/lib/http';
import { compactId } from '@/lib/ids';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';

export const maxDuration = 120;

interface AnalysisRequest {
  sensorId?: string;
  filepath?: string;
  filename?: string;
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

async function saveVideo(
  db: PostgrestClient,
  video: { videoId: string; filepath: string; sensorId: string; uploadedAt: string; duration?: number | null },
): Promise<void> {
  const row: Record<string, unknown> = {
    id: video.videoId,
    filepath: video.filepath,
    source: video.sensorId,
    uploaded_datetime: video.uploadedAt,
  };
  if (video.duration !== undefined) row.duration = video.duration;
  await db.upsert('videos', row, 'id');
}

async function saveModelRun(db: PostgrestClient, report: AnalysisReport): Promise<void> {
  await db.upsert(
    'model_runs',
    {
      id: report.modelRunId,
      model_name: report.model,
      model_version: null,
      prompt_version: report.promptVersion ?? null,
      run_datetime: report.generatedAt,
      notes: JSON.stringify({
        incidentConsoleV2: {
          report,
          rawModelOutput: report.rawModelOutput,
          normalizedModelOutput: report.normalizedModelOutput,
        },
      }),
    },
    'id',
  );
}

async function saveReport(db: PostgrestClient, report: AnalysisReport): Promise<void> {
  await db.upsert(
    'reports',
    {
      id: report.reportId,
      incident_id: report.videoId,
      query_id: null,
      model_run_id: report.modelRunId,
      filepath: null,
      generated_datetime: report.generatedAt,
    },
    'id',
  );
}

async function analyzeViaGateway(
  input: AnalysisRequest & { sensorId: string; filepath: string; filename: string },
  config: ServiceConfiguration,
): Promise<AnalysisReport> {
  let operation = 'creating the signed R2 video URL';
  try {
    const playbackUrl = await createR2PlaybackUrl(config, input.filepath);
    const gateway = new GatewayClient(config.gatewayUrl!);
    operation = 'calling the VLM gateway';
    const completion = await gateway.complete({
      model: config.vlmModel,
      messages: [
        {
          role: 'user',
          content: [
            { type: 'text', text: INCIDENT_ANALYSIS_PROMPT },
            { type: 'video_url', video_url: { url: playbackUrl } },
          ],
        },
      ],
      stream: false,
      temperature: 0,
      max_tokens: 4096,
    });
    const content = completion.choices[0]?.message.content;
    if (!content) throw new Error('The VLM returned no report content');
    let normalizedModelOutput = content;
    let analysis;
    try {
      operation = 'validating the VLM response';
      analysis = parseIncidentAnalysis(content);
    } catch (firstError) {
      operation = 'repairing the VLM response JSON';
      const corrected = await gateway.complete({
        model: config.vlmModel,
        messages: [
          {
            role: 'user',
            content: `Convert the response below into the exact JSON structure originally requested. Return JSON only. Preserve its factual content and do not add new observations. Numeric fields must be JSON numbers, never quoted strings: use 3, not "3". For instruments.threat_level, use an integer from 1 to 5 or null when unknown.\n\n${content}`,
          },
        ],
        stream: false,
        temperature: 0,
        max_tokens: 4096,
      });
      const correctedContent = corrected.choices[0]?.message.content;
      if (!correctedContent) throw firstError;
      normalizedModelOutput = correctedContent;
      analysis = parseIncidentAnalysis(correctedContent);
    }

    const generatedAt = new Date().toISOString();
    const videoId = compactId('v', input.sensorId);
    const modelRunId = compactId('m', `${videoId}:${generatedAt}:${randomUUID()}`);
    const reportId = compactId('r', `${videoId}:${modelRunId}`);
    const report: AnalysisReport = {
      ...analysis,
      videoId,
      modelRunId,
      reportId,
      filename: input.filename,
      playbackUrl,
      model: completion.model || config.vlmModel,
      generatedAt,
      promptVersion: INCIDENT_PROMPT_VERSION,
      rawModelOutput: content,
      normalizedModelOutput,
    };

    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    operation = 'saving the video to PostgREST';
    await saveVideo(db, {
      videoId,
      filepath: input.filepath,
      sensorId: input.sensorId,
      uploadedAt: generatedAt,
      duration: analysis.duration_seconds,
    });
    operation = 'saving the model run to PostgREST';
    await saveModelRun(db, report);
    operation = 'saving the incident through the PostgREST RPC';
    await db.insertIncident({
      p_incident_id: videoId,
      p_model_run_id: modelRunId,
      p_type: analysis.incident_type,
      p_start_timestamp: analysis.incident_start,
      p_end_timestamp: analysis.incident_end,
      p_duration: analysis.duration_seconds,
      p_description: analysis.description,
      p_severity_level: analysis.severity,
      p_confidence_score: analysis.confidence,
    });

    operation = 'resetting incident evidence in PostgREST';
    await Promise.all([
      db.deleteWhere('entities', { incident_id: videoId, model_run_id: modelRunId }),
      db.deleteWhere('instruments', { incident_id: videoId, model_run_id: modelRunId }),
      db.deleteWhere('assets', { incident_id: videoId, model_run_id: modelRunId }),
    ]);
    if (analysis.persons.length) {
      operation = 'saving entities to PostgREST';
      await db.upsert(
        'entities',
        analysis.persons.map((person, index) => ({
          incident_id: videoId,
          model_run_id: modelRunId,
          entity_id: `e${String(index + 1).padStart(2, '0')}`,
          type: 'person',
          description: [person.description?.trim(), person.actions?.trim()].filter(Boolean).join(' ') || 'Person',
          image: null,
        })),
      );
    }
    if (analysis.instruments.length) {
      operation = 'saving instruments to PostgREST';
      await db.upsert(
        'instruments',
        analysis.instruments.map((item, index) => ({
          incident_id: videoId,
          model_run_id: modelRunId,
          instrument_id: `i${String(index + 1).padStart(2, '0')}`,
          entity_id: null,
          name: item.name,
          description: item.description,
          threat_level: item.threat_level,
          image: null,
        })),
      );
    }
    if (analysis.assets.length) {
      operation = 'saving assets to PostgREST';
      await db.upsert(
        'assets',
        analysis.assets.map((item, index) => ({
          incident_id: videoId,
          model_run_id: modelRunId,
          asset_id: `a${String(index + 1).padStart(2, '0')}`,
          name: item.name,
          description: item.description,
          image: null,
        })),
      );
    }
    operation = 'saving report metadata to PostgREST';
    await saveReport(db, report);

    return report;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`${operation} failed: ${detail}`);
  }
}

async function analyzeViaAgent(
  input: AnalysisRequest & { sensorId: string; filepath: string; filename: string },
  config: ServiceConfiguration,
): Promise<AnalysisReport> {
  let operation = 'creating the signed R2 video URL';
  try {
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
    await saveVideo(db, { videoId, filepath: input.filepath, sensorId: input.sensorId, uploadedAt: generatedAt });

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

    operation = 'saving the model run to PostgREST';
    await saveModelRun(db, report);
    operation = 'restoring the video R2 key in PostgREST';
    await saveVideo(db, { videoId, filepath: input.filepath, sensorId: input.sensorId, uploadedAt: generatedAt });
    operation = 'saving report metadata to PostgREST';
    await saveReport(db, report);

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

    const report =
      config.analysisMode === 'agent'
        ? await analyzeViaAgent(input as AnalysisRequest & { sensorId: string; filepath: string; filename: string }, config)
        : await analyzeViaGateway(input as AnalysisRequest & { sensorId: string; filepath: string; filename: string }, config);

    return NextResponse.json({ report });
  } catch (error) {
    return errorResponse(error, 'Video analysis failed');
  }
}

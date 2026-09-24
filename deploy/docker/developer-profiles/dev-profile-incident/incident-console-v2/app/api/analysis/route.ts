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

interface AgentIncidentReportResponse {
  incident_type?: string;
  severity?: number;
  confidence?: number;
  incident_start?: string | null;
  incident_end?: string | null;
  incident_start_confirmed?: boolean;
  description?: string;
  summary?: string;
  persons?: Array<{
    description?: string;
    actions?: string;
  }>;
  entities?: Array<{
    type?: string;
    description?: string;
  }>;
  location?: string;
  title?: string;
  severity_reason?: string;
  timeline?: Array<{
    start_seconds?: number;
    end_seconds?: number | null;
    description?: string;
  }>;
  instruments?: Array<{
    name?: string;
    description?: string;
    threat_level?: number | null;
  }>;
  assets?: Array<{
    name?: string;
    description?: string;
  }>;
  uncertainties?: string[];
  duration_seconds?: number | null;
  model_name?: string;
  model?: string;
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
            content: `Convert the response below into the exact JSON structure originally requested. Return JSON only. Preserve its factual content and do not add new observations. Numeric fields must be JSON numbers, never quoted strings: use 3, not "3". For instruments.threatLevel, use an integer from 1 to 5 or null when unknown.\n\n${content}`,
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
      duration: analysis.durationSeconds,
    });
    operation = 'saving the model run to PostgREST';
    await saveModelRun(db, report);
    operation = 'saving the incident through the PostgREST RPC';
    await db.insertIncident({
      p_incident_id: videoId,
      p_model_run_id: modelRunId,
      p_type: analysis.incidentType,
      p_start_timestamp: analysis.startTimestamp,
      p_end_timestamp: analysis.endTimestamp,
      p_duration: analysis.durationSeconds,
      p_description: analysis.summary,
      p_severity_level: analysis.severityLevel,
      p_confidence_score: analysis.confidenceScore,
    });

    operation = 'resetting incident evidence in PostgREST';
    await Promise.all([
      db.deleteWhere('entities', { incident_id: videoId, model_run_id: modelRunId }),
      db.deleteWhere('instruments', { incident_id: videoId, model_run_id: modelRunId }),
      db.deleteWhere('assets', { incident_id: videoId, model_run_id: modelRunId }),
    ]);
    if (analysis.entities.length) {
      operation = 'saving entities to PostgREST';
      await db.upsert(
        'entities',
        analysis.entities.map((item, index) => ({
          incident_id: videoId,
          model_run_id: modelRunId,
          entity_id: `e${String(index + 1).padStart(2, '0')}`,
          type: item.type,
          description: item.description,
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
          threat_level: item.threatLevel,
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
    const agentPayload = (await readUpstream(response, 'Incident agent')) as AgentIncidentReportResponse | null;
    if (!agentPayload || typeof agentPayload !== 'object') {
      throw new Error('Incident agent returned an empty report');
    }

    const rawOutput = JSON.stringify(agentPayload);

    operation = 'mapping the incident report';
    const title = (agentPayload.title || '').trim() || 'Incident Report';
    const incidentType = (agentPayload.incident_type || '').trim() || 'other';
    const summary = (agentPayload.description || agentPayload.summary || '').trim() || 'No incident summary available.';
    const startTimestamp =
      agentPayload.incident_start && agentPayload.incident_start.trim().length > 0
        ? agentPayload.incident_start.trim()
        : null;
    const endTimestamp =
      agentPayload.incident_end && agentPayload.incident_end.trim().length > 0
        ? agentPayload.incident_end.trim()
        : null;
    const durationSeconds =
      typeof agentPayload.duration_seconds === 'number' && agentPayload.duration_seconds >= 0
        ? Math.round(agentPayload.duration_seconds)
        : null;
    const severityLevel = Math.min(5, Math.max(1, Math.round(agentPayload.severity ?? 1)));
    const severityReason = (agentPayload.severity_reason || '').trim() || 'Assessed by agent.';
    const confidenceScore =
      typeof agentPayload.confidence === 'number' ? Math.min(1, Math.max(0, agentPayload.confidence)) : 0;

    const timeline = Array.isArray(agentPayload.timeline)
      ? agentPayload.timeline.map((item) => ({
          startSeconds: typeof item.start_seconds === 'number' ? Math.max(0, item.start_seconds) : 0,
          endSeconds: typeof item.end_seconds === 'number' ? Math.max(0, item.end_seconds) : null,
          description: (item.description || '').trim() || 'Observed event',
        }))
      : [];

    let entities: Array<{ type: 'human' | 'animal' | 'unknown'; description: string }> = [];
    if (Array.isArray(agentPayload.entities) && agentPayload.entities.length > 0) {
      entities = agentPayload.entities.map((item) => {
        let type: 'human' | 'animal' | 'unknown' = 'unknown';
        const lower = (item.type || '').toLowerCase();
        if (lower === 'human' || lower === 'person') type = 'human';
        else if (lower === 'animal') type = 'animal';
        return {
          type,
          description: (item.description || '').trim() || 'Entity',
        };
      });
    } else if (Array.isArray(agentPayload.persons)) {
      entities = agentPayload.persons.map((person) => {
        const desc = [person.description?.trim(), person.actions?.trim()].filter(Boolean).join(': ');
        return {
          type: 'human' as const,
          description: desc || person.description?.trim() || 'Person',
        };
      });
    }

    const instruments = Array.isArray(agentPayload.instruments)
      ? agentPayload.instruments.map((inst) => ({
          name: (inst.name || '').trim() || 'Instrument',
          description: (inst.description || '').trim() || 'Identified instrument',
          threatLevel:
            typeof inst.threat_level === 'number'
              ? Math.min(5, Math.max(1, Math.round(inst.threat_level)))
              : null,
        }))
      : [];

    const assets = Array.isArray(agentPayload.assets)
      ? agentPayload.assets.map((asset) => ({
          name: (asset.name || '').trim() || 'Asset',
          description: (asset.description || '').trim() || 'Identified asset',
        }))
      : [];

    const uncertainties = Array.isArray(agentPayload.uncertainties)
      ? agentPayload.uncertainties.map((u) => String(u).trim()).filter(Boolean)
      : [];

    const analysis = incidentAnalysisSchema.parse({
      title,
      incidentType,
      summary,
      startTimestamp,
      endTimestamp,
      durationSeconds,
      severityLevel,
      severityReason,
      confidenceScore,
      timeline,
      entities,
      instruments,
      assets,
      uncertainties,
    });

    const report: AnalysisReport = {
      ...analysis,
      videoId,
      modelRunId,
      reportId,
      filename: input.filename,
      playbackUrl,
      model: agentPayload.model || agentPayload.model_name || 'vss-agent',
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

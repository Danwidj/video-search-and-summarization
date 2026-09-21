// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';

import { INCIDENT_ANALYSIS_PROMPT, INCIDENT_PROMPT_VERSION } from '@/lib/analysis/prompt';
import { parseIncidentAnalysis } from '@/lib/analysis/parse';
import type { AnalysisReport } from '@/lib/analysis/schema';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { GatewayClient } from '@/lib/gateway/client';
import { errorResponse } from '@/lib/http';
import { compactId } from '@/lib/ids';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';

export const maxDuration = 120;

interface AnalysisRequest {
  sensorId?: string;
  filepath?: string;
  filename?: string;
}

function requireAnalysisConfiguration() {
  const config = getServiceConfiguration();
  if (!config.gatewayUrl) throw new Error('VLM_GATEWAY_URL is not configured');
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return config;
}

export async function POST(request: Request) {
  let operation = 'reading the analysis request';
  try {
    const input = (await request.json()) as AnalysisRequest;
    if (!input.sensorId || !input.filepath || !input.filename) {
      return NextResponse.json({ error: 'sensorId, filepath, and filename are required' }, { status: 400 });
    }

    operation = 'validating service configuration';
    const config = requireAnalysisConfiguration();
    operation = 'creating the signed R2 video URL';
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
            content: `Convert the response below into the exact JSON structure originally requested. Return JSON only. Preserve its factual content and do not add new observations.\n\n${content}`,
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
    await db.upsert(
      'videos',
      {
        id: videoId,
        filepath: input.filepath,
        duration: analysis.durationSeconds,
        source: input.sensorId,
        uploaded_datetime: generatedAt,
      },
      'id',
    );
    operation = 'saving the model run to PostgREST';
    await db.upsert(
      'model_runs',
      {
        id: modelRunId,
        model_name: report.model,
        model_version: null,
        prompt_version: INCIDENT_PROMPT_VERSION,
        run_datetime: generatedAt,
        notes: JSON.stringify({
          incidentConsoleV2: {
            report,
            rawModelOutput: content,
            normalizedModelOutput,
          },
        }),
      },
      'id',
    );
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
    await db.upsert(
      'reports',
      {
        id: reportId,
        incident_id: videoId,
        query_id: null,
        model_run_id: modelRunId,
        filepath: null,
        generated_datetime: generatedAt,
      },
      'id',
    );

    return NextResponse.json({ report });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return errorResponse(new Error(`${operation} failed: ${detail}`), 'Video analysis failed');
  }
}

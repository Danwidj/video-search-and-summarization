// SPDX-License-Identifier: Apache-2.0

import type { AnalysisReport } from '@/lib/analysis/schema';
import { PostgrestClient } from '@/lib/postgrest/client';

interface VideoReference {
  r2Key: string;
  sensorId: string;
  uploadedAt: string;
  duration?: number | null;
}

async function saveVideo(db: PostgrestClient, report: { videoId: string }, video: VideoReference): Promise<void> {
  const row: Record<string, unknown> = {
    id: report.videoId,
    filepath: video.r2Key,
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

export async function verifySavedReport(
  db: PostgrestClient,
  report: AnalysisReport,
  expectedR2Key: string,
): Promise<void> {
  const [video, modelRun, incident, reportRow] = await Promise.all([
    db.selectOne('videos', { id: report.videoId }, 'id,filepath'),
    db.selectOne('model_runs', { id: report.modelRunId }, 'id'),
    db.selectOne('incidents', { incident_id: report.videoId, model_run_id: report.modelRunId }, 'incident_id,model_run_id'),
    db.selectOne('reports', { id: report.reportId }, 'id,incident_id,model_run_id'),
  ]);

  const missing = [
    !video && 'videos',
    !modelRun && 'model_runs',
    !incident && 'incidents',
    !reportRow && 'reports',
  ].filter(Boolean);
  if (missing.length > 0) throw new Error(`persistence verification found missing rows: ${missing.join(', ')}`);
  if (video?.filepath !== expectedR2Key) {
    throw new Error('persistence verification found an unexpected videos.filepath value');
  }
}

export async function persistGatewayAnalysis(
  db: PostgrestClient,
  report: AnalysisReport,
  video: VideoReference,
  setOperation: (operation: string) => void,
): Promise<void> {
  setOperation('saving the video to PostgREST');
  await saveVideo(db, report, video);
  setOperation('saving the model run to PostgREST');
  await saveModelRun(db, report);
  setOperation('saving the incident through the PostgREST RPC');
  await db.insertIncident({
    p_incident_id: report.videoId,
    p_model_run_id: report.modelRunId,
    p_type: report.incident_type,
    p_start_timestamp: report.incident_start,
    p_end_timestamp: report.incident_end,
    p_duration: report.duration_seconds,
    p_description: report.description,
    p_severity_level: report.severity,
    p_confidence_score: report.confidence,
  });

  setOperation('resetting incident evidence in PostgREST');
  await Promise.all([
    db.deleteWhere('entities', { incident_id: report.videoId, model_run_id: report.modelRunId }),
    db.deleteWhere('instruments', { incident_id: report.videoId, model_run_id: report.modelRunId }),
    db.deleteWhere('assets', { incident_id: report.videoId, model_run_id: report.modelRunId }),
  ]);
  if (report.persons.length) {
    setOperation('saving entities to PostgREST');
    await db.upsert('entities', report.persons.map((person, index) => ({
      incident_id: report.videoId,
      model_run_id: report.modelRunId,
      entity_id: `e${String(index + 1).padStart(2, '0')}`,
      type: 'person',
      description: [person.description?.trim(), person.actions?.trim()].filter(Boolean).join(' ') || 'Person',
      image: null,
    })));
  }
  if (report.instruments.length) {
    setOperation('saving instruments to PostgREST');
    await db.upsert('instruments', report.instruments.map((item, index) => ({
      incident_id: report.videoId,
      model_run_id: report.modelRunId,
      instrument_id: `i${String(index + 1).padStart(2, '0')}`,
      entity_id: null,
      name: item.name,
      description: item.description,
      threat_level: item.threat_level,
      image: null,
    })));
  }
  if (report.assets.length) {
    setOperation('saving assets to PostgREST');
    await db.upsert('assets', report.assets.map((item, index) => ({
      incident_id: report.videoId,
      model_run_id: report.modelRunId,
      asset_id: `a${String(index + 1).padStart(2, '0')}`,
      name: item.name,
      description: item.description,
      image: null,
    })));
  }
  setOperation('saving report metadata to PostgREST');
  await saveReport(db, report);
  setOperation('verifying the persisted report in PostgREST');
  await verifySavedReport(db, report, video.r2Key);
}

export async function persistAgentBookkeeping(
  db: PostgrestClient,
  report: AnalysisReport,
  video: VideoReference,
  setOperation: (operation: string) => void,
): Promise<void> {
  setOperation('saving the model run to PostgREST');
  await saveModelRun(db, report);
  setOperation('restoring the video R2 key in PostgREST');
  await saveVideo(db, report, video);
  setOperation('saving report metadata to PostgREST');
  await saveReport(db, report);
  setOperation('verifying the persisted report in PostgREST');
  await verifySavedReport(db, report, video.r2Key);
}

export async function prepareAgentVideo(
  db: PostgrestClient,
  report: { videoId: string },
  video: VideoReference,
): Promise<void> {
  await saveVideo(db, report, video);
}

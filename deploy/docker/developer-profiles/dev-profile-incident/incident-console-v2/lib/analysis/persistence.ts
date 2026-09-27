// SPDX-License-Identifier: Apache-2.0

import { contractPart, type AnalysisReport } from '@/lib/analysis/contract-types';
import { PostgrestClient } from '@/lib/postgrest/client';

interface VideoReference {
  r2Key: string;
  sensorId: string;
  uploadedAt: string;
}

async function saveVideo(db: PostgrestClient, report: { videoId: string }, video: VideoReference): Promise<void> {
  await db.upsert(
    'videos',
    { id: report.videoId, filepath: video.r2Key, source: video.sensorId, uploaded_datetime: video.uploadedAt },
    'id',
  );
}

/** Stored notes shape: {"incidentConsoleV2": {report, rawModelOutput, reportText?, editedReport?}}. */
export function notesForReport(report: AnalysisReport): string {
  return JSON.stringify({
    incidentConsoleV2: {
      report,
      rawModelOutput: report.rawModelOutput,
      reportText: report.reportText,
    },
  });
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
      notes: notesForReport(report),
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

export async function verifySavedReport(db: PostgrestClient, report: AnalysisReport, expectedR2Key: string): Promise<void> {
  const [video, modelRun, incident, reportRow] = await Promise.all([
    db.selectOne('videos', { id: report.videoId }, 'id,filepath'),
    db.selectOne('model_runs', { id: report.modelRunId }, 'id'),
    db.selectOne('incidents', { incident_id: report.videoId, model_run_id: report.modelRunId }, 'incident_id,model_run_id'),
    db.selectOne('reports', { id: report.reportId }, 'id,incident_id,model_run_id'),
  ]);

  const missing = [!video && 'videos', !modelRun && 'model_runs', !incident && 'incidents', !reportRow && 'reports'].filter(Boolean);
  if (missing.length > 0) throw new Error(`persistence verification found missing rows: ${missing.join(', ')}`);
  if (video?.filepath !== expectedR2Key) throw new Error('persistence verification found an unexpected videos.filepath value');
}

/** incidents-table columns for a contract report (timestamps stored as bare seconds, like eval). */
export function incidentColumns(report: AnalysisReport) {
  const { incident } = contractPart(report);
  return {
    type: incident.type,
    start_timestamp: String(incident.start_timestamp),
    end_timestamp: String(incident.end_timestamp),
    duration: incident.duration,
    description: incident.description,
    severity_level: incident.severity_level,
    confidence_score: incident.confidence_score,
  };
}

/** Gateway mode: the console is the only writer, so it persists every table. */
export async function persistGatewayAnalysis(
  db: PostgrestClient,
  report: AnalysisReport,
  video: VideoReference,
  setOperation: (operation: string) => void,
): Promise<void> {
  const ids = { incident_id: report.videoId, model_run_id: report.modelRunId };
  setOperation('saving the video to PostgREST');
  await saveVideo(db, report, video);
  setOperation('saving the model run to PostgREST');
  await saveModelRun(db, report);
  setOperation('saving the incident through the PostgREST RPC');
  const columns = incidentColumns(report);
  await db.insertIncident({
    p_incident_id: report.videoId,
    p_model_run_id: report.modelRunId,
    p_type: columns.type,
    p_start_timestamp: columns.start_timestamp,
    p_end_timestamp: columns.end_timestamp,
    p_duration: columns.duration,
    p_description: columns.description,
    p_severity_level: columns.severity_level,
    p_confidence_score: columns.confidence_score,
  });

  setOperation('resetting incident evidence in PostgREST');
  await Promise.all([
    db.deleteWhere('entities', ids),
    db.deleteWhere('instruments', ids),
    db.deleteWhere('assets', ids),
  ]);
  if (report.entities.length) {
    setOperation('saving entities to PostgREST');
    await db.upsert('entities', report.entities.map((entity) => ({
      ...ids,
      entity_id: entity.entity_id,
      type: entity.type,
      description: entity.description,
      image: null,
    })));
  }
  if (report.instruments.length) {
    setOperation('saving instruments to PostgREST');
    await db.upsert('instruments', report.instruments.map((item) => ({
      ...ids,
      instrument_id: item.instrument_id,
      entity_id: item.entity_id,
      name: item.name,
      description: item.description,
      threat_level: item.threat_level,
      image: null,
    })));
  }
  if (report.assets.length) {
    setOperation('saving assets to PostgREST');
    await db.upsert('assets', report.assets.map((item) => ({
      ...ids,
      asset_id: item.asset_id,
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

/** Agent mode: the agent writes incidents and evidence; the console keeps notes, the R2 key and reports. */
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

export async function prepareAgentVideo(db: PostgrestClient, report: { videoId: string }, video: VideoReference): Promise<void> {
  await saveVideo(db, report, video);
}

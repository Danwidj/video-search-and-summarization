// SPDX-License-Identifier: Apache-2.0

// AnalysisRunRepository over PostgREST. A valid run is written as separate
// requests in this order: model_runs (with the notes record), incidents through
// the insert_incident RPC (which also creates the review_status row), the
// E#/I#/A# evidence rows, the reports row, then a read-back. Not atomic: a
// transactional save_analysis_run RPC is a database change and is on hold
// (lib/ports/analysis.ts).

import type { AnalysisAttemptRecord, AnalysisRunRepository, ContractRunRecord, UploadedVideo } from '@/lib/ports';
import type { PostgrestClient } from '@/lib/postgrest/client';

/**
 * The immutable model_runs.notes record. Written once and never modified;
 * reviewer edits change only the relational projection. The wrapper key
 * stays incidentConsoleV2 (with the final report at incidentConsoleV2.report)
 * so the existing list/dashboard SQL title lookups keep working.
 */
export function attemptNotes(attempt: AnalysisAttemptRecord | ContractRunRecord): string {
  return JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', ...attempt } });
}

const modelRunRow = (attempt: AnalysisAttemptRecord, runAt: string) => ({
  id: attempt.modelRunId,
  model_name: attempt.request.model,
  model_version: null,
  prompt_version: attempt.contractVersion,
  run_datetime: runAt,
  notes: attemptNotes(attempt),
});

export class SupabaseAnalysisRunAdapter implements AnalysisRunRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async recordUploadedVideo(video: UploadedVideo): Promise<void> {
    await this.db.insertIfAbsent('videos', { id: video.videoId, filepath: video.r2Key, source: video.sensorId, uploaded_datetime: video.uploadedAt }, 'id');
  }

  async saveFailedAttempt(attempt: AnalysisAttemptRecord): Promise<void> {
    if (attempt.status !== 'contract_failed' && attempt.status !== 'request_failed') {
      throw new Error(`saveFailedAttempt called with a ${attempt.status} attempt`);
    }
    await this.db.upsert('model_runs', modelRunRow(attempt, attempt.attemptedAt), 'id');
  }

  async saveRun(run: ContractRunRecord, onStep: (step: string) => void = () => {}): Promise<void> {
    const { incident, entities, instruments, assets } = run.report;
    onStep('saving the model run to PostgREST');
    await this.db.upsert('model_runs', modelRunRow(run, run.generatedAt), 'id');
    onStep('saving the incident through the PostgREST RPC');
    await this.db.insertIncident({
      p_incident_id: run.videoId,
      p_model_run_id: run.modelRunId,
      p_type: incident.type,
      // incidents.start_timestamp/end_timestamp are VARCHAR; contract runs store
      // integer seconds as text (as eval does), legacy runs hold "M:SS".
      p_start_timestamp: String(incident.start_timestamp),
      p_end_timestamp: String(incident.end_timestamp),
      p_duration: incident.duration,
      p_description: incident.description,
      p_severity_level: incident.severity_level,
      p_confidence_score: incident.confidence_score,
    });
    if (entities.length) {
      onStep('saving entities to PostgREST');
      await this.db.upsert('entities', entities.map((entity) => ({
        incident_id: run.videoId,
        model_run_id: run.modelRunId,
        entity_id: entity.entity_id,
        type: entity.type,
        description: entity.description,
        image: null,
      })));
    }
    if (instruments.length) {
      onStep('saving instruments to PostgREST');
      await this.db.upsert('instruments', instruments.map((instrument) => ({
        incident_id: run.videoId,
        model_run_id: run.modelRunId,
        instrument_id: instrument.instrument_id,
        entity_id: instrument.entity_id,
        name: instrument.name,
        description: instrument.description,
        threat_level: instrument.threat_level,
        image: null,
      })));
    }
    if (assets.length) {
      onStep('saving assets to PostgREST');
      await this.db.upsert('assets', assets.map((asset) => ({
        incident_id: run.videoId,
        model_run_id: run.modelRunId,
        asset_id: asset.asset_id,
        name: asset.name,
        description: asset.description,
        image: null,
      })));
    }
    onStep('saving report metadata to PostgREST');
    await this.db.upsert(
      'reports',
      {
        id: run.reportId,
        incident_id: run.videoId,
        query_id: null,
        model_run_id: run.modelRunId,
        filepath: null,
        generated_datetime: run.generatedAt,
      },
      'id',
    );
    onStep('verifying the persisted report in PostgREST');
    await this.verifySavedRun(run);
  }

  private async verifySavedRun(run: ContractRunRecord): Promise<void> {
    const [video, modelRun, incident, reportRow] = await Promise.all([
      this.db.selectOne('videos', { id: run.videoId }, 'id,filepath'),
      this.db.selectOne('model_runs', { id: run.modelRunId }, 'id'),
      this.db.selectOne('incidents', { incident_id: run.videoId, model_run_id: run.modelRunId }, 'incident_id,model_run_id'),
      this.db.selectOne('reports', { id: run.reportId }, 'id,incident_id,model_run_id'),
    ]);

    const missing = [
      !video && 'videos',
      !modelRun && 'model_runs',
      !incident && 'incidents',
      !reportRow && 'reports',
    ].filter(Boolean);
    if (missing.length > 0) throw new Error(`persistence verification found missing rows: ${missing.join(', ')}`);
    if (video?.filepath !== run.r2Key) {
      throw new Error('persistence verification found an unexpected videos.filepath value');
    }
  }
}

// SPDX-License-Identifier: Apache-2.0

// AnalysisRunRepository over PostgREST. A valid run is written as separate
// requests in this order: model_runs (with the notes record), then the AI
// report revision (unless the agent stored it), then a read-back. Not atomic:
// a transactional save RPC is a database change and is on hold
// (modules/analysis/domain/AnalysisRunRepository.ts).

import type { PostgrestClient } from '@/lib/postgrest/client';
import {
  type AgentStoredRevision,
  type AnalysisAttemptRecord,
  type AnalysisRunRepository,
  type ContractRunRecord,
  type UploadedVideo,
} from '@/modules/analysis/domain/AnalysisRunRepository';
import { placeholderEvidence, revisionFacets, type EvidenceEntry } from '@/modules/reports/domain/revision';

/**
 * The immutable model_runs.notes record. Written once and never modified;
 * reviewer edits are new human revisions. The wrapper key
 * stays incidentConsoleV2 (with the final report at incidentConsoleV2.report)
 * so the existing SQL lookups keep working.
 */
export function attemptNotes(attempt: AnalysisAttemptRecord | ContractRunRecord): string {
  return JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', ...attempt } });
}

const modelRunRow = (attempt: AnalysisAttemptRecord | ContractRunRecord, runAt: string) => ({
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

  /**
   * Records the uploaded video once. The row is created on the first analysis
   * of a newly uploaded video, before inference, so it exists even if that
   * analysis fails. An existing row is never updated, so re-runs cannot reset
   * the original upload timestamp.
   */
  async recordUploadedVideo(video: UploadedVideo): Promise<void> {
    await this.db.insertIfAbsent('videos', { id: video.videoId, filepath: video.r2Key, source: video.sensorId, uploaded_datetime: video.uploadedAt }, 'id');
  }

  async saveFailedAttempt(attempt: AnalysisAttemptRecord): Promise<void> {
    if (attempt.status !== 'contract_failed' && attempt.status !== 'request_failed') {
      throw new Error(`saveFailedAttempt called with a ${attempt.status} attempt`);
    }
    await this.db.upsert('model_runs', modelRunRow(attempt, attempt.attemptedAt), 'id');
  }

  async saveRun(run: ContractRunRecord, agent: AgentStoredRevision, onStep: (step: string) => void): Promise<number> {
    onStep('saving the model run to PostgREST');
    await this.db.upsert('model_runs', modelRunRow(run, run.generatedAt), 'id');
    let revisionId = agent.revisionId ?? null;
    if (revisionId === null) {
      onStep('saving the AI report revision to PostgREST');
      const payload = run.report as unknown as Record<string, unknown>;
      const evidence = agent.evidence ?? placeholderEvidence(payload, 'not cropped (gateway analysis)');
      revisionId = await this.insertAiRevision({ videoId: run.videoId, modelRunId: run.modelRunId, payload, evidence });
    }
    onStep('verifying the persisted report in PostgREST');
    await this.verifySavedRevision({ videoId: run.videoId, modelRunId: run.modelRunId, revisionId }, run.r2Key);
    return revisionId;
  }

  /**
   * Appends an AI revision (kind 'ai', no parent) with the video's next revision
   * number. revision_no is unique per video, so a concurrent insert that took
   * the same number is retried with the next one.
   */
  private async insertAiRevision(input: { videoId: string; modelRunId: string; payload: Record<string, unknown>; evidence: EvidenceEntry[] }): Promise<number> {
    for (let attempt = 0; ; attempt += 1) {
      const [latest] = await this.db.selectMany('report_revisions', { filters: { video_id: input.videoId }, select: 'revision_no', order: 'revision_no.desc', limit: 1 });
      const revisionNo = (typeof latest?.revision_no === 'number' ? latest.revision_no : 0) + 1;
      try {
        const row = await this.db.insertRow('report_revisions', {
          video_id: input.videoId,
          revision_no: revisionNo,
          kind: 'ai',
          model_run_id: input.modelRunId,
          parent_id: null,
          payload: input.payload,
          evidence: input.evidence,
          ...revisionFacets(input.payload),
        });
        return Number(row.id);
      } catch (error) {
        const duplicate = error instanceof Error && /23505|duplicate key/.test(error.message);
        if (!duplicate || attempt >= 3) throw error;
      }
    }
  }

  private async verifySavedRevision(saved: { videoId: string; modelRunId: string; revisionId: number }, expectedR2Key: string): Promise<void> {
    const [video, modelRun, revision] = await Promise.all([
      this.db.selectOne('videos', { id: saved.videoId }, 'id,filepath'),
      this.db.selectOne('model_runs', { id: saved.modelRunId }, 'id'),
      this.db.selectOne('report_revisions', { video_id: saved.videoId, id: String(saved.revisionId) }, 'id,model_run_id'),
    ]);

    const missing = [
      !video && 'videos',
      !modelRun && 'model_runs',
      !revision && 'report_revisions',
    ].filter(Boolean);
    if (missing.length > 0) throw new Error(`persistence verification found missing rows: ${missing.join(', ')}`);
    if (video?.filepath !== expectedR2Key) {
      throw new Error('persistence verification found an unexpected videos.filepath value');
    }
    if (revision?.model_run_id !== saved.modelRunId) {
      throw new Error('persistence verification found an AI revision for a different model run');
    }
  }
}

// SPDX-License-Identifier: Apache-2.0

import type { AnalysisReport } from '@/lib/analysis/schema';
import type { RepairOperation, RepairIneligibility } from '@/lib/contract/repair';
import type { DerivedContractReport } from '@/lib/contract/types';
import type { ContractViolation, ContractViolationCode } from '@/lib/contract/validate';
import { PostgrestClient } from '@/lib/postgrest/client';

interface VideoReference {
  r2Key: string;
  sensorId: string;
  uploadedAt: string;
  duration?: number | null;
}

/**
 * Agent mode: create the video row once (keeping its original upload time),
 * then make sure filepath/source hold the R2 key. The upsert deliberately
 * omits uploaded_datetime so a re-analysis never resets it.
 */
async function saveVideo(db: PostgrestClient, report: { videoId: string }, video: VideoReference): Promise<void> {
  await recordUploadedVideo(db, report.videoId, video);
  const row: Record<string, unknown> = { id: report.videoId, filepath: video.r2Key, source: video.sensorId };
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
  report: { videoId: string; modelRunId: string; reportId: string },
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

/** The four analysis outcomes. Only the two valid ones ever produce report rows. */
export type AttemptStatus = 'valid_first_pass' | 'valid_after_structural_repair' | 'contract_failed' | 'request_failed';

/** Where a failed attempt was decided. */
export type AttemptStage = 'gateway' | 'upstream_response' | 'contract_validation' | 'structural_repair';

export type AttemptRepair =
  | { eligible: false; ruleSet: string; reason: RepairIneligibility; blockingCodes: ContractViolationCode[]; detail: string }
  | { eligible: true; ruleSet: string; operations: RepairOperation[]; revalidation: ContractViolation[] };

/** Everything recorded for one incident-contract-v2 analysis attempt, whatever its outcome. */
export interface AnalysisAttemptRecord {
  status: AttemptStatus;
  stage: AttemptStage | null;
  failure: { code: string; message: string } | null;
  contractVersion: string;
  videoId: string;
  r2Key: string;
  modelRunId: string;
  attemptedAt: string;
  request: {
    model: string;
    inferenceConfig: Record<string, unknown>;
    additionalInstruction: string | null;
    promptSha256: string;
    schemaSha256: string;
  };
  /** Only the fields the gateway actually returned; the content is the original, never altered. */
  response: {
    httpStatus?: number;
    errorBody?: string;
    content?: string | null;
    reasoningContent?: string | null;
    finishReason?: string | null;
    usage?: Record<string, unknown> | null;
  } | null;
  validation: { firstPass: ContractViolation[] };
  repair: AttemptRepair | null;
}

/** A valid attempt: it also carries the final validated report and its report row id. */
export interface ContractRunRecord extends AnalysisAttemptRecord {
  status: 'valid_first_pass' | 'valid_after_structural_repair';
  reportId: string;
  generatedAt: string;
  report: DerivedContractReport;
}

/**
 * The immutable model_runs.notes record. Written once and never modified;
 * reviewer edits change only the relational projection. The wrapper key
 * stays incidentConsoleV2 (with the final report at incidentConsoleV2.report)
 * so the existing list/dashboard SQL title lookups keep working.
 */
export function attemptNotes(attempt: AnalysisAttemptRecord | ContractRunRecord): string {
  return JSON.stringify({ incidentConsoleV2: { recordType: 'analysis_attempt', ...attempt } });
}

/**
 * Record the uploaded video once. The upload and its analyses are separate
 * lifecycle events: the row is created on the first analysis of a newly
 * uploaded video, before inference, so it exists even if that analysis fails.
 * An existing row is never updated, so re-runs cannot reset the original
 * upload timestamp.
 */
export async function recordUploadedVideo(db: PostgrestClient, videoId: string, video: VideoReference): Promise<void> {
  await db.insertIfAbsent('videos', { id: videoId, filepath: video.r2Key, source: video.sensorId, uploaded_datetime: video.uploadedAt }, 'id');
}

/**
 * Record a contract_failed or request_failed attempt: a model_runs row only,
 * never incident, evidence, review_status or report rows, so it can never
 * appear as a report or in incident statistics.
 */
export async function persistFailedAttempt(db: PostgrestClient, attempt: AnalysisAttemptRecord): Promise<void> {
  if (attempt.status !== 'contract_failed' && attempt.status !== 'request_failed') {
    throw new Error(`persistFailedAttempt called with a ${attempt.status} attempt`);
  }
  await db.upsert(
    'model_runs',
    {
      id: attempt.modelRunId,
      model_name: attempt.request.model,
      model_version: null,
      prompt_version: attempt.contractVersion,
      run_datetime: attempt.attemptedAt,
      notes: attemptNotes(attempt),
    },
    'id',
  );
}

/**
 * Persist one valid contract run as a new model run: model_runs (with the notes
 * record), incidents through the insert_incident RPC (which also creates the
 * review_status row), the E#/I#/A# evidence rows, and the reports row. The
 * videos row is recorded separately (recordUploadedVideo).
 */
export async function persistContractRun(
  db: PostgrestClient,
  run: ContractRunRecord,
  expectedR2Key: string,
  setOperation: (operation: string) => void,
): Promise<void> {
  const { incident, entities, instruments, assets } = run.report;
  setOperation('saving the model run to PostgREST');
  await db.upsert(
    'model_runs',
    {
      id: run.modelRunId,
      model_name: run.request.model,
      model_version: null,
      prompt_version: run.contractVersion,
      run_datetime: run.generatedAt,
      notes: attemptNotes(run),
    },
    'id',
  );
  setOperation('saving the incident through the PostgREST RPC');
  await db.insertIncident({
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
    setOperation('saving entities to PostgREST');
    await db.upsert('entities', entities.map((entity) => ({
      incident_id: run.videoId,
      model_run_id: run.modelRunId,
      entity_id: entity.entity_id,
      type: entity.type,
      description: entity.description,
      image: null,
    })));
  }
  if (instruments.length) {
    setOperation('saving instruments to PostgREST');
    await db.upsert('instruments', instruments.map((instrument) => ({
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
    setOperation('saving assets to PostgREST');
    await db.upsert('assets', assets.map((asset) => ({
      incident_id: run.videoId,
      model_run_id: run.modelRunId,
      asset_id: asset.asset_id,
      name: asset.name,
      description: asset.description,
      image: null,
    })));
  }
  setOperation('saving report metadata to PostgREST');
  await db.upsert(
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
  setOperation('verifying the persisted report in PostgREST');
  await verifySavedReport(db, run, expectedR2Key);
}


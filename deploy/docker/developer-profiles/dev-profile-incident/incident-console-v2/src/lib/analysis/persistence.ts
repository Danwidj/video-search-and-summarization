// SPDX-License-Identifier: Apache-2.0

import type { RepairOperation, RepairIneligibility } from '@/modules/contract/domain/repair';
import type { DerivedContractReport } from '@/modules/contract/domain/types';
import type { ContractViolation, ContractViolationCode, ViolationScope } from '@/modules/contract/domain/validate';
import { PostgrestClient } from '@/lib/postgrest/client';
import { placeholderEvidence, revisionFacets, type EvidenceEntry } from '@/modules/reports/domain/revision';

interface VideoReference {
  r2Key: string;
  sensorId: string;
  uploadedAt: string;
  duration?: number | null;
}

export async function verifySavedRevision(
  db: PostgrestClient,
  saved: { videoId: string; modelRunId: string; revisionId: number },
  expectedR2Key: string,
): Promise<void> {
  const [video, modelRun, revision] = await Promise.all([
    db.selectOne('videos', { id: saved.videoId }, 'id,filepath'),
    db.selectOne('model_runs', { id: saved.modelRunId }, 'id'),
    db.selectOne('report_revisions', { video_id: saved.videoId, id: String(saved.revisionId) }, 'id,model_run_id'),
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
    /** The video's length from its MP4 header; null when it could not be read (video-length rule not applied). */
    videoDurationSeconds?: number | null;
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
  /**
   * firstPass: every violation of the original response, each with its
   * core-scored-v1 scope. The outcome follows core validity; fullContractValid
   * records incident-contract validity (schema + every cross-field rule) of the
   * original response for comparison with eval. Absent on records written
   * before the policy existed (those required full contract validity).
   */
  validation: {
    firstPass: Array<ContractViolation & { scope?: ViolationScope }>;
    policy?: string;
    fullContractValid?: boolean;
    coreValid?: boolean;
    videoBoundsChecked?: boolean;
  };
  repair: AttemptRepair | null;
}

/** A valid attempt: it also carries the final validated report. Its AI revision id is known only once the revision is stored. */
export interface ContractRunRecord extends AnalysisAttemptRecord {
  status: 'valid_first_pass' | 'valid_after_structural_repair';
  generatedAt: string;
  report: DerivedContractReport;
}

/**
 * The immutable model_runs.notes record. Written once and never modified;
 * reviewer edits are new human revisions. The wrapper key
 * stays incidentConsoleV2 (with the final report at incidentConsoleV2.report)
 * so the existing SQL lookups keep working.
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
 * never a report revision, so it can never
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

/** What was stored for a valid run. */
export interface PersistedRevision {
  revisionId: number;
}

/**
 * Persist one valid contract run as a new model run (model_runs with the
 * notes record) and its AI report revision: the full contract report as the
 * payload, the evidence list (the agent's crops when it supplied them, else
 * one image-less entry per item) and the facet columns. When the agent has
 * already stored the revision (agentRevisionId) only its presence is checked.
 * The videos row is recorded separately (recordUploadedVideo).
 */
export async function persistContractRun(
  db: PostgrestClient,
  run: ContractRunRecord,
  expectedR2Key: string,
  setOperation: (operation: string) => void,
  agent: { revisionId?: number | null; evidence?: EvidenceEntry[] | null } = {},
): Promise<PersistedRevision> {
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
  let revisionId = agent.revisionId ?? null;
  if (revisionId === null) {
    setOperation('saving the AI report revision to PostgREST');
    const payload = run.report as unknown as Record<string, unknown>;
    const evidence = agent.evidence ?? placeholderEvidence(payload, 'not cropped (gateway analysis)');
    revisionId = await insertAiRevision(db, { videoId: run.videoId, modelRunId: run.modelRunId, payload, evidence });
  }
  setOperation('verifying the persisted report in PostgREST');
  await verifySavedRevision(db, { videoId: run.videoId, modelRunId: run.modelRunId, revisionId }, expectedR2Key);
  return { revisionId };
}

/**
 * Append an AI revision (kind 'ai', no parent) with the video's next revision
 * number. revision_no is unique per video, so a concurrent insert that took
 * the same number is retried with the next one.
 */
export async function insertAiRevision(
  db: PostgrestClient,
  input: { videoId: string; modelRunId: string; payload: Record<string, unknown>; evidence: EvidenceEntry[] },
): Promise<number> {
  for (let attempt = 0; ; attempt += 1) {
    const [latest] = await db.selectMany('report_revisions', { filters: { video_id: input.videoId }, select: 'revision_no', order: 'revision_no.desc', limit: 1 });
    const revisionNo = (typeof latest?.revision_no === 'number' ? latest.revision_no : 0) + 1;
    try {
      const row = await db.insertRow('report_revisions', {
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

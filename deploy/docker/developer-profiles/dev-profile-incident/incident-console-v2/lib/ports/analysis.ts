// SPDX-License-Identifier: Apache-2.0

// AnalysisRunRepository: saving what one incident-contract-v3 analysis
// produced. Every attempt that reaches the model is saved with its outcome;
// only a valid one gets an incident, evidence, a review and a report.
//
// The saves are separate writes, in the order the adapter documents, not one
// transaction: a failure part-way leaves the earlier rows. A single
// transactional save_analysis_run RPC (review of 2026-10-22, B-fix 2) would
// close that gap, but it is a database change and is on hold.

import type { RepairIneligibility, RepairOperation } from '@/lib/contract/repair';
import type { DerivedContractReport } from '@/lib/contract/types';
import type { ContractViolation, ContractViolationCode, ViolationScope } from '@/lib/contract/validate';

/** The four analysis outcomes. Only the two valid ones ever produce report rows. */
export type AttemptStatus = 'valid_first_pass' | 'valid_after_structural_repair' | 'contract_failed' | 'request_failed';

/** Where a failed attempt was decided. */
export type AttemptStage = 'gateway' | 'upstream_response' | 'contract_validation' | 'structural_repair';

export type AttemptRepair =
  | { eligible: false; ruleSet: string; reason: RepairIneligibility; blockingCodes: ContractViolationCode[]; detail: string }
  | { eligible: true; ruleSet: string; operations: RepairOperation[]; revalidation: ContractViolation[] };

/** Everything recorded for one incident-contract analysis attempt, whatever its outcome. */
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

/** A valid attempt: it also carries the final validated report and its report row id. */
export interface ContractRunRecord extends AnalysisAttemptRecord {
  status: 'valid_first_pass' | 'valid_after_structural_repair';
  reportId: string;
  generatedAt: string;
  report: DerivedContractReport;
}

/** A newly uploaded video, recorded before its first analysis. */
export interface UploadedVideo {
  videoId: string;
  r2Key: string;
  /** The uploading sensor; stored as the video's source. */
  sensorId: string;
  uploadedAt: string;
}

export interface AnalysisRunRepository {
  /**
   * Records the uploaded video once, before inference, so it exists even if
   * that analysis fails. An existing video is never updated, so re-runs cannot
   * reset its upload time.
   */
  recordUploadedVideo(video: UploadedVideo): Promise<void>;
  /**
   * Saves a contract_failed or request_failed attempt: the run record only,
   * never an incident, evidence, review or report, so it can never appear as
   * a report or in incident statistics. Throws for a valid attempt.
   */
  saveFailedAttempt(attempt: AnalysisAttemptRecord): Promise<void>;
  /**
   * Saves one valid run as a new model run (its immutable attempt record, the
   * incident with its review, the evidence and the report), then reads it back
   * and throws if any part is missing or the video's storage key is not
   * run.r2Key. onStep receives a description of each step before it starts,
   * for the caller's error message.
   */
  saveRun(run: ContractRunRecord, onStep?: (step: string) => void): Promise<void>;
}

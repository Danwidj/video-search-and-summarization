// SPDX-License-Identifier: Apache-2.0

// The single incident-contract-v2 analysis path, shared by the upload flow and
// (later) re-runs of an existing video: allowlisted model -> signed R2 URL ->
// P1 request identical to eval's -> strict contract validation -> optional
// id-normalization-v1 repair (re-validated) -> a new, unique model run.
//
// Every attempt that reaches the model is recorded with one of four outcomes:
//   valid_first_pass | valid_after_structural_repair  -> report rows + notes
//   contract_failed  | request_failed                 -> model_runs notes only
// The original model response is stored unaltered in every case.

import { randomUUID } from 'node:crypto';

import { buildP1Request, normalizeAdditionalInstruction, p1InferenceConfig } from '@/lib/analysis/build-request';
import {
  persistContractRun,
  persistFailedAttempt,
  recordUploadedVideo,
  type AnalysisAttemptRecord,
  type AttemptRepair,
  type ContractRunRecord,
} from '@/lib/analysis/persistence';
import { contractVersion, findAllowedModel, promptSha256, schemaSha256 } from '@/lib/contract/load';
import { attemptIdNormalization, REPAIR_RULE_SET } from '@/lib/contract/repair';
import type { IncidentContractReport } from '@/lib/contract/types';
import { ContractError, decodeContent, validateReport, withDerivedFields, type ContractViolation } from '@/lib/contract/validate';
import type { ServiceConfiguration } from '@/lib/env';
import { GatewayClient, GatewayError, type GatewayCompletionResponse } from '@/lib/gateway/client';
import { compactId } from '@/lib/ids';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl, verifyR2Video } from '@/lib/r2/config';

/** A request the caller must fix, or an attempt whose outcome is a recorded failure. */
export class AnalysisRequestError extends Error {
  status: number;
  details?: Record<string, unknown>;

  constructor(status: number, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = 'AnalysisRequestError';
    this.status = status;
    this.details = details;
  }
}

export interface ContractAnalysisInput {
  videoId: string;
  r2Key: string;
  model: unknown;
  additionalInstruction?: unknown;
  /** Present only for a newly uploaded video; its row is created once and never reset. */
  newVideo?: { sensorId: string; uploadedAt: string };
}

export interface ContractAnalysisResult {
  run: ContractRunRecord;
  playbackUrl: string;
}

export function resolveAllowedModel(model: unknown) {
  const allowed = typeof model === 'string' ? findAllowedModel(model.trim()) : undefined;
  if (!allowed) throw new AnalysisRequestError(400, `Unsupported model: ${typeof model === 'string' && model.trim() ? model.trim() : '(none)'}`);
  return allowed;
}

type Outcome =
  | { kind: 'valid'; report: IncidentContractReport; firstPass: ContractViolation[]; repair: AttemptRepair | null }
  | { kind: 'contract_failed'; stage: 'contract_validation' | 'structural_repair'; firstPass: ContractViolation[]; repair: AttemptRepair | null; message: string };

/** Strict validation, then id-normalization-v1 only when every first-pass violation is eligible, then strict validation again. */
export function evaluateContent(content: string): Outcome {
  let decoded: unknown;
  try {
    decoded = decodeContent(content);
    return { kind: 'valid', report: validateReport(decoded), firstPass: [], repair: null };
  } catch (error) {
    if (!(error instanceof ContractError)) throw error;
    const firstPass = error.violations;
    const structural = firstPass.every((violation) => !['EMPTY_CONTENT', 'INVALID_JSON', 'SCHEMA_VIOLATION'].includes(violation.code));
    if (!structural) {
      const blockingCodes = [...new Set(firstPass.map((violation) => violation.code))];
      return {
        kind: 'contract_failed',
        stage: 'contract_validation',
        firstPass,
        repair: { eligible: false, ruleSet: REPAIR_RULE_SET, reason: 'INELIGIBLE_VIOLATION', blockingCodes, detail: error.message },
        message: error.message,
      };
    }
    const attempt = attemptIdNormalization(decoded as IncidentContractReport, firstPass);
    if (!attempt.eligible) {
      const { eligible, ruleSet, reason, blockingCodes, detail } = attempt;
      return { kind: 'contract_failed', stage: 'contract_validation', firstPass, repair: { eligible, ruleSet, reason, blockingCodes, detail }, message: error.message };
    }
    try {
      const report = validateReport(attempt.repaired);
      return { kind: 'valid', report, firstPass, repair: { eligible: true, ruleSet: attempt.ruleSet, operations: attempt.operations, revalidation: [] } };
    } catch (revalidationError) {
      if (!(revalidationError instanceof ContractError)) throw revalidationError;
      return {
        kind: 'contract_failed',
        stage: 'structural_repair',
        firstPass,
        repair: { eligible: true, ruleSet: attempt.ruleSet, operations: attempt.operations, revalidation: revalidationError.violations },
        message: `${error.message}; after ${attempt.ruleSet}: ${revalidationError.message}`,
      };
    }
  }
}

function completionResponse(completion: GatewayCompletionResponse): NonNullable<AnalysisAttemptRecord['response']> {
  const choice = completion.choices[0];
  const response: NonNullable<AnalysisAttemptRecord['response']> = { content: choice.message.content ?? null };
  if ('reasoning_content' in choice.message) response.reasoningContent = choice.message.reasoning_content ?? null;
  if ('finish_reason' in choice) response.finishReason = choice.finish_reason ?? null;
  if ('usage' in completion) response.usage = completion.usage ?? null;
  return response;
}

async function recordFailure(db: PostgrestClient, attempt: AnalysisAttemptRecord): Promise<boolean> {
  try {
    await persistFailedAttempt(db, attempt);
    return true;
  } catch {
    return false;
  }
}

export async function runContractAnalysis(input: ContractAnalysisInput, config: ServiceConfiguration): Promise<ContractAnalysisResult> {
  const model = resolveAllowedModel(input.model);
  let additionalInstruction: string | null;
  try {
    additionalInstruction = normalizeAdditionalInstruction(input.additionalInstruction);
  } catch (error) {
    throw new AnalysisRequestError(400, error instanceof Error ? error.message : String(error));
  }

  const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
  let operation = 'verifying the R2 video object';
  try {
    await verifyR2Video(config, input.r2Key);
    if (input.newVideo) {
      operation = 'recording the uploaded video';
      await recordUploadedVideo(db, input.videoId, { r2Key: input.r2Key, sensorId: input.newVideo.sensorId, uploadedAt: input.newVideo.uploadedAt });
    }
    operation = 'creating the signed R2 video URL';
    const playbackUrl = await createR2PlaybackUrl(config, input.r2Key);

    const attemptedAt = new Date().toISOString();
    const modelRunId = compactId('m', `${input.videoId}:${attemptedAt}:${randomUUID()}`);
    const base: Omit<AnalysisAttemptRecord, 'status' | 'stage' | 'failure' | 'response' | 'validation' | 'repair'> = {
      contractVersion: contractVersion(),
      videoId: input.videoId,
      r2Key: input.r2Key,
      modelRunId,
      attemptedAt,
      request: {
        model: model.id,
        inferenceConfig: p1InferenceConfig(),
        additionalInstruction,
        promptSha256: promptSha256(),
        schemaSha256: schemaSha256(),
      },
    };

    operation = `calling the VLM gateway (${model.id})`;
    let completion: GatewayCompletionResponse;
    try {
      completion = await new GatewayClient(config.gatewayUrl!).complete(
        buildP1Request(model.id, playbackUrl, additionalInstruction),
        AbortSignal.timeout(model.timeout_seconds * 1000),
      );
    } catch (error) {
      if (!(error instanceof GatewayError)) throw error;
      const response: AnalysisAttemptRecord['response'] = error.httpStatus !== undefined || error.errorBody !== undefined
        ? { ...(error.httpStatus !== undefined ? { httpStatus: error.httpStatus } : {}), ...(error.errorBody !== undefined ? { errorBody: error.errorBody } : {}) }
        : null;
      const attempt: AnalysisAttemptRecord = { ...base, status: 'request_failed', stage: 'gateway', failure: { code: error.code, message: error.message }, response, validation: { firstPass: [] }, repair: null };
      const recorded = await recordFailure(db, attempt);
      throw new AnalysisRequestError(error.code === 'GATEWAY_TIMEOUT' ? 504 : 502, `The model request failed (${error.code}): ${error.message}`, {
        outcome: 'request_failed', code: error.code, model: model.id, attemptId: modelRunId, attemptRecorded: recorded,
      });
    }

    const response = completionResponse(completion);
    const content = response.content ?? '';
    const finishReason = response.finishReason;
    if ((finishReason !== undefined && finishReason !== null && finishReason !== 'stop') || !content) {
      const code = content ? `FINISH_${String(finishReason).toUpperCase()}` : 'UPSTREAM_EMPTY_CONTENT';
      const message = content
        ? `The model stopped with finish_reason "${finishReason}" before a usable response`
        : 'The model returned no response content';
      const attempt: AnalysisAttemptRecord = { ...base, status: 'request_failed', stage: 'upstream_response', failure: { code, message }, response, validation: { firstPass: [] }, repair: null };
      const recorded = await recordFailure(db, attempt);
      throw new AnalysisRequestError(502, `${message} (${code}).`, { outcome: 'request_failed', code, model: model.id, finishReason: finishReason ?? null, attemptId: modelRunId, attemptRecorded: recorded });
    }

    operation = 'validating the VLM response against the incident contract';
    const outcome = evaluateContent(content);
    if (outcome.kind === 'contract_failed') {
      const codes = [...new Set([...outcome.firstPass, ...(outcome.repair?.eligible ? outcome.repair.revalidation : [])].map((violation) => violation.code))];
      const attempt: AnalysisAttemptRecord = {
        ...base, status: 'contract_failed', stage: outcome.stage, failure: { code: codes.join(','), message: outcome.message },
        response, validation: { firstPass: outcome.firstPass }, repair: outcome.repair,
      };
      const recorded = await recordFailure(db, attempt);
      throw new AnalysisRequestError(422, `The model's response did not satisfy the incident contract: ${outcome.message}`, {
        outcome: 'contract_failed', codes, model: model.id, finishReason: finishReason ?? null, rawContent: content.slice(0, 20000), attemptId: modelRunId, attemptRecorded: recorded,
      });
    }

    const run: ContractRunRecord = {
      ...base,
      status: outcome.repair ? 'valid_after_structural_repair' : 'valid_first_pass',
      stage: null,
      failure: null,
      response,
      validation: { firstPass: outcome.firstPass },
      repair: outcome.repair,
      reportId: compactId('r', `${input.videoId}:${modelRunId}`),
      generatedAt: attemptedAt,
      report: withDerivedFields(outcome.report),
    };
    await persistContractRun(db, run, input.r2Key, (nextOperation) => { operation = nextOperation; });
    return { run, playbackUrl };
  } catch (error) {
    if (error instanceof AnalysisRequestError) throw error;
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`${operation} failed: ${detail}`);
  }
}

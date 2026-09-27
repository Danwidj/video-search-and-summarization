// SPDX-License-Identifier: Apache-2.0

// Reads model_runs.notes, which holds either the immutable incident-contract-v2
// attempt record (lib/analysis/persistence.ts attemptNotes) or a legacy console
// report. Nothing here writes notes.

import type { AnalysisReport } from '@/lib/analysis/schema';
import type { DerivedContractReport } from '@/lib/contract/types';
import { validateReport } from '@/lib/contract/validate';
import { reportFromNotes } from '@/lib/reports/storage';

export interface ContractRunRequest {
  model?: string;
  inferenceConfig?: Record<string, unknown>;
  additionalInstruction?: string | null;
  promptSha256?: string;
  schemaSha256?: string;
}

export interface ContractRunResponse {
  httpStatus?: number;
  errorBody?: string;
  content?: string | null;
  reasoningContent?: string | null;
  finishReason?: string | null;
  usage?: Record<string, unknown> | null;
}

export type ValidStatus = 'valid_first_pass' | 'valid_after_structural_repair';
export type FailedStatus = 'contract_failed' | 'request_failed';

export interface AttemptAudit {
  /** Stage-1 records predate the status field; the only outcome that stage could persist was valid_first_pass. */
  statusInferred: boolean;
  validation: { firstPass: Array<{ code: string; path: string; message: string }> };
  repair: Record<string, unknown> | null;
}

export type RunNotes =
  | ({ kind: 'contract'; status: ValidStatus; contractVersion: string; videoId: string | null; attemptedAt: string | null; report: DerivedContractReport; request: ContractRunRequest; response: ContractRunResponse } & AttemptAudit)
  | ({ kind: 'failed-attempt'; status: FailedStatus; contractVersion: string; videoId: string | null; attemptedAt: string | null; stage: string | null; failure: { code: string; message: string } | null; request: ContractRunRequest; response: ContractRunResponse | null } & AttemptAudit)
  | { kind: 'invalid-contract'; contractVersion: string; error: string; request: ContractRunRequest; response: ContractRunResponse }
  | { kind: 'legacy'; report: AnalysisReport; rawModelOutput?: string; legacyReviewerEdits?: Record<string, unknown> }
  | { kind: 'none' };

function asObject(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

/**
 * The videoId a run record explicitly names in its notes (attempt records:
 * incidentConsoleV2.videoId; legacy console reports: incidentConsoleV2.report.videoId
 * or a flat incidentConsoleV2.videoId), without validating the report. Null when absent.
 */
export function explicitVideoId(notes: unknown): string | null {
  if (typeof notes !== 'string') return null;
  try {
    const wrapper = asObject(asObject(JSON.parse(notes))?.incidentConsoleV2);
    if (!wrapper) return null;
    if (typeof wrapper.videoId === 'string' && wrapper.videoId) return wrapper.videoId;
    const report = asObject(wrapper.report);
    return typeof report?.videoId === 'string' && report.videoId ? report.videoId : null;
  } catch {
    return null;
  }
}

/**
 * Cheap outcome lookup for listings (no contract re-validation): the recorded
 * status, 'valid_first_pass' for pre-outcome contract records, and 'legacy'
 * for everything recorded before outcomes existed.
 */
export function recordedOutcome(notes: unknown): ValidStatus | FailedStatus | 'legacy' {
  if (typeof notes !== 'string') return 'legacy';
  try {
    const wrapper = asObject(asObject(JSON.parse(notes))?.incidentConsoleV2);
    if (!wrapper || typeof wrapper.contractVersion !== 'string') return 'legacy';
    const status = wrapper.status;
    if (status === 'valid_after_structural_repair' || status === 'contract_failed' || status === 'request_failed') return status;
    return 'valid_first_pass';
  } catch {
    return 'legacy';
  }
}

export function parseRunNotes(notes: unknown): RunNotes {
  if (typeof notes !== 'string' || !notes.trim()) return { kind: 'none' };
  let wrapper: Record<string, unknown> | undefined;
  try {
    wrapper = asObject(asObject(JSON.parse(notes))?.incidentConsoleV2);
  } catch {
    return { kind: 'none' };
  }
  if (!wrapper) return { kind: 'none' };

  if (typeof wrapper.contractVersion === 'string') {
    const request = (asObject(wrapper.request) ?? {}) as ContractRunRequest;
    const response = (asObject(wrapper.response) ?? {}) as ContractRunResponse;
    const rawStatus = typeof wrapper.status === 'string' ? wrapper.status : null;
    const validation = asObject(wrapper.validation);
    const audit: AttemptAudit = {
      statusInferred: rawStatus === null,
      validation: { firstPass: Array.isArray(validation?.firstPass) ? (validation!.firstPass as AttemptAudit['validation']['firstPass']) : [] },
      repair: asObject(wrapper.repair) ?? null,
    };
    if (rawStatus === 'contract_failed' || rawStatus === 'request_failed') {
      const failure = asObject(wrapper.failure);
      return {
        kind: 'failed-attempt', status: rawStatus, contractVersion: wrapper.contractVersion,
        videoId: typeof wrapper.videoId === 'string' ? wrapper.videoId : null,
        attemptedAt: typeof wrapper.attemptedAt === 'string' ? wrapper.attemptedAt : null,
        stage: typeof wrapper.stage === 'string' ? wrapper.stage : null,
        failure: failure && typeof failure.code === 'string' ? { code: failure.code, message: String(failure.message ?? '') } : null,
        request, response: asObject(wrapper.response) ? response : null, ...audit,
      };
    }
    const status: ValidStatus = rawStatus === 'valid_after_structural_repair' ? 'valid_after_structural_repair' : 'valid_first_pass';
    if (rawStatus !== null && rawStatus !== 'valid_first_pass' && rawStatus !== 'valid_after_structural_repair') {
      return { kind: 'invalid-contract', contractVersion: wrapper.contractVersion, error: `unknown attempt status ${rawStatus}`, request, response };
    }
    const stored = asObject(wrapper.report);
    const incident = asObject(stored?.incident);
    try {
      if (!stored || !incident) throw new Error('the run record has no contract report');
      // The stored report carries the derived incident.duration, which the
      // schema forbids from the model; validate the model-shaped part and
      // check the derivation separately.
      const { duration, ...modelIncident } = incident;
      const report = validateReport({ ...stored, incident: modelIncident });
      const expected = report.incident.end_timestamp - report.incident.start_timestamp;
      if (duration !== expected) throw new Error(`stored incident.duration ${String(duration)} is not ${expected}`);
      return { kind: 'contract', status, contractVersion: wrapper.contractVersion, videoId: typeof wrapper.videoId === 'string' ? wrapper.videoId : null, attemptedAt: typeof wrapper.attemptedAt === 'string' ? wrapper.attemptedAt : typeof wrapper.generatedAt === 'string' ? wrapper.generatedAt : null, report: { ...report, incident: { ...report.incident, duration: expected } }, request, response, ...audit };
    } catch (error) {
      return { kind: 'invalid-contract', contractVersion: wrapper.contractVersion, error: error instanceof Error ? error.message : String(error), request, response };
    }
  }

  const report = reportFromNotes(notes);
  if (!report) return { kind: 'none' };
  return {
    kind: 'legacy',
    report,
    rawModelOutput: report.rawModelOutput,
    legacyReviewerEdits: asObject(wrapper.editedReport),
  };
}

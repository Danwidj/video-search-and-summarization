// SPDX-License-Identifier: Apache-2.0

// Browser-side analysis: one call to POST /api/analysis, which analyses a video with the agent and stores the
// analysis. It answers { incidentId, videoName, analysisId, ... } and creates no report version; the incident's
// report is rebuilt afterwards through the build route (see lib/reports/regenerate.ts). Both the upload batch and
// the report page's Re-analyse share this client so the answer is checked in one place.

import { describeCode } from '@/modules/videos/domain/run-labels';
import { type RegeneratedVersion, regenerateReport } from '@/lib/reports/regenerate';

/** What the analyse route is asked: a fresh upload, or a video already stored (by its real name). */
export type AnalysisRequestBody = { model?: string; additionalInstruction?: string } & (
  | { sensorId: string; filepath: string; filename: string }
  | { videoName: string }
);

export interface AnalysedVideo {
  incidentId: number;
  videoName: string;
  analysisId: number;
}

/** A refused or failed analysis, carrying the route's own message and recorded outcome. */
export class AnalysisClientError extends Error {
  readonly status: number;
  readonly outcome: string | null;
  readonly code: string | null;
  readonly codes: string[];

  constructor(message: string, details: { status: number; outcome?: unknown; code?: unknown; codes?: unknown }) {
    super(message);
    this.name = 'AnalysisClientError';
    this.status = details.status;
    this.outcome = typeof details.outcome === 'string' ? details.outcome : null;
    this.code = typeof details.code === 'string' ? details.code : null;
    this.codes = Array.isArray(details.codes) ? details.codes.filter((entry): entry is string => typeof entry === 'string') : [];
  }
}

const isId = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;

/** The ids out of a successful analyse answer, or null when the answer is not in the P5.1 shape. */
export function parseAnalysedVideo(payload: unknown): AnalysedVideo | null {
  if (!payload || typeof payload !== 'object') return null;
  const { incidentId, videoName, analysisId } = payload as Record<string, unknown>;
  if (!isId(incidentId) || !isId(analysisId) || typeof videoName !== 'string' || !videoName) return null;
  return { incidentId, videoName, analysisId };
}

/** Analyses one video and returns the ids the route answers with. Throws AnalysisClientError on failure. */
export async function requestAnalysis(body: AnalysisRequestBody, signal?: AbortSignal): Promise<AnalysedVideo> {
  const response = await fetch('/api/analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const message = typeof payload.error === 'string' && payload.error ? payload.error : `Video analysis failed (HTTP ${response.status})`;
    throw new AnalysisClientError(message, { status: response.status, outcome: payload.outcome, code: payload.code, codes: payload.codes });
  }
  const analysed = parseAnalysedVideo(payload);
  if (!analysed) {
    throw new AnalysisClientError('The analysis answered without the incident id, video name and analysis id', { status: response.status });
  }
  return analysed;
}

export interface ReanalysedVideo extends AnalysedVideo {
  /** The incident's new version, built from the stored analyses once the new one is in. */
  version: RegeneratedVersion;
}

/**
 * Re-analyses a stored video, then builds the incident a new version so the new analysis shows. The caller learns
 * which step is running through onStage.
 */
export async function reanalyseVideo(
  input: { videoName: string; model: string; additionalInstruction?: string },
  options: { signal?: AbortSignal; onStage?: (stage: 'analyse' | 'build') => void } = {},
): Promise<ReanalysedVideo> {
  options.onStage?.('analyse');
  const analysed = await requestAnalysis(
    {
      videoName: input.videoName,
      model: input.model,
      ...(input.additionalInstruction?.trim() ? { additionalInstruction: input.additionalInstruction } : {}),
    },
    options.signal,
  );
  options.onStage?.('build');
  const version = await regenerateReport(String(analysed.incidentId), options.signal);
  return { ...analysed, version };
}

/** The report page address for an incident, with the version and camera when chosen. */
export function reportHref(incidentId: number, revisionId: number | null = null, camera: string | null = null): string {
  const params = new URLSearchParams();
  if (revisionId !== null) params.set('revision', String(revisionId));
  if (camera) params.set('camera', camera);
  const query = params.toString();
  return `/reports/${encodeURIComponent(String(incidentId))}${query ? `?${query}` : ''}`;
}

/** The lines shown when a re-analysis fails: recorded outcomes explain themselves, anything else shows its message. */
export function reanalysisFailureLines(error: unknown): string[] {
  if (error instanceof AnalysisClientError) {
    if (error.outcome === 'contract_failed') {
      return [
        'The model answered, but the answer broke the incident contract, so no analysis was stored. The attempt is recorded in the history.',
        ...error.codes.map(describeCode),
      ];
    }
    if (error.outcome === 'request_failed') {
      return ['The model request did not produce a usable answer. The attempt is recorded in the history.', describeCode(error.code || '')];
    }
  }
  return [error instanceof Error && error.message ? error.message : 'Re-analysis failed'];
}

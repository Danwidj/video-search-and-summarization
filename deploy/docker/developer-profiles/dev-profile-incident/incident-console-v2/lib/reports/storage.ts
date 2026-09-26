// SPDX-License-Identifier: Apache-2.0

import { incidentAnalysisSchema, type AnalysisReport } from '@/lib/analysis/schema';

interface StoredNotes {
  incidentConsoleV2?: AnalysisReport | Record<string, unknown> | {
    report?: AnalysisReport | Record<string, unknown>;
    rawModelOutput?: string;
    normalizedModelOutput?: string;
  };
}

const LEGACY_KEYS: Record<string, string> = {
  incidentType: 'incident_type',
  summary: 'description',
  severityLevel: 'severity',
  severityReason: 'severity_reason',
  confidenceScore: 'confidence',
  startTimestamp: 'incident_start',
  endTimestamp: 'incident_end',
  durationSeconds: 'duration_seconds',
};

function records(value: unknown): Record<string, unknown>[] | undefined {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object') : undefined;
}

function legacyToSnake(report: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = { ...report };
  for (const [legacy, current] of Object.entries(LEGACY_KEYS)) {
    if (result[current] === undefined && report[legacy] !== undefined) result[current] = report[legacy];
  }
  const entities = records(report.entities);
  if (result.persons === undefined && entities) {
    result.persons = entities.map((item) => ({ description: item.description, actions: '' }));
  }
  const timeline = records(report.timeline);
  if (timeline) {
    result.timeline = timeline.map(({ startSeconds, endSeconds, ...item }) => ({
      ...item,
      start_seconds: item.start_seconds ?? startSeconds,
      end_seconds: item.end_seconds ?? endSeconds,
    }));
  }
  const instruments = records(report.instruments);
  if (instruments) {
    result.instruments = instruments.map(({ threatLevel, ...item }) => ({
      ...item,
      threat_level: item.threat_level ?? threatLevel,
    }));
  }
  return result;
}

export function reportFromNotes(notes: unknown): AnalysisReport | null {
  if (typeof notes !== 'string') return null;
  try {
    const parsed = JSON.parse(notes) as StoredNotes;
    const stored = parsed.incidentConsoleV2;
    if (!stored || typeof stored !== 'object') return null;

    let baseReport: Record<string, unknown>;
    let rawModelOutput: string | undefined;
    let normalizedModelOutput: string | undefined;

    if ('videoId' in stored) {
      baseReport = stored as Record<string, unknown>;
      rawModelOutput = typeof stored.rawModelOutput === 'string' ? stored.rawModelOutput : undefined;
      normalizedModelOutput = typeof stored.normalizedModelOutput === 'string' ? stored.normalizedModelOutput : undefined;
    } else if ('report' in stored && stored.report && typeof stored.report === 'object') {
      baseReport = stored.report as Record<string, unknown>;
      rawModelOutput = typeof stored.rawModelOutput === 'string' ? stored.rawModelOutput : (typeof baseReport.rawModelOutput === 'string' ? baseReport.rawModelOutput : undefined);
      normalizedModelOutput = typeof stored.normalizedModelOutput === 'string' ? stored.normalizedModelOutput : (typeof baseReport.normalizedModelOutput === 'string' ? baseReport.normalizedModelOutput : undefined);
    } else {
      return null;
    }

    const validated = incidentAnalysisSchema.parse(legacyToSnake(baseReport));

    return {
      ...validated,
      videoId: typeof baseReport.videoId === 'string' ? baseReport.videoId : '',
      modelRunId: typeof baseReport.modelRunId === 'string' ? baseReport.modelRunId : '',
      reportId: typeof baseReport.reportId === 'string' ? baseReport.reportId : '',
      filename: typeof baseReport.filename === 'string' ? baseReport.filename : '',
      playbackUrl: typeof baseReport.playbackUrl === 'string' ? baseReport.playbackUrl : '',
      model: typeof baseReport.model === 'string' ? baseReport.model : '',
      generatedAt: typeof baseReport.generatedAt === 'string' ? baseReport.generatedAt : '',
      promptVersion: typeof baseReport.promptVersion === 'string' ? baseReport.promptVersion : undefined,
      rawModelOutput,
      normalizedModelOutput,
      reviewStatus: typeof baseReport.reviewStatus === 'string' ? (baseReport.reviewStatus as 'unreviewed' | 'under review' | 'verified') : undefined,
      verifiedBy: typeof baseReport.verifiedBy === 'string' ? baseReport.verifiedBy : undefined,
      verifiedAt: typeof baseReport.verifiedAt === 'string' ? baseReport.verifiedAt : undefined,
    };
  } catch {
    return null;
  }
}

export type ReviewStatus = 'unreviewed' | 'under review' | 'verified';

export interface ReportLibraryItem {
  reportId: string;
  videoId: string;
  modelRunId: string;
  title: string;
  filename: string;
  incident_type: string;
  description: string;
  severity: number;
  confidence: number;
  generatedAt: string;
  uploadedAt?: string;
  model: string;
  status: ReviewStatus;
  verifiedBy?: string;
  verifiedAt?: string;
  editedBy?: string;
  editedAt?: string;
  thumbnailUrl?: string;
  r2Key?: string;
  sensorId?: string;
}

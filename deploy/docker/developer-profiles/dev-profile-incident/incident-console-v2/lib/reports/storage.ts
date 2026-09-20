// SPDX-License-Identifier: Apache-2.0

import type { AnalysisReport } from '@/lib/analysis/schema';

interface StoredNotes {
  incidentConsoleV2?: AnalysisReport | {
    report?: AnalysisReport;
    rawModelOutput?: string;
    normalizedModelOutput?: string;
  };
}

export function reportFromNotes(notes: unknown): AnalysisReport | null {
  if (typeof notes !== 'string') return null;
  try {
    const stored = (JSON.parse(notes) as StoredNotes).incidentConsoleV2;
    if (!stored) return null;
    if ('videoId' in stored) return stored;
    if (!stored.report) return null;
    return {
      ...stored.report,
      rawModelOutput: stored.rawModelOutput || stored.report.rawModelOutput,
      normalizedModelOutput: stored.normalizedModelOutput || stored.report.normalizedModelOutput,
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
  incidentType: string;
  summary: string;
  severityLevel: number;
  confidenceScore: number;
  generatedAt: string;
  uploadedAt?: string;
  model: string;
  status: ReviewStatus;
  verifiedBy?: string;
  verifiedAt?: string;
  editedBy?: string;
  editedAt?: string;
  playbackUrl?: string;
  r2Key?: string;
  sensorId?: string;
  searchableEvidence: string;
}

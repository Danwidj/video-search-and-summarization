// SPDX-License-Identifier: Apache-2.0

import { z } from 'zod';

const nullableText = z.string().trim().min(1).nullable();
const threatLevel = z.preprocess(
  (value) => {
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (trimmed === '') return value;
    const numericValue = Number(trimmed);
    return Number.isFinite(numericValue) ? numericValue : value;
  },
  z.number().int().min(1).max(5).nullable(),
);

export const incidentAnalysisSchema = z.object({
  title: z.string().trim().min(1).max(160),
  incidentType: z.string().trim().min(1).max(32),
  summary: z.string().trim().min(1),
  startTimestamp: nullableText,
  endTimestamp: nullableText,
  durationSeconds: z.number().int().nonnegative().nullable(),
  severityLevel: z.number().int().min(1).max(5),
  severityReason: z.string().trim().min(1),
  confidenceScore: z.number().min(0).max(1),
  timeline: z.array(
    z.object({
      startSeconds: z.number().nonnegative(),
      endSeconds: z.number().nonnegative().nullable(),
      description: z.string().trim().min(1),
    }),
  ),
  entities: z.array(
    z.object({ type: z.enum(['human', 'animal', 'unknown']), description: z.string().trim().min(1) }),
  ),
  instruments: z.array(
    z.object({
      name: z.string().trim().min(1),
      description: z.string().trim().min(1),
      threatLevel,
    }),
  ),
  assets: z.array(z.object({ name: z.string().trim().min(1), description: z.string().trim().min(1) })),
  uncertainties: z.array(z.string().trim().min(1)),
});

export type IncidentAnalysis = z.infer<typeof incidentAnalysisSchema>;

export interface AnalysisReport extends IncidentAnalysis {
  videoId: string;
  modelRunId: string;
  reportId: string;
  filename: string;
  playbackUrl: string;
  model: string;
  generatedAt: string;
  promptVersion?: string;
  rawModelOutput?: string;
  normalizedModelOutput?: string;
  reviewStatus?: 'unreviewed' | 'under review' | 'verified';
  verifiedBy?: string;
  verifiedAt?: string;
}

// SPDX-License-Identifier: Apache-2.0

import { z } from 'zod';

function coerceTrimmedString(value: unknown): string {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  return trimmed;
}

function coerceTrimmedStringOrNull(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

function coerceNonNegativeNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return Math.floor(value);
  if (typeof value === 'string') {
    const num = Number(value.trim());
    if (Number.isFinite(num) && num >= 0) return Math.floor(num);
  }
  return null;
}

function coerceNumberClamped(value: unknown, min: number, max: number, fallback: number): number {
  if (value === null || value === undefined) return fallback;
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(min, Math.min(max, value));
  if (typeof value === 'string') {
    const num = Number(value.trim());
    if (Number.isFinite(num)) return Math.max(min, Math.min(max, num));
  }
  return fallback;
}

function coerceConfidenceScore(value: unknown): number {
  if (value === null || value === undefined) return 0.5;
  if (typeof value === 'number' && Number.isFinite(value)) {
    let num = value;
    if (num > 1) num = num / 100;
    return Math.max(0, Math.min(1, num));
  }
  if (typeof value === 'string') {
    const num = Number(value.trim());
    if (Number.isFinite(num)) {
      let n = num;
      if (n > 1) n = n / 100;
      return Math.max(0, Math.min(1, n));
    }
  }
  return 0.5;
}

function mapSeverityLevel(value: unknown): number {
  if (value === null || value === undefined) return 1;
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(1, Math.min(5, Math.floor(value)));
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'critical' || normalized === 'severe') return 5;
    if (normalized === 'high') return 4;
    if (normalized === 'medium' || normalized === 'moderate') return 3;
    if (normalized === 'low') return 2;
    if (normalized === 'none' || normalized === 'minimal') return 1;
    const num = Number(normalized);
    if (Number.isFinite(num)) return Math.max(1, Math.min(5, Math.floor(num)));
  }
  return 1;
}

function mapThreatLevel(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    const n = Math.floor(value);
    return n >= 1 && n <= 5 ? n : null;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'critical' || normalized === 'severe') return 5;
    if (normalized === 'high') return 4;
    if (normalized === 'medium' || normalized === 'moderate') return 3;
    if (normalized === 'low') return 2;
    if (normalized === 'none') return 1;
    const num = Number(normalized);
    if (Number.isFinite(num)) {
      const n = Math.floor(num);
      return n >= 1 && n <= 5 ? n : null;
    }
  }
  return null;
}

function mapEntityType(value: unknown): 'human' | 'animal' | 'unknown' {
  if (typeof value !== 'string') return 'unknown';
  const normalized = value.trim().toLowerCase();
  if (normalized === 'human') return 'human';
  if (normalized === 'animal') return 'animal';
  return 'unknown';
}

const timelineItemSchema = z.object({
  startSeconds: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return 0;
    if (typeof val === 'number' && Number.isFinite(val) && val >= 0) return Math.floor(val);
    if (typeof val === 'string') {
      const num = Number(val.trim());
      if (Number.isFinite(num) && num >= 0) return Math.floor(num);
    }
    return 0;
  }),
  endSeconds: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return null;
    if (typeof val === 'number' && Number.isFinite(val)) return Math.floor(val);
    if (typeof val === 'string') {
      const num = Number(val.trim());
      if (Number.isFinite(num)) return Math.floor(num);
    }
    return null;
  }),
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
}).passthrough();

const entitySchema = z.object({
  type: z.union([z.string(), z.null(), z.undefined()]).optional().transform(mapEntityType),
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
}).passthrough();

const instrumentSchema = z.object({
  name: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
  threatLevel: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional().transform(mapThreatLevel),
}).passthrough();

const assetSchema = z.object({
  name: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
}).passthrough();

export const incidentAnalysisSchema = z.object({
  title: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return 'Untitled Incident';
    const trimmed = String(val).trim();
    if (trimmed === '') return 'Untitled Incident';
    return trimmed.length > 160 ? trimmed.slice(0, 160) : trimmed;
  }),
  incidentType: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return 'other';
    const trimmed = String(val).trim();
    if (trimmed === '') return 'other';
    return trimmed.length > 32 ? trimmed.slice(0, 32) : trimmed;
  }),
  summary: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    return String(val).trim();
  }),
  startTimestamp: z.union([z.string(), z.null(), z.undefined()]).optional().transform(coerceTrimmedStringOrNull),
  endTimestamp: z.union([z.string(), z.null(), z.undefined()]).optional().transform(coerceTrimmedStringOrNull),
  durationSeconds: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional().transform(coerceNonNegativeNumberOrNull),
  severityLevel: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional().transform(mapSeverityLevel),
  severityReason: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return 'Severity determined from visible evidence.';
    const trimmed = String(val).trim();
    return trimmed === '' ? 'Severity determined from visible evidence.' : trimmed;
  }),
  confidenceScore: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional().transform(coerceConfidenceScore),
  timeline: z.union([z.array(timelineItemSchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  entities: z.union([z.array(entitySchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  instruments: z.union([z.array(instrumentSchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  assets: z.union([z.array(assetSchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  uncertainties: z.union([z.array(z.union([z.string(), z.null(), z.undefined()])), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val.map((v) => (v === null || v === undefined ? '' : String(v).trim())).filter((v) => v !== '');
  }),
}).passthrough();

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
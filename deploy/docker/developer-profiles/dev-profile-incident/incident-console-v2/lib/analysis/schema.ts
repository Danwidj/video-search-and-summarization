// SPDX-License-Identifier: Apache-2.0

import { z } from 'zod';

function coerceTrimmedString(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value !== 'string') return String(value).trim();
  return value.trim();
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

function coerceConfidence(value: unknown): number {
  if (value === null || value === undefined) return 0.0;
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
  return 0.0;
}

function mapSeverity(value: unknown): number {
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
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    const rounded = Math.round(value);
    if (rounded < 1) return null;
    return Math.min(5, rounded);
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'critical' || normalized === 'severe') return 5;
    if (normalized === 'high') return 4;
    if (normalized === 'medium' || normalized === 'moderate') return 3;
    if (normalized === 'low') return 2;
    if (normalized === 'none' || normalized === 'minimal') return 1;
    const num = Number(normalized);
    if (Number.isFinite(num)) {
      const rounded = Math.round(num);
      if (rounded < 1) return null;
      return Math.min(5, rounded);
    }
  }
  return null;
}

export const timelineItemSchema = z.object({
  start_seconds: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional(),
  end_seconds: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional(),
  description: z.union([z.string(), z.null(), z.undefined()]).optional(),
}).passthrough().transform((val) => {
  const rawStart = val.start_seconds;
  let start_seconds = 0.0;
  if (typeof rawStart === 'number' && Number.isFinite(rawStart) && rawStart >= 0) {
    start_seconds = rawStart;
  } else if (typeof rawStart === 'string') {
    const num = Number(rawStart.trim());
    if (Number.isFinite(num) && num >= 0) start_seconds = num;
  }

  const rawEnd = val.end_seconds;
  let end_seconds: number | null = null;
  if (typeof rawEnd === 'number' && Number.isFinite(rawEnd)) {
    end_seconds = rawEnd;
  } else if (typeof rawEnd === 'string') {
    const num = Number(rawEnd.trim());
    if (Number.isFinite(num)) end_seconds = num;
  }

  const description = val.description == null ? '' : String(val.description).trim();
  return { start_seconds, end_seconds, description };
});

export const personSchema = z.object({
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => (val == null ? '' : String(val).trim())),
  actions: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => (val == null ? '' : String(val).trim())),
}).passthrough();

export const instrumentSchema = z.object({
  name: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => (val == null ? '' : String(val).trim())),
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => (val == null ? '' : String(val).trim())),
  threat_level: z.union([z.number(), z.string(), z.boolean(), z.null(), z.undefined()]).optional(),
}).passthrough().transform((val) => ({
  name: val.name,
  description: val.description,
  threat_level: mapThreatLevel(val.threat_level),
}));

export const assetSchema = z.object({
  name: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => (val == null ? '' : String(val).trim())),
  description: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => (val == null ? '' : String(val).trim())),
}).passthrough();

export const incidentAnalysisSchema = z.object({
  title: z.union([z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (val === null || val === undefined) return '';
    const trimmed = String(val).trim();
    return trimmed.length > 160 ? trimmed.slice(0, 160) : trimmed;
  }),
  incident_type: z.union([z.string(), z.null(), z.undefined()]).optional(),
  description: z.union([z.string(), z.null(), z.undefined()]).optional(),
  severity: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional(),
  severity_reason: z.union([z.string(), z.null(), z.undefined()]).optional(),
  confidence: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional(),
  incident_start: z.union([z.string(), z.null(), z.undefined()]).optional(),
  incident_end: z.union([z.string(), z.null(), z.undefined()]).optional(),
  incident_start_confirmed: z.union([z.boolean(), z.string(), z.null(), z.undefined()]).optional().transform((val) => {
    if (typeof val === 'boolean') return val;
    if (typeof val === 'string') return val.trim().toLowerCase() === 'true';
    return false;
  }),
  duration_seconds: z.union([z.number(), z.string(), z.null(), z.undefined()]).optional(),
  persons: z.union([z.array(personSchema), z.null(), z.undefined()]).optional(),
  instruments: z.union([z.array(instrumentSchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  assets: z.union([z.array(assetSchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  timeline: z.union([z.array(timelineItemSchema), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val;
  }),
  uncertainties: z.union([z.array(z.union([z.string(), z.null(), z.undefined()])), z.null(), z.undefined()]).optional().transform((val) => {
    if (!Array.isArray(val)) return [];
    return val.map((v) => (v === null || v === undefined ? '' : String(v).trim())).filter((v) => v !== '');
  }),
  location: z.union([z.string(), z.null(), z.undefined()]).optional().transform(coerceTrimmedString),
}).passthrough().transform((val) => {
  const rawIncidentType = val.incident_type;
  let incident_type = 'road accident';
  if (rawIncidentType != null) {
    const trimmed = String(rawIncidentType).trim();
    if (trimmed !== '') {
      incident_type = trimmed.length > 32 ? trimmed.slice(0, 32) : trimmed;
    }
  }

  const rawDescription = val.description;
  const description = rawDescription != null ? String(rawDescription).trim() : '';

  const severity = mapSeverity(val.severity);

  const rawSeverityReason = val.severity_reason;
  const severity_reason = rawSeverityReason != null ? String(rawSeverityReason).trim() : '';

  const confidence = coerceConfidence(val.confidence);

  const rawStart = val.incident_start;
  const incident_start = rawStart != null && String(rawStart).trim() !== '' ? String(rawStart).trim() : '0:00';

  const rawEnd = val.incident_end;
  const incident_end = rawEnd != null && String(rawEnd).trim() !== '' ? String(rawEnd).trim() : '0:00';

  let duration_seconds = coerceNonNegativeNumberOrNull(val.duration_seconds);
  if ((duration_seconds === null || duration_seconds === 0) && val.timeline.length > 0) {
    const minStart = Math.min(...val.timeline.map((e) => e.start_seconds));
    const maxEnd = Math.max(...val.timeline.map((e) => e.end_seconds ?? e.start_seconds));
    const span = maxEnd - minStart;
    if (span > 0) {
      duration_seconds = Math.max(0, Math.round(span));
    }
  }

  const persons = Array.isArray(val.persons) ? val.persons : [];

  return {
    title: val.title,
    incident_type,
    severity,
    severity_reason,
    confidence,
    incident_start,
    incident_end,
    incident_start_confirmed: val.incident_start_confirmed,
    duration_seconds,
    description,
    persons,
    instruments: val.instruments,
    assets: val.assets,
    timeline: val.timeline,
    uncertainties: val.uncertainties,
    location: val.location,
  };
});

export type Person = z.infer<typeof personSchema>;
export type Instrument = z.infer<typeof instrumentSchema>;
export type Asset = z.infer<typeof assetSchema>;
export type TimelineItem = z.infer<typeof timelineItemSchema>;
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
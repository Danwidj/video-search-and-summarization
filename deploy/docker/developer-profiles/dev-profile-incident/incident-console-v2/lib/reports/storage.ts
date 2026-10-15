// SPDX-License-Identifier: Apache-2.0

export interface LegacyTimelineItem {
  start_seconds: number;
  end_seconds: number | null;
  description: string;
}

export interface LegacyAnalysisReport {
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

  incident_type: string;
  title: string;
  description: string;
  severity: number;
  severity_reason: string;
  confidence: number;
  incident_start: string;
  incident_end: string;
  incident_start_confirmed?: boolean;
  duration_seconds: number | null;
  location?: string | null;
  timeline: LegacyTimelineItem[];
  uncertainties: string[];
  persons?: Array<{ description: string; actions: string }>;
  instruments?: Array<{ name: string; description: string; threat_level?: number | null }>;
  assets?: Array<{ name: string; description: string }>;
}

interface StoredNotes {
  incidentConsoleV2?: LegacyAnalysisReport | Record<string, unknown> | {
    report?: LegacyAnalysisReport | Record<string, unknown>;
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

function text(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const num = Number(value.trim());
    if (Number.isFinite(num)) return num;
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

function toSeconds(val: unknown): number {
  if (typeof val === 'number' && Number.isFinite(val)) return Math.max(0, Math.floor(val));
  if (typeof val === 'string') {
    const trimmed = val.trim();
    if (!trimmed) return 0;
    const parts = trimmed.split(':').map((p) => Number(p));
    if (parts.length === 2 && parts.every((p) => Number.isFinite(p))) return Math.max(0, Math.floor(parts[0] * 60 + parts[1]));
    if (parts.length === 3 && parts.every((p) => Number.isFinite(p))) return Math.max(0, Math.floor(parts[0] * 3600 + parts[1] * 60 + parts[2]));
    const num = Number(trimmed);
    if (Number.isFinite(num)) return Math.max(0, Math.floor(num));
  }
  return 0;
}

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

export function reportFromNotes(notes: unknown): LegacyAnalysisReport | null {
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

    const raw = legacyToSnake(baseReport);
    const incidentType = text(raw.incident_type) || 'other';
    const title = text(raw.title);
    const description = text(raw.description);
    const severity = mapSeverity(raw.severity);
    const severityReason = text(raw.severity_reason);
    const confidence = coerceConfidence(raw.confidence);
    const incidentStart = text(raw.incident_start) || '0:00';
    const incidentEnd = text(raw.incident_end) || '0:00';
    const durationSeconds = nullableNumber(raw.duration_seconds);
    const location = raw.location !== undefined && raw.location !== null ? text(raw.location) : null;
    const timelineRaw = Array.isArray(raw.timeline) ? raw.timeline : [];
    const timeline: LegacyTimelineItem[] = timelineRaw
      .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
      .map((item) => ({
        start_seconds: toSeconds(item.start_seconds),
        end_seconds: item.end_seconds === null || item.end_seconds === undefined || item.end_seconds === '' ? null : toSeconds(item.end_seconds),
        description: text(item.description),
      }));
    const uncertainties = Array.isArray(raw.uncertainties) ? raw.uncertainties.map(text).filter(Boolean) : [];
    const persons = Array.isArray(raw.persons)
      ? raw.persons.map((p) => ({ description: text(p?.description), actions: text(p?.actions) }))
      : undefined;
    const instruments = Array.isArray(raw.instruments)
      ? raw.instruments.map((i) => ({
          name: text(i?.name),
          description: text(i?.description),
          threat_level: nullableNumber(i?.threat_level),
        }))
      : undefined;
    const assets = Array.isArray(raw.assets)
      ? raw.assets.map((a) => ({ name: text(a?.name), description: text(a?.description) }))
      : undefined;

    return {
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

      incident_type: incidentType,
      title,
      description,
      severity,
      severity_reason: severityReason,
      confidence,
      incident_start: incidentStart,
      incident_end: incidentEnd,
      incident_start_confirmed: typeof raw.incident_start_confirmed === 'boolean' ? raw.incident_start_confirmed : undefined,
      duration_seconds: durationSeconds,
      location,
      timeline,
      uncertainties,
      ...(persons ? { persons } : {}),
      ...(instruments ? { instruments } : {}),
      ...(assets ? { assets } : {}),
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
  /** null when the model reported no confidence (incident-contract-v2 allows null). */
  confidence: number | null;
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
  /** How the report's analysis ended (from model_runs.notes); 'legacy' for runs recorded before outcomes existed. */
  outcome?: 'valid_first_pass' | 'valid_after_structural_repair' | 'legacy';
  /** The video's explicitly selected official report (D6). */
  isOfficial?: boolean;
}

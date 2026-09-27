// SPDX-License-Identifier: Apache-2.0

import { ContractError, validateContractReport } from '@/lib/analysis/contract';
import type { AnalysisReport, IncidentContractReport, ReportMetadata, ReviewStatus } from '@/lib/analysis/contract-types';

export type { ReviewStatus } from '@/lib/analysis/contract-types';

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : value == null ? fallback : String(value);
}

function records(value: unknown): Json[] {
  return Array.isArray(value) ? value.filter(isObject) : [];
}

/** Seconds from a bare number, "12", "12.5", "M:SS" or "H:MM:SS". Unparseable -> 0. */
export function toSeconds(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.floor(value));
  if (typeof value !== 'string' || !value.trim()) return 0;
  const trimmed = value.trim();
  if (/^\d+(\.\d+)?$/.test(trimmed)) return Math.floor(Number(trimmed));
  const parts = trimmed.split(':').map(Number);
  if (parts.some((part) => !Number.isFinite(part))) return 0;
  return Math.max(0, Math.floor(parts.reduce((total, part) => total * 60 + part, 0)));
}

const LEGACY_TYPES: Record<string, string> = { fighting: 'assault', animal: 'animal attack' };

function nullableNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

/**
 * Read-only conversion of a pre-contract report (flat snake_case or camelCase, `persons`, "M:SS" times)
 * into the contract shape, for display. Never validated as contract output and never written back.
 */
export function legacyToContract(report: Json): IncidentContractReport {
  const pick = (...keys: string[]) => keys.map((key) => report[key]).find((value) => value !== undefined && value !== null);
  const rawType = text(pick('incident_type', 'incidentType', 'type')).trim().toLowerCase();
  const start = toSeconds(pick('incident_start', 'incidentStart', 'startTimestamp', 'start_timestamp'));
  const endRaw = toSeconds(pick('incident_end', 'incidentEnd', 'endTimestamp', 'end_timestamp'));
  const end = Math.max(start, endRaw);
  const people = records(report.persons).length ? records(report.persons) : records(report.entities);
  return {
    incident: {
      type: LEGACY_TYPES[rawType] ?? rawType,
      title: text(report.title),
      start_timestamp: start,
      end_timestamp: end,
      duration: nullableNumber(pick('duration_seconds', 'durationSeconds', 'duration')) ?? end - start,
      description: text(pick('description', 'summary')),
      severity_level: nullableNumber(pick('severity', 'severityLevel', 'severity_level')) ?? 1,
      severity_reason: text(pick('severity_reason', 'severityReason')),
      confidence_score: nullableNumber(pick('confidence', 'confidenceScore', 'confidence_score')),
      location: text(report.location) || null,
    },
    entities: people.map((person, index) => ({
      entity_id: `E${index + 1}`,
      type: person.type === 'animal' ? 'animal' : 'human',
      description: [text(person.description), text(person.actions)].filter(Boolean).join(' ') || 'Person',
    })),
    instruments: records(report.instruments).map((item, index) => ({
      instrument_id: `I${index + 1}`,
      entity_id: null,
      name: text(item.name),
      description: text(item.description),
      threat_level: nullableNumber(item.threat_level ?? item.threatLevel) ?? 1,
    })),
    assets: records(report.assets).map((item, index) => ({
      asset_id: `A${index + 1}`,
      name: text(item.name),
      description: text(item.description),
    })),
    timeline: records(report.timeline).map((item) => {
      const rawEnd = item.end_seconds ?? item.endSeconds;
      return {
        start_seconds: toSeconds(item.start_seconds ?? item.startSeconds),
        end_seconds: rawEnd === undefined || rawEnd === null || rawEnd === '' ? null : toSeconds(rawEnd),
        description: text(item.description),
      };
    }),
    uncertainties: Array.isArray(report.uncertainties) ? report.uncertainties.map((item) => text(item)).filter(Boolean) : [],
  };
}

/** A stored report body: contract reports are validated strictly; anything else is converted as legacy. */
export function contractFromStored(value: unknown): { report: IncidentContractReport; legacy: boolean } | null {
  if (!isObject(value)) return null;
  if (isObject(value.incident)) {
    try {
      return { report: validateContractReport(value), legacy: false };
    } catch (error) {
      if (!(error instanceof ContractError)) throw error;
      // A stored contract report that no longer validates (e.g. written by an older contract version)
      // is shown read-only through the legacy path rather than hidden.
    }
  }
  return { report: legacyToContract(value), legacy: true };
}

function metadataFrom(stored: Json, wrapper: Json): ReportMetadata {
  return {
    videoId: text(stored.videoId),
    modelRunId: text(stored.modelRunId),
    reportId: text(stored.reportId),
    filename: text(stored.filename),
    playbackUrl: text(stored.playbackUrl),
    model: text(stored.model),
    generatedAt: text(stored.generatedAt),
    promptVersion: typeof stored.promptVersion === 'string' ? stored.promptVersion : undefined,
    rawModelOutput: typeof wrapper.rawModelOutput === 'string' ? wrapper.rawModelOutput : typeof stored.rawModelOutput === 'string' ? stored.rawModelOutput : undefined,
    reportText: typeof wrapper.reportText === 'string' ? wrapper.reportText : typeof stored.reportText === 'string' ? stored.reportText : undefined,
    reportTextError: typeof stored.reportTextError === 'string' ? stored.reportTextError : undefined,
  };
}

export interface StoredReports {
  /** The preserved AI report. */
  original: AnalysisReport;
  /** The reviewer-edited copy, when one was saved. */
  edited: AnalysisReport | null;
}

/** Parse model_runs.notes ({"incidentConsoleV2": {report, editedReport?, rawModelOutput?, reportText?}}). */
export function reportsFromNotes(notes: unknown): StoredReports | null {
  if (typeof notes !== 'string') return null;
  let wrapper: Json;
  try {
    const parsed = JSON.parse(notes) as unknown;
    if (!isObject(parsed) || !isObject(parsed.incidentConsoleV2)) return null;
    wrapper = parsed.incidentConsoleV2;
  } catch {
    return null;
  }
  // Oldest layout stored the report directly under incidentConsoleV2.
  const stored = isObject(wrapper.report) ? wrapper.report : 'videoId' in wrapper ? wrapper : null;
  if (!stored) return null;
  const original = contractFromStored(stored);
  if (!original) return null;
  const metadata = metadataFrom(stored, wrapper);
  const edited = contractFromStored(wrapper.editedReport);
  return {
    original: { ...metadata, ...original.report, legacy: original.legacy || undefined },
    edited: edited ? { ...metadata, ...edited.report, legacy: edited.legacy || undefined } : null,
  };
}

export interface ReportLibraryItem {
  reportId: string;
  videoId: string;
  modelRunId: string;
  title: string;
  filename: string;
  incident_type: string;
  description: string;
  severity: number;
  /** Null when the model gave no native confidence (incident-contract-v2). */
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
}

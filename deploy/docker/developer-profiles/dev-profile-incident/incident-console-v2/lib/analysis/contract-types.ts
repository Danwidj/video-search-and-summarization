// SPDX-License-Identifier: Apache-2.0

// Client-safe types for the shared incident contract (../../contracts/, incident-contract-v2).
// The JSON Schema file is the source of truth; lib/analysis/contract.ts validates against it
// on the server. These types mirror it, and tests/contract.test.mjs checks the key sets match.

export const INCIDENT_TYPES = ['road accident', 'burglary', 'explosion', 'assault', 'animal attack'] as const;
export const ENTITY_TYPES = ['human', 'animal', 'unknown'] as const;

export interface ContractIncident {
  type: string;
  title: string;
  start_timestamp: number;
  end_timestamp: number;
  /** Derived by code as end_timestamp - start_timestamp; never requested from the model. */
  duration: number;
  description: string;
  severity_level: number;
  severity_reason: string;
  /** Native model confidence only; null when the model/API gives none. */
  confidence_score: number | null;
  location: string | null;
}

export interface ContractEntity {
  entity_id: string;
  type: string;
  description: string;
}

export interface ContractInstrument {
  instrument_id: string;
  entity_id: string | null;
  name: string;
  description: string;
  threat_level: number;
}

export interface ContractAsset {
  asset_id: string;
  name: string;
  description: string;
}

export interface ContractTimelineEvent {
  start_seconds: number;
  end_seconds: number | null;
  description: string;
}

/** A validated P1 report with derived fields added. */
export interface IncidentContractReport {
  incident: ContractIncident;
  entities: ContractEntity[];
  instruments: ContractInstrument[];
  assets: ContractAsset[];
  timeline: ContractTimelineEvent[];
  uncertainties: string[];
}

export type ReviewStatus = 'unreviewed' | 'under review' | 'verified';

export interface ReportMetadata {
  videoId: string;
  modelRunId: string;
  reportId: string;
  filename: string;
  playbackUrl: string;
  model: string;
  generatedAt: string;
  /** Contract version (e.g. incident-contract-v2), or an older prompt tag for legacy reports. */
  promptVersion?: string;
  /** Raw P1 message content, kept for provenance. */
  rawModelOutput?: string;
  /** RP1 prose report generated from the validated P1 JSON. */
  reportText?: string;
  /** Why RP1 produced no report text (P1 is still saved when RP1 fails). */
  reportTextError?: string;
  reviewStatus?: ReviewStatus;
  verifiedBy?: string;
  verifiedAt?: string;
  /** True when the report predates the contract and was converted for display only. */
  legacy?: boolean;
}

export type AnalysisReport = ReportMetadata & IncidentContractReport;

export const CONTRACT_KEYS = ['incident', 'entities', 'instruments', 'assets', 'timeline', 'uncertainties'] as const;

/** The contract part of a report (drops metadata). */
export function contractPart(report: IncidentContractReport): IncidentContractReport {
  return {
    incident: report.incident,
    entities: report.entities,
    instruments: report.instruments,
    assets: report.assets,
    timeline: report.timeline,
    uncertainties: report.uncertainties,
  };
}

export function secondsLabel(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  return `${String(minutes).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`;
}

export function confidenceLabel(confidence: number | null | undefined): string {
  return typeof confidence === 'number' ? `${Math.round(confidence * 100)}% confidence` : 'No model confidence';
}

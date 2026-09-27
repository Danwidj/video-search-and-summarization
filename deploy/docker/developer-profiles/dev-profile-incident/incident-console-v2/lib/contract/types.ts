// SPDX-License-Identifier: Apache-2.0

// TypeScript view of contracts/incident_report.schema.json (incident-contract-v2).
// The JSON Schema file is the source of truth; tests/contract-validate.test.mjs
// checks that these keys match it.

export const INCIDENT_TYPES = ['road accident', 'burglary', 'explosion', 'assault', 'animal attack'] as const;
export const ENTITY_TYPES = ['human', 'animal', 'unknown'] as const;

export type IncidentType = (typeof INCIDENT_TYPES)[number];
export type EntityType = (typeof ENTITY_TYPES)[number];

export interface ContractIncident {
  type: IncidentType;
  title: string;
  start_timestamp: number;
  end_timestamp: number;
  description: string;
  severity_level: number;
  severity_reason: string;
  confidence_score: number | null;
  location: string | null;
}

export interface ContractEntity {
  entity_id: string;
  type: EntityType;
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

/** A model response that passed schema and cross-field validation. */
export interface IncidentContractReport {
  incident: ContractIncident;
  entities: ContractEntity[];
  instruments: ContractInstrument[];
  assets: ContractAsset[];
  timeline: ContractTimelineEvent[];
  uncertainties: string[];
}

/** A validated report plus the fields code derives after validation (never requested from the model). */
export interface DerivedContractReport extends IncidentContractReport {
  incident: ContractIncident & { duration: number };
}

export interface InferenceModel {
  id: string;
  label: string;
  timeout_seconds: number;
  notes?: string;
}

export interface InferenceSettings {
  p1: {
    temperature: number;
    max_tokens: number;
    media_io_kwargs: { video: { num_frames: number } };
  };
  models: InferenceModel[];
}

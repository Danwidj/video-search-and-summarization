// SPDX-License-Identifier: Apache-2.0

// get_incident_dashboard (20260927180000): incident statistics come only from
// each video's explicitly selected official report (D6); videos are counted
// separately; model coverage counts analysis attempts by outcome.

export interface RankedValue {
  label: string;
  count: number;
}

export interface SeverityCounts {
  low: number;
  medium: number;
  high: number;
}

export interface TypeDetail {
  type: string;
  count: number;
  severity: SeverityCounts;
  /** Canonical entity types (human / animal / unknown), counted per incident. */
  entities: RankedValue[];
  /** Normalised instrument names, counted per incident. */
  instruments: RankedValue[];
  assets: RankedValue[];
}

export interface ModelCoverage {
  model: string;
  withReport: number;
  validFirstPass: number;
  repaired: number;
  legacy: number;
  contractFailed: number;
  requestFailed: number;
}

export interface DashboardAnalytics {
  /** Official incidents in the period (one per video with an official report). */
  total: number;
  /** All-time video counts; they match the /videos lists they link to. */
  videos: { uploaded: number; withOfficial: number; awaitingSelection: number; withoutReport: number };
  previous: { total: number; verified: number; unreviewed: number; high: number } | null;
  /** Mean of the confidences the models provided; null when none did. */
  averageConfidence: number | null;
  confidenceNotProvided: number;
  severity: SeverityCounts;
  reviews: { unreviewed: number; under_review: number; verified: number };
  types: TypeDetail[];
  trend: Array<{ date: string; count: number }>;
  heatmap: Array<{ day: number; hour: number; count: number }>;
  confidence: Array<{ bucket: number; count: number }>;
  entityTypes: RankedValue[];
  topInstruments: RankedValue[];
  topAssets: RankedValue[];
  threatLevels: Array<{ level: number; count: number }>;
  modelCoverage: ModelCoverage[];
}

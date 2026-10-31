// SPDX-License-Identifier: Apache-2.0

// get_incident_dashboard (latest definition in supabase/migrations/): incident
// statistics count each video once, through its official revision, else its
// newest, and say how many of each are official; videos are counted separately;
// model coverage counts analysis attempts by outcome.

export interface RankedValue {
  label: string;
  count: number;
}

/** How many of a count come from an official revision, and how many from a newest one with none. */
export interface OfficialSplit {
  official: number;
  notOfficial: number;
}

export interface SplitRankedValue extends RankedValue, OfficialSplit {}

export interface SeverityCounts {
  low: number;
  medium: number;
  high: number;
}

export interface TypeDetail extends OfficialSplit {
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
  /** Incidents in the period: one per video with a report, official else newest. */
  total: number;
  /** total, split by whether the counted revision is official. */
  official: number;
  notOfficial: number;
  /** All-time video counts, whatever the period and filters. */
  videos: { uploaded: number; withOfficial: number; awaitingSelection: number; withoutReport: number };
  previous: { total: number; human: number; ai: number; high: number } | null;
  /** Mean of the confidences the models provided; null when none did. */
  averageConfidence: number | null;
  confidenceNotProvided: number;
  severity: SeverityCounts;
  severityByScope: { official: SeverityCounts; notOfficial: SeverityCounts };
  /** The counted reports by kind: as the model generated them, or saved by a reviewer. */
  revisions: { ai: number; human: number };
  types: TypeDetail[];
  /** One entry per day of the period, in the viewer's time zone. */
  trend: Array<{ date: string; count: number } & OfficialSplit>;
  /** day and hour are null only for a report without generated_datetime. */
  heatmap: Array<{ day: number | null; hour: number | null; count: number } & OfficialSplit>;
  confidence: Array<{ bucket: number; count: number }>;
  entityTypes: RankedValue[];
  topInstruments: RankedValue[];
  topAssets: SplitRankedValue[];
  threatLevels: Array<{ level: number; count: number }>;
  modelCoverage: ModelCoverage[];
}

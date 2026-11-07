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

/** A ranked value whose split an older get_incident_dashboard does not return: then official and notOfficial are null, never 0. */
export interface MaybeSplitRankedValue extends RankedValue {
  official: number | null;
  notOfficial: number | null;
}

export interface SeverityCounts {
  low: number;
  medium: number;
  high: number;
}

export interface TypeDetail extends OfficialSplit {
  type: string;
  count: number;
  /**
   * Evidence items (one per entity, instrument or asset entry) of the type's counted reports, from
   * 20261107110000; null when the RPC does not return it, so evidence per report is not available.
   */
  evidence: number | null;
  severity: SeverityCounts;
  /** Canonical entity types (human / animal / unknown), counted per incident. */
  entities: RankedValue[];
  /** Normalised instrument names, counted per incident. */
  instruments: RankedValue[];
  assets: RankedValue[];
}

/** The three kinds of evidence item the dashboard counts; each item is one entry of a counted report's payload. */
export type EvidenceKind = 'entities' | 'instruments' | 'assets';

/** Evidence items of the counted reports of one kind, split by whether the counted revision is official. */
export interface EvidenceTotal extends OfficialSplit {
  kind: EvidenceKind;
  count: number;
}

/** Counted reports with one severity level and one evidence item count, from 20261107110000. */
export interface SeverityEvidenceCell extends OfficialSplit {
  /** The report's severity level, 1 to 5. */
  severity: number;
  evidenceItems: number;
  count: number;
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
  /**
   * Counted reports whose video has more than one report version (AI and human alike); not part of the split. null when
   * the RPC does not return it (a definition older than 20261106140000).
   */
  multipleVersions: number | null;
  /**
   * Every version of the videos behind the counted reports, split by kind (total = ai + human). null when the RPC does not
   * return it (a definition older than 20261107090000).
   */
  versions: { total: number; ai: number; human: number } | null;
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
  /**
   * Evidence items of the counted reports, one entry per kind, in the order entities, instruments, assets. null when the
   * RPC does not return it (a definition older than 20261106140000).
   */
  evidence: EvidenceTotal[] | null;
  /**
   * Counted reports by (severity level, evidence item count), for severity against evidence. null when the RPC does not
   * return it (a definition older than 20261107110000).
   */
  severityEvidence: SeverityEvidenceCell[] | null;
  entityTypes: MaybeSplitRankedValue[];
  topInstruments: MaybeSplitRankedValue[];
  topAssets: SplitRankedValue[];
  threatLevels: Array<{ level: number; count: number }>;
  modelCoverage: ModelCoverage[];
}

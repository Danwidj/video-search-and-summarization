// SPDX-License-Identifier: Apache-2.0

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
  entities: RankedValue[];
  instruments: RankedValue[];
  assets: RankedValue[];
}

export interface DashboardAnalytics {
  total: number;
  previous: { total: number; verified: number; unreviewed: number; high: number } | null;
  averageConfidence: number;
  severity: SeverityCounts;
  reviews: { unreviewed: number; under_review: number; verified: number };
  types: TypeDetail[];
  trend: Array<{ date: string; count: number }>;
  heatmap: Array<{ day: number; hour: number; count: number }>;
  confidence: Array<{ bucket: number; count: number }>;
  topEntities: RankedValue[];
  topAssets: RankedValue[];
}

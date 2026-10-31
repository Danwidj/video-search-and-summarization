// SPDX-License-Identifier: Apache-2.0

// In-memory DashboardRepository for tests: it serves the analytics it was
// given and records each query. Like get_incident_dashboard, it has no
// previous-period comparison unless both period bounds are set.

import type { DashboardAnalytics } from '@/modules/dashboard/domain/types';
import type { DashboardQuery, DashboardRepository } from '@/modules/dashboard/domain/DashboardRepository';

const NO_INCIDENTS: DashboardAnalytics = {
  total: 0,
  official: 0,
  notOfficial: 0,
  videos: { uploaded: 0, withOfficial: 0, awaitingSelection: 0, withoutReport: 0 },
  previous: { total: 0, human: 0, ai: 0, high: 0 },
  averageConfidence: null,
  confidenceNotProvided: 0,
  severity: { low: 0, medium: 0, high: 0 },
  severityByScope: { official: { low: 0, medium: 0, high: 0 }, notOfficial: { low: 0, medium: 0, high: 0 } },
  revisions: { ai: 0, human: 0 },
  types: [],
  trend: [],
  heatmap: [],
  confidence: [],
  entityTypes: [],
  topInstruments: [],
  topAssets: [],
  threatLevels: [],
  modelCoverage: [],
};

export class InMemoryDashboardRepository implements DashboardRepository {
  readonly queries: DashboardQuery[] = [];
  private readonly analytics: DashboardAnalytics;

  constructor(analytics: DashboardAnalytics = NO_INCIDENTS) {
    this.analytics = analytics;
  }

  async getDashboard(query: DashboardQuery): Promise<DashboardAnalytics> {
    this.queries.push(query);
    return { ...this.analytics, previous: query.periodStart && query.periodEnd ? this.analytics.previous : null };
  }
}

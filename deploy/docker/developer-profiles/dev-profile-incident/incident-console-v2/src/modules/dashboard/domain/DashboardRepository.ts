// SPDX-License-Identifier: Apache-2.0

import type { DashboardAnalytics } from '@/modules/dashboard/domain/types';

export type DashboardSeverity = 'low' | 'medium' | 'high';
/** Which reports count: every video's counted revision, or only the official or not-yet-official ones. */
export type DashboardScope = 'all' | 'official' | 'not_official';

/** get_incident_dashboard's inputs, validated and resolved by the route. */
export interface DashboardQuery {
  /** Null for the all-time period. Instants; the adapter formats them as naive UTC. */
  periodStart: Date | null;
  periodEnd: Date | null;
  type: string | null;
  severity: DashboardSeverity | null;
  /** 0 (Sunday) to 6 and 0 to 23, read in `timezone`. */
  dayOfWeek: number | null;
  hour: number | null;
  timezone: string;
  scope: DashboardScope;
}

export interface DashboardRepository {
  /** Everything the dashboard shows; the previous-period comparison only for a bounded period. */
  getDashboard(query: DashboardQuery): Promise<DashboardAnalytics>;
}

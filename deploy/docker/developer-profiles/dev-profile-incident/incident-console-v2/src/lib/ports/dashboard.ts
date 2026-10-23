// SPDX-License-Identifier: Apache-2.0

import type { DashboardAnalytics } from '@/lib/dashboard/types';

export type DashboardSeverity = 'low' | 'medium' | 'high';

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
}

export interface DashboardRepository {
  /** Everything the dashboard shows; the previous-period comparison only for a bounded period. */
  getDashboard(query: DashboardQuery): Promise<DashboardAnalytics>;
}

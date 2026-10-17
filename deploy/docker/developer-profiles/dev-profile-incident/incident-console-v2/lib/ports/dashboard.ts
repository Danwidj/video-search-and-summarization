// SPDX-License-Identifier: Apache-2.0

import type { DashboardAnalytics } from '@/lib/dashboard/types';

/** get_incident_dashboard's inputs, validated and resolved by the route. */
export interface DashboardQuery {
  /** Null for the all-time period. Instants; the adapter formats them as naive UTC. */
  periodStart: Date | null;
  periodEnd: Date | null;
  type: string | null;
  severity: 'low' | 'medium' | 'high' | null;
  dayOfWeek: number | null;
  hour: number | null;
  timezone: string;
}

export interface DashboardRepository {
  getDashboard(query: DashboardQuery): Promise<DashboardAnalytics>;
}

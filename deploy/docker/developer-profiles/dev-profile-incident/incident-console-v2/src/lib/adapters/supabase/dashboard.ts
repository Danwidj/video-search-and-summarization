// SPDX-License-Identifier: Apache-2.0

import { dashboardFromRpc, dashboardRpcArgs } from '@/lib/adapters/supabase/mappers/dashboard';
import type { DashboardAnalytics } from '@/lib/dashboard/types';
import type { DashboardQuery, DashboardRepository } from '@/lib/ports';
import type { PostgrestClient } from '@/lib/postgrest/client';

export class SupabaseDashboardAdapter implements DashboardRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async getDashboard(query: DashboardQuery): Promise<DashboardAnalytics> {
    return dashboardFromRpc(await this.db.rpc('get_incident_dashboard', dashboardRpcArgs(query)));
  }
}

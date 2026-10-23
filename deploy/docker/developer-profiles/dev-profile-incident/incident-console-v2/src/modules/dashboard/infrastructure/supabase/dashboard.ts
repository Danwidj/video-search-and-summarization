// SPDX-License-Identifier: Apache-2.0

import { dashboardFromRpc, dashboardRpcArgs } from '@/modules/dashboard/infrastructure/supabase/mappers/dashboard';
import type { DashboardAnalytics } from '@/modules/dashboard/domain/types';
import type { DashboardQuery, DashboardRepository } from '@/modules/dashboard/domain/DashboardRepository';
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

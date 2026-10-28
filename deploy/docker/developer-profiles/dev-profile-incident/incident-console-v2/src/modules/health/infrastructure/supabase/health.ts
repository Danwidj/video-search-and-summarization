// SPDX-License-Identifier: Apache-2.0

import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import type { DatabaseHealth, HealthRepository } from '@/modules/health/domain/HealthRepository';
import { PostgrestClient } from '@/lib/postgrest/client';

/** Never throws: an unconfigured database is a health result, not an error. */
export class SupabaseHealthAdapter implements HealthRepository {
  private readonly config: ServiceConfiguration;

  constructor(config: ServiceConfiguration = getServiceConfiguration()) {
    this.config = config;
  }

  async checkHealth(): Promise<DatabaseHealth> {
    const configured = isSupabaseConfigured(this.config);
    const { supabaseUrl, supabaseServiceRoleKey } = this.config;
    const reachable =
      configured && supabaseUrl && supabaseServiceRoleKey ? await new PostgrestClient(supabaseUrl, supabaseServiceRoleKey).health() : false;
    return { configured, reachable };
  }
}

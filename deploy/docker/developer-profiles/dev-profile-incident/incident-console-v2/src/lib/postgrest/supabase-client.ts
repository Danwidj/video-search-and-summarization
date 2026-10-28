// SPDX-License-Identifier: Apache-2.0

import { getServiceConfiguration, isSupabaseConfigured, type ServiceConfiguration } from '@/lib/env';
import { PostgrestClient } from '@/lib/postgrest/client';

/** The service-role PostgREST client; throws the message every route used before the adapters existed. */
export function createPostgrestClient(config: ServiceConfiguration = getServiceConfiguration()): PostgrestClient {
  if (!isSupabaseConfigured(config) || !config.supabaseUrl || !config.supabaseServiceRoleKey) {
    throw new Error('Supabase PostgREST is not configured');
  }
  return new PostgrestClient(config.supabaseUrl, config.supabaseServiceRoleKey);
}

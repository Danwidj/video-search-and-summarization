// SPDX-License-Identifier: Apache-2.0

// The composition root for database access: the only place that chooses which
// adapter backs each port. Built per call (a client is two strings), so the
// configuration is read at request time and never cached at module load.

import { SupabaseDashboardAdapter } from '@/lib/adapters/supabase/dashboard';
import { SupabaseHealthAdapter } from '@/lib/adapters/supabase/health';
import { SupabaseVideoAdapter } from '@/modules/videos/infrastructure/supabase/videos';
import type { ServiceConfiguration } from '@/lib/env';
import type { HealthRepository } from '@/lib/ports/health';
import { createPostgrestClient } from '@/lib/postgrest/supabase-client';
import type { DbAdapters } from '@/modules/shared/domain/adapters';
import { SupabaseIncidentAdapter } from '@/modules/reports/infrastructure/supabase/incidents';

/** Throws 'Supabase PostgREST is not configured' when the service-role settings are missing. */
export function getDbAdapters(config?: ServiceConfiguration): DbAdapters {
  const db = createPostgrestClient(config);
  return {
    dashboard: new SupabaseDashboardAdapter(db),
    incidents: new SupabaseIncidentAdapter(db),
    videos: new SupabaseVideoAdapter(db),
  };
}

/** Never throws: /api/health must answer when the database is not configured. */
export function getDbHealth(config?: ServiceConfiguration): HealthRepository {
  return new SupabaseHealthAdapter(config);
}

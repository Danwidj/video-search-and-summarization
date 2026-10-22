// SPDX-License-Identifier: Apache-2.0

// The composition root for database access: the only place that chooses which
// adapter backs each port. Built per call (a client is two strings), so the
// configuration is read at request time and never cached at module load.

import { SupabaseAnalysisRunAdapter } from '@/lib/adapters/supabase/analysis-runs';
import { createPostgrestClient } from '@/lib/adapters/supabase/client';
import { SupabaseDashboardAdapter } from '@/lib/adapters/supabase/dashboard';
import { SupabaseHealthAdapter } from '@/lib/adapters/supabase/health';
import { SupabaseIncidentAdapter } from '@/lib/adapters/supabase/incidents';
import { SupabaseVideoAdapter } from '@/lib/adapters/supabase/videos';
import type { ServiceConfiguration } from '@/lib/env';
import type { DbAdapters, HealthRepository } from '@/lib/ports';

/** Throws 'Supabase PostgREST is not configured' when the service-role settings are missing. */
export function getDbAdapters(config?: ServiceConfiguration): DbAdapters {
  const db = createPostgrestClient(config);
  return {
    analysisRuns: new SupabaseAnalysisRunAdapter(db),
    dashboard: new SupabaseDashboardAdapter(db),
    incidents: new SupabaseIncidentAdapter(db),
    videos: new SupabaseVideoAdapter(db),
  };
}

/** Never throws: /api/health must answer when the database is not configured. */
export function getDbHealth(config?: ServiceConfiguration): HealthRepository {
  return new SupabaseHealthAdapter(config);
}

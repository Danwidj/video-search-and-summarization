// SPDX-License-Identifier: Apache-2.0

// The composition root for database access: the only place that chooses which
// adapter backs each port. Built per call (a client is two strings), so the
// configuration is read at request time and never cached at module load.

import { SupabaseHealthAdapter } from '@/lib/adapters/supabase/health';
import type { ServiceConfiguration } from '@/lib/env';
import type { HealthRepository } from '@/lib/ports';

/** Never throws: /api/health must answer when the database is not configured. */
export function getDbHealth(config?: ServiceConfiguration): HealthRepository {
  return new SupabaseHealthAdapter(config);
}

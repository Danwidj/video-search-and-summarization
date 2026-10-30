// SPDX-License-Identifier: Apache-2.0

// The composition root: the only place that chooses which adapter backs each
// port. Built per call (a client is two strings), so the configuration is read
// at request time and never cached at module load.

import { randomUUID } from 'node:crypto';

import { SupabaseDashboardAdapter } from '@/modules/dashboard/infrastructure/supabase/dashboard';
import { SupabaseHealthAdapter } from '@/modules/health/infrastructure/supabase/health';
import { SupabaseVideoAdapter } from '@/modules/videos/infrastructure/supabase/videos';
import { getServiceConfiguration, type ServiceConfiguration } from '@/lib/env';
import type { HealthRepository } from '@/modules/health/domain/HealthRepository';
import { createPostgrestClient } from '@/lib/postgrest/supabase-client';
import type { DbAdapters } from '@/modules/shared/domain/adapters';
import { SupabaseIncidentAdapter } from '@/modules/reports/infrastructure/supabase/incidents';
import type { AnalysisPorts } from '@/modules/analysis/application/run-contract-analysis';
import { SupabaseAnalysisRunAdapter } from '@/modules/analysis/infrastructure/supabase/analysis-runs';
import { GatewayClient } from '@/modules/analysis/infrastructure/gateway/client';
import { HttpIncidentAgent } from '@/modules/analysis/infrastructure/agent/incident-agent';
import { R2VideoObjectStore } from '@/modules/analysis/infrastructure/r2/video-object-store';
import type { ContractCatalog } from '@/modules/contract/domain/ContractCatalog';
import { defaultContractCatalog } from '@/modules/contract/infrastructure/loader';
import type { RemoveVstSensor } from '@/modules/reports/application/types';
import { removeVstSensor } from '@/modules/videos/infrastructure/vst/sensor';

/** Outbound contract catalog port: provides shared prompts, schemas and model allowlists. */
export function getContractCatalog(): ContractCatalog {
  return defaultContractCatalog;
}

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

/**
 * The analysis ports. The model port is built only when its URL is configured;
 * the analysis refuses the mode whose port is null. Throws like getDbAdapters
 * when the database is not configured.
 */
export function getAnalysisPorts(config: ServiceConfiguration = getServiceConfiguration()): AnalysisPorts {
  const db = createPostgrestClient(config);
  return {
    runs: new SupabaseAnalysisRunAdapter(db),
    videos: new R2VideoObjectStore(config),
    gateway: config.gatewayUrl ? new GatewayClient(config.gatewayUrl) : null,
    agent: config.agentUrl ? new HttpIncidentAgent(config.agentUrl) : null,
    catalog: defaultContractCatalog,
    randomUUID,
  };
}

/** The VST camera deletion port, reached through INCIDENT_VST_BASE_URL (the agent URL when unset). */
export function getRemoveVstSensor(config: ServiceConfiguration = getServiceConfiguration()): RemoveVstSensor {
  return (video) => removeVstSensor(config, video);
}
